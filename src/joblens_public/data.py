"""Load and validate the synthetic demo data.

The public snapshot deliberately keeps the evidence bank server-side. The
browser receives candidate metadata and synthetic postings, never the bank
itself. All records in this directory are fictional.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_DIR = ROOT / "data" / "candidates"
JOB_DIR = ROOT / "data" / "jobs"


class DemoDataError(ValueError):
    """Raised when the synthetic data is incomplete or inconsistent."""


def _require_string(value: Any, label: str, *, maximum: int = 50_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DemoDataError(f"{label} must be a non-empty string")
    if len(value) > maximum:
        raise DemoDataError(f"{label} is too long")
    return value.strip()


def validate_bank(payload: Any, source: str) -> dict[str, Any]:
    """Validate a fictional, explicitly attested bank without repairing it."""
    if not isinstance(payload, dict):
        raise DemoDataError(f"{source}: bank must be a JSON object")
    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        raise DemoDataError(f"{source}: missing candidate metadata")
    candidate_id = _require_string(candidate.get("id"), f"{source}.candidate.id", maximum=80)
    _require_string(candidate.get("name"), f"{source}.candidate.name", maximum=120)
    _require_string(candidate.get("headline"), f"{source}.candidate.headline", maximum=240)
    _require_string(candidate.get("note"), f"{source}.candidate.note", maximum=500)

    facts = payload.get("facts")
    if not isinstance(facts, list) or not facts:
        raise DemoDataError(f"{source}: facts must be a non-empty list")
    seen: set[str] = set()
    for index, row in enumerate(facts):
        label = f"{source}.facts[{index}]"
        if not isinstance(row, dict):
            raise DemoDataError(f"{label} must be an object")
        fact_id = _require_string(row.get("id"), f"{label}.id", maximum=120)
        if fact_id in seen:
            raise DemoDataError(f"{source}: duplicate fact id {fact_id!r}")
        seen.add(fact_id)
        _require_string(row.get("text"), f"{label}.text", maximum=1600)
        _require_string(row.get("source"), f"{label}.source", maximum=300)
        if row.get("attested_by_user") is not True:
            raise DemoDataError(f"{label} must be explicitly attested")
        tags = row.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise DemoDataError(f"{label}.tags must be a list of strings")

    return {
        "id": candidate_id,
        "name": candidate["name"].strip(),
        "headline": candidate["headline"].strip(),
        "note": candidate["note"].strip(),
        "bank": payload,
    }


def load_candidates(directory: Path = CANDIDATE_DIR) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        candidate = validate_bank(json.loads(path.read_text(encoding="utf-8")), path.name)
        if candidate["id"] in candidates:
            raise DemoDataError(f"Duplicate candidate id: {candidate['id']!r}")
        candidates[candidate["id"]] = candidate
    if not candidates:
        raise DemoDataError("No candidate banks found")
    return candidates


def validate_job(payload: Any, source: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DemoDataError(f"{source}: posting must be a JSON object")
    job_id = _require_string(payload.get("id"), f"{source}.id", maximum=100)
    if payload.get("synthetic") is not True:
        raise DemoDataError(f"{source} must be marked synthetic")
    return {
        "id": job_id,
        "title": _require_string(payload.get("title"), f"{source}.title", maximum=160),
        "company": _require_string(payload.get("company"), f"{source}.company", maximum=120),
        "location": _require_string(payload.get("location"), f"{source}.location", maximum=160),
        "description": _require_string(
            payload.get("description"), f"{source}.description", maximum=50_000
        ),
        "synthetic": True,
    }


def load_jobs(directory: Path = JOB_DIR) -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        job = validate_job(json.loads(path.read_text(encoding="utf-8")), path.name)
        if job["id"] in jobs:
            raise DemoDataError(f"Duplicate job id: {job['id']!r}")
        jobs[job["id"]] = job
    if not jobs:
        raise DemoDataError("No synthetic postings found")
    return jobs


def public_candidates(candidates: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "headline": row["headline"],
            "note": row["note"],
        }
        for row in candidates.values()
    ]


def public_jobs(jobs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(job) for job in jobs.values()]


def load_demo_data() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    return load_candidates(), load_jobs()
