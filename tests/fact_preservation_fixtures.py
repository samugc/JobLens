"""Fictional equivalents of the reported Safari case, not byte-identical originals."""

SMALL_A = """Alex Rivera
Skills
Python, SQL, Git, Docker
Experience
Software Engineer
Built a local Python service with REST APIs and automated tests.
Education
BSc in Computer Science.
Projects
Project Atlas: Built a Python API for document ingestion.
Project Boreal: Prototyped document retrieval and evaluation.
Languages
English (C1)
Spanish (Native)
Certifications
AWS Certified Cloud Practitioner.
"""
SMALL_B = (
    SMALL_A.replace("Git, Docker", "Git, Docker, JavaScript")
    .replace(
        "Built a local Python service with REST APIs and automated tests.",
        "Documented backend APIs and tested ingestion workflows.",
    )
    .replace(
        "Built a Python API for document ingestion.",
        "Built a JavaScript API for customer requests.",
    )
    .replace("English (C1)", "English (B2)")
)
JOB = "Junior AI Engineer. Required: Python, SQL, Git, Docker, software engineering, REST APIs, document retrieval and automated tests. BSc Computer Science preferred. Kubernetes desirable."
RICH = """Morgan Example
Skills
Python, SQL, Git, Docker, JavaScript
Experience
Software Engineer | Fictional Cedar Labs | 2021-2024
Built Python REST APIs and automated tests, reducing failed ingestion jobs by 25%.
Education
BSc in Computer Science, Fictional Northbridge Institute, 2017-2021
Projects
Project Meridian: Built a Python document retrieval service with SQL, reducing lookup time by 30%.
Project Lantern: Built a JavaScript dashboard for API evaluation.
Languages
English (C1)
Spanish (Native)
Certifications
AWS Certified Cloud Practitioner
"""
