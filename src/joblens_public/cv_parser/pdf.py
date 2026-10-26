"""PDF text extraction with page-level provenance.

Only text is extracted. Layout reconstruction, OCR, language detection and
skill inference are deliberately out of scope.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

from pypdf import PdfReader

from .models import (
    DocumentFormat,
    ExtractedSegment,
    Extraction,
    ExtractionStatus,
    ExtractionWarning,
    ParseLimits,
    WarningCode,
    warning,
)


def _normalise_page_text(text: str) -> str:
    """Normalise line endings and trailing whitespace without reflowing text."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalised.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _resolve(value: Any) -> Any:
    getter = getattr(value, "get_object", None)
    return getter() if callable(getter) else value


def _page_has_image(page: Any) -> bool:
    """Best-effort check used only to distinguish scanned PDFs from blank ones."""
    resources = _resolve(page.get("/Resources"))
    if not isinstance(resources, dict):
        return False
    xobjects = _resolve(resources.get("/XObject"))
    if not isinstance(xobjects, dict):
        return False
    for reference in xobjects.values():
        obj = _resolve(reference)
        if isinstance(obj, dict) and obj.get("/Subtype") == "/Image":
            return True
    return False


def _empty_pdf_result(code: WarningCode, *, page_count: int | None) -> Extraction:
    return Extraction(
        document_format=DocumentFormat.PDF,
        status=ExtractionStatus.EMPTY,
        warnings=(warning(code),),
        page_count=page_count,
    )


def extract_pdf(data: bytes, limits: ParseLimits) -> Extraction:
    """Extract page text from an in-memory PDF.

    Corrupt input is reported as a structured ``malformed`` result. Exception
    text is never copied into the response because it can contain local paths.
    """
    try:
        reader = PdfReader(BytesIO(data), strict=False)
    except Exception:
        return Extraction(
            document_format=DocumentFormat.PDF,
            status=ExtractionStatus.MALFORMED,
            warnings=(warning(WarningCode.MALFORMED_DOCUMENT),),
        )

    try:
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if not unlocked:
                return Extraction(
                    document_format=DocumentFormat.PDF,
                    status=ExtractionStatus.ENCRYPTED,
                    warnings=(warning(WarningCode.PDF_ENCRYPTED),),
                )
        page_count = len(reader.pages)
    except Exception:
        return Extraction(
            document_format=DocumentFormat.PDF,
            status=ExtractionStatus.MALFORMED,
            warnings=(warning(WarningCode.MALFORMED_DOCUMENT),),
        )

    if page_count == 0:
        return _empty_pdf_result(WarningCode.EMPTY_PDF, page_count=0)

    processed = min(page_count, limits.max_pdf_pages)
    segments: list[ExtractedSegment] = []
    warnings: list[ExtractionWarning] = []
    pages_without_text = 0
    failed_pages = 0
    has_image = False

    if processed < page_count:
        warnings.append(
            warning(WarningCode.PAGE_LIMIT_REACHED, limit=limits.max_pdf_pages)
        )

    for index in range(processed):
        try:
            page = reader.pages[index]
        except Exception:
            failed_pages += 1
            continue

        try:
            if _page_has_image(page):
                has_image = True
        except Exception:
            pass

        try:
            raw_text = page.extract_text() or ""
        except Exception:
            failed_pages += 1
            continue
        if not isinstance(raw_text, str):
            raw_text = ""

        text = _normalise_page_text(raw_text)
        if text:
            segments.append(
                ExtractedSegment(locator={"kind": "page", "page": index + 1}, text=text)
            )
        else:
            pages_without_text += 1

    if failed_pages:
        warnings.append(
            warning(WarningCode.PAGE_EXTRACTION_FAILED, count=failed_pages)
        )

    if not segments:
        if failed_pages == processed:
            warnings.append(warning(WarningCode.MALFORMED_DOCUMENT))
            return Extraction(
                document_format=DocumentFormat.PDF,
                status=ExtractionStatus.MALFORMED,
                warnings=tuple(warnings),
                page_count=page_count,
            )
        if has_image:
            warnings.append(warning(WarningCode.SCANNED_PDF))
            return Extraction(
                document_format=DocumentFormat.PDF,
                status=ExtractionStatus.SCANNED_PDF,
                warnings=tuple(warnings),
                page_count=page_count,
            )
        warnings.append(warning(WarningCode.EMPTY_DOCUMENT))
        return Extraction(
            document_format=DocumentFormat.PDF,
            status=ExtractionStatus.EMPTY,
            warnings=tuple(warnings),
            page_count=page_count,
        )

    if pages_without_text:
        warnings.append(
            warning(WarningCode.PAGES_WITHOUT_TEXT, count=pages_without_text)
        )

    return Extraction(
        document_format=DocumentFormat.PDF,
        status=ExtractionStatus.EXTRACTED,
        segments=tuple(segments),
        warnings=tuple(warnings),
        page_count=page_count,
    )
