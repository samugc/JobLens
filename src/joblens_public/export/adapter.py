"""Narrow adapter from a CvDraft (parser dataclass, dict or mapping) to the
canonical model used by the renderers.

The adapter deliberately tolerates additive fields: unknown keys on drafts,
sections and items are ignored. It does not tolerate missing required fields
or wrong types.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import (
    ApprovalError,
    ContactError,
    EvidenceContractError,
    InvalidDraftError,
    UnsupportedSchemaError,
)
from .models import (
    SUPPORTED_SCHEMA_VERSIONS,
    CanonicalCandidate,
    CanonicalDraft,
    CanonicalItem,
    CanonicalSection,
    CanonicalTargetJob,
)


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping) and not isinstance(value, (str, bytes, bytearray))


def _as_mapping(draft: Any) -> Mapping[str, Any]:
    """Coerce any supported draft representation into a mapping."""
    if _is_mapping(draft):
        return draft
    if hasattr(draft, "as_dict") and callable(draft.as_dict):
        try:
            result = draft.as_dict()
        except Exception as exc:  # pragma: no cover - defensive
            raise InvalidDraftError(f"as_dict() failed: {exc}") from exc
        if not _is_mapping(result):
            raise InvalidDraftError("as_dict() did not return a mapping")
        return result
    if hasattr(draft, "model_dump") and callable(draft.model_dump):
        try:
            result = draft.model_dump()
        except Exception as exc:
            raise InvalidDraftError(f"model_dump() failed: {exc}") from exc
        if not _is_mapping(result):
            raise InvalidDraftError("model_dump() did not return a mapping")
        return result
    if hasattr(draft, "dict") and callable(draft.dict):
        try:
            result = draft.dict()
        except Exception as exc:
            raise InvalidDraftError(f"dict() failed: {exc}") from exc
        if _is_mapping(result):
            return result
    # Last resort: read known attributes.
    known = (
        "cv_draft_version",
        "target_job",
        "candidate",
        "sections",
        "warnings",
        "unmet_requirements",
    )
    if any(hasattr(draft, name) for name in known):
        payload: dict[str, Any] = {}
        for name in known:
            if hasattr(draft, name):
                value = getattr(draft, name)
                if name in ("target_job", "candidate") and hasattr(value, "as_dict"):
                    value = value.as_dict()
                if name == "sections" and isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    new_sections = []
                    for section in value:
                        if hasattr(section, "as_dict"):
                            new_sections.append(section.as_dict())
                        else:
                            new_sections.append(section)
                    value = new_sections
                payload[name] = value
        if "sections" not in payload:
            payload["sections"] = []
        return payload
    raise InvalidDraftError("unsupported draft type: cannot convert to a mapping")


def _require_str(value: Any, field: str, *, allow_none: bool = False) -> str | None:
    if value is None:
        if allow_none:
            return None
        raise InvalidDraftError(f"{field} must be a string")
    if not isinstance(value, str):
        raise InvalidDraftError(f"{field} must be a string")
    return value


def _to_str_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)):
        raise InvalidDraftError(f"{field} must be an array, not a string")
    if not isinstance(value, Sequence):
        raise InvalidDraftError(f"{field} must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            # Tolerate non-string scalars by stringifying.
            if item is None:
                continue
            result.append(str(item))
        else:
            result.append(item)
    return tuple(result)


def _convert_candidate(raw: Any) -> CanonicalCandidate:
    if not _is_mapping(raw):
        raise InvalidDraftError("candidate must be an object")
    full_name = raw.get("full_name")
    if full_name is not None and not isinstance(full_name, str):
        raise InvalidDraftError("candidate.full_name must be a string or null")
    full_name = (full_name or "").strip() if isinstance(full_name, str) else ""
    email = raw.get("email")
    phone = raw.get("phone")
    location = raw.get("location")
    for name, val in (("email", email), ("phone", phone), ("location", location)):
        if val is not None and not isinstance(val, str):
            raise InvalidDraftError(f"candidate.{name} must be a string or null")
    links = _to_str_tuple(raw.get("links", []), "candidate.links")
    # Links may be objects in additive schemas: stringify mappings.
    normalised_links = [link for link in links]
    # Re-handle links if they were mappings.
    raw_links = raw.get("links", [])
    if isinstance(raw_links, Sequence) and not isinstance(raw_links, (str, bytes)):
        normalised_links = []
        for item in raw_links:
            if isinstance(item, str):
                normalised_links.append(item)
            elif _is_mapping(item):
                # Accept {"url":..., "label":...} or {"href":...}
                url = item.get("url") or item.get("href") or item.get("link")
                if url is not None:
                    normalised_links.append(str(url))
            else:
                normalised_links.append(str(item))
    return CanonicalCandidate(
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        links=tuple(normalised_links),
    )


def _convert_target_job(raw: Any) -> CanonicalTargetJob:
    if raw is None:
        raw = {}
    if not _is_mapping(raw):
        raise InvalidDraftError("target_job must be an object")
    title = raw.get("title")
    company = raw.get("company")
    if title is not None and not isinstance(title, str):
        title = str(title)
    if company is not None and not isinstance(company, str):
        company = str(company)
    return CanonicalTargetJob(title=title, company=company)


def _convert_item(raw: Any, index: int) -> CanonicalItem:
    if not _is_mapping(raw):
        raise InvalidDraftError(f"items[{index}] must be an object")
    # Required fields.
    try:
        item_id = raw["item_id"]
    except KeyError as exc:
        raise InvalidDraftError(f"items[{index}] missing item_id") from exc
    try:
        text = raw["text"]
    except KeyError as exc:
        raise InvalidDraftError(f"items[{index}] missing text") from exc
    if not isinstance(item_id, str) or not item_id.strip():
        raise InvalidDraftError(f"items[{index}].item_id must be a non-empty string")
    if not isinstance(text, str):
        raise InvalidDraftError(f"items[{index}].text must be a string")
    status = raw.get("review_status", "needs_review")
    if not isinstance(status, str):
        raise InvalidDraftError(f"items[{index}].review_status must be a string")
    fact_ids_raw = raw.get("approved_fact_ids", [])
    if fact_ids_raw is None:
        fact_ids_raw = []
    if isinstance(fact_ids_raw, (str, bytes, bytearray)):
        raise InvalidDraftError(f"items[{index}].approved_fact_ids must be an array")
    if not isinstance(fact_ids_raw, Sequence):
        raise InvalidDraftError(f"items[{index}].approved_fact_ids must be an array")
    fact_ids: list[str] = []
    for fid in fact_ids_raw:
        if fid is None:
            continue
        fact_ids.append(str(fid))
    # Optional fields.
    heading = raw.get("heading")
    subheading = raw.get("subheading")
    period = raw.get("period")
    location = raw.get("location")
    for fname, val in (
        ("heading", heading),
        ("subheading", subheading),
        ("period", period),
        ("location", location),
    ):
        if val is not None and not isinstance(val, str):
            # Tolerate non-string by stringifying (additive).
            pass
    if heading is not None and not isinstance(heading, str):
        heading = str(heading)
    if subheading is not None and not isinstance(subheading, str):
        subheading = str(subheading)
    if period is not None and not isinstance(period, str):
        period = str(period)
    if location is not None and not isinstance(location, str):
        location = str(location)
    # Extra fields.
    known = {
        "item_id",
        "text",
        "approved_fact_ids",
        "review_status",
        "heading",
        "subheading",
        "period",
        "location",
    }
    extra = {k: v for k, v in raw.items() if k not in known}
    return CanonicalItem(
        item_id=item_id,
        text=text,
        approved_fact_ids=tuple(fact_ids),
        review_status=status,
        heading=heading,
        subheading=subheading,
        period=period,
        location=location,
        extra=extra,
    )


def _convert_section(raw: Any, index: int) -> CanonicalSection:
    if not _is_mapping(raw):
        raise InvalidDraftError(f"sections[{index}] must be an object")
    try:
        section_id = raw["section_id"]
    except KeyError as exc:
        raise InvalidDraftError(f"sections[{index}] missing section_id") from exc
    try:
        kind = raw["kind"]
    except KeyError as exc:
        raise InvalidDraftError(f"sections[{index}] missing kind") from exc
    try:
        title = raw["title"]
    except KeyError as exc:
        raise InvalidDraftError(f"sections[{index}] missing title") from exc
    if not isinstance(section_id, str) or not section_id.strip():
        raise InvalidDraftError(f"sections[{index}].section_id must be a non-empty string")
    if not isinstance(kind, str) or not kind.strip():
        raise InvalidDraftError(f"sections[{index}].kind must be a non-empty string")
    if not isinstance(title, str):
        raise InvalidDraftError(f"sections[{index}].title must be a string")
    items_raw = raw.get("items", [])
    if items_raw is None:
        items_raw = []
    if isinstance(items_raw, (str, bytes, bytearray)):
        raise InvalidDraftError(f"sections[{index}].items must be an array")
    if not isinstance(items_raw, Sequence):
        raise InvalidDraftError(f"sections[{index}].items must be an array")
    items = tuple(_convert_item(item, i) for i, item in enumerate(items_raw))
    known = {"section_id", "kind", "title", "items"}
    extra = {k: v for k, v in raw.items() if k not in known}
    return CanonicalSection(
        section_id=section_id,
        kind=kind,
        title=title,
        items=items,
        extra=extra,
    )


def adapt_draft(draft: Any) -> CanonicalDraft:
    """Convert and validate a draft into the canonical model."""
    payload = _as_mapping(draft)

    version = payload.get("cv_draft_version", "0.1")
    if version is None:
        version = "0.1"
    if not isinstance(version, str):
        version = str(version)
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaError(
            f"unsupported cv_draft_version {version!r}; expected one of {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    target_job = _convert_target_job(payload.get("target_job", {}))
    candidate = _convert_candidate(payload.get("candidate", {}))

    sections_raw = payload.get("sections", [])
    if sections_raw is None:
        sections_raw = []
    if isinstance(sections_raw, (str, bytes, bytearray)):
        raise InvalidDraftError("sections must be an array")
    if not isinstance(sections_raw, Sequence):
        raise InvalidDraftError("sections must be an array")
    sections = tuple(_convert_section(s, i) for i, s in enumerate(sections_raw))

    warnings = _to_str_tuple(payload.get("warnings", []), "warnings")
    unmet = _to_str_tuple(payload.get("unmet_requirements", []), "unmet_requirements")

    return CanonicalDraft(
        cv_draft_version=version,
        target_job=target_job,
        candidate=candidate,
        sections=sections,
        warnings=warnings,
        unmet_requirements=unmet,
        raw=draft,
    )


def validate_export(
    draft: CanonicalDraft,
    *,
    evidence_support: Any = None,
) -> None:
    """Raise on any blocking condition. Returns None if export is allowed."""
    # Candidate contact.
    if not draft.candidate.full_name or not draft.candidate.full_name.strip():
        raise ContactError("candidate full name is missing")

    items = [item for section in draft.sections for item in section.items]
    if not items:
        raise InvalidDraftError("the draft has no items")

    pending = [item.item_id for item in items if item.review_status != "approved"]
    if pending:
        raise ApprovalError(f"{len(pending)} item(s) are not approved: {', '.join(pending)}")

    missing_facts = [item.item_id for item in items if not item.approved_fact_ids]
    if missing_facts:
        raise EvidenceContractError(
            f"item(s) without supporting approved facts: {', '.join(missing_facts)}"
        )

    # Evidence-support contract validation.
    if evidence_support is not None:
        fact_ids = _extract_fact_ids(evidence_support)
        if fact_ids is None:
            raise EvidenceContractError("invalid evidence-support contract")
        # Cross-check: every item fact id must be present in the contract.
        all_item_ids = {fid for item in items for fid in item.approved_fact_ids}
        unknown = sorted(all_item_ids - fact_ids)
        if unknown:
            raise EvidenceContractError(
                f"item(s) reference unknown approved facts: {', '.join(unknown)}"
            )


def _extract_fact_ids(value: Any) -> set[str] | None:
    """Return a set of approved fact ids from a support object, or None if invalid."""
    if value is None:
        return set()
    # Direct iterable of strings.
    if isinstance(value, (set, frozenset, list, tuple)):
        if all(isinstance(x, str) for x in value):
            return set(value)
        # Could be iterable of mappings/dicts.
        ids: set[str] = set()
        ok = False
        for item in value:
            if isinstance(item, str):
                ids.add(item)
                ok = True
            elif _is_mapping(item):
                fid = item.get("fact_id") or item.get("id") or item.get("approved_fact_id")
                if isinstance(fid, str):
                    ids.add(fid)
                    ok = True
                else:
                    return None
            else:
                return None
        return ids if ok else None
    if _is_mapping(value):
        # ApprovedProfile-like: has "facts"
        if "facts" in value:
            facts = value.get("facts")
            if not isinstance(facts, Sequence) or isinstance(facts, (str, bytes)):
                return None
            ids = set()
            for fact in facts:
                if _is_mapping(fact):
                    fid = fact.get("fact_id") or fact.get("id")
                    if not isinstance(fid, str):
                        return None
                    ids.add(fid)
                elif isinstance(fact, str):
                    ids.add(fact)
                else:
                    # Could be ApprovedFact dataclass.
                    if hasattr(fact, "fact_id"):
                        ids.add(str(fact.fact_id))
                    else:
                        return None
            return ids
        # Mapping keyed by fact id.
        if all(isinstance(k, str) for k in value):
            # Heuristic: if values look like facts, use keys.
            sample = next(iter(value.values()), None)
            if _is_mapping(sample) or hasattr(sample, "fact_id") or sample is None:
                return set(value.keys())
        return None
    # Object with .facts attribute.
    if hasattr(value, "facts"):
        facts = value.facts
        if isinstance(facts, Sequence) and not isinstance(facts, (str, bytes)):
            ids = set()
            for fact in facts:
                if hasattr(fact, "fact_id"):
                    ids.add(str(fact.fact_id))
                elif _is_mapping(fact):
                    fid = fact.get("fact_id") or fact.get("id")
                    if not isinstance(fid, str):
                        return None
                    ids.add(fid)
                elif isinstance(fact, str):
                    ids.add(fact)
                else:
                    return None
            return ids
        return None
    # Object with .approved_fact_ids? 
    if hasattr(value, "approved_fact_ids"):
        ids = value.approved_fact_ids
        if isinstance(ids, (set, frozenset, list, tuple)) and all(isinstance(x, str) for x in ids):
            return set(ids)
    return None