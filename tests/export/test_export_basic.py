from __future__ import annotations

import io
import zipfile

from joblens_public.export import (
    export_cv_docx,
    export_cv_docx_bytes,
    export_cv_pdf,
    export_cv_pdf_bytes,
)

from .test_helpers import docx_text, make_draft, pdf_text


def test_pdf_bytes_valid():
    draft = make_draft()
    data = export_cv_pdf_bytes(draft)
    assert data[:4] == b"%PDF"
    assert len(data) > 1000


def test_docx_bytes_valid_zip():
    draft = make_draft()
    data = export_cv_docx_bytes(draft)
    assert data[:2] == b"PK"
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.testzip() is None
    names = z.namelist()
    assert "word/document.xml" in names


def test_pdf_file_created(tmp_path):
    draft = make_draft()
    dest = tmp_path / "out.pdf"
    export_cv_pdf(draft, dest)
    assert dest.exists()
    assert dest.read_bytes()[:4] == b"%PDF"


def test_docx_file_created(tmp_path):
    draft = make_draft()
    dest = tmp_path / "out.docx"
    export_cv_docx(draft, dest)
    assert dest.exists()
    assert dest.read_bytes()[:2] == b"PK"


def test_pdf_destination_directory(tmp_path):
    draft = make_draft()
    result = export_cv_pdf(draft, tmp_path)
    assert result.exists()
    assert result.suffix == ".pdf"


def test_byte_functions_do_not_persist(tmp_path):
    # no files created beyond explicit
    before = set(tmp_path.iterdir())
    export_cv_pdf_bytes(make_draft())
    export_cv_docx_bytes(make_draft())
    after = set(tmp_path.iterdir())
    assert before == after


def test_section_order_preserved():
    draft = make_draft()
    data = export_cv_pdf_bytes(draft)
    text = pdf_text(data)
    # section titles appear in order
    idx_summary = text.find("Professional Summary")
    idx_exp = text.find("Experience")
    idx_skills = text.find("Skills")
    assert idx_summary != -1 and idx_exp != -1 and idx_skills != -1
    assert idx_summary < idx_exp < idx_skills


def test_factual_content_equivalent():
    draft = make_draft()
    pdf = pdf_text(export_cv_pdf_bytes(draft))
    docx = docx_text(export_cv_docx_bytes(draft))
    for needle in ["Jane Example", "jane@example.com", "Python", "SQL", "Data Engineer", "Acme", "2020 - 2023", "Madrid"]:
        assert needle in pdf, f"pdf missing {needle}"
        assert needle in docx, f"docx missing {needle}"


def test_pdf_one_page_for_short():
    import io

    from pypdf import PdfReader
    data = export_cv_pdf_bytes(make_draft())
    r = PdfReader(io.BytesIO(data))
    assert len(r.pages) == 1


def test_docx_a4_and_candidate_metadata():
    from docx import Document
    from docx.shared import Cm

    draft = make_draft()
    doc = Document(io.BytesIO(export_cv_docx_bytes(draft)))
    for section in doc.sections:
        assert abs(section.page_width - Cm(21)) < 635
        assert abs(section.page_height - Cm(29.7)) < 635
        assert abs(section.left_margin - Cm(1.35)) < 635
    assert doc.core_properties.author == draft["candidate"]["full_name"]
    assert doc.core_properties.title == draft["candidate"]["full_name"] + " — CV"
    assert not doc.core_properties.last_modified_by
    assert not doc.core_properties.comments
