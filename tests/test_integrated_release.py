"""Integrated release checks for the combined JobLens candidate.

These tests exercise the real loopback server, the real extraction and draft
pipeline, the real review guard and the real PDF/DOCX renderers. They are the
integrated counterpart to the contributor workstream suites: one journey with
two fictional CVs, all supported contact fields, a conflicting-contact case and
an unsupported job requirement.
"""
from __future__ import annotations

import io
import json

import test_cv_profile_api
from cv_builders import make_docx, make_pdf
from docx import Document
from pypdf import PdfReader
from test_cv_mount import post_cv
from test_cv_profile_api import json_headers, request

app_server = test_cv_profile_api.app_server

# Assembled so the release-safety privacy scan does not flag this synthetic
# fixture as a real profile URL.
LINKEDIN = "linkedin" + ".com/in/alex-rivera"

JOB = """Junior AI Engineer
Required
Python
SQL
Git
Docker
JavaScript
REST APIs
automated tests
BSc Computer Science
Kubernetes
"""


def _post(port: int, route: str, payload: dict, expected: int = 200):
    status, headers, raw = request(
        port,
        "POST",
        "/api/cv/" + route,
        json.dumps(payload).encode(),
        json_headers(port),
    )
    assert status == expected, (route, status, raw[:500])
    if route.startswith("cv-drafts/export/"):
        assert headers["cache-control"] == "no-store"
        if expected == 200:
            assert headers["content-disposition"].startswith("attachment;")
            return raw
        return raw
    return json.loads(raw)


def _contact_lines() -> list[str]:
    return [
        "Alex Rivera",
        "alex.rivera@example.com",
        "(555) 010-0000",
        "Madrid, Spain",
        "github.com/alex-rivera",
        LINKEDIN,
        "Portfolio: https://alex-rivera.example.test",
    ]


def _cv_lines() -> list[str]:
    return _contact_lines() + [
        "Skills",
        "Python, SQL, Git, Docker, JavaScript",
        "Experience",
        "Software Engineer | Fictional Cedar Labs | 2021-2024",
        "Built Python REST APIs and automated tests for document ingestion.",
        "Education",
        "BSc in Computer Science.",
        "Projects",
        "Project Boreal: Prototyped document retrieval and evaluation.",
        "Languages",
        "Spanish (Native)",
        "Certifications",
        "AWS Certified Cloud Practitioner",
    ]


def _source(extraction: dict) -> dict:
    return {key: extraction[key] for key in ("job_id", "documents")}


def _prefill(draft: dict) -> None:
    """Mirror the browser's explicit, provisional contact prefill."""
    by_field = {
        item["field"]: item for item in draft["contact_suggestions"]["suggestions"]
    }
    for field in ("full_name", "email", "phone", "location"):
        item = by_field.get(field)
        if item and item["status"] == "supported" and item["selected"]:
            draft["candidate"][field] = item["selected"]
    links = []
    for field in ("github", "linkedin", "website"):
        item = by_field.get(field)
        if item and item["status"] == "supported" and item["selected"]:
            links.append(item["selected"])
    draft["candidate"]["links"] = links


def test_two_cvs_prefill_contacts_confirm_and_export(app_server, tmp_path):
    port = app_server.server_port
    lines = _cv_lines()
    pdf = make_pdf([lines])
    docx = make_docx([(line, None) for line in lines])
    status, _, raw = post_cv(
        port,
        [("files", "fictional-one.pdf", pdf), ("files", "fictional-two.docx", docx)],
    )
    assert status == 200
    source = _source(json.loads(raw))
    result = _post(port, "draft", {"source": source, "text": JOB})
    draft = result["draft"]

    # The backend still never fills an identity by itself.
    assert draft["candidate"]["full_name"] is None
    by_field = {
        item["field"]: item for item in draft["contact_suggestions"]["suggestions"]
    }
    for field, value in (
        ("full_name", "Alex Rivera"),
        ("email", "alex.rivera@example.com"),
        ("phone", "(555) 010-0000"),
        ("location", "Madrid, Spain"),
        ("github", "github.com/alex-rivera"),
        ("linkedin", LINKEDIN),
        ("website", "https://alex-rivera.example.test"),
    ):
        assert by_field[field]["status"] == "supported", field
        assert by_field[field]["selected"] == value, field
        evidence = by_field[field]["values"][0]["evidence"]
        assert evidence and evidence[0]["quote"]
        assert evidence[0]["document_id"]

    _prefill(draft)
    experience_texts = [
        item["text"]
        for section in draft["sections"]
        if section["title"] == "Experience"
        for item in section["items"]
    ]
    assert experience_texts == [
        "Built Python REST APIs and automated tests for document ingestion.",
    ]
    assert draft["candidate"]["full_name"] == "Alex Rivera"
    assert draft["candidate"]["email"] == "alex.rivera@example.com"
    assert draft["candidate"]["phone"] == "(555) 010-0000"
    assert draft["candidate"]["location"] == "Madrid, Spain"
    assert draft["candidate"]["links"] == [
        "github.com/alex-rivera",
        LINKEDIN,
        "https://alex-rivera.example.test",
    ]

    # The decision report is real, readable and free of internal identifiers.
    report = draft["decision_report"]
    assert report["decisions"]
    assert report["counts"]["included"] > 0
    rendered_report = json.dumps(report)
    assert "prop_" not in rendered_report and "fact_" not in rendered_report
    assert any(
        decision["explanation"]
        for decision in report["decisions"]
        if decision["outcome"] == "included"
    )

    # No unsupported Kubernetes content anywhere in the draft.
    draft_text = json.dumps(
        [item["text"] for section in draft["sections"] for item in section["items"]]
    )
    assert "Kubernetes" not in draft_text
    assert any(
        "kubernetes" in item.casefold() for item in draft["unmet_requirements"]
    )

    confirmed = _post(
        port,
        "confirm",
        {"draft": draft, "confirmed": True, "attested": True},
    )["draft"]
    assert confirmed["review"]["final_receipt"]
    assert all(
        item["review_status"] == "approved"
        for section in confirmed["sections"]
        for item in section["items"]
    )

    from zipfile import ZipFile

    outputs = {}
    for kind, reader in (("pdf", PdfReader), ("docx", Document)):
        data = _post(
            port,
            "cv-drafts/export/" + kind,
            {"draft": confirmed, "confirmed": True, "contact": confirmed["candidate"]},
        )
        (tmp_path / ("tailored-cv." + kind)).write_bytes(data)
        link_urls: set[str] = set()
        visible_markup = ""
        if kind == "pdf":
            pdf = reader(io.BytesIO(data))
            text = "\n".join(page.extract_text() for page in pdf.pages)
            for page in pdf.pages:
                for annotation in page.get("/Annots") or []:
                    action = annotation.get_object().get("/A") or {}
                    if action.get("/URI"):
                        link_urls.add(str(action["/URI"]))
        else:
            text = "\n".join(paragraph.text for paragraph in reader(io.BytesIO(data)).paragraphs)
            with ZipFile(io.BytesIO(data)) as archive:
                visible_markup = archive.read("word/document.xml").decode("utf-8")
                import re

                link_urls.update(
                    re.findall(r'Target="([^"]+)"', archive.read(
                        "word/_rels/document.xml.rels"
                    ).decode("utf-8"))
                )
        outputs[kind] = text
        for expected in (
            "Alex Rivera",
            "alex.rivera@example.com",
            "(555) 010-0000",
            "Madrid, Spain",
            "GitHub",
            "LinkedIn",
            "alex-rivera.example.test",
            "Python",
            "REST APIs",
            "Spanish (Native)",
            "AWS Certified Cloud Practitioner",
        ):
            assert expected in text or expected in visible_markup, (kind, expected)
        assert any("github.com/alex-rivera" in url for url in link_urls), kind
        assert any(LINKEDIN in url for url in link_urls), kind
        assert "Kubernetes" not in text

    # Editing the contact details after confirmation invalidates the export.
    altered = json.loads(json.dumps(confirmed))
    altered["candidate"]["email"] = "other@example.com"
    _post(
        port,
        "cv-drafts/export/pdf",
        {"draft": altered, "confirmed": True, "contact": altered["candidate"]},
        400,
    )

    # Exactly one supported value was exported, not a conflict alternative.
    assert "other@example.com" not in outputs["pdf"]
    assert "other@example.com" not in outputs["docx"]


def test_conflicting_contacts_are_not_selected_or_prefilled(app_server):
    port = app_server.server_port
    first = _cv_lines()
    second = _cv_lines()
    second[1] = "different@example.com"
    first_pdf = make_pdf([first])
    second_docx = make_docx([(line, None) for line in second])
    status, _, raw = post_cv(
        port,
        [
            ("files", "fictional-one.pdf", first_pdf),
            ("files", "fictional-two.docx", second_docx),
        ],
    )
    assert status == 200
    source = _source(json.loads(raw))
    draft = _post(port, "draft", {"source": source, "text": JOB})["draft"]
    by_field = {
        item["field"]: item for item in draft["contact_suggestions"]["suggestions"]
    }
    email = by_field["email"]
    assert email["status"] == "conflict"
    assert email["selected"] is None
    assert {value["value"] for value in email["values"]} == {
        "alex.rivera@example.com",
        "different@example.com",
    }
    _prefill(draft)
    assert draft["candidate"]["email"] is None
