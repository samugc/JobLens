"""Fictional source-to-export integrity regression; actual parser and HTTP."""

import io
import json
from pathlib import Path

import pytest
import test_cv_profile_api
from cv_builders import make_docx, make_pdf
from docx import Document
from fact_preservation_fixtures import JOB, RICH, SMALL_A, SMALL_B
from pypdf import PdfReader
from test_cv_mount import post_cv
from test_cv_profile_api import json_headers, request

from joblens_public.jobs import parse_job_posting
from joblens_public.provisional import draft_from_source

app_server = test_cv_profile_api.app_server


@pytest.mark.parametrize("rich", [False, True])
def test_source_facts_survive_real_exports(app_server, rich):
    port = app_server.server_port
    texts = [RICH, RICH] if rich else [SMALL_A, SMALL_B]
    pdf = make_pdf([texts[0].splitlines()])
    docx = make_docx([(line, None) for line in texts[1].splitlines()])
    status, _, raw = post_cv(
        port, [("files", "fictional-a.pdf", pdf), ("files", "fictional-b.docx", docx)]
    )
    assert status == 200
    batch = json.loads(raw)
    assert len(batch["documents"]) == 2
    source = {k: batch[k] for k in ("job_id", "documents")}
    assert all("Python" in "\n".join(s["text"] for s in d["segments"]) for d in source["documents"])

    def post(route, payload):
        status, _, raw = request(
            port, "POST", "/api/cv/" + route, json.dumps(payload).encode(), json_headers(port)
        )
        assert status == 200, (status, raw[:200])
        return raw if "export/" in route else json.loads(raw)

    draft = post("draft", {"source": source, "text": JOB})["draft"]
    sections = {s["kind"]: s for s in draft["sections"]}
    skills = [i["text"] for i in sections["skills"]["items"]]
    assert set(skills) == {"Python", "SQL", "Git", "Docker", "JavaScript"}
    assert skills[0] == "Python"
    assert len(skills) == len(set(skills))
    assert "AWS" not in skills and "Kubernetes" not in skills
    assert "BSc in Computer Science" in str(sections["education"])
    assert "AWS Certified Cloud Practitioner" in str(sections["certifications"])
    assert "Spanish (Native)" in str(sections["languages"])
    if not rich:
        assert len(sections["experience"]["items"]) == 2
        assert "Built a local Python service" in str(sections["experience"])
        assert "Documented backend APIs" in str(sections["experience"])
        assert len(sections["projects"]["items"]) == 1
        assert sections["projects"]["items"][0]["heading"] == "Project Boreal"
        assert "Project Boreal" not in sections["projects"]["items"][0]["text"]
        assert "Atlas" not in str(draft["sections"])
        assert "English" not in str(sections["languages"])
    if rich:
        assert len(sections["experience"]["items"]) == 1
    if "summary" in sections:
        assert "Software Engineer" in str(sections["summary"])
        assert "Skills include" not in str(sections["summary"])
    # Every citation remains exact, including DOCX paragraph boundaries.
    documents = {d["document_id"]: d for d in source["documents"]}
    for refs in draft["review"]["baseline"]["evidence"].values():
        for e in refs:
            segment = documents[e["document_id"]]["segments"][e["segment_index"]]
            assert segment["text"][e["start"] : e["end"]] == e["quote"]
            assert segment["locator"] == e["locator"]
    draft["candidate"]["full_name"] = "Morgan Example" if rich else "Alex Rivera"
    draft = post("confirm", {"draft": draft, "confirmed": True, "attested": True})["draft"]
    output = Path(".integration-verification/fact-preservation") / ("rich" if rich else "small")
    output.mkdir(parents=True, exist_ok=True)
    (output / "source-a.pdf").write_bytes(pdf)
    (output / "source-b.docx").write_bytes(docx)
    rendered = {}
    for kind in ("pdf", "docx"):
        raw = post(
            "cv-drafts/export/" + kind,
            {"draft": draft, "confirmed": True, "contact": draft["candidate"]},
        )
        (output / ("tailored-cv." + kind)).write_bytes(raw)
        text = (
            "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages)
            if kind == "pdf"
            else "\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
        )
        for phrase in (
            "Python",
            "JavaScript",
            "Computer Science",
            "Software Engineer",
            "Spanish (Native)",
            "AWS Certified Cloud Practitioner",
        ):
            assert phrase in text
        assert "Kubernetes" not in text and "proposal_" not in text
        if rich:
            for phrase in ("2021-2024", "Cedar Labs", "25%", "30%", "Meridian", "Lantern"):
                assert phrase in text
        else:
            assert text.count("Project Boreal") == 1
            assert "Atlas" not in text and "English" not in text
        headings = [s["title"] for s in draft["sections"]]
        assert [line for line in text.splitlines() if line in headings] == headings
        rendered[kind] = text
    trace = []
    draft_from_source(source, parse_job_posting(JOB), trace=trace)
    (output / "trace.json").write_text(
        json.dumps(
            {
                "extracted": source,
                "selection": trace,
                "draft": draft["sections"],
                "rendered": rendered,
            },
            indent=2,
        )
    )
