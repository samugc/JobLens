"""Batch orchestration and the stable JSON response contract.

The response is transport-agnostic and JSON-serialisable. It contains only
basenames, extracted text, provenance locators, statuses and fixed warnings.
It never contains local paths, exception messages or evidence assessments.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from .docx import extract_docx
from .models import (
    DEFAULT_LIMITS,
    SCHEMA_VERSION,
    BatchStatus,
    DocumentFormat,
    ExtractedSegment,
    Extraction,
    ExtractionStatus,
    ParseLimits,
    UploadDocument,
    WarningCode,
    warning,
)
from .pdf import extract_pdf

PDF_MAGIC = b"%PDF-"
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FORMAT_BY_EXTENSION = {".pdf": DocumentFormat.PDF, ".docx": DocumentFormat.DOCX}
STATUS_ORDER = tuple(status.value for status in ExtractionStatus)
PARTIAL_WARNING_CODES = frozenset(
    {
        WarningCode.PAGES_WITHOUT_TEXT,
        WarningCode.PAGE_EXTRACTION_FAILED,
        WarningCode.PAGE_LIMIT_REACHED,
        WarningCode.PARAGRAPH_LIMIT_REACHED,
        WarningCode.TEXT_TRUNCATED,
    }
)


def _safe_filename(filename: str) -> str:
    """Return a basename only, with no path components or control characters."""
    if not isinstance(filename, str):
        raise TypeError("filename must be a string")
    value = filename.replace("\\", "/").rsplit("/", 1)[-1]
    value = re.sub(r"^[A-Za-z]:", "", value)
    value = unicodedata.normalize("NFC", value)
    value = "".join(
        character
        for character in value
        if character.isprintable() and character not in {"\x00", "\x7f"}
    ).strip()
    if not value or value in {".", ".."}:
        return "document"
    return value[:200]


def _extension(filename: str) -> str:
    lowered = filename.casefold()
    dot = lowered.rfind(".")
    return lowered[dot:] if dot >= 0 else ""


def _signature(data: bytes) -> str:
    if data.startswith(ZIP_MAGICS):
        return "zip"
    if PDF_MAGIC in data[:1024]:
        return "pdf"
    if data.startswith(OLE_MAGIC):
        return "ole"
    return "unknown"


def _empty_extraction(
    document_format: DocumentFormat,
    code: WarningCode,
) -> Extraction:
    return Extraction(
        document_format=document_format,
        status=ExtractionStatus.EMPTY,
        warnings=(warning(code),),
        page_count=0 if document_format is DocumentFormat.PDF else None,
        paragraph_count=0 if document_format is DocumentFormat.DOCX else None,
    )


def _extract_one(
    filename: str,
    data: bytes,
    limits: ParseLimits,
) -> Extraction:
    format_hint = FORMAT_BY_EXTENSION.get(_extension(filename))

    if len(data) > limits.max_file_bytes:
        return Extraction(
            document_format=format_hint or DocumentFormat.UNKNOWN,
            status=ExtractionStatus.TOO_LARGE,
            warnings=(
                warning(WarningCode.DOCUMENT_TOO_LARGE, limit=limits.max_file_bytes),
            ),
        )

    if not data:
        return _empty_extraction(
            format_hint or DocumentFormat.UNKNOWN,
            WarningCode.EMPTY_DOCUMENT,
        )

    signature = _signature(data)
    if signature == "pdf":
        result = extract_pdf(data, limits)
    elif signature == "zip":
        result = extract_docx(data, limits)
    elif signature == "ole":
        result = Extraction(
            document_format=DocumentFormat.UNKNOWN,
            status=ExtractionStatus.UNSUPPORTED_FORMAT,
            warnings=(warning(WarningCode.LEGACY_DOC),),
        )
    elif format_hint is not None:
        result = Extraction(
            document_format=format_hint,
            status=ExtractionStatus.MALFORMED,
            warnings=(warning(WarningCode.MALFORMED_DOCUMENT),),
        )
    else:
        result = Extraction(
            document_format=DocumentFormat.UNKNOWN,
            status=ExtractionStatus.UNSUPPORTED_FORMAT,
            warnings=(warning(WarningCode.UNSUPPORTED_FORMAT),),
        )

    if (
        format_hint is not None
        and result.document_format in {DocumentFormat.PDF, DocumentFormat.DOCX}
        and result.document_format is not format_hint
    ):
        result = Extraction(
            document_format=result.document_format,
            status=result.status,
            segments=result.segments,
            warnings=(*result.warnings, warning(WarningCode.FORMAT_MISMATCH)),
            page_count=result.page_count,
            paragraph_count=result.paragraph_count,
        )
    return result


def _truncate_segments(
    segments: tuple[ExtractedSegment, ...],
    max_chars: int,
) -> tuple[tuple[ExtractedSegment, ...], bool]:
    kept: list[ExtractedSegment] = []
    used = 0
    for segment in segments:
        separator = 2 if kept else 0
        available = max_chars - used - separator
        if available <= 0:
            return tuple(kept), True
        if len(segment.text) > available:
            piece = segment.text[:available].rstrip()
            if piece:
                kept.append(ExtractedSegment(locator=dict(segment.locator), text=piece))
            return tuple(kept), True
        kept.append(
            ExtractedSegment(locator=dict(segment.locator), text=segment.text)
        )
        used += separator + len(segment.text)
    return tuple(kept), False


def _document_payload(
    *,
    index: int,
    filename: str,
    size_bytes: int,
    result: Extraction,
    limits: ParseLimits,
) -> dict[str, Any]:
    segments, truncated = _truncate_segments(result.segments, limits.max_text_chars)
    warnings = list(result.warnings)
    if truncated:
        warnings.append(warning(WarningCode.TEXT_TRUNCATED, limit=limits.max_text_chars))

    serialised_segments = [
        {"locator": dict(segment.locator), "text": segment.text} for segment in segments
    ]
    text = "\n\n".join(segment.text for segment in segments)

    document_status = result.status
    if document_status is ExtractionStatus.EXTRACTED and any(
        item.code in PARTIAL_WARNING_CODES for item in warnings
    ):
        document_status = ExtractionStatus.PARTIAL

    return {
        "index": index,
        "filename": filename,
        "format": result.document_format.value,
        "status": document_status.value,
        "text": text,
        "segments": serialised_segments,
        "warnings": [
            {"code": item.code.value, "message": item.message} for item in warnings
        ],
        "metadata": {
            "size_bytes": size_bytes,
            "page_count": result.page_count,
            "paragraph_count": result.paragraph_count,
        },
    }


def _normalise_uploads(documents: Iterable[UploadDocument]) -> list[UploadDocument]:
    try:
        items = list(documents)
    except TypeError as error:
        raise TypeError("documents must be an iterable of UploadDocument") from error

    normalised: list[UploadDocument] = []
    for item in items:
        if not isinstance(item, UploadDocument):
            raise TypeError("documents must contain UploadDocument instances")
        if not isinstance(item.filename, str):
            raise TypeError("document filename must be a string")
        if not isinstance(item.data, (bytes, bytearray, memoryview)):
            raise TypeError("document data must be bytes")
        normalised.append(
            UploadDocument(
                filename=item.filename,
                data=item.data if isinstance(item.data, bytes) else bytes(item.data),
            )
        )
    return normalised


def _zero_status_counts() -> dict[str, int]:
    return {status: 0 for status in STATUS_ORDER}


def _rejected_batch(
    *,
    code: str,
    message: str,
    document_count: int,
    total_bytes: int,
    limits: ParseLimits,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "batch": {
            "status": BatchStatus.REJECTED.value,
            "document_count": document_count,
            "total_bytes": total_bytes,
            "status_counts": _zero_status_counts(),
            "limits": limits.as_dict(),
            "error": {"code": code, "message": message},
        },
        "documents": [],
    }


def extract_batch(
    documents: Iterable[UploadDocument],
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
) -> dict[str, Any]:
    """Extract up to ``limits.max_documents`` CVs and return the JSON contract.

    Per-document failures are returned in ``documents`` with a status and
    warnings. Batch-level problems (empty batch, too many documents, total byte
    limit) produce a rejected batch with no partial results.
    """
    if not isinstance(limits, ParseLimits):
        raise TypeError("limits must be a ParseLimits instance")

    uploads = _normalise_uploads(documents)
    total_bytes = sum(len(upload.data) for upload in uploads)

    if not uploads:
        return _rejected_batch(
            code="empty_batch",
            message="A batch must contain at least one document.",
            document_count=0,
            total_bytes=0,
            limits=limits,
        )
    if len(uploads) > limits.max_documents:
        return _rejected_batch(
            code="too_many_documents",
            message="A batch may contain at most {limit} documents.".format(
                limit=limits.max_documents
            ),
            document_count=len(uploads),
            total_bytes=total_bytes,
            limits=limits,
        )
    if total_bytes > limits.max_batch_bytes:
        return _rejected_batch(
            code="batch_too_large",
            message="The batch exceeds the configured total size limit.",
            document_count=len(uploads),
            total_bytes=total_bytes,
            limits=limits,
        )

    results: list[dict[str, Any]] = []
    status_counts = _zero_status_counts()
    for index, upload in enumerate(uploads):
        filename = _safe_filename(upload.filename)
        extraction = _extract_one(filename, upload.data, limits)
        payload = _document_payload(
            index=index,
            filename=filename,
            size_bytes=len(upload.data),
            result=extraction,
            limits=limits,
        )
        results.append(payload)
        status_counts[payload["status"]] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "batch": {
            "status": (
                BatchStatus.COMPLETED.value
                if all(
                    document["status"] == ExtractionStatus.EXTRACTED.value
                    for document in results
                )
                else BatchStatus.PARTIAL.value
            ),
            "document_count": len(results),
            "total_bytes": total_bytes,
            "status_counts": status_counts,
            "limits": limits.as_dict(),
            "error": None,
        },
        "documents": results,
    }


def extract_document(
    filename: str,
    data: bytes,
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
) -> dict[str, Any]:
    """Extract one in-memory document using the same per-document contract."""
    if not isinstance(limits, ParseLimits):
        raise TypeError("limits must be a ParseLimits instance")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes")

    safe_name = _safe_filename(filename)
    raw = bytes(data)
    extraction = _extract_one(safe_name, raw, limits)
    return _document_payload(
        index=0,
        filename=safe_name,
        size_bytes=len(raw),
        result=extraction,
        limits=limits,
    )
