"""Synthetic PDF/DOCX builders used by the parser tests.

No real CVs, names, contact details or committed binary fixtures are used.
Everything is generated in memory at test time.
"""
from __future__ import annotations

import io
from collections.abc import Iterable, Sequence
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfReader, PdfWriter

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _text_stream(lines: Sequence[str], *, x: int = 72, y: int = 720) -> bytes:
    operations = ["BT", "/F1 12 Tf", f"{x} {y} Td"]
    for index, line in enumerate(lines):
        if index:
            operations.append("0 -16 Td")
        operations.append(f"({_pdf_escape(line)}) Tj")
    operations.append("ET")
    return "\n".join(operations).encode("latin-1")


def make_pdf(
    pages: Sequence[Sequence[str]],
    *,
    image_pages: Iterable[int] = (),
    streams: Sequence[bytes] | None = None,
) -> bytes:
    """Build a minimal valid PDF.

    ``image_pages`` are 0-based page indexes. ``streams`` optionally replaces the
    generated text content for each page, which lets tests exercise adversarial
    layouts such as two-column pages.
    """
    if streams is not None and len(streams) != len(pages):
        raise ValueError("streams must have one entry per page")
    image_indexes = set(image_pages)
    objects: dict[int, bytes] = {}
    next_number = 4  # 1 catalog, 2 pages, 3 shared font

    page_numbers: list[int] = []
    page_bodies: list[tuple[int, bytes]] = []
    content_objects: list[tuple[int, bytes]] = []
    image_objects: list[tuple[int, bytes]] = []

    for page_index, lines in enumerate(pages):
        page_number = next_number
        next_number += 1
        page_numbers.append(page_number)

        has_image = page_index in image_indexes
        resources: list[str] = []
        content_parts: list[bytes] = []

        if streams is not None:
            resources.append("/Font << /F1 3 0 R >>")
            content_parts.append(streams[page_index])
        elif lines:
            resources.append("/Font << /F1 3 0 R >>")
            content_parts.append(_text_stream(lines))
        if has_image:
            image_number = next_number
            next_number += 1
            resources.append(f"/XObject << /Im0 {image_number} 0 R >>")
            content_parts.append(b"q 100 0 0 100 72 600 cm /Im0 Do Q")
            image_objects.append(
                (
                    image_number,
                    b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
                    b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >>\n"
                    b"stream\n\x80\nendstream",
                )
            )

        content_reference = ""
        if content_parts:
            content_number = next_number
            next_number += 1
            stream = b"\n".join(content_parts)
            content_objects.append(
                (
                    content_number,
                    b"<< /Length %d >>\nstream\n" % len(stream)
                    + stream
                    + b"\nendstream",
                )
            )
            content_reference = f"/Contents {content_number} 0 R"

        resource_dictionary = f"<< {' '.join(resources)} >>" if resources else "<< >>"
        page_bodies.append(
            (
                page_number,
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources {resource_dictionary} {content_reference} >>"
                ).encode("latin-1"),
            )
        )

    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for number, body in page_bodies + content_objects + image_objects:
        objects[number] = body

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = output.tell()
        output.write(b"%d 0 obj\n" % number)
        output.write(objects[number])
        output.write(b"\nendobj\n")

    xref_offset = output.tell()
    size = max(objects) + 1
    output.write(b"xref\n0 %d\n" % size)
    output.write(b"0000000000 65535 f \n")
    for number in range(1, size):
        output.write(b"%010d 00000 n \n" % offsets.get(number, 0))
    output.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (size, xref_offset)
    )
    return output.getvalue()


def encrypt_pdf(data: bytes, password: str = "synthetic-password") -> bytes:
    reader = PdfReader(io.BytesIO(data), strict=False)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(password)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def make_two_column_pdf(
    left_column: Sequence[str],
    right_column: Sequence[str],
) -> bytes:
    """Build a one-page PDF with two visual columns in the content stream."""
    stream = b"\n".join(
        (
            _text_stream(left_column, x=72, y=720),
            _text_stream(right_column, x=320, y=720),
        )
    )
    return make_pdf([[]], streams=[stream])


def _paragraph_xml(
    text: str,
    style: str | None,
    *,
    list_item: bool = False,
) -> str:
    property_parts: list[str] = []
    if style:
        property_parts.append(f'<w:pStyle w:val="{escape(style)}"/>')
    if list_item:
        property_parts.append(
            '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
        )
    properties = (
        f"<w:pPr>{''.join(property_parts)}</w:pPr>" if property_parts else ""
    )
    if not text:
        return f"<w:p>{properties}</w:p>"
    return (
        f"<w:p>{properties}<w:r><w:t xml:space=\"preserve\">"
        f"{escape(text)}</w:t></w:r></w:p>"
    )


def make_docx(
    paragraphs: Sequence[tuple[str, str | None]] = (),
    *,
    list_items: Sequence[str] = (),
    table_rows: Sequence[Sequence[str]] = (),
    document_xml: bytes | None = None,
    include_document: bool = True,
) -> bytes:
    """Build a minimal synthetic DOCX with headings, lists, tables and raw XML."""
    body_parts = [_paragraph_xml(text, style) for text, style in paragraphs]
    body_parts.extend(
        _paragraph_xml(item, "ListParagraph", list_item=True) for item in list_items
    )
    for row in table_rows:
        cells = "".join(
            f"<w:tc>{_paragraph_xml(cell, None)}</w:tc>" for cell in row
        )
        body_parts.append(f"<w:tbl><w:tr>{cells}</w:tr></w:tbl>")
    body_parts.append("<w:sectPr/>")

    if document_xml is None:
        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body>'
            + "".join(body_parts)
            + "</w:body></w:document>"
        ).encode("utf-8")

    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        if include_document:
            archive.writestr("word/document.xml", document_xml)
    return output.getvalue()


def make_non_word_zip() -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return output.getvalue()


def make_legacy_doc() -> bytes:
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32
