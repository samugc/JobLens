"""Regression for experience contributions after a leading-space role line.

The original fictional CVs are extracted with a leading space before the role
line. Evidence offsets point at that whitespace, while the provisional
following-line logic used to compare against the first non-space character.
The comparison failed, so the contribution lines were never attached.

This test builds an equivalent synthetic PDF in memory. It is deliberately
independent of the owner's Downloads directory.
"""
from __future__ import annotations

import http.client
import io
import json
import re

from cv_builders import make_pdf
from docx import Document
from pypdf import PdfReader

from joblens_public.data import load_demo_data
from joblens_public.webapp import create_server


def _request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _post_files(port, files):
    boundary = "----joblens-leading-space"
    body = bytearray()
    for filename, data in files:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="files"; '
                f'filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
        )
        body.extend(data)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    status, raw = _request(
        port,
        "POST",
        "/api/cv/extractions",
        bytes(body),
        {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-JobLens-Request": "1",
            "Origin": f"http://127.0.0.1:{port}",
        },
    )
    return status, json.loads(raw)


def _post_json(port, path, payload):
    status, raw = _request(
        port,
        "POST",
        "/api/cv/" + path,
        json.dumps(payload).encode(),
        {
            "Content-Type": "application/json",
            "X-JobLens-Request": "1",
            "Origin": f"http://127.0.0.1:{port}",
        },
    )
    assert status == 200, (path, status, raw[:400])
    return raw if path.startswith("cv-drafts/export/") else json.loads(raw)


def _source_pdf() -> bytes:
    return make_pdf(
        [
            [
                "Alex Rivera",
                "Skills",
                "Python, SQL, Git, Docker, JavaScript",
                "Experience",
                " Software Engineer",
                "Built a local Python service with REST APIs and automated tests.",
                "Documented backend APIs and tested ingestion workflows.",
                "Education",
                "BSc in Computer Science",
                "Projects",
                "Project Boreal: Prototyped document retrieval and evaluation.",
                "Languages",
                "Spanish (Native)",
                "Certifications",
                "AWS Certified Cloud Practitioner",
            ]
        ]
    )


def test_leading_space_role_keeps_consecutive_contributions(tmp_path):
    candidates, jobs = load_demo_data()
    server = create_server(candidates, jobs, 0)
    port = server.server_port
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, extraction = _post_files(
            port, [("fictional-leading-space.pdf", _source_pdf())]
        )
        assert status == 200
        source = {key: extraction[key] for key in ("job_id", "documents")}

        # The source really does carry the leading whitespace that triggered
        # the defect.
        segment_text = source["documents"][0]["segments"][0]["text"]
        assert "\n Software Engineer\n" in segment_text

        draft = _post_json(
            port,
            "draft",
            {
                "source": source,
                "text": (
                    "Junior AI Engineer. Required: Python, SQL, Git, Docker, "
                    "JavaScript, REST APIs, automated tests. Kubernetes desirable."
                ),
            },
        )["draft"]

        experience = next(
            section for section in draft["sections"] if section["title"] == "Experience"
        )
        assert len(experience["items"]) == 1
        assert experience["items"][0]["heading"] == "Software Engineer"
        assert experience["items"][0]["text"].split("; ") == [
            "Built a local Python service with REST APIs and automated tests.",
            "Documented backend APIs and tested ingestion workflows.",
        ]

        # Preview data is the draft item text; make the contract explicit.
        preview_texts = [item["text"] for item in experience["items"]]
        assert "Built a local Python service with REST APIs and automated tests." in preview_texts[0]
        assert "Documented backend APIs and tested ingestion workflows." in preview_texts[0]

        # Evidence offsets still match the extracted source exactly, including
        # the leading-space role line.
        documents = {doc["document_id"]: doc for doc in source["documents"]}
        for refs in draft["review"]["baseline"]["evidence"].values():
            for evidence in refs:
                segment = documents[evidence["document_id"]]["segments"][
                    evidence["segment_index"]
                ]
                assert segment["text"][evidence["start"] : evidence["end"]] == evidence["quote"]

        draft["candidate"]["full_name"] = "Alex Rivera"
        confirmed = _post_json(
            port, "confirm", {"draft": draft, "confirmed": True, "attested": True}
        )["draft"]

        exported = {}
        for kind in ("pdf", "docx"):
            raw = _post_json(
                port,
                "cv-drafts/export/" + kind,
                {"draft": confirmed, "confirmed": True, "contact": confirmed["candidate"]},
            )
            (tmp_path / ("tailored-cv." + kind)).write_bytes(raw)
            if kind == "pdf":
                text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(raw)).pages)
            else:
                text = "\n".join(paragraph.text for paragraph in Document(io.BytesIO(raw)).paragraphs)
            exported[kind] = text
            # PDF text extraction can wrap a bullet across lines. Compare the
            # rendered content, not the renderer's line breaks.
            flattened = re.sub(r"\s+", " ", text)
            assert "Built a local Python service with REST APIs and automated tests." in flattened
            assert "Documented backend APIs and tested ingestion workflows." in flattened
            assert "Kubernetes" not in flattened
            assert "Software Engineer; Built" not in flattened
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
