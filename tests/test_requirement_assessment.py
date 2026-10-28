"""Tests for typed, alias-aware requirement assessment.

These are unit tests over closed, synthetic strings. They protect the two
properties the experiment is about: generic words never create coverage, and a
canonical alias or explicitly stated element is recognised without inventing a
tenure claim from employment dates.
"""

from __future__ import annotations

from joblens_public.jobs import parse_job_posting
from joblens_public.requirements import (
    COVERED,
    PARTIAL,
    UNCOVERED,
    assess_requirements,
    extract_requirements,
)


def _state(text: str, evidence: list[str], requirement: str) -> str:
    job = parse_job_posting(text)
    assessments = {item.requirement.text: item for item in assess_requirements(job, evidence)}
    return assessments[requirement].state


def test_postgres_alias_matches_the_canonical_skill():
    assert (
        _state(
            "Data Engineer\n\nRequirements:\n- Production experience with Postgres\n",
            ["PostgreSQL", "Designed reporting tables in PostgreSQL."],
            "Production experience with Postgres",
        )
        == PARTIAL  # the technology is present; "production" is not stated
    )


def test_google_cloud_alias_matches_gcp():
    assert (
        _state(
            "Cloud Engineer\n\nRequirements:\n- GCP\n",
            ["Google Cloud", "Built batch jobs on Google Cloud."],
            "GCP",
        )
        == COVERED
    )


def test_a_generic_word_does_not_cover_a_named_technology():
    assert (
        _state(
            "Data Engineer\n\nRequirements:\n- Experience with Rust\n- Python\n",
            ["Python", "Built tooling for the developer experience team in Python."],
            "Experience with Rust",
        )
        == UNCOVERED
    )


def test_two_named_technologies_are_not_one_element():
    assert (
        _state(
            "Backend Engineer\n\nRequirements:\n- Python and SQL\n",
            ["Python", "Built Python services for internal reporting."],
            "Python and SQL",
        )
        == PARTIAL
    )


def test_tenure_is_never_derived_from_employment_dates():
    assert (
        _state(
            "Platform Engineer\n\nRequirements:\n- 4+ years of Terraform experience\n",
            [
                "Software Engineer | Fictional Cedar Labs | 2019-2024",
                "Managed Terraform state for a small service.",
            ],
            "4+ years of Terraform experience",
        )
        == PARTIAL
    )


def test_an_explicitly_stated_tenure_can_be_covered():
    assert (
        _state(
            "Platform Engineer\n\nRequirements:\n- 4+ years of Terraform experience\n",
            ["6 years of Terraform experience."],
            "4+ years of Terraform experience",
        )
        == COVERED
    )


def test_a_short_language_name_does_not_match_a_compound_word():
    assert (
        _state(
            "Backend Engineer\n\nRequirements:\n- Go\n",
            ["Supported go-to-market planning for three products."],
            "Go",
        )
        == UNCOVERED
    )


def test_a_short_language_name_matches_a_standalone_mention():
    assert (
        _state(
            "Backend Engineer\n\nRequirements:\n- Go\n",
            ["Built Go services for billing."],
            "Go",
        )
        == COVERED
    )


def test_preferred_importance_is_preserved():
    job = parse_job_posting(
        "Frontend Engineer\n\nRequirements:\n- TypeScript\n\nNice to have:\n- GraphQL\n"
    )
    assessments = {
        item.requirement.text: item for item in assess_requirements(job, ["GraphQL"])
    }
    assert assessments["TypeScript"].requirement.importance == "required"
    assert assessments["TypeScript"].state == UNCOVERED
    assert assessments["GraphQL"].requirement.importance == "preferred"
    assert assessments["GraphQL"].state == COVERED


def test_a_technology_already_named_by_a_line_is_not_duplicated():
    job = parse_job_posting(
        "Data Engineer\n\nRequirements:\n- PostgreSQL and Airflow\n"
    )
    texts = [requirement.text for requirement in extract_requirements(job)]
    assert texts == ["PostgreSQL and Airflow"]


def test_a_compound_requirement_can_be_covered_across_documents():
    assert (
        _state(
            "Data Engineer\n\nRequirements:\n- PostgreSQL and Airflow\n",
            ["Postgres", "Scheduled pipelines with Airflow."],
            "PostgreSQL and Airflow",
        )
        == COVERED
    )


def test_the_gap_list_is_deduplicated_and_typed():
    job = parse_job_posting(
        "Data Engineer\n\nRequirements:\n- Python\n\nPreferred\n- Terraform\n"
    )
    coverage = assess_requirements(job, ["Python"])
    gaps = [item.requirement.text for item in coverage if item.state != COVERED]
    assert gaps == ["Terraform"]
