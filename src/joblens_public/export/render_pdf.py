"""ReportLab-based PDF renderer."""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import CanonicalDraft, CanonicalItem, CanonicalSection
from .utils import (
    clean_period,
    link_label,
    normalize_url,
    page_size_from_name,
    register_reportlab_font,
)

ACCENT = colors.HexColor("#0F766E")
GREY = colors.HexColor("#444444")


def _bold_name(font: str) -> str:
    from reportlab.pdfbase import pdfmetrics

    cand = font + "-Bold"
    try:
        pdfmetrics.getFont(cand)
        return cand
    except KeyError:
        return "Helvetica-Bold"


def _font_names() -> tuple[str, str]:
    font = register_reportlab_font()
    return font, _bold_name(font)


BASE_FONT, BOLD_FONT = _font_names()


def _styles(font: str, bold: str) -> dict[str, ParagraphStyle]:
    return {
        "name": ParagraphStyle(
            "name",
            fontName=bold,
            fontSize=17,
            leading=20,
            alignment=TA_CENTER,
            spaceAfter=2,
            textColor=colors.black,
        ),
        "headline": ParagraphStyle(
            "headline",
            fontName=bold,
            fontSize=11,
            leading=13,
            alignment=TA_CENTER,
            spaceAfter=2,
            textColor=ACCENT,
        ),
        "contact": ParagraphStyle(
            "contact",
            fontName=font,
            fontSize=9,
            leading=11,
            alignment=TA_CENTER,
            spaceAfter=6,
            textColor=GREY,
        ),
        "section": ParagraphStyle(
            "section",
            fontName=bold,
            fontSize=11.5,
            leading=14,
            spaceBefore=9,
            spaceAfter=4,
            textColor=ACCENT,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=font,
            fontSize=10,
            leading=12.5,
            alignment=TA_LEFT,
            spaceAfter=3,
        ),
        "entry_heading": ParagraphStyle(
            "entry_heading",
            fontName=bold,
            fontSize=10,
            leading=12.5,
            spaceAfter=0,
            keepWithNext=True,
        ),
        "entry_sub": ParagraphStyle(
            "entry_sub",
            fontName=font,
            fontSize=10,
            leading=12.5,
            spaceAfter=2,
            textColor=GREY,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            fontName=font,
            fontSize=10,
            leading=12.5,
            leftIndent=1.2 * 28.346,  # 1.2em approx
            firstLineIndent=-1.2 * 28.346,
            spaceAfter=1.5,
            alignment=TA_LEFT,
        ),
        "small": ParagraphStyle(
            "small",
            fontName=font,
            fontSize=9,
            leading=11,
            spaceAfter=2,
        ),
    }


STYLES = _styles(BASE_FONT, BOLD_FONT)


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _link(url: str) -> str:
    href = normalize_url(url)
    label = link_label(url)
    return f'<link href="{_esc(href)}" color="#0F766E"><u>{_esc(label)}</u></link>'


def _contact_paragraph(draft: CanonicalDraft) -> Paragraph | None:
    parts: list[str] = []
    c = draft.candidate
    if c.location:
        parts.append(_esc(c.location))
    if c.email:
        parts.append(f'<link href="mailto:{_esc(c.email)}" color="#0F766E">{_esc(c.email)}</link>')
    if c.phone:
        parts.append(_esc(c.phone))
    for link in c.links:
        parts.append(_link(link))
    if not parts:
        return None
    text = "  ·  ".join(parts)
    return Paragraph(text, STYLES["contact"])


def _section_title(title: str) -> list:
    return [
        Paragraph(_esc(title), STYLES["section"]),
        HRFlowable(width="100%", thickness=0.35, color=ACCENT, spaceAfter=4, spaceBefore=0),
    ]


def _entry_block(item: CanonicalItem) -> list:
    flowables: list = []
    heading = (item.heading or "").strip()
    sub = (item.subheading or "").strip()
    period = clean_period(item.period)
    text = (item.text or "").strip()

    # Heading line with period on the right.
    if heading or sub or period:
        if period and (heading or sub):
            # Use a 2-col table for alignment.
            left_parts = []
            if heading:
                left_parts.append(f'<font name="{BOLD_FONT}">{_esc(heading)}</font>')
            if sub and sub != heading:
                left_parts.append(_esc(sub))
            # Heading and subheading are rendered on separate lines below.
            # Rebuild left properly:
            left_flow = []
            if heading:
                left_flow.append(Paragraph(f'<font name="{BOLD_FONT}">{_esc(heading)}</font>', STYLES["entry_heading"]))
            if sub and sub != heading:
                left_flow.append(Paragraph(_esc(sub), STYLES["entry_sub"]))
            if not left_flow:
                left_flow.append(Paragraph("", STYLES["entry_heading"]))
            # table
            t = Table(
                [[left_flow, Paragraph(_esc(period) if period else "", ParagraphStyle("pr", parent=STYLES["body"], alignment=TA_RIGHT, fontSize=9, textColor=GREY, leading=11))]],
                colWidths=["75%", "25%"],
            )
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            flowables.append(t)
            flowables.append(Spacer(1, 1))
        else:
            if heading:
                flowables.append(Paragraph(f'<font name="{BOLD_FONT}">{_esc(heading)}</font>', STYLES["entry_heading"]))
            if sub and sub != heading:
                flowables.append(Paragraph(_esc(sub), STYLES["entry_sub"]))
            if period:
                flowables.append(Paragraph(_esc(period), STYLES["small"]))
    # Body text: render if not redundant with heading/sub.
    combined = " ".join(x for x in (heading, sub) if x).strip().lower()
    if text and text.strip().lower() != combined and text.strip().lower() != (heading or "").strip().lower():
        # Render as bullet for experience/projects; paragraph for others.
        flowables.append(Paragraph(f"•  {_esc(text)}", STYLES["bullet"]))
    if item.location:
        flowables.append(Paragraph(_esc(item.location), STYLES["small"]))
    return flowables


def _render_section(section: CanonicalSection) -> list:
    flowables: list = []
    flowables.extend(_section_title(section.title))
    kind = (section.kind or "").lower()

    if kind in ("skills", "languages", "certifications"):
        # Inline comma-separated.
        names = []
        for item in section.items:
            t = (item.text or "").strip()
            if t:
                names.append(t)
        if names:
            text = ", ".join(_esc(n) for n in names)
            flowables.append(Paragraph(text, STYLES["body"]))
        return flowables

    if kind in ("summary",):
        for item in section.items:
            if (item.text or "").strip():
                flowables.append(Paragraph(_esc(item.text.strip()), STYLES["body"]))
        return flowables

    if kind in ("education",):
        for item in section.items:
            text = (item.text or "").strip()
            heading = (item.heading or "").strip()
            period = clean_period(item.period)
            if heading and heading.lower() != text.lower():
                flowables.append(Paragraph(f'<font name="{BOLD_FONT}">{_esc(heading)}</font>', STYLES["entry_heading"]))
            if text:
                flowables.append(Paragraph(_esc(text), STYLES["body"]))
            if period:
                flowables.append(Paragraph(_esc(period), STYLES["small"]))
            if item.location:
                flowables.append(Paragraph(_esc(item.location), STYLES["small"]))
            flowables.append(Spacer(1, 2))
        return flowables

    # Default: experience/projects/generic.
    for item in section.items:
        block = _entry_block(item)
        # Keep each entry together when reasonable.
        flowables.append(KeepTogether(block + [Spacer(1, 3)]))
    return flowables


def build_pdf_story(draft: CanonicalDraft) -> list:
    story: list = []
    # Header
    name = draft.candidate.full_name.strip()
    story.append(Paragraph(_esc(name), STYLES["name"]))
    # Optional headline from target job title? Render muted target role.
    # We intentionally do not invent a professional title.
    contact = _contact_paragraph(draft)
    if contact is not None:
        story.append(contact)
    story.append(Spacer(1, 2))

    for section in draft.sections:
        story.extend(_render_section(section))

    # Remove trailing spacer? keep.
    return story


def render_pdf(draft: CanonicalDraft, destination: Any, *, page_size: str = "A4") -> None:

    ps = page_size_from_name(page_size)
    buffer = None

    if hasattr(destination, "write"):
        buffer = destination
        target = buffer
    else:
        target = str(destination)

    doc = SimpleDocTemplate(
        target,
        pagesize=ps,
        leftMargin=1.35 * cm,
        rightMargin=1.35 * cm,
        topMargin=1.35 * cm,
        bottomMargin=1.35 * cm,
        title=draft.candidate.full_name,
        author=draft.candidate.full_name,
    )

    story = build_pdf_story(draft)
    # Ensure no empty trailing page: SimpleDocTemplate handles.
    doc.build(story)


def render_pdf_bytes(draft: CanonicalDraft, *, page_size: str = "A4") -> bytes:
    buf = io.BytesIO()
    render_pdf(draft, buf, page_size=page_size)
    return buf.getvalue()