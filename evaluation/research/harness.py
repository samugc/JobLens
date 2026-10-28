"""Measure source-to-export achievement retention and requirement coverage.

The harness uses the real local HTTP application and the real PDF/DOCX
renderers. It never calls a model and never reads a real document.

Run: ``python -m evaluation.research.run_research --split development``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from evaluation.support import Document as UploadDocument
from evaluation.support import LocalServer, json_payload

from .cases import (
    AchievementCase,
    CoverageCase,
    RequirementLabel,
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _norm(text))
        if token
    }


@dataclass
class AchievementResult:
    case_id: str
    ok: bool = False
    checks: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})


@dataclass
class CoverageResult:
    case_id: str
    requirements: list[dict[str, Any]] = field(default_factory=list)
    duplicate_gap_entries: int = 0
    unmet: list[str] = field(default_factory=list)
    error: str | None = None


def _prepare(server: LocalServer, documents) -> tuple[dict[str, Any], dict[str, Any]]:
    uploads = [
        UploadDocument(document.filename, document.kind, document.text)
        for document in documents
    ]
    status, _, raw = server.post_files(uploads)
    if status != 200:
        raise RuntimeError(f"extraction failed: {status} {raw[:200]!r}")
    extraction = json_payload(raw)
    return {key: extraction[key] for key in ("job_id", "documents")}, extraction


def _draft(server: LocalServer, source: dict[str, Any], job_text: str) -> dict[str, Any]:
    status, _, raw = server.post_json(
        "/api/cv/draft", {"source": source, "text": job_text}
    )
    if status != 200:
        raise RuntimeError(f"draft failed: {status} {raw[:300]!r}")
    return json_payload(raw)["draft"]


def _experience_texts(draft: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for section in draft.get("sections", []):
        if section.get("kind") != "experience":
            continue
        for item in section.get("items", []):
            for key in ("text", "heading", "subheading", "period"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(value)
    return values


def _export(server: LocalServer, draft: dict[str, Any], kind: str) -> str:
    status, _, raw = server.post_json(
        "/api/cv/cv-drafts/export/" + kind,
        {"draft": draft, "confirmed": True, "contact": draft["candidate"]},
    )
    if status != 200:
        raise RuntimeError(f"export {kind} failed: {status} {raw[:300]!r}")
    if kind == "pdf":
        from evaluation.support import pdf_text

        return pdf_text(raw)
    from evaluation.support import docx_text

    return docx_text(raw)


def run_achievement_case(server: LocalServer, case: AchievementCase) -> AchievementResult:
    result = AchievementResult(case.id)
    try:
        source, _ = _prepare(server, case.documents)
        draft = _draft(server, source, case.job_text)
        if not draft["candidate"].get("full_name"):
            draft["candidate"]["full_name"] = "Fictional Candidate"
        if not draft["candidate"].get("email"):
            draft["candidate"]["email"] = "fictional@example.com"
        status, _, raw = server.post_json(
            "/api/cv/confirm",
            {"draft": draft, "confirmed": True, "attested": True},
        )
        if status != 200:
            raise RuntimeError(f"confirm failed: {status} {raw[:300]!r}")
        confirmed = json_payload(raw)["draft"]

        experience = _norm(" ".join(_experience_texts(draft)))
        experience_items = sum(
            len(section.get("items", []))
            for section in draft.get("sections", [])
            if section.get("kind") == "experience"
        )
        if case.max_experience_items is not None:
            result.check(
                "draft_experience_item_count",
                experience_items <= case.max_experience_items,
                f"count={experience_items} max={case.max_experience_items}",
            )
        for phrase in case.experience_text:
            result.check(
                f"draft_experience:{phrase}",
                _norm(phrase) in experience,
                experience[:200],
            )
        for phrase in case.experience_must_not_contain:
            result.check(
                f"draft_experience_absent:{phrase}",
                _norm(phrase) not in experience,
                experience[:200],
            )

        rendered = {kind: _norm(_export(server, confirmed, kind)) for kind in ("pdf", "docx")}
        for kind, text in rendered.items():
            for phrase in case.must_preserve:
                result.check(
                    f"{kind}_preserved:{phrase}",
                    _norm(phrase) in text,
                    text[:300],
                )
            for phrase in case.must_not_preserve:
                result.check(
                    f"{kind}_absent:{phrase}",
                    _norm(phrase) not in text,
                    text[:300],
                )
            for phrase, maximum in case.max_occurrences.items():
                count = text.count(_norm(phrase))
                result.check(
                    f"{kind}_max_occurrences:{phrase}",
                    count <= maximum,
                    f"count={count} max={maximum}",
                )
        result.ok = all(check["passed"] for check in result.checks)
    except Exception as exc:  # noqa: BLE001 - reported, not hidden
        result.error = str(exc)[:400]
    return result


def _importance_for(job: Any, label: RequirementLabel) -> str:
    folded = _norm(label.text)
    for value in getattr(job, "required", ()):
        if _norm(value) == folded:
            return "required"
    for value in getattr(job, "preferred", ()):
        if _norm(value) == folded:
            return "preferred"
    for value in getattr(job, "responsibilities", ()):
        if _norm(value) == folded:
            return "responsibility"
    for value in getattr(job, "technologies", ()):
        if _norm(value) == folded:
            return "unknown"
    return "unknown"


def _coverage_entry(draft: dict[str, Any], label: RequirementLabel) -> dict[str, Any] | None:
    for entry in draft.get("requirement_coverage", []) or []:
        if isinstance(entry, dict) and _norm(str(entry.get("requirement", ""))) == _norm(label.text):
            return entry
    return None


def _duplicate_gap_count(unmet: list[str]) -> int:
    token_sets = [(_norm(item), _tokens(item)) for item in unmet]
    duplicates = 0
    for index, (_, tokens) in enumerate(token_sets):
        for other_index, (_, other) in enumerate(token_sets):
            if index == other_index:
                continue
            if tokens and tokens < other:
                duplicates += 1
                break
    return duplicates


def run_coverage_case(server: LocalServer, case: CoverageCase) -> CoverageResult:
    result = CoverageResult(case.id)
    try:
        source, _ = _prepare(server, case.documents)
        draft = _draft(server, source, case.job_text)
        result.unmet = list(draft.get("unmet_requirements", []))
        report = draft.get("decision_report", {}) or {}
        supports: list[str] = []
        for decision in report.get("decisions", []) or []:
            if decision.get("outcome") != "included":
                continue
            for item in decision.get("supports", []) or []:
                supports.append(_norm(str(item)))

        for label in case.requirements:
            from joblens_public.jobs import parse_job_posting

            job = parse_job_posting(case.job_text)
            entry = _coverage_entry(draft, label)
            if entry is not None:
                predicted = str(entry.get("state", "unknown"))
                predicted_importance = str(entry.get("importance", "unknown"))
            else:
                predicted = (
                    "uncovered"
                    if any(_norm(item) == _norm(label.text) for item in result.unmet)
                    else "covered"
                )
                predicted_importance = _importance_for(job, label)
            supported_in_report = any(
                _norm(label.text) == support or _norm(label.text) in support
                for support in supports
            )
            result.requirements.append(
                {
                    "text": label.text,
                    "gold_state": label.state,
                    "predicted_state": predicted,
                    "gold_importance": label.importance,
                    "predicted_importance": predicted_importance,
                    "supported_in_report": supported_in_report,
                    "coverage_entry_present": entry is not None,
                }
            )
        result.duplicate_gap_entries = _duplicate_gap_count(result.unmet)
    except Exception as exc:  # noqa: BLE001 - reported, not hidden
        result.error = str(exc)[:400]
    return result


def aggregate(
    achievements: list[AchievementResult],
    coverage: list[CoverageResult],
) -> dict[str, Any]:
    ach_checks = [check for case in achievements for check in case.checks]
    reqs = [item for case in coverage for item in case.requirements]

    def count(predicate) -> int:
        return sum(1 for item in reqs if predicate(item))

    covered = [item for item in reqs if item["gold_state"] == "covered"]
    partial = [item for item in reqs if item["gold_state"] == "partial"]
    uncovered = [item for item in reqs if item["gold_state"] == "uncovered"]

    metrics = {
        "achievement_cases": len(achievements),
        "achievement_cases_ok": sum(1 for case in achievements if case.ok),
        "achievement_checks": len(ach_checks),
        "achievement_checks_passed": sum(1 for check in ach_checks if check["passed"]),
        "coverage_cases": len(coverage),
        "coverage_cases_ok": sum(1 for case in coverage if case.error is None),
        "requirements": len(reqs),
        "state_correct": count(lambda item: item["gold_state"] == item["predicted_state"]),
        "unsafe_cover": count(
            lambda item: item["gold_state"] in {"partial", "uncovered"}
            and item["predicted_state"] == "covered"
        ),
        "covered_requirements": len(covered),
        "covered_recalled": sum(
            1 for item in covered if item["predicted_state"] == "covered"
        ),
        "partial_requirements": len(partial),
        "partial_recalled": sum(
            1 for item in partial if item["predicted_state"] == "partial"
        ),
        "uncovered_requirements": len(uncovered),
        "uncovered_recalled": sum(
            1 for item in uncovered if item["predicted_state"] == "uncovered"
        ),
        "importance_checks": len(reqs),
        "importance_correct": count(
            lambda item: item["gold_importance"] == item["predicted_importance"]
        ),
        "duplicate_gap_entries": sum(case.duplicate_gap_entries for case in coverage),
        "report_support_false_claims": count(
            lambda item: item["gold_state"] in {"partial", "uncovered"}
            and item["supported_in_report"]
        ),
        "report_support_missing": count(
            lambda item: item["gold_state"] == "covered"
            and not item["supported_in_report"]
        ),
        "coverage_report_inconsistent": count(
            lambda item: (
                item["predicted_state"] in {"covered", "partial"}
                and not item["supported_in_report"]
            )
            or (
                item["predicted_state"] == "uncovered"
                and item["supported_in_report"]
            )
        ),
        "errors": sum(1 for case in achievements if case.error)
        + sum(1 for case in coverage if case.error),
    }
    return metrics
