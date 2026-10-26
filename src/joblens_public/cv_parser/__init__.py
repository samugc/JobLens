"""Local, evidence-neutral CV extraction for JobLens 2.0.

Public API:
    extract_batch(documents) -> JSON-ready batch response
    extract_document(filename, data) -> JSON-ready document response
    UploadDocument(filename, data)
    ParseLimits / DEFAULT_LIMITS

Extraction never evaluates evidence, infers skills or attests claims.

The extraction functions are imported lazily. They need ``pypdf``, and the
HTTP transport does not, so ``joblens_public.cv_parser.http_transport`` stays
importable in an environment without ``pypdf``. A host application can then
mount the transport and answer ``503 parser_unavailable`` instead of failing
to start.
"""
from __future__ import annotations

from typing import Any

from .models import (
    DEFAULT_LIMITS,
    SCHEMA_VERSION,
    BatchStatus,
    DocumentFormat,
    ExtractionStatus,
    ParseLimits,
    UploadDocument,
    WarningCode,
)

__all__ = [
    "DEFAULT_LIMITS",
    "SCHEMA_VERSION",
    "BatchStatus",
    "DocumentFormat",
    "ExtractionStatus",
    "ParseLimits",
    "UploadDocument",
    "WarningCode",
    "extract_batch",
    "extract_document",
]


def __getattr__(name: str) -> Any:
    """Import the extraction functions on first use."""
    if name in {"extract_batch", "extract_document"}:
        from .service import extract_batch, extract_document

        return {
            "extract_batch": extract_batch,
            "extract_document": extract_document,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
