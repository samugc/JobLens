"""DOCX text extraction with paragraph and heading provenance.

The extractor reads ``word/document.xml`` directly with the standard library.
It does not unzip embedded media, run macros, resolve external entities or
extract headers and footers. "Section" means the nearest preceding Word
heading paragraph, not a page-layout section break.
"""
from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree
from xml.parsers import expat
from zipfile import BadZipFile, ZipFile

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

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W_BODY = f"{{{WORD_NS}}}body"
W_P = f"{{{WORD_NS}}}p"
W_PPR = f"{{{WORD_NS}}}pPr"
W_PSTYLE = f"{{{WORD_NS}}}pStyle"
W_OUTLINE_LVL = f"{{{WORD_NS}}}outlineLvl"
W_T = f"{{{WORD_NS}}}t"
W_TAB = f"{{{WORD_NS}}}tab"
W_BR = f"{{{WORD_NS}}}br"
W_CR = f"{{{WORD_NS}}}cr"
W_NO_BREAK_HYPHEN = f"{{{WORD_NS}}}noBreakHyphen"
W_VAL = f"{{{WORD_NS}}}val"

DOCUMENT_XML = "word/document.xml"
CONTENT_TYPES_XML = "[Content_Types].xml"
HEADING_STYLE_PREFIXES = ("heading", "titre", "titel", "überschrift")


def _malformed() -> Extraction:
    return Extraction(
        document_format=DocumentFormat.DOCX,
        status=ExtractionStatus.MALFORMED,
        warnings=(warning(WarningCode.MALFORMED_DOCUMENT),),
    )


def _unsupported() -> Extraction:
    return Extraction(
        document_format=DocumentFormat.UNKNOWN,
        status=ExtractionStatus.UNSUPPORTED_FORMAT,
        warnings=(warning(WarningCode.NON_WORD_OOXML),),
    )


def _normalise_paragraph_text(text: str) -> str:
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalised.split("\n")]
    return "\n".join(lines).strip()


def _collect_paragraph_text(node: ElementTree.Element, parts: list[str]) -> None:
    """Collect runs while skipping nested paragraphs (e.g. text boxes).

    Nested paragraphs are visited separately in document order, so their text
    is not counted twice.
    """
    for child in node:
        if child.tag == W_P:
            continue
        if child.tag == W_T:
            parts.append(child.text or "")
        elif child.tag == W_TAB:
            parts.append("\t")
        elif child.tag in (W_BR, W_CR):
            parts.append("\n")
        elif child.tag == W_NO_BREAK_HYPHEN:
            parts.append("-")
        else:
            _collect_paragraph_text(child, parts)


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    _collect_paragraph_text(paragraph, parts)
    return _normalise_paragraph_text("".join(parts))


def _is_heading(paragraph: ElementTree.Element) -> bool:
    properties = paragraph.find(W_PPR)
    if properties is None:
        return False

    style = properties.find(W_PSTYLE)
    if style is not None:
        style_name = (style.get(W_VAL) or "").strip().casefold()
        if style_name.startswith(HEADING_STYLE_PREFIXES):
            return True

    outline = properties.find(W_OUTLINE_LVL)
    if outline is not None:
        value = (outline.get(W_VAL) or "").strip()
        if value.isdecimal() and 0 <= int(value) <= 8:
            return True
    return False


def _read_document_xml(
    data: bytes,
    limits: ParseLimits,
) -> tuple[bytes | None, Extraction | None]:
    try:
        archive = ZipFile(BytesIO(data))
    except (BadZipFile, OSError, ValueError):
        return None, _malformed()
    with archive:
        try:
            names = set(archive.namelist())
        except Exception:
            return None, _malformed()

        if DOCUMENT_XML not in names:
            if CONTENT_TYPES_XML in names:
                return None, _unsupported()
            return None, _malformed()

        try:
            info = archive.getinfo(DOCUMENT_XML)
        except KeyError:
            return None, _malformed()

        if info.file_size > limits.max_docx_xml_bytes:
            return None, Extraction(
                document_format=DocumentFormat.DOCX,
                status=ExtractionStatus.TOO_LARGE,
                warnings=(
                    warning(
                        WarningCode.DOCUMENT_TOO_LARGE,
                        limit=limits.max_docx_xml_bytes,
                    ),
                ),
            )

        try:
            xml_bytes = archive.read(info)
        except Exception:
            return None, _malformed()

    return xml_bytes, None


class _UnsafeXml(ValueError):
    """Raised when a DOCX XML part declares a DTD or entities."""


def _xml_declarations_are_safe(xml_bytes: bytes) -> bool:
    """Reject DTDs and entity declarations before building a tree.

    Expat honours XML encoding declarations, so a UTF-16 document cannot bypass
    the check the way a raw byte search could.
    """

    parser = expat.ParserCreate()

    def reject_declaration(*_args: object) -> None:
        raise _UnsafeXml

    parser.StartDoctypeDeclHandler = reject_declaration
    parser.EntityDeclHandler = reject_declaration

    try:
        parser.Parse(xml_bytes, True)
    except _UnsafeXml:
        return False
    except (expat.ExpatError, UnicodeError, ValueError, LookupError):
        return False
    return True


def extract_docx(data: bytes, limits: ParseLimits) -> Extraction:
    """Extract body paragraphs and their nearest heading from an in-memory DOCX."""
    xml_bytes, failure = _read_document_xml(data, limits)
    if failure is not None:
        return failure
    assert xml_bytes is not None

    if not _xml_declarations_are_safe(xml_bytes):
        return _malformed()

    try:
        root = ElementTree.fromstring(xml_bytes)
    except Exception:
        return _malformed()

    body = root.find(W_BODY)
    if body is None:
        return _malformed()

    paragraphs = list(body.iter(W_P))
    paragraph_count = len(paragraphs)
    processed = paragraphs[: limits.max_docx_paragraphs]
    segments: list[ExtractedSegment] = []
    warnings: list[ExtractionWarning] = []
    current_section: str | None = None

    if paragraph_count > len(processed):
        warnings.append(
            warning(
                WarningCode.PARAGRAPH_LIMIT_REACHED,
                limit=limits.max_docx_paragraphs,
            )
        )

    for index, paragraph in enumerate(processed, start=1):
        text = _paragraph_text(paragraph)
        if not text:
            continue

        if _is_heading(paragraph):
            current_section = text
        segments.append(
            ExtractedSegment(
                locator={
                    "kind": "paragraph",
                    "paragraph": index,
                    "section": current_section,
                },
                text=text,
            )
        )

    if not segments:
        code = (
            WarningCode.NO_BODY_PARAGRAPHS
            if paragraph_count == 0
            else WarningCode.EMPTY_DOCUMENT
        )
        warnings.append(warning(code))
        return Extraction(
            document_format=DocumentFormat.DOCX,
            status=ExtractionStatus.EMPTY,
            warnings=tuple(warnings),
            paragraph_count=paragraph_count,
        )

    return Extraction(
        document_format=DocumentFormat.DOCX,
        status=ExtractionStatus.EXTRACTED,
        segments=tuple(segments),
        warnings=tuple(warnings),
        paragraph_count=paragraph_count,
    )
