#!/usr/bin/env python3
"""Create fictional PDF/DOCX inputs for the two-minute JobLens demo.

The output goes to the git-ignored ``.integration-verification/demo-input``
directory. Every name, employer and contact detail below is synthetic.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".integration-verification" / "demo-input"

DOC_A = [
    "Alex Rivera",
    "Skills",
    "Python, SQL, Git, Docker",
    "Experience",
    "Software Engineer | Fictional Cedar Labs | 2021-2024",
    "Built a local Python service with REST APIs and automated tests.",
    "Education",
    "BSc in Computer Science.",
    "Projects",
    "Project Atlas: Built a Python API for document ingestion.",
    "Project Boreal: Prototyped document retrieval and evaluation.",
    "Languages",
    "English (C1)",
    "Spanish (Native)",
    "Certifications",
    "AWS Certified Cloud Practitioner.",
]

DOC_B = [
    "Alex Rivera",
    "Skills",
    "Python, SQL, Git, Docker, JavaScript",
    "Experience",
    "Software Engineer | Fictional Cedar Labs | 2021-2024",
    "Documented backend APIs and tested ingestion workflows.",
    "Education",
    "BSc in Computer Science.",
    "Projects",
    "Project Atlas: Built a JavaScript API for customer requests.",
    "Project Boreal: Prototyped document retrieval and evaluation.",
    "Languages",
    "English (B2)",
    "Spanish (Native)",
]

JOB = """Junior AI Engineer
Required
Python
SQL
Git
Docker
software engineering
REST APIs
document retrieval
automated tests
BSc Computer Science preferred
Kubernetes desirable
"""


def write_pdf(path: Path, lines: list[str]) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 48
    for line in lines:
        if y < 40:
            pdf.showPage()
            y = height - 48
        pdf.setFont("Helvetica", 11)
        pdf.drawString(48, y, line)
        y -= 16
    pdf.save()


def write_docx(path: Path, lines: list[str]) -> None:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    document.save(str(path))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    write_pdf(OUT / "alex-rivera-cv.pdf", DOC_A)
    write_docx(OUT / "alex-rivera-notes.docx", DOC_B)
    (OUT / "job-posting.txt").write_text(JOB, encoding="utf-8")
    print("Synthetic demo files written to:", OUT)
    for path in sorted(OUT.iterdir()):
        print(f"  {path.name} ({path.stat().st_size} bytes)")
    print("All names, employers and contact details are fictional.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
