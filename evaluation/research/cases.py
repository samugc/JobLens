"""Frozen synthetic research cases for the evidence-quality programme.

Every person, employer, school and posting here is fictional. The cases are
declared before the experiments and are not derived from any real CV or from
private material. ``DEVELOPMENT`` cases may be used to diagnose and fix
defects; ``HOLDOUT`` cases are frozen and are evaluated once per candidate
implementation, then reported as-is.

Two families:

* achievement cases exercise source-to-export preservation of experience
  entries: every labelled contribution must survive into both exports, numbers
  must be exact, and content must not leak between entries or sections.
* coverage cases exercise requirement assessment: for each labelled job
  requirement the expected state is ``covered`` (the approved evidence states
  every distinctive element), ``partial`` (some elements are evidenced, others
  are not), or ``uncovered`` (no approved evidence states it).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Document:
    filename: str
    kind: str
    text: str


@dataclass(frozen=True)
class AchievementCase:
    id: str
    description: str
    documents: tuple[Document, ...]
    job_text: str
    must_preserve: tuple[str, ...]
    experience_text: tuple[str, ...] = ()
    experience_must_not_contain: tuple[str, ...] = ()
    must_not_preserve: tuple[str, ...] = ()
    max_occurrences: dict[str, int] = field(default_factory=dict)
    max_experience_items: int | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequirementLabel:
    text: str
    importance: str  # required | preferred
    state: str  # covered | partial | uncovered


@dataclass(frozen=True)
class CoverageCase:
    id: str
    description: str
    documents: tuple[Document, ...]
    job_text: str
    requirements: tuple[RequirementLabel, ...]
    tags: tuple[str, ...] = ()


JOB_GENERIC = """Data Engineer

Requirements:
- Experience with Rust
- Python
"""

JOB_PYTHON_SQL = """Backend Engineer

Requirements:
- Python and SQL
"""

JOB_K8S_TENURE = """Platform Engineer

Requirements:
- 5+ years of production Kubernetes experience
- Python
"""

JOB_POSTGRES = """Data Engineer

Requirements:
- Production experience with Postgres
"""

JOB_TERRAFORM = """Platform Engineer

Requirements:
- Python

Nice to have:
- Terraform
"""

JOB_KUBERNETES_ONLY = """Platform Engineer

Requirements:
- Kubernetes
"""

JOB_RESPONSIBILITY = """Data Engineer

Responsibilities:
- Build reliable data pipelines
- Design warehouse schemas

Requirements:
- Python
"""

JOB_GO = """Backend Engineer

Requirements:
- Go
- SQL
"""

JOB_COMMUNICATION = """Programme Manager

Requirements:
- Excellent written communication skills
- Python
"""

JOB_ML_ALIASES = """ML Engineer

Requirements:
- Machine learning and NLP
"""

# ---------------------------------------------------------------------------
# Achievement cases (development)
# ---------------------------------------------------------------------------

ACHIEVEMENT_DEVELOPMENT: tuple[AchievementCase, ...] = (
    AchievementCase(
        id="ach_nonverb_first",
        description="An achievement that does not open with a whitelisted verb must not hide the bullets after it.",
        documents=(
            Document(
                "nadia.pdf",
                "pdf",
                """Nadia Okonkwo
Skills
Python, SQL
Experience
Software Engineer | Fictional Cedar Labs | 2021-2024
Increased checkout conversion by 18% by rebuilding the payment service.
Built Python REST APIs and automated tests.
Education
BSc in Computer Science, Fictional Northbridge Institute, 2017-2021
""",
            ),
        ),
        job_text="Software Engineer. Requirements:\n- Python\n- SQL\n",
        must_preserve=(
            "Increased checkout conversion by 18% by rebuilding the payment service.",
            "Built Python REST APIs and automated tests.",
        ),
        experience_text=(
            "Increased checkout conversion by 18%",
            "Built Python REST APIs and automated tests.",
        ),
        experience_must_not_contain=("BSc in Computer Science",),
        max_occurrences={"BSc in Computer Science": 1},
    ),
    AchievementCase(
        id="ach_mixed_verbs",
        description="A whitelisted bullet followed by a non-whitelisted achievement must both survive.",
        documents=(
            Document(
                "omar.pdf",
                "pdf",
                """Omar Haddad
Skills
Python, Docker
Experience
Software Engineer | Fictional Cedar Labs | 2020-2024
Built Python REST APIs and automated tests.
Managed a team of four engineers across two time zones.
Reduced deployment time from 40 minutes to 6 minutes.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Software Engineer. Requirements:\n- Python\n- Docker\n",
        must_preserve=(
            "Built Python REST APIs and automated tests.",
            "Managed a team of four engineers across two time zones.",
            "Reduced deployment time from 40 minutes to 6 minutes.",
        ),
        experience_text=(
            "Managed a team of four engineers",
            "Reduced deployment time from 40 minutes to 6 minutes.",
        ),
    ),
    AchievementCase(
        id="ach_bullet_markers",
        description="Bullet markers must be stripped and both achievements preserved.",
        documents=(
            Document(
                "lucia.docx",
                "docx",
                """Lucia Ferreira
Skills
SQL, Python
Experience
Data Analyst | Fictional Harbor | 2019-2023
• Led migration of the reporting stack to PostgreSQL.
• Negotiated a 12% reduction in vendor costs.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Data Analyst. Requirements:\n- SQL\n- Python\n",
        must_preserve=(
            "Led migration of the reporting stack to PostgreSQL.",
            "Negotiated a 12% reduction in vendor costs.",
        ),
        experience_text=("Led migration", "Negotiated a 12% reduction"),
        experience_must_not_contain=("•",),
    ),
    AchievementCase(
        id="ach_section_boundary",
        description="The Education line must not be absorbed into the experience entry.",
        documents=(
            Document(
                "ravi.pdf",
                "pdf",
                """Ravi Menon
Skills
Python
Experience
Software Engineer | Fictional Cedar Labs | 2021-2024
Automated nightly reconciliation reports.
Education
BSc in Computer Science, Fictional Northbridge Institute, 2017-2021
Languages
English (C1)
""",
            ),
        ),
        job_text="Software Engineer. Requirements:\n- Python\n",
        must_preserve=("Automated nightly reconciliation reports.", "BSc in Computer Science"),
        experience_text=("Automated nightly reconciliation reports.",),
        must_not_preserve=(),
        max_occurrences={"BSc in Computer Science": 1},
    ),
    AchievementCase(
        id="ach_adjacent_entries",
        description="Two roles in one document must keep their own contributions.",
        documents=(
            Document(
                "sofia.pdf",
                "pdf",
                """Sofia Alvarez
Skills
Python, SQL
Experience
Data Analyst | Fictional Harbor | 2019-2021
Built SQL reports for operations teams.
Software Engineer | Fictional Cedar Labs | 2021-2024
Owned the ingestion roadmap for three regions.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Data Engineer. Requirements:\n- Python\n- SQL\n",
        must_preserve=(
            "Built SQL reports for operations teams.",
            "Owned the ingestion roadmap for three regions.",
        ),
        experience_text=("Built SQL reports", "Owned the ingestion roadmap"),
        must_not_preserve=(),
    ),
    AchievementCase(
        id="ach_numeric_exact",
        description="Numeric achievements must keep exact values and units.",
        documents=(
            Document(
                "tomas.pdf",
                "pdf",
                """Tomas Weber
Skills
Python
Experience
Engineering Manager | Fictional Cedar Labs | 2018-2024
Grew the platform team from 3 to 11 engineers.
Cut cloud spend by $2.4M over two years.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Engineering Manager. Requirements:\n- Python\n",
        must_preserve=(
            "Grew the platform team from 3 to 11 engineers.",
            "Cut cloud spend by $2.4M over two years.",
        ),
        experience_text=("Grew the platform team from 3 to 11 engineers.", "$2.4M"),
    ),
    AchievementCase(
        id="ach_unicode",
        description="Accented content inside an achievement must survive both exports.",
        documents=(
            Document(
                "ines.docx",
                "docx",
                """Inés Peña
Skills
Python, SQL
Experience
Data Analyst | Fictional Harbor | 2019-2024
Improved conversion for España and México by 9%.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Data Analyst. Requirements:\n- Python\n- SQL\n",
        must_preserve=("Improved conversion for España and México by 9%.",),
        experience_text=("España and México",),
    ),
    AchievementCase(
        id="ach_long_line",
        description="A long achievement line must not be clipped.",
        documents=(
            Document(
                "grace.pdf",
                "pdf",
                """Grace Lin
Skills
Python
Experience
Software Engineer | Fictional Cedar Labs | 2020-2024
Coordinated the migration of eleven internal services to a shared deployment pipeline, documented rollback procedures, and trained four teams on the new release process.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Software Engineer. Requirements:\n- Python\n",
        must_preserve=(
            "Coordinated the migration of eleven internal services",
            "trained four teams on the new release process",
        ),
        experience_text=("Coordinated the migration", "trained four teams"),
    ),
    AchievementCase(
        id="ach_two_documents",
        description="Complementary documents contribute different achievements to the same role.",
        documents=(
            Document(
                "jamie-a.pdf",
                "pdf",
                """Jamie Chen
Skills
Python, SQL
Experience
Software Engineer | Fictional Cedar Labs | 2021-2024
Built Python REST APIs and automated tests.
Education
BSc in Computer Science.
""",
            ),
            Document(
                "jamie-b.docx",
                "docx",
                """Jamie Chen
Skills
Docker
Experience
Software Engineer | Fictional Cedar Labs | 2021-2024
Increased test coverage from 61% to 88%.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Software Engineer. Requirements:\n- Python\n- Docker\n",
        must_preserve=(
            "Built Python REST APIs and automated tests.",
            "Increased test coverage from 61% to 88%.",
        ),
        experience_text=("Built Python REST APIs", "Increased test coverage"),
        max_experience_items=2,
    ),
    AchievementCase(
        id="ach_no_terminal_period",
        description="Lowercase, unpunctuated achievement text must still be preserved and readable.",
        documents=(
            Document(
                "noah.pdf",
                "pdf",
                """Noah Kim
Skills
Python
Experience
Software Engineer | Fictional Cedar Labs | 2022-2024
rewrote the billing reconciliation job
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Software Engineer. Requirements:\n- Python\n",
        must_preserve=("rewrote the billing reconciliation job",),
        experience_text=("rewrote the billing reconciliation job",),
    ),
)

# ---------------------------------------------------------------------------
# Achievement cases (holdout)
# ---------------------------------------------------------------------------

ACHIEVEMENT_HOLDOUT: tuple[AchievementCase, ...] = (
    AchievementCase(
        id="hold_ach_verbs",
        description="Holdout: achievement verbs outside every previously seen list.",
        documents=(
            Document(
                "hold-a.pdf",
                "pdf",
                """Marta Silva
Skills
Python, SQL
Experience
Operations Analyst | Fictional Harbor | 2020-2024
Authored the incident review standard used by four teams.
Reorganized the weekly reporting cycle, cutting preparation time by 11 hours.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Operations Analyst. Requirements:\n- Python\n- SQL\n",
        must_preserve=(
            "Authored the incident review standard used by four teams.",
            "Reorganized the weekly reporting cycle, cutting preparation time by 11 hours.",
        ),
        experience_text=("Authored the incident review standard", "Reorganized the weekly reporting cycle"),
    ),
    AchievementCase(
        id="hold_ach_chain",
        description="Holdout: a non-standard first line must not hide a later standard bullet.",
        documents=(
            Document(
                "hold-b.pdf",
                "pdf",
                """Peter Novak
Skills
Docker
Experience
Platform Engineer | Fictional Cedar Labs | 2019-2024
Cut infrastructure cost per request by 22%.
Built Docker images and automated deployment checks.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Platform Engineer. Requirements:\n- Docker\n",
        must_preserve=(
            "Cut infrastructure cost per request by 22%.",
            "Built Docker images and automated deployment checks.",
        ),
        experience_text=("Cut infrastructure cost", "Built Docker images"),
    ),
    AchievementCase(
        id="hold_ach_docx_boundaries",
        description="Holdout: DOCX paragraphs and a section heading after achievements.",
        documents=(
            Document(
                "hold-c.docx",
                "docx",
                """Amara Okafor
Skills
Python, SQL
Experience
Data Engineer | Fictional Cedar Labs | 2021-2024
Designed the warehouse schema for three product lines.
Maintained data quality checks across 40 tables.
Projects
Project Lantern: Built a Python dashboard for finance.
""",
            ),
        ),
        job_text="Data Engineer. Requirements:\n- Python\n- SQL\n",
        must_preserve=(
            "Designed the warehouse schema for three product lines.",
            "Maintained data quality checks across 40 tables.",
        ),
        experience_text=("Designed the warehouse schema", "Maintained data quality checks"),
        must_not_preserve=("Project Lantern: Built a Python dashboard",),
    ),
    AchievementCase(
        id="hold_ach_numbers_units",
        description="Holdout: percentages, currency and counts in one entry.",
        documents=(
            Document(
                "hold-d.docx",
                "docx",
                """Elena Rossi
Skills
Python
Experience
Product Manager | Fictional Harbor | 2017-2024
Grew annual recurring revenue by 24% to €3.1M.
Reduced churn across 1,200 accounts by 7 points.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Product Manager. Requirements:\n- Python\n",
        must_preserve=(
            "Grew annual recurring revenue by 24% to €3.1M.",
            "Reduced churn across 1,200 accounts by 7 points.",
        ),
        experience_text=("€3.1M", "1,200 accounts"),
    ),
    AchievementCase(
        id="hold_ach_no_bullets",
        description="Holdout: an entry with no contributions must not borrow from the next entry.",
        documents=(
            Document(
                "hold-e.pdf",
                "pdf",
                """Ibrahim Saleh
Skills
Python, SQL
Experience
Data Analyst | Fictional Harbor | 2016-2018
Software Engineer | Fictional Cedar Labs | 2018-2024
Migrated 15 reporting jobs to a scheduled pipeline.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Data Engineer. Requirements:\n- Python\n- SQL\n",
        must_preserve=("Migrated 15 reporting jobs to a scheduled pipeline.",),
        experience_text=("Migrated 15 reporting jobs",),
        max_occurrences={"Migrated 15 reporting jobs": 1},
    ),
    AchievementCase(
        id="hold_ach_mixed_markers",
        description="Holdout: mixed bullet markers and an unpunctuated achievement.",
        documents=(
            Document(
                "hold-f.docx",
                "docx",
                """Yuki Tanaka
Skills
Python, Git
Experience
Software Engineer | Fictional Cedar Labs | 2020-2024
- Introduced trunk-based development for six teams
• Reviewed 240 pull requests in the first year.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Software Engineer. Requirements:\n- Python\n- Git\n",
        must_preserve=(
            "Introduced trunk-based development for six teams",
            "Reviewed 240 pull requests in the first year.",
        ),
        experience_text=("Introduced trunk-based development", "Reviewed 240 pull requests"),
        experience_must_not_contain=("•",),
    ),
)

# ---------------------------------------------------------------------------
# Coverage cases (development)
# ---------------------------------------------------------------------------

COVERAGE_DEVELOPMENT: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="cov_generic_word",
        description="A generic word such as 'experience' is not evidence of a named technology.",
        documents=(
            Document(
                "priya.pdf",
                "pdf",
                """Priya Raman
Skills
Python
Experience
Software Engineer | Fictional Cedar Labs | 2021-2024
Built tooling for the developer experience team in Python.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text=JOB_GENERIC,
        requirements=(
            RequirementLabel("Experience with Rust", "required", "uncovered"),
            RequirementLabel("Python", "required", "covered"),
        ),
        tags=("generic-word", "unsafe-cover"),
    ),
    CoverageCase(
        id="cov_multi_term_partial",
        description="One of two named technologies is not evidence that both are held.",
        documents=(
            Document(
                "isaac.pdf",
                "pdf",
                """Isaac Bell
Skills
Python
Experience
Software Engineer | Fictional Cedar Labs | 2021-2024
Built Python services for internal reporting.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text=JOB_PYTHON_SQL,
        requirements=(
            RequirementLabel("Python and SQL", "required", "partial"),
        ),
        tags=("partial",),
    ),
    CoverageCase(
        id="cov_alias_postgres",
        description="A technology alias must match the canonical skill.",
        documents=(
            Document(
                "hana.pdf",
                "pdf",
                """Hana Suzuki
Skills
PostgreSQL
Experience
Data Engineer | Fictional Cedar Labs | 2021-2024
Designed reporting tables in PostgreSQL.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text=JOB_POSTGRES,
        requirements=(
            RequirementLabel("Production experience with Postgres", "required", "partial"),
        ),
        tags=("alias",),
    ),
    CoverageCase(
        id="cov_tenure_unverified",
        description="A technology mention does not prove a stated tenure.",
        documents=(
            Document(
                "marcus.pdf",
                "pdf",
                """Marcus Reed
Skills
Kubernetes, Python
Experience
Software Engineer | Fictional Cedar Labs | 2022-2024
Deployed services to Kubernetes.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text=JOB_K8S_TENURE,
        requirements=(
            RequirementLabel("5+ years of production Kubernetes experience", "required", "partial"),
            RequirementLabel("Python", "required", "covered"),
        ),
        tags=("tenure", "partial"),
    ),
    CoverageCase(
        id="cov_preferred_not_required",
        description="A nice-to-have technology must not be treated as essential.",
        documents=(
            Document(
                "nora.pdf",
                "pdf",
                """Nora Haddad
Skills
Python, Terraform
Experience
Platform Engineer | Fictional Cedar Labs | 2020-2024
Built Terraform modules for three teams.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text=JOB_TERRAFORM,
        requirements=(
            RequirementLabel("Python", "required", "covered"),
            RequirementLabel("Terraform", "preferred", "covered"),
        ),
        tags=("importance",),
    ),
    CoverageCase(
        id="cov_absent",
        description="A requirement with no evidence must stay a gap.",
        documents=(
            Document(
                "paul.pdf",
                "pdf",
                """Paul Mensah
Skills
Python
Experience
Software Engineer | Fictional Cedar Labs | 2021-2024
Built Python services.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text=JOB_KUBERNETES_ONLY,
        requirements=(
            RequirementLabel("Kubernetes", "required", "uncovered"),
        ),
        tags=("absent",),
    ),
    CoverageCase(
        id="cov_responsibility",
        description="Responsibilities are context, not essential qualifications.",
        documents=(
            Document(
                "quinn.pdf",
                "pdf",
                """Quinn Alvarez
Skills
Python
Experience
Data Engineer | Fictional Cedar Labs | 2019-2024
Built reliable data pipelines for finance.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text=JOB_RESPONSIBILITY,
        requirements=(
            RequirementLabel("Build reliable data pipelines", "responsibility", "covered"),
            RequirementLabel("Python", "required", "covered"),
        ),
        tags=("responsibilities",),
    ),
    CoverageCase(
        id="cov_keyword_collision",
        description="A short language name must not match an unrelated compound word.",
        documents=(
            Document(
                "rosa.pdf",
                "pdf",
                """Rosa Delgado
Skills
SQL
Experience
Product Analyst | Fictional Harbor | 2020-2024
Supported go-to-market planning for three products.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text=JOB_GO,
        requirements=(
            RequirementLabel("Go", "required", "uncovered"),
            RequirementLabel("SQL", "required", "covered"),
        ),
        tags=("collision", "unsafe-cover"),
    ),
    CoverageCase(
        id="cov_communication",
        description="Generic soft-skill wording needs an explicit statement, not an adjacent word.",
        documents=(
            Document(
                "sam.pdf",
                "pdf",
                """Sam Whitfield
Skills
Python
Experience
Programme Coordinator | Fictional Harbor | 2019-2024
Maintained the project intranet.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text=JOB_COMMUNICATION,
        requirements=(
            RequirementLabel("Excellent written communication skills", "required", "uncovered"),
            RequirementLabel("Python", "required", "covered"),
        ),
        tags=("soft-skill",),
    ),
    CoverageCase(
        id="cov_multi_document",
        description="Distinct documents can jointly evidence a compound requirement.",
        documents=(
            Document(
                "dana-a.pdf",
                "pdf",
                """Dana Whitfield
Skills
Python
Experience
Software Engineer | Fictional Cedar Labs | 2021-2024
Built Python services.
Education
BSc in Computer Science.
""",
            ),
            Document(
                "dana-b.docx",
                "docx",
                """Dana Whitfield
Skills
SQL
Experience
Data Analyst | Fictional Harbor | 2019-2021
Built SQL reports.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text=JOB_PYTHON_SQL,
        requirements=(
            RequirementLabel("Python and SQL", "required", "covered"),
        ),
        tags=("multi-document",),
    ),
)

# ---------------------------------------------------------------------------
# Coverage cases (holdout)
# ---------------------------------------------------------------------------

COVERAGE_HOLDOUT: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="hold_cov_generic",
        description="Holdout: generic seniority words must not satisfy a named technology.",
        documents=(
            Document(
                "hold-g.pdf",
                "pdf",
                """Bilal Aziz
Skills
Python
Experience
Senior Analyst | Fictional Harbor | 2018-2024
Built experience analytics for the support team.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Analytics Engineer\n\nRequirements:\n- Experience with dbt\n- Python\n",
        requirements=(
            RequirementLabel("Experience with dbt", "required", "uncovered"),
            RequirementLabel("Python", "required", "covered"),
        ),
        tags=("generic-word",),
    ),
    CoverageCase(
        id="hold_cov_partial",
        description="Holdout: two named technologies, one evidenced.",
        documents=(
            Document(
                "hold-h.pdf",
                "pdf",
                """Camila Duarte
Skills
Kafka
Experience
Data Engineer | Fictional Cedar Labs | 2020-2024
Operated Kafka topics for event ingestion.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Streaming Engineer\n\nRequirements:\n- Kafka and Spark\n",
        requirements=(
            RequirementLabel("Kafka and Spark", "required", "partial"),
        ),
        tags=("partial",),
    ),
    CoverageCase(
        id="hold_cov_alias",
        description="Holdout: a multi-word alias for a cloud platform.",
        documents=(
            Document(
                "hold-i.pdf",
                "pdf",
                """Diego Morales
Skills
Google Cloud
Experience
Data Engineer | Fictional Cedar Labs | 2020-2024
Built batch jobs on Google Cloud.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Cloud Engineer\n\nRequirements:\n- GCP\n- Python\n",
        requirements=(
            RequirementLabel("GCP", "required", "covered"),
        ),
        tags=("alias",),
    ),
    CoverageCase(
        id="hold_cov_tenure",
        description="Holdout: a project mention is not a stated number of years.",
        documents=(
            Document(
                "hold-j.pdf",
                "pdf",
                """Anika Rao
Skills
Terraform
Experience
Software Engineer | Fictional Cedar Labs | 2023-2024
Managed Terraform state for a small service.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Platform Engineer\n\nRequirements:\n- 4+ years of Terraform experience\n",
        requirements=(
            RequirementLabel("4+ years of Terraform experience", "required", "partial"),
        ),
        tags=("tenure",),
    ),
    CoverageCase(
        id="hold_cov_preferred",
        description="Holdout: preferred technology with no required-skill overlap.",
        documents=(
            Document(
                "hold-k.pdf",
                "pdf",
                """Leo Fischer
Skills
GraphQL
Experience
Frontend Engineer | Fictional Cedar Labs | 2020-2024
Built GraphQL gateways for three products.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Frontend Engineer\n\nRequirements:\n- TypeScript\n\nNice to have:\n- GraphQL\n",
        requirements=(
            RequirementLabel("TypeScript", "required", "uncovered"),
            RequirementLabel("GraphQL", "preferred", "covered"),
        ),
        tags=("importance",),
    ),
    CoverageCase(
        id="hold_cov_collision",
        description="Holdout: a short technology name inside a longer word.",
        documents=(
            Document(
                "hold-l.pdf",
                "pdf",
                """Mina Park
Skills
Python
Experience
Support Engineer | Fictional Harbor | 2019-2024
Resolved customer issues and rustled up weekly reports.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Systems Engineer\n\nRequirements:\n- Rust\n- Python\n",
        requirements=(
            RequirementLabel("Rust", "required", "uncovered"),
            RequirementLabel("Python", "required", "covered"),
        ),
        tags=("collision",),
    ),
    CoverageCase(
        id="hold_cov_multi_document_alias",
        description="Holdout: alias in one document, required technology in another.",
        documents=(
            Document(
                "hold-m-a.pdf",
                "pdf",
                """Tariq Hassan
Skills
Postgres
Experience
Data Engineer | Fictional Cedar Labs | 2020-2024
Built Postgres reporting tables.
Education
BSc in Computer Science.
""",
            ),
            Document(
                "hold-m-b.docx",
                "docx",
                """Tariq Hassan
Skills
Airflow
Experience
Data Engineer | Fictional Cedar Labs | 2020-2024
Scheduled pipelines with Airflow.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Data Engineer\n\nRequirements:\n- PostgreSQL and Airflow\n",
        requirements=(
            RequirementLabel("PostgreSQL and Airflow", "required", "covered"),
        ),
        tags=("multi-document", "alias"),
    ),
    CoverageCase(
        id="hold_cov_absent",
        description="Holdout: absent soft requirement stays a gap.",
        documents=(
            Document(
                "hold-n.pdf",
                "pdf",
                """Freya Larsen
Skills
SQL
Experience
Analyst | Fictional Harbor | 2021-2024
Built weekly SQL reports.
Education
BSc in Computer Science.
""",
            ),
        ),
        job_text="Analyst\n\nRequirements:\n- Stakeholder presentation experience\n- SQL\n",
        requirements=(
            RequirementLabel("Stakeholder presentation experience", "required", "uncovered"),
            RequirementLabel("SQL", "required", "covered"),
        ),
        tags=("absent",),
    ),
)

DEVELOPMENT_ACHIEVEMENT = ACHIEVEMENT_DEVELOPMENT
HOLDOUT_ACHIEVEMENT = ACHIEVEMENT_HOLDOUT
DEVELOPMENT_COVERAGE = COVERAGE_DEVELOPMENT
HOLDOUT_COVERAGE = COVERAGE_HOLDOUT
