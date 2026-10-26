"""Synthetic CV documents for the candidate profile tests.

Every document is written here by hand. No real CV, name, employer or contact
detail is used.
"""
from __future__ import annotations

from typing import Any, Sequence

SEGMENTS: list[dict[str, Any]] = []


def make_segment(text: str, *, paragraph: int = 1) -> dict[str, Any]:
    return {
        "locator": {"kind": "paragraph", "paragraph": paragraph},
        "text": text,
    }


def make_document(
    document_id: str,
    text: str,
    *,
    index: int = 0,
    filename: str = "synthetic-cv.pdf",
    status: str = "extracted",
    document_format: str = "pdf",
    segments: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one document in the shape the HTTP transport returns."""
    used = list(segments) if segments is not None else [make_segment(text)]
    return {
        "document_id": document_id,
        "index": index,
        "filename": filename,
        "format": document_format,
        "status": status,
        "text": text,
        "segments": used,
        "warnings": [],
        "metadata": {
            "size_bytes": len(text),
            "page_count": len(used),
            "paragraph_count": None,
        },
    }


def make_response(
    documents: Sequence[dict[str, Any]],
    *,
    job_id: str = "job_synthetic",
) -> dict[str, Any]:
    """Build a transport response around the given documents."""
    return {
        "transport_version": "1.0",
        "schema_version": "1.1",
        "job_id": job_id,
        "batch": {
            "status": "completed",
            "document_count": len(documents),
            "total_bytes": sum(document["metadata"]["size_bytes"] for document in documents),
            "status_counts": {},
            "limits": {},
            "error": None,
        },
        "documents": list(documents),
    }


SKILLS_SECTION = """Skills
Python, SQL, Docker, Kubernetes
"""

EXPERIENCE_SECTION = """Experience
Senior Data Engineer | Acme Corporation | 2020-2023
Backend Engineer - Globex Industries
"""

EDUCATION_SECTION = """Education
BSc in Computer Science, University of Manchester
MSc Data Science
"""

PROJECTS_SECTION = """Projects
CV Evidence Workspace - a local HTTP transport
Invoice Tracker: a small billing application
"""

CERTIFICATIONS_SECTION = """Certifications
AWS Certified Solutions Architect
"""

LANGUAGES_SECTION = """Languages
English (C1), Spanish (B2)
"""


def full_cv() -> str:
    """A synthetic CV with one section per recognised heading."""
    return "\n".join(
        [
            SKILLS_SECTION.rstrip("\n"),
            EXPERIENCE_SECTION.rstrip("\n"),
            EDUCATION_SECTION.rstrip("\n"),
            PROJECTS_SECTION.rstrip("\n"),
            CERTIFICATIONS_SECTION.rstrip("\n"),
            LANGUAGES_SECTION.rstrip("\n"),
        ]
    )
