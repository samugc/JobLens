"""Tests for deterministic job-posting extraction."""
from __future__ import annotations

from joblens_public.jobs import JobPosting, parse_job_posting

JOB_TEXT = """Senior AI Engineer

Required
Python
SQL
Docker
Kubernetes
5+ years experience

Preferred
AWS
Machine learning

Responsibilities
Build and deploy machine learning pipelines
Maintain data infrastructure

About
We are a fast-growing AI company.
Benefits
Competitive salary and remote work
"""


def test_required_and_preferred_are_extracted():
    job = parse_job_posting(JOB_TEXT, title="Senior AI Engineer", company="Acme AI")
    assert job.title == "Senior AI Engineer"
    assert job.company == "Acme AI"
    assert "Python" in job.required
    assert "Kubernetes" in job.required
    assert "AWS" in job.preferred


def test_technologies_are_extracted_from_closed_vocabulary():
    job = parse_job_posting(JOB_TEXT)
    assert "python" in job.technologies
    assert "docker" in job.technologies
    assert "kubernetes" in job.technologies
    assert "aws" in job.technologies


def test_responsibilities_and_experience_are_captured():
    job = parse_job_posting(JOB_TEXT)
    assert any("machine learning pipelines" in r for r in job.responsibilities)
    assert any("years" in e for e in job.experience_expectations)


def test_noise_and_benefits_are_not_requirements():
    job = parse_job_posting(JOB_TEXT)
    joined = " ".join(job.required + job.preferred + job.responsibilities).casefold()
    assert "competitive salary" not in joined
    assert "apply now" not in joined


def test_a_job_posting_round_trips():
    job = parse_job_posting(JOB_TEXT, title="T", company="C", location="Remote")
    from joblens_public.jobs import JobPosting

    restored = JobPosting.from_dict(job.as_dict())
    assert restored.as_dict() == job.as_dict()


def test_an_unsupported_job_posting_is_rejected():
    try:
        JobPosting.from_dict({"raw_text": 123})
    except ValueError:
        pass
    else:
        raise AssertionError("malformed job posting must be rejected")
