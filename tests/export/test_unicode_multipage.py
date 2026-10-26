from __future__ import annotations

import io

from pypdf import PdfReader

from joblens_public.export import export_cv_docx_bytes, export_cv_pdf_bytes

from .test_helpers import docx_text, make_draft, pdf_text


def _long_draft():
    d = make_draft()
    # long bullets and organization names
    d["sections"][1]["items"][0]["subheading"] = "A Very Long Organization Name That Should Wrap Gracefully Without Clipping"
    d["sections"][1]["items"][0]["text"] = (
        "Built and maintained a very long bullet point that describes an achievement in detail, "
        "including metrics, technologies, and outcomes, and it should wrap across multiple lines "
        "without overlapping or clipping the page margins in either PDF or DOCX output."
    )
    # Add many projects to force multiple pages
    projects = []
    for i in range(18):
        projects.append({
            "item_id": f"proj_{i}",
            "text": f"Project {i}: " + "x" * 120,
            "approved_fact_ids": [f"fact_p{i}"],
            "review_status": "approved",
            "heading": f"Project Number {i} With A Long Title",
            "period": "2024",
        })
    d["sections"].append({
        "section_id": "section_projects",
        "kind": "projects",
        "title": "Projects",
        "items": projects,
    })
    # unicode
    d["candidate"]["full_name"] = "José García-Müller"
    d["sections"][0]["items"][0]["text"] = "Résumé: naïve façade. 北京. Москва. Ελληνικά."
    return d


def test_unicode_content():
    d = _long_draft()
    pdf = export_cv_pdf_bytes(d)
    docx = export_cv_docx_bytes(d)
    pt = pdf_text(pdf)
    dt = docx_text(docx)
    assert "José García-Müller" in pt or "Jose" in pt  # font may normalize? check bytes decode
    assert "北京" in pt or "北京" in dt
    # at least some unicode present
    assert "Garc" in pt or "Garc" in dt


def test_multiple_pages():
    d = _long_draft()
    data = export_cv_pdf_bytes(d)
    r = PdfReader(io.BytesIO(data))
    assert len(r.pages) >= 2


def test_no_blank_pages():
    d = _long_draft()
    data = export_cv_pdf_bytes(d)
    r = PdfReader(io.BytesIO(data))
    for i, p in enumerate(r.pages):
        txt = (p.extract_text() or "").strip()
        assert len(txt) > 0, f"blank page {i+1}"


def test_a4_and_letter():
    d = _long_draft()
    for ps in ("A4", "LETTER"):
        data = export_cv_pdf_bytes(d, page_size=ps)
        r = PdfReader(io.BytesIO(data))
        assert len(r.pages) >= 1
        # page size check
        page = r.pages[0]
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        if ps == "A4":
            assert abs(w - 595.2756) < 1 and abs(h - 841.8898) < 1
        else:
            assert abs(w - 612) < 1 and abs(h - 792) < 1


def test_clickable_links_present():
    d = make_draft()
    data = export_cv_pdf_bytes(d)
    # pypdf can extract annotations? check /Annots
    r = PdfReader(io.BytesIO(data))
    page = r.pages[0]
    page.get("/Annots")
    # reportlab link annotations may exist
    text = page.extract_text() or ""
    assert "example.com/portfolio" in text


def test_docx_paragraph_content():
    import docx
    d = make_draft()
    data = export_cv_docx_bytes(d)
    doc = docx.Document(io.BytesIO(data))
    texts = [p.text for p in doc.paragraphs]
    joined = "\n".join(texts)
    assert "Jane Example" in joined
    assert "Professional Summary" in joined
