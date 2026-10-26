"""Stable data model for local CV extraction.

This module deliberately contains no evidence logic. It describes what a
document *contains*, never what a candidate claims or is able to do.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

SCHEMA_VERSION: Final = "1.1"
MAX_BATCH_DOCUMENTS: Final = 5


class DocumentFormat(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    UNKNOWN = "unknown"


class ExtractionStatus(str, Enum):
    EXTRACTED = "extracted"
    PARTIAL = "partial"
    EMPTY = "empty"
    SCANNED_PDF = "scanned_pdf"
    ENCRYPTED = "encrypted"
    MALFORMED = "malformed"
    UNSUPPORTED_FORMAT = "unsupported_format"
    TOO_LARGE = "too_large"


class BatchStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    REJECTED = "rejected"


class WarningCode(str, Enum):
    EMPTY_DOCUMENT = "empty_document"
    EMPTY_PDF = "empty_pdf"
    SCANNED_PDF = "scanned_pdf"
    PDF_ENCRYPTED = "pdf_encrypted"
    PAGES_WITHOUT_TEXT = "pages_without_text"
    PAGE_EXTRACTION_FAILED = "page_extraction_failed"
    PAGE_LIMIT_REACHED = "page_limit_reached"
    PARAGRAPH_LIMIT_REACHED = "paragraph_limit_reached"
    NO_BODY_PARAGRAPHS = "no_body_paragraphs"
    TEXT_TRUNCATED = "text_truncated"
    DOCUMENT_TOO_LARGE = "document_too_large"
    UNSUPPORTED_FORMAT = "unsupported_format"
    NON_WORD_OOXML = "non_word_ooxml"
    LEGACY_DOC = "legacy_doc"
    MALFORMED_DOCUMENT = "malformed_document"
    FORMAT_MISMATCH = "format_mismatch"


WARNING_MESSAGES: Final[dict[WarningCode, str]] = {
    WarningCode.EMPTY_DOCUMENT: "No extractable text was found in the document.",
    WarningCode.EMPTY_PDF: "The PDF contains no pages.",
    WarningCode.SCANNED_PDF: (
        "No extractable text was found; the PDF appears to be image-only or scanned."
    ),
    WarningCode.PDF_ENCRYPTED: (
        "The PDF is password-protected; remove the password before extraction."
    ),
    WarningCode.PAGES_WITHOUT_TEXT: "{count} PDF page(s) contained no extractable text.",
    WarningCode.PAGE_EXTRACTION_FAILED: "{count} PDF page(s) could not be read.",
    WarningCode.PAGE_LIMIT_REACHED: "Only the first {limit} PDF pages were read.",
    WarningCode.PARAGRAPH_LIMIT_REACHED: "Only the first {limit} DOCX paragraphs were read.",
    WarningCode.NO_BODY_PARAGRAPHS: "The DOCX file contains no body paragraphs.",
    WarningCode.TEXT_TRUNCATED: "Extracted text was truncated at {limit} characters.",
    WarningCode.DOCUMENT_TOO_LARGE: "The document exceeds the {limit}-byte size limit.",
    WarningCode.UNSUPPORTED_FORMAT: "Only PDF and DOCX documents are supported.",
    WarningCode.NON_WORD_OOXML: "The ZIP file is not a Word DOCX document.",
    WarningCode.LEGACY_DOC: (
        "Legacy Word .doc files are not supported; save the file as DOCX or PDF."
    ),
    WarningCode.MALFORMED_DOCUMENT: (
        "The document could not be read as a valid PDF or DOCX file."
    ),
    WarningCode.FORMAT_MISMATCH: (
        "The filename extension does not match the detected document content."
    ),
}


@dataclass(frozen=True, slots=True)
class ParseLimits:
    """Hard limits applied without reading document content into logs."""

    max_documents: int = MAX_BATCH_DOCUMENTS
    max_file_bytes: int = 10 * 1024 * 1024
    max_batch_bytes: int = 25 * 1024 * 1024
    max_text_chars: int = 200_000
    max_pdf_pages: int = 100
    max_docx_paragraphs: int = 20_000
    max_docx_xml_bytes: int = 10 * 1024 * 1024

    def __post_init__(self) -> None:
        values = {
            "max_documents": self.max_documents,
            "max_file_bytes": self.max_file_bytes,
            "max_batch_bytes": self.max_batch_bytes,
            "max_text_chars": self.max_text_chars,
            "max_pdf_pages": self.max_pdf_pages,
            "max_docx_paragraphs": self.max_docx_paragraphs,
            "max_docx_xml_bytes": self.max_docx_xml_bytes,
        }
        for name, value in values.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_documents > MAX_BATCH_DOCUMENTS:
            raise ValueError(
                "max_documents cannot exceed the five-document contract cap"
            )

    def as_dict(self) -> dict[str, int]:
        return {
            "max_documents": self.max_documents,
            "max_file_bytes": self.max_file_bytes,
            "max_batch_bytes": self.max_batch_bytes,
            "max_text_chars": self.max_text_chars,
            "max_pdf_pages": self.max_pdf_pages,
            "max_docx_paragraphs": self.max_docx_paragraphs,
            "max_docx_xml_bytes": self.max_docx_xml_bytes,
        }


DEFAULT_LIMITS: Final = ParseLimits()


@dataclass(frozen=True, slots=True)
class UploadDocument:
    """One in-memory upload. No filesystem path is ever part of this model."""

    filename: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ExtractedSegment:
    """A piece of text with a stable, non-filesystem source locator."""

    locator: dict[str, Any]
    text: str


@dataclass(frozen=True, slots=True)
class ExtractionWarning:
    code: WarningCode
    message: str


@dataclass(frozen=True, slots=True)
class Extraction:
    """Internal parser result before serialisation and text truncation."""

    document_format: DocumentFormat
    status: ExtractionStatus
    segments: tuple[ExtractedSegment, ...] = ()
    warnings: tuple[ExtractionWarning, ...] = ()
    page_count: int | None = None
    paragraph_count: int | None = None


def warning(code: WarningCode, **values: int) -> ExtractionWarning:
    """Build a fixed warning message. Only numeric details are interpolated."""
    return ExtractionWarning(code=code, message=WARNING_MESSAGES[code].format(**values))
