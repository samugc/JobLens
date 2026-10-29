"""Stateless, process-local review receipts and evidence authority.

No candidate data is stored here. Receipts bind approvals to exact content, not
client IDs or review labels. Restarting the server invalidates receipts;
portable profiles are revalidated against their bundled source and explicitly
confirmed again.

Each issued draft also carries an ``authority`` record: an HMAC over the fact
ids the server validated (approved profile facts or provisional source-backed
facts), the documentary citations bound to each item, and the session id. Export
verifies that record, so a client cannot authorise a new identifier by editing
the draft. Candidate attestations stay outside that record: they are bound by
the per-item receipt (content, contact and mode) and are rendered with an
``attestation:<item_id>`` citation rather than a fact id.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import secrets

from .cv import CvDraft
from .profile import build_profile_proposals
from .profile.approved import import_approved_profile


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class ReviewValidationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ReviewGuard:
    def __init__(self):
        self.key = secrets.token_bytes(32)
        self.session_id = secrets.token_hex(16)

    def sign(self, kind, value):
        return hmac.new(self.key, (kind + canonical(value)).encode(), hashlib.sha256).hexdigest()

    def verify(self, kind, value, receipt):
        if not isinstance(receipt, str) or not hmac.compare_digest(self.sign(kind, value), receipt):
            if kind == "final":
                raise ReviewValidationError(
                    "draft_changed",
                    "The draft changed or has not been confirmed. Review it and confirm the current version again.",
                )
            raise ReviewValidationError(
                "invalid_request",
                "The draft validation token is invalid. Generate a new draft; do not reuse altered review data.",
            )

    def profile(self, payload, source, confirmed):
        if confirmed is not True:
            raise ValueError("Explicit profile confirmation is required")
        profile = import_approved_profile(payload, source_response=source)
        envelope = build_profile_proposals({"schema_version": "1.1", **source})
        proposals = {p.proposal_id: p.as_dict() for p in envelope.proposals}
        history = profile.review_history
        for fact in profile.facts:
            expected = proposals.get(fact.fact_id)
            if not expected or any(
                fact.as_dict()[k] != expected[k] for k in ("category", "value", "evidence")
            ):
                raise ValueError("Approved fact differs from the canonical source proposal")
            actions = [e for e in history if e.get("proposal_id") == fact.fact_id]
            if not actions or actions[-1].get("kind") != "approve":
                raise ValueError("Fact has no explicit current approval")
            for conflict in envelope.conflicts:
                c = conflict.as_dict()
                if fact.fact_id not in c.get("proposal_ids", []):
                    continue
                resolutions = [
                    e.get("detail", {})
                    for e in history
                    if e.get("kind") in ("resolve_conflict", "use_recommendation")
                    and (e.get("detail") or {}).get("conflict_id") == c["conflict_id"]
                ]
                if not resolutions:
                    raise ValueError("Unresolved profile conflict")
                resolution = resolutions[-1]
                kept = resolution.get("kept", [])
                if (
                    len(kept) != 1
                    or fact.fact_id not in kept
                    or not str(resolution.get("note", "")).strip()
                ):
                    raise ValueError("Conflict needs an explicit selection and justification")
        result = profile.as_dict()
        result["source"] = source
        result["receipt"] = self.sign("profile", result)
        return result

    def trusted_profile(self, payload):
        value = dict(payload)
        receipt = value.pop("receipt", None)
        self.verify("profile", value, receipt)
        return import_approved_profile(value, source_response=value["source"])

    def issue_draft(self, draft, *, approved_profile=None, provisional_evidence=None):
        """Issue a draft with a signed record of the evidence it may cite.

        The authority record is built from server-validated input only: the
        approved profile's facts, or the source-backed provisional fact ids.
        It is never derived from the draft's own citation lists, which the
        client can edit. It binds the allowed ids, each item's documentary
        citations, and this server session into one HMAC.
        """
        value = draft.as_dict()
        value["review"] = {
            "baseline": draft.as_dict(),
            "approvals": {},
            "history": [],
            "session_id": self.session_id,
        }
        value["review"]["receipt"] = self.sign("baseline", value["review"]["baseline"])
        value["review"]["authority"] = self._authority_record(
            draft, approved_profile, provisional_evidence
        )
        return value

    def _authority_record(self, draft, approved_profile, provisional_evidence):
        if approved_profile is not None:
            basis = "approved_profile"
            fact_ids = sorted({str(fact.fact_id) for fact in approved_profile.facts})
        elif provisional_evidence is not None:
            basis = "provisional_source"
            fact_ids = sorted({str(fact_id) for fact_id in provisional_evidence})
        else:
            basis = "none"
            fact_ids = []
        record = {
            "session_id": self.session_id,
            "basis": basis,
            "fact_ids": fact_ids,
            "items": {
                item.item_id: sorted(str(fid) for fid in item.approved_fact_ids)
                for section in draft.sections
                for item in section.items
            },
        }
        record["receipt"] = self.sign("authority", record)
        return record

    def _trusted_authority(self, payload):
        """Return the verified allowed fact ids and per-item mapping."""
        authority = payload["review"].get("authority")
        if not isinstance(authority, dict):
            raise ReviewValidationError(
                "missing_authority",
                "This draft has no evidence authority record. Generate a new draft "
                "and review it again.",
            )
        unsigned = {key: value for key, value in authority.items() if key != "receipt"}
        self.verify("authority", unsigned, authority.get("receipt"))
        if unsigned.get("session_id") != self.session_id:
            raise ReviewValidationError(
                "session_expired",
                "This draft belongs to an earlier server session. Generate a new "
                "draft and review it again.",
            )
        fact_ids = unsigned.get("fact_ids")
        items = unsigned.get("items")
        if (
            not isinstance(fact_ids, list)
            or not all(isinstance(fid, str) for fid in fact_ids)
            or not isinstance(items, dict)
        ):
            raise ReviewValidationError(
                "invalid_request", "The evidence authority record is malformed."
            )
        return set(fact_ids), items

    def draft(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("review"), dict):
            raise ValueError("Generate a draft before reviewing it")
        review = payload["review"]
        if review.get("session_id") != self.session_id:
            raise ReviewValidationError(
                "session_expired",
                "This draft belongs to an earlier server session. Generate a new draft and review it again.",
            )
        self.verify("baseline", review.get("baseline"), review.get("receipt"))
        draft = CvDraft.from_dict(payload)
        if draft.cv_draft_version != "0.1":
            raise ValueError("Unsupported draft version")
        ids = [i.item_id for s in draft.sections for i in s.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate item identifiers")
        return draft

    def item_content(self, section, item):
        data = item.as_dict()
        data.pop("review_status")
        return {
            "section": {"id": section.section_id, "kind": section.kind, "title": section.title},
            "item": data,
        }

    def edit(self, payload, item_id, text):
        self.draft(payload)
        value = copy.deepcopy(payload)
        found = False
        for section in value["sections"]:
            for item in section["items"]:
                if item["item_id"] == item_id:
                    item["text"] = text
                    item["review_status"] = "needs_review"
                    found = True
        if not found:
            raise ValueError("Unknown item")
        value["review"]["approvals"].pop(item_id, None)
        value["review"]["history"].append({"action": "edit", "item_id": item_id, "text": text})
        return value

    def approve(self, payload, item_id, confirmed, attested):
        draft = self.draft(payload)
        if confirmed is not True:
            raise ValueError("Explicit wording confirmation required")
        baseline = CvDraft.from_dict(payload["review"]["baseline"])
        originals = {i.item_id: self.item_content(s, i) for s in baseline.sections for i in s.items}
        value = copy.deepcopy(payload)
        for section in draft.sections:
            for item in section.items:
                if item.item_id != item_id:
                    continue
                content = self.item_content(section, item)
                documentary = content == originals.get(item_id)
                if not documentary and attested is not True:
                    raise ValueError("Changed or new wording needs explicit candidate attestation")
                if not item.text.strip():
                    raise ValueError("Empty wording cannot be approved")
                mode = "documentary" if documentary else "candidate_attested"
                receipt = self.sign(
                    "item",
                    {
                        "baseline": payload["review"]["receipt"],
                        "content": content,
                        "mode": mode,
                        # Contact details are part of the approval: changing
                        # them after approval invalidates every item receipt,
                        # so a final document confirmation cannot survive a
                        # silent contact edit.
                        "contact": draft.candidate.as_dict(),
                    },
                )
                value["review"]["approvals"][item_id] = {"mode": mode, "receipt": receipt}
                for s in value["sections"]:
                    for i in s["items"]:
                        if i["item_id"] == item_id:
                            i["review_status"] = "approved"
                value["review"]["history"].append(
                    {"action": "approve", "item_id": item_id, "mode": mode, "content": content}
                )
                return value
        raise ValueError("Unknown item")

    def export(self, payload, confirmed, contact):
        draft = self.draft(payload)
        allowed_ids, documentary = self._trusted_authority(payload)
        if (
            payload["review"]["baseline"].get("review_mode") == "provisional"
            or payload["review"].get("final_receipt")
        ):
            self.verify("final", draft.as_dict(), payload["review"].get("final_receipt"))
        if confirmed is not True or contact != draft.candidate.as_dict():
            raise ValueError("Confirm the exact contact details before export")
        if not draft.candidate.full_name or not draft.sections:
            raise ValueError("Name and reviewed CV content are required")
        value = draft.as_dict()
        support: list[str] = []
        attested_ids: list[str] = []
        for section, out_section in zip(draft.sections, value["sections"]):
            for item, out_item in zip(section.items, out_section["items"]):
                approval = payload["review"]["approvals"].get(item.item_id, {})
                if item.review_status != "approved":
                    raise ValueError("Unreviewed item")
                self.verify(
                    "item",
                    {
                        "baseline": payload["review"]["receipt"],
                        "content": self.item_content(section, item),
                        "mode": approval.get("mode"),
                        "contact": draft.candidate.as_dict(),
                    },
                    approval.get("receipt"),
                )
                # Renderer requires support IDs. Attested content is distinctly
                # labelled in the review model, never represented as a source fact.
                if approval["mode"] == "candidate_attested":
                    out_item["approved_fact_ids"] = ["attestation:" + item.item_id]
                    attested_ids.append("attestation:" + item.item_id)
                else:
                    # Documentary wording must cite exactly what the signed
                    # authority bound to this item, and every id must exist in
                    # the server-validated fact set.
                    expected = documentary.get(item.item_id)
                    if not isinstance(expected, list) or sorted(
                        item.approved_fact_ids
                    ) != sorted(str(fid) for fid in expected):
                        raise ReviewValidationError(
                            "evidence_mismatch",
                            "An item cites evidence that was not issued for it. "
                            "Generate a new draft.",
                        )
                    if not set(item.approved_fact_ids) <= allowed_ids:
                        raise ReviewValidationError(
                            "unknown_evidence",
                            "An item cites evidence that is not part of a validated "
                            "source. Generate a new draft.",
                        )
                support.extend(out_item["approved_fact_ids"])
        # The support handed to the renderer is the authority set, not the
        # draft's own citation list, plus the attestations actually confirmed.
        return value, sorted(allowed_ids | set(attested_ids))

    def confirm_all(self, payload, confirmed, attested):
        parsed = self.draft(payload)
        if not (parsed.candidate.full_name or "").strip():
            raise ReviewValidationError(
                "missing_contact",
                "Enter your full name in the contact details before confirming the CV.",
            )
        if confirmed is not True:
            raise ValueError("Confirm the accuracy of the complete CV")
        value = copy.deepcopy(payload)
        for section in payload["sections"]:
            for item in section["items"]:
                value = self.approve(value, item["item_id"], True, attested)
        value["review"]["final_receipt"] = self.sign("final", CvDraft.from_dict(value).as_dict())
        return value
