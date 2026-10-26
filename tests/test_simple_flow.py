"""Main product flow against a real loopback server, with synthetic files only."""

import copy
import io
import json
import subprocess
from pathlib import Path

import test_cv_profile_api
from cv_builders import make_docx, make_pdf
from docx import Document
from pypdf import PdfReader
from test_cv_mount import post_cv
from test_cv_profile_api import json_headers, request

app_server = test_cv_profile_api.app_server


def test_simple_product(app_server, tmp_path):
    port = app_server.server_port

    def post(route, payload, expected=200):
        status, headers, data = request(
            port, "POST", "/api/cv/" + route, json.dumps(payload).encode(), json_headers(port)
        )
        assert status == expected, (route, status, data[:400])
        if expected == 200 and "export/" in route:
            assert headers["cache-control"] == "no-store"
            assert headers["content-disposition"].startswith("attachment;")
            return data
        return json.loads(data)

    pdf = make_pdf(
        [
            [
                "Skills",
                "Python, SQL",
                "Experience",
                "Data Engineer | Fictional Harbor | 2020-2022",
                "Projects",
                "Atlas - a Python pipeline that reduced processing time by 30%",
                "Languages",
                "English (C1)",
            ]
        ]
    )
    docx = make_docx(
        [
            ("Skills", "Heading1"),
            ("Python, Docker", None),
            ("Languages", "Heading1"),
            ("English (B2)", None),
            ("Education", "Heading1"),
            ("BSc Computer Science", None),
        ]
    )
    status, _, data = post_cv(
        port, [("files", "fictional.pdf", pdf), ("files", "fictional.docx", docx)]
    )
    assert status == 200
    extraction = json.loads(data)
    source = {key: extraction[key] for key in ("job_id", "documents")}
    result = post(
        "draft",
        {
            "source": source,
            "text": "Junior AI Engineer. Required: Python, SQL and Kubernetes. Build reliable data pipelines.",
        },
    )
    draft = result["draft"]
    assert draft["review"]["baseline"]["review_mode"] == "provisional"
    items = [i for s in draft["sections"] for i in s["items"]]
    sections = {s["kind"]: s for s in draft["sections"]}
    assert all(i["review_status"] == "needs_review" for i in items)
    assert draft["omitted_count"] > 0
    text = str([i["text"] for i in items])
    assert "C1" not in text and "B2" not in text and "Kubernetes" not in text
    assert "30%" in text
    assert "Fictional Harbor" in str(sections["experience"])
    assert "2020-2022" in str(sections["experience"])
    error = post("confirm", {"draft": draft, "confirmed": True, "attested": True}, 400)
    assert error["code"] == "missing_contact"
    assert "full name" in error["error"]
    expired = copy.deepcopy(draft)
    expired["review"]["session_id"] = "old-session"
    assert (
        post("confirm", {"draft": expired, "confirmed": True, "attested": True}, 400)["code"]
        == "session_expired"
    )
    draft["candidate"]["full_name"] = "Alex Example"

    def export(d):
        return {"draft": d, "confirmed": True, "contact": d["candidate"]}

    post("cv-drafts/export/pdf", export(draft), 400)
    forged = copy.deepcopy(draft)
    for s in forged["sections"]:
        for i in s["items"]:
            i["review_status"] = "approved"
    post("cv-drafts/export/pdf", export(forged), 400)
    post("confirm", {"draft": draft, "confirmed": False, "attested": True}, 400)
    draft = post("confirm", {"draft": draft, "confirmed": True, "attested": True})["draft"]
    for mutation in ("text", "contact", "order", "baseline"):
        altered = copy.deepcopy(draft)
        if mutation == "text":
            altered["sections"][0]["items"][0]["text"] = "Invented employment"
        elif mutation == "contact":
            altered["candidate"]["full_name"] = "Other Candidate"
        elif mutation == "order":
            altered["sections"].reverse()
        else:
            altered["review"]["baseline"]["sections"][0]["items"][0]["text"] = "Forged source"
        post("cv-drafts/export/pdf", export(altered), 400)
    item = draft["sections"][0]["items"][0]
    draft = post(
        "cv-drafts/edit", {"draft": draft, "item_id": item["item_id"], "text": item["text"] + " "}
    )["draft"]
    post("cv-drafts/export/docx", export(draft), 400)
    post("confirm", {"draft": draft, "confirmed": True, "attested": False}, 400)
    draft = post("confirm", {"draft": draft, "confirmed": True, "attested": True})["draft"]
    assert draft["review"]["approvals"][item["item_id"]]["mode"] == "candidate_attested"
    output = Path(".integration-verification/simple-demo")
    output.mkdir(parents=True, exist_ok=True)
    contents = []
    for kind in ("pdf", "docx"):
        data = post("cv-drafts/export/" + kind, export(draft))
        (output / ("tailored-cv." + kind)).write_bytes(data)
        text = (
            "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)
            if kind == "pdf"
            else "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
        )
        for expected in ("Alex Example", "Python", "30%", "2020-2022", "Fictional Harbor", "Atlas"):
            assert expected in text
        assert "Kubernetes" not in text and "C1" not in text and "B2" not in text
        headings = [s["title"] for s in draft["sections"] if s["items"]]
        assert [line for line in text.splitlines() if line in headings] == headings
        contents.append(text)
    (output / "fictional.pdf").write_bytes(pdf)
    (output / "fictional.docx").write_bytes(docx)
    assert b"Generate my CV" in request(port, "GET", "/")[2]
    for path in (
        "/workspace/fixtures/profile-synthetic.json",
        "/src/joblens_public/cv.py",
        "/.env",
    ):
        assert request(port, "GET", path)[0] == 404
    result = subprocess.run(
        [
            "node",
            "tests/ui/simple-http.mjs",
            f"http://127.0.0.1:{port}",
            str(output / "fictional.pdf"),
            str(output / "fictional.docx"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
