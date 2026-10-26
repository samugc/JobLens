"""Run the synthetic scenarios through the real local HTTP pipeline."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from .scenarios import SCENARIOS, Scenario
from .support import (
    LocalServer,
    docx_text,
    json_payload,
    normalise,
    pdf_text,
    token_jaccard,
)


@dataclass
class ScenarioResult:
    id: str
    description: str
    tags: tuple[str, ...]
    status: str = "error"
    checks: list[dict[str, Any]] = field(default_factory=list)
    preserved_hits: int = 0
    preserved_total: int = 0
    forbidden_hits: int = 0
    forbidden_total: int = 0
    conflict_hits: int = 0
    conflict_total: int = 0
    supported_req_hits: int = 0
    supported_req_total: int = 0
    unsupported_req_hits: int = 0
    unsupported_req_total: int = 0
    parity: float = 0.0
    enforcement_attempts: int = 0
    enforcement_rejected: int = 0
    draft_items: int = 0
    omitted_count: int | None = None
    unmet_requirements: list[str] = field(default_factory=list)
    unmet_checked: int = 0
    unmet_present_in_cv: int = 0
    unmet_present_terms: list[str] = field(default_factory=list)
    pdf_pages: int = 0
    error: str | None = None

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})


def _export(server: LocalServer, draft: dict[str, Any], kind: str) -> tuple[int, dict[str, str], bytes]:
    return server.post_json(
        f"/api/cv/cv-drafts/export/{kind}",
        {"draft": draft, "confirmed": True, "contact": draft["candidate"]},
    )


def _confirm(server: LocalServer, draft: dict[str, Any], *, attested: bool = True) -> tuple[int, dict[str, str], bytes]:
    return server.post_json(
        "/api/cv/confirm",
        {"draft": draft, "confirmed": True, "attested": attested},
    )


def _set_contact(draft: dict[str, Any], contact: dict[str, Any] | None) -> None:
    if contact:
        draft["candidate"].update(contact)


def _prepare(server: LocalServer, scenario: Scenario) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    status, _, raw = server.post_files(list(scenario.documents))
    if status != 200:
        return None, {"stage": "extraction", "status": status, "body": raw[:400].decode("utf-8", "replace")}
    extraction = json_payload(raw)
    source = {key: extraction[key] for key in ("job_id", "documents")}
    status, _, raw = server.post_json(
        "/api/cv/draft", {"source": source, "text": scenario.job_text}
    )
    if status != 200:
        return None, {
            "stage": "draft",
            "status": status,
            "body": raw[:400].decode("utf-8", "replace"),
            "payload": json_payload(raw) if raw else {},
        }
    return json_payload(raw), {"stage": "ok", "status": status}


def _count_occurrences(text: str, needle: str) -> int:
    return normalise(text).count(normalise(needle))


def _review_battery(server: LocalServer, draft: dict[str, Any]) -> list[tuple[str, bool, str]]:
    """Return (attempt, rejected, detail) for invalid export attempts."""
    attempts: list[tuple[str, bool, str]] = []
    contact = draft["candidate"]

    def run(name: str, payload: dict[str, Any], *, expect: int = 400) -> None:
        status, _, raw = server.post_json(
            "/api/cv/cv-drafts/export/pdf", payload
        )
        body = raw[:200].decode("utf-8", "replace")
        attempts.append((name, status == expect, f"status={status} {body}"))

    forged = copy.deepcopy(draft)
    for section in forged["sections"]:
        for item in section["items"]:
            item["review_status"] = "approved"
    forged.get("review", {}).pop("final_receipt", None)
    forged.get("review", {}).pop("approvals", None)
    run("forged_status", {"draft": forged, "confirmed": True, "contact": contact})

    changed = copy.deepcopy(draft)
    changed["sections"][0]["items"][0]["text"] = "Invented employment at Example Corp."
    run("changed_text", {"draft": changed, "confirmed": True, "contact": contact})

    changed_contact = copy.deepcopy(draft)
    changed_contact["candidate"]["full_name"] = "Other Candidate"
    run("changed_contact", {"draft": changed_contact, "confirmed": True, "contact": contact})

    changed_email = copy.deepcopy(draft)
    changed_email["candidate"]["email"] = "other@example.com"
    run("changed_email", {"draft": changed_email, "confirmed": True, "contact": contact})

    reordered = copy.deepcopy(draft)
    reordered["sections"].reverse()
    run("reordered_sections", {"draft": reordered, "confirmed": True, "contact": contact})

    reordered_items = copy.deepcopy(draft)
    multi_item = next(
        (section for section in reordered_items["sections"] if len(section["items"]) > 1),
        None,
    )
    if multi_item is not None:
        multi_item["items"].reverse()
    run("reordered_items", {"draft": reordered_items, "confirmed": True, "contact": contact})

    added_section = copy.deepcopy(draft)
    added_section["sections"].append(copy.deepcopy(added_section["sections"][0]))
    run("added_section", {"draft": added_section, "confirmed": True, "contact": contact})

    tampered = copy.deepcopy(draft)
    tampered["review"]["baseline"]["sections"][0]["items"][0]["text"] = "Forged source"
    run("tampered_baseline", {"draft": tampered, "confirmed": True, "contact": contact})

    stale = copy.deepcopy(draft)
    stale["review"]["session_id"] = "old-session"
    run("stale_session", {"draft": stale, "confirmed": True, "contact": contact})

    wrong_contact = dict(contact)
    wrong_contact["full_name"] = "Someone Else"
    run("wrong_contact", {"draft": draft, "confirmed": True, "contact": wrong_contact})

    no_receipt = copy.deepcopy(draft)
    no_receipt["review"].pop("final_receipt", None)
    run("missing_final_receipt", {"draft": no_receipt, "confirmed": True, "contact": contact})

    run("string_confirmation", {"draft": draft, "confirmed": "true", "contact": contact})

    extra_contact = dict(contact)
    extra_contact["unexpected"] = "field"
    run("extra_contact_field", {"draft": draft, "confirmed": True, "contact": extra_contact})
    return attempts


def run_scenario(server: LocalServer, scenario: Scenario) -> ScenarioResult:
    result = ScenarioResult(
        id=scenario.id,
        description=scenario.description,
        tags=scenario.tags,
    )
    prepared, meta = _prepare(server, scenario)
    if prepared is None:
        if not scenario.expect_draft_success:
            body = meta.get("body", "")
            expected = scenario.expected_draft_error or ""
            result.status = "expected_error"
            result.check("draft_rejected", meta.get("status") == 400, body)
            result.check("expected_error_message", expected.casefold() in body.casefold(), body)
            return result
        result.status = "error"
        result.error = f"{meta.get('stage')} failed: {meta.get('status')} {meta.get('body', '')}"
        result.check("pipeline", False, result.error)
        return result

    if not scenario.expect_draft_success:
        result.status = "error"
        result.error = "expected the draft to be rejected, but it succeeded"
        result.check("draft_rejected", False, result.error)
        return result

    draft = prepared["draft"]
    result.draft_items = sum(len(section.get("items", [])) for section in draft.get("sections", []))
    result.omitted_count = prepared.get("omitted_count")
    result.unmet_requirements = list(draft.get("unmet_requirements", []))
    _set_contact(draft, scenario.contact)

    # Special positive path: edit, then re-confirm explicitly.
    if scenario.id == "edited_reconfirmed":
        status, _, raw = _confirm(server, draft)
        if status != 200:
            result.status = "error"
            result.error = f"first confirm failed: {status} {raw[:300]!r}"
            result.check("first_confirm", False, result.error)
            return result
        draft = json_payload(raw)["draft"]
        item = draft["sections"][0]["items"][0]
        status, _, raw = server.post_json(
            "/api/cv/cv-drafts/edit",
            {
                "draft": draft,
                "item_id": item["item_id"],
                "text": "Delivered Python services with tested REST APIs",
            },
        )
        if status != 200:
            result.status = "error"
            result.error = f"edit failed: {status} {raw[:300]!r}"
            result.check("edit", False, result.error)
            return result
        draft = json_payload(raw)["draft"]
        status, _, raw = _confirm(server, draft, attested=True)
        if status != 200:
            result.status = "error"
            result.error = f"reconfirm failed: {status} {raw[:300]!r}"
            result.check("reconfirm", False, result.error)
            return result
        draft = json_payload(raw)["draft"]
        result.check(
            "edited_item_candidate_attested",
            draft.get("review", {}).get("approvals", {}).get(item["item_id"], {}).get("mode")
            == "candidate_attested",
            str(
                draft.get("review", {})
                .get("approvals", {})
                .get(item["item_id"], {})
                .get("mode")
            ),
        )

    if scenario.id == "edited_without_reconfirm":
        status, _, raw = _confirm(server, draft)
        if status != 200:
            result.status = "error"
            result.error = f"confirm failed: {status} {raw[:300]!r}"
            result.check("confirm", False, result.error)
            return result
        draft = json_payload(raw)["draft"]
        item = draft["sections"][0]["items"][0]
        status, _, raw = server.post_json(
            "/api/cv/cv-drafts/edit",
            {
                "draft": draft,
                "item_id": item["item_id"],
                "text": "Edited but not re-confirmed",
            },
        )
        if status != 200:
            result.status = "error"
            result.error = f"edit failed: {status} {raw[:300]!r}"
            result.check("edit", False, result.error)
            return result
        draft = json_payload(raw)["draft"]
        status, _, raw = _export(server, draft, "pdf")
        result.check(
            "edited_export_rejected",
            status == 400,
            f"status={status} {raw[:200].decode('utf-8', 'replace')}",
        )

    if scenario.id == "unconfirmed_export":
        status, _, raw = _export(server, draft, "pdf")
        result.check(
            "unconfirmed_export_rejected",
            status == 400,
            f"status={status} {raw[:200].decode('utf-8', 'replace')}",
        )

    if scenario.id == "forged_approval":
        forged = copy.deepcopy(draft)
        for section in forged["sections"]:
            for item in section["items"]:
                item["review_status"] = "approved"
        status, _, raw = _export(server, forged, "pdf")
        result.check(
            "forged_approval_rejected",
            status == 400,
            f"status={status} {raw[:200].decode('utf-8', 'replace')}",
        )

    if scenario.id == "stale_session":
        stale = copy.deepcopy(draft)
        stale["review"]["session_id"] = "old-session"
        status, _, raw = _confirm(server, stale)
        result.check(
            "stale_session_rejected",
            status == 400,
            f"status={status} {raw[:200].decode('utf-8', 'replace')}",
        )

    # Normal confirmation for scenarios that should export.
    if scenario.id not in ("unconfirmed_export", "forged_approval", "stale_session"):
        if scenario.id != "edited_without_reconfirm" and scenario.id != "edited_reconfirmed":
            status, _, raw = _confirm(server, draft)
            if status != 200:
                result.status = "error"
                result.error = f"confirm failed: {status} {raw[:300]!r}"
                result.check("confirm", False, result.error)
                return result
            draft = json_payload(raw)["draft"]
        elif scenario.id == "edited_reconfirmed":
            # already confirmed above
            pass
        elif scenario.id == "edited_without_reconfirm":
            # export must remain blocked; do not try a successful export
            pass

    # Run the common review-enforcement battery for dedicated scenarios.
    if scenario.enforcement:
        attempts = _review_battery(server, draft)
        result.enforcement_attempts += len(attempts)
        for name, rejected, detail in attempts:
            result.enforcement_rejected += int(rejected)
            result.check(f"enforcement:{name}", rejected, detail)

    # Export and compare for scenarios that are expected to export.
    if scenario.id not in ("edited_without_reconfirm", "unconfirmed_export", "forged_approval", "stale_session"):
        status_pdf, _, pdf_bytes = _export(server, draft, "pdf")
        status_docx, _, docx_bytes = _export(server, draft, "docx")
        result.check("pdf_export", status_pdf == 200, f"status={status_pdf}")
        result.check("docx_export", status_docx == 200, f"status={status_docx}")
        if status_pdf != 200 or status_docx != 200:
            result.status = "error"
            result.error = "export failed"
            return result
        pdf = pdf_text(pdf_bytes)
        docx = docx_text(docx_bytes)
        result.pdf_pages = _pdf_pages(pdf_bytes)
        result.check("pdf_pages_nonzero", result.pdf_pages >= 1, f"pages={result.pdf_pages}")
        result.parity = token_jaccard(pdf, docx)
        result.check("pdf_docx_token_parity", result.parity >= 0.95, f"jaccard={result.parity:.3f}")

        for term in scenario.expected_preserved:
            result.preserved_total += 1
            hit = normalise(term) in normalise(pdf) and normalise(term) in normalise(docx)
            result.preserved_hits += int(hit)
            result.check(f"preserved:{term}", hit, "")

        for term in scenario.expected_absent:
            result.forbidden_total += 1
            present = normalise(term) in normalise(pdf) or normalise(term) in normalise(docx)
            result.forbidden_hits += int(present)
            result.check(f"absent:{term}", not present, "")

        for pattern in scenario.forbidden_patterns:
            result.forbidden_total += 1
            present = bool(re.search(pattern, pdf, re.I) or re.search(pattern, docx, re.I))
            result.forbidden_hits += int(present)
            result.check(f"absent_pattern:{pattern}", not present, "")

        for term in scenario.conflict_terms:
            result.conflict_total += 1
            present = normalise(term) in normalise(pdf) or normalise(term) in normalise(docx)
            result.conflict_hits += int(present)
            result.check(f"conflict_omitted:{term}", not present, "")

        for term in scenario.supported_requirements:
            result.supported_req_total += 1
            hit = normalise(term) in normalise(pdf)
            result.supported_req_hits += int(hit)
            result.check(f"supported_requirement:{term}", hit, "")

        for term in scenario.unsupported_requirements:
            result.unsupported_req_total += 1
            present = normalise(term) in normalise(pdf) or normalise(term) in normalise(docx)
            result.unsupported_req_hits += int(present)
            result.check(f"unsupported_requirement_absent:{term}", not present, "")

        # Soft quality metric: the draft's own gap report should not list a
        # requirement whose text is already present in the generated CV.
        # This is reported separately because it is a quality finding, not an
        # export-safety invariant.
        for term in result.unmet_requirements:
            result.unmet_checked += 1
            present = normalise(term) in normalise(pdf) or normalise(term) in normalise(docx)
            result.unmet_present_in_cv += int(present)
            if present:
                result.unmet_present_terms.append(term)

        for term, maximum in scenario.max_occurrences.items():
            count = _count_occurrences(pdf, term)
            result.check(
                f"max_occurrences:{term}",
                count <= maximum,
                f"count={count} max={maximum}",
            )

        result.status = "ok" if all(check["passed"] for check in result.checks) else "failed"
        return result

    result.status = "ok" if all(check["passed"] for check in result.checks) else "failed"
    return result


def _pdf_pages(data: bytes) -> int:
    import io

    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(data)).pages)


def run_all() -> dict[str, Any]:
    results: list[ScenarioResult] = []
    with LocalServer() as server:
        for scenario in SCENARIOS:
            results.append(run_scenario(server, scenario))
    return summarise(results)


def summarise(results: list[ScenarioResult]) -> dict[str, Any]:
    preserved_hits = sum(item.preserved_hits for item in results)
    preserved_total = sum(item.preserved_total for item in results)
    forbidden_hits = sum(item.forbidden_hits for item in results)
    forbidden_total = sum(item.forbidden_total for item in results)
    conflict_hits = sum(item.conflict_hits for item in results)
    conflict_total = sum(item.conflict_total for item in results)
    supported_req_hits = sum(item.supported_req_hits for item in results)
    supported_req_total = sum(item.supported_req_total for item in results)
    unsupported_req_hits = sum(item.unsupported_req_hits for item in results)
    unsupported_req_total = sum(item.unsupported_req_total for item in results)
    unmet_checked = sum(item.unmet_checked for item in results)
    unmet_present_in_cv = sum(item.unmet_present_in_cv for item in results)
    enforcement_attempts = sum(item.enforcement_attempts for item in results)
    enforcement_rejected = sum(item.enforcement_rejected for item in results)
    parity_values = [item.parity for item in results if item.parity > 0]
    hard_failures = [
        {"scenario": item.id, "checks": [c for c in item.checks if not c["passed"]]}
        for item in results
        if item.status in ("failed", "error")
    ]
    metrics = {
        "scenarios": len(results),
        "scenarios_ok": sum(1 for item in results if item.status == "ok"),
        "scenarios_expected_error": sum(1 for item in results if item.status == "expected_error"),
        "scenarios_failed": sum(1 for item in results if item.status in ("failed", "error")),
        "supported_fact_preservation_rate": _ratio(preserved_hits, preserved_total),
        "supported_fact_preserved": preserved_hits,
        "supported_fact_expected": preserved_total,
        "unsupported_or_forbidden_insertion_rate": _ratio(forbidden_hits, forbidden_total),
        "unsupported_or_forbidden_insertions": forbidden_hits,
        "unsupported_or_forbidden_checks": forbidden_total,
        "conflict_omission_rate": _ratio(conflict_total - conflict_hits, conflict_total),
        "conflict_terms_omitted": conflict_total - conflict_hits,
        "conflict_terms_checked": conflict_total,
        "supported_requirement_recall": _ratio(supported_req_hits, supported_req_total),
        "supported_requirements_present": supported_req_hits,
        "supported_requirements_checked": supported_req_total,
        "unsupported_requirement_leakage_rate": _ratio(unsupported_req_hits, unsupported_req_total),
        "unsupported_requirements_present": unsupported_req_hits,
        "unsupported_requirements_checked": unsupported_req_total,
        "unmet_requirements_checked": unmet_checked,
        "unmet_requirements_present_in_cv": unmet_present_in_cv,
        "unmet_requirement_false_gap_rate": _ratio(unmet_present_in_cv, unmet_checked),
        "pdf_docx_mean_token_jaccard": round(sum(parity_values) / len(parity_values), 4)
        if parity_values
        else None,
        "review_enforcement_rate": _ratio(enforcement_rejected, enforcement_attempts),
        "review_attempts_rejected": enforcement_rejected,
        "review_attempts": enforcement_attempts,
    }
    return {
        "metrics": metrics,
        "hard_failures": hard_failures,
        "scenarios": [item.__dict__ for item in results],
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)
