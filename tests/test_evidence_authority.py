"""Adversarial tests for independent evidence authority at export.

Threat model: the draft JSON is editable by the client. Every check that reads
fact ids *from the draft* can therefore be satisfied by editing the draft. These
tests assume the client is hostile and assert that:

* export fails when no server-issued authority record is present;
* a forged or re-signed authority record is refused;
* adding, swapping or inventing documentary ids is refused;
* ``unverified`` rendering cannot be activated from JSON, at the library or the
  HTTP layer, and requires an explicit Python argument;
* candidate attestation remains the only path for non-documentary wording;
* PDF and DOCX enforce the same rules.
"""

from __future__ import annotations

import copy
import json
import types

import pytest
import test_cv_profile_api
from cv_builders import make_docx, make_pdf
from test_cv_mount import post_cv
from test_cv_profile_api import json_headers, request

from joblens_public.cv import CvDraft, CvDraftItem, CvDraftSection
from joblens_public.export import export_cv_docx_bytes, export_cv_pdf_bytes
from joblens_public.export.errors import EvidenceContractError
from joblens_public.profile.approved import CandidateContact
from joblens_public.profile.contact import ContactSuggestions
from joblens_public.release_guard import ReviewGuard, ReviewValidationError

app_server = test_cv_profile_api.app_server


def _profile_stub(*fact_ids: str):
    return types.SimpleNamespace(
        facts=[types.SimpleNamespace(fact_id=fact_id) for fact_id in fact_ids]
    )


def _draft(*items: CvDraftItem) -> CvDraft:
    return CvDraft(
        candidate=CandidateContact(full_name="Alex Example", email="alex@example.com"),
        sections=(CvDraftSection("skills", "skills", "Skills", tuple(items)),),
        contact_suggestions=ContactSuggestions(),
    )


def _confirmed(guard, *, profile=None):
    value = guard.issue_draft(
        _draft(CvDraftItem("i1", "Python", ("fact_python",))), approved_profile=profile
    )
    return guard.confirm_all(value, True, False)


# ---------------------------------------------------------------------------
# Authority record: absent / forged / cross-session
# ---------------------------------------------------------------------------


def test_export_refuses_when_authority_record_is_absent():
    guard = ReviewGuard()
    confirmed = _confirmed(guard, profile=_profile_stub("fact_python"))
    stripped = copy.deepcopy(confirmed)
    stripped["review"].pop("authority")
    with pytest.raises(ReviewValidationError) as error:
        guard.export(stripped, True, stripped["candidate"])
    assert error.value.code == "missing_authority"


def test_export_refuses_forged_authority_record():
    guard = ReviewGuard()
    confirmed = _confirmed(guard, profile=_profile_stub("fact_python"))
    forged = copy.deepcopy(confirmed)
    forged["review"]["authority"]["fact_ids"].append("fact_invented")
    with pytest.raises(ReviewValidationError) as error:
        guard.export(forged, True, forged["candidate"])
    assert error.value.code == "invalid_request"


def test_export_refuses_authority_from_another_session():
    guard = ReviewGuard()
    confirmed = _confirmed(guard, profile=_profile_stub("fact_python"))
    other = ReviewGuard()
    with pytest.raises(ReviewValidationError) as error:
        other.export(confirmed, True, confirmed["candidate"])
    assert error.value.code == "session_expired"


# ---------------------------------------------------------------------------
# Draft-side tampering with documentary ids
# ---------------------------------------------------------------------------


def test_export_refuses_added_documentary_fact_id():
    guard = ReviewGuard()
    confirmed = _confirmed(guard, profile=_profile_stub("fact_python"))
    tampered = copy.deepcopy(confirmed)
    tampered["sections"][0]["items"][0]["approved_fact_ids"].append("fact_invented")
    with pytest.raises(ReviewValidationError):
        guard.export(tampered, True, tampered["candidate"])


def test_export_refuses_id_swapped_between_items():
    guard = ReviewGuard()
    value = guard.issue_draft(
        _draft(
            CvDraftItem("i1", "Python", ("fact_python",)),
            CvDraftItem("i2", "SQL", ("fact_sql",)),
        ),
        approved_profile=_profile_stub("fact_python", "fact_sql"),
    )
    confirmed = guard.confirm_all(value, True, False)
    swapped = copy.deepcopy(confirmed)
    items = swapped["sections"][0]["items"]
    items[0]["approved_fact_ids"], items[1]["approved_fact_ids"] = (
        items[1]["approved_fact_ids"],
        items[0]["approved_fact_ids"],
    )
    with pytest.raises(ReviewValidationError):
        guard.export(swapped, True, swapped["candidate"])


def test_support_is_the_authority_set_not_the_item_list():
    guard = ReviewGuard()
    confirmed = _confirmed(guard, profile=_profile_stub("fact_python", "fact_unused"))
    exported, support = guard.export(confirmed, True, confirmed["candidate"])
    # The unused approved fact is authorised; the item's own list is not the
    # source of truth.
    assert support == ["fact_python", "fact_unused"]
    assert exported["sections"][0]["items"][0]["approved_fact_ids"] == ["fact_python"]


def test_documentary_item_citing_an_unauthorised_id_is_refused():
    guard = ReviewGuard()
    # Issued without a profile: nothing is authorised, so documentary ids cannot
    # be trusted even though they are signed into the item mapping.
    value = guard.issue_draft(_draft(CvDraftItem("i1", "Python", ("fact_python",))))
    confirmed = guard.confirm_all(value, True, False)
    with pytest.raises(ReviewValidationError) as error:
        guard.export(confirmed, True, confirmed["candidate"])
    assert error.value.code == "unknown_evidence"


# ---------------------------------------------------------------------------
# Attestation remains the only path for changed wording
# ---------------------------------------------------------------------------


def test_attested_item_is_labelled_and_does_not_claim_facts():
    guard = ReviewGuard()
    confirmed = _confirmed(guard, profile=_profile_stub("fact_python"))
    edited = guard.edit(confirmed, "i1", "Python and SQL")
    attested = guard.confirm_all(edited, True, True)
    exported, support = guard.export(attested, True, attested["candidate"])
    assert exported["sections"][0]["items"][0]["approved_fact_ids"] == ["attestation:i1"]
    assert support == ["attestation:i1", "fact_python"]


# ---------------------------------------------------------------------------
# Unverified mode is a Python opt-in, never a JSON field
# ---------------------------------------------------------------------------


def _renderable_draft(**extra):
    value = {
        "cv_draft_version": "0.1",
        "target_job": {"title": "X", "company": "Y"},
        "candidate": {"full_name": "Alex Example"},
        "sections": [
            {
                "section_id": "s1",
                "kind": "summary",
                "title": "Summary",
                "items": [
                    {
                        "item_id": "i1",
                        "text": "Data engineer",
                        "approved_fact_ids": ["fact_1"],
                        "review_status": "approved",
                    }
                ],
            }
        ],
    }
    value.update(extra)
    return value


def test_json_evidence_mode_cannot_disable_verification():
    draft = _renderable_draft(evidence_mode="unverified")
    with pytest.raises(EvidenceContractError):
        export_cv_pdf_bytes(draft)
    with pytest.raises(EvidenceContractError):
        export_cv_docx_bytes(draft)


def test_python_opt_in_is_required_and_shared_by_both_renderers():
    draft = _renderable_draft()
    assert export_cv_pdf_bytes(draft, allow_unverified=True)[:4] == b"%PDF"
    assert export_cv_docx_bytes(draft, allow_unverified=True)[:2] == b"PK"


def test_support_still_checks_membership_even_with_unverified_allowed():
    draft = _renderable_draft()
    with pytest.raises(EvidenceContractError):
        export_cv_pdf_bytes(
            draft, evidence_support={"facts": [{"fact_id": "fact_other"}]},
            allow_unverified=True,
        )


# ---------------------------------------------------------------------------
# HTTP: the client cannot reach the unverified path
# ---------------------------------------------------------------------------


def _synthetic_source():
    pdf = make_pdf([[ "Skills", "Python, SQL", "Experience",
                     "Data Engineer | Fictional Harbor | 2020-2022" ]])
    docx = make_docx([("Skills", "Heading1"), ("Python", None)])
    return pdf, docx


@pytest.fixture()
def confirmed_draft(app_server):
    port = app_server.server_port
    pdf, docx = _synthetic_source()
    status, _, data = post_cv(
        port, [("files", "fictional.pdf", pdf), ("files", "fictional.docx", docx)]
    )
    assert status == 200
    extraction = json.loads(data)
    source = {key: extraction[key] for key in ("job_id", "documents")}

    def post(route, payload, expected=200):
        status, _, body = request(
            port, "POST", "/api/cv/" + route, json.dumps(payload).encode(),
            json_headers(port),
        )
        assert status == expected, (route, status, body[:400])
        return body if "export/" in route else json.loads(body)

    draft = post(
        "draft",
        {
            "source": source,
            "text": "Junior AI Engineer. Required: Python and SQL. Build reliable pipelines.",
        },
    )["draft"]
    draft["candidate"]["full_name"] = "Alex Example"
    draft = post("confirm", {"draft": draft, "confirmed": True, "attested": False})["draft"]
    return port, post, draft


def test_http_export_works_with_authority(confirmed_draft):
    port, post, draft = confirmed_draft
    for kind in ("pdf", "docx"):
        data = post("cv-drafts/export/" + kind, {"draft": draft, "confirmed": True,
                                                 "contact": draft["candidate"]})
        assert data[:4] == b"%PDF" if kind == "pdf" else data[:2] == b"PK"


def test_http_export_refuses_missing_authority(confirmed_draft):
    port, post, draft = confirmed_draft
    stripped = copy.deepcopy(draft)
    stripped["review"].pop("authority", None)
    post("cv-drafts/export/pdf", {"draft": stripped, "confirmed": True,
                                  "contact": stripped["candidate"]}, 400)


def test_http_export_refuses_tampered_authority(confirmed_draft):
    port, post, draft = confirmed_draft
    tampered = copy.deepcopy(draft)
    tampered["review"]["authority"]["fact_ids"] = ["fact_invented"]
    post("cv-drafts/export/pdf", {"draft": tampered, "confirmed": True,
                                  "contact": tampered["candidate"]}, 400)


def test_http_export_cannot_be_switched_to_unverified(confirmed_draft):
    port, post, draft = confirmed_draft
    # A draft with no approvals is refused even when the body asks for
    # "unverified" output at the top level or inside the draft.
    unapproved = copy.deepcopy(draft)
    for section in unapproved["sections"]:
        for item in section["items"]:
            item["review_status"] = "needs_review"
    unapproved["review"]["approvals"] = {}
    unapproved["evidence_mode"] = "unverified"
    post(
        "cv-drafts/export/docx",
        {"draft": unapproved, "confirmed": True,
         "contact": unapproved["candidate"], "allow_unverified": True,
         "evidence_mode": "unverified"},
        400,
    )


def test_http_export_ignores_evidence_mode_on_a_valid_draft(confirmed_draft):
    port, post, draft = confirmed_draft
    # The flag is inert: a valid draft still exports through the authority path.
    data = post(
        "cv-drafts/export/pdf",
        {"draft": dict(draft, evidence_mode="unverified"), "confirmed": True,
         "contact": draft["candidate"], "allow_unverified": True},
    )
    assert data[:4] == b"%PDF"
