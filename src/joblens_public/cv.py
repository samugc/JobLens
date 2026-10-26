"""Deterministic, evidence-grounded CV drafting.

The generator never calls a model. It only uses approved facts, ranks them by
relevance to an untrusted job posting, and emits a structured :class:`CvDraft`
whose every factual item cites the approved facts that support it. Every item
starts in ``needs_review``; nothing is ever approved automatically.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from joblens_public.profile.approved import ApprovedFact, ApprovedProfile, CandidateContact
from joblens_public.profile.contact import (
    ContactSuggestions,
    extract_contact_suggestions,
)
from joblens_public.profile.models import Category

#: Version of the CV draft contract.
CV_DRAFT_VERSION = "0.1"

#: Item review states.
NEEDS_REVIEW = "needs_review"
APPROVED = "approved"

#: Ollama endpoint used only by the optional adapter.
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "llama3.2"
OLLAMA_TIMEOUT = 10.0


@dataclass(frozen=True)
class CvDraftItem:
    item_id: str
    text: str
    approved_fact_ids: tuple[str, ...]
    review_status: str = NEEDS_REVIEW
    heading: str | None = None
    subheading: str | None = None
    period: str | None = None
    location: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "item_id": self.item_id,
            "text": self.text,
            "approved_fact_ids": list(self.approved_fact_ids),
            "review_status": self.review_status,
        }
        if self.heading is not None:
            payload["heading"] = self.heading
        if self.subheading is not None:
            payload["subheading"] = self.subheading
        if self.period is not None:
            payload["period"] = self.period
        if self.location is not None:
            payload["location"] = self.location
        return payload


@dataclass(frozen=True)
class CvDraftSection:
    section_id: str
    kind: str
    title: str
    items: tuple[CvDraftItem, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "kind": self.kind,
            "title": self.title,
            "items": [item.as_dict() for item in self.items],
        }


@dataclass(frozen=True)
class TargetJob:
    title: str | None = None
    company: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "company": self.company}


@dataclass(frozen=True)
class CvDraft:
    cv_draft_version: str = CV_DRAFT_VERSION
    target_job: TargetJob = field(default_factory=TargetJob)
    candidate: CandidateContact = field(default_factory=CandidateContact)
    sections: tuple[CvDraftSection, ...] = ()
    warnings: tuple[str, ...] = ()
    unmet_requirements: tuple[str, ...] = ()
    contact_suggestions: ContactSuggestions = field(default_factory=ContactSuggestions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cv_draft_version": self.cv_draft_version,
            "target_job": self.target_job.as_dict(),
            "candidate": self.candidate.as_dict(),
            "sections": [section.as_dict() for section in self.sections],
            "warnings": list(self.warnings),
            "unmet_requirements": list(self.unmet_requirements),
            "contact_suggestions": self.contact_suggestions.as_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "CvDraft":
        if not isinstance(payload, Mapping):
            raise ValueError("a CV draft must be an object")
        target = payload.get("target_job", {})
        if not isinstance(target, Mapping):
            raise ValueError("target_job must be an object")
        candidate_payload = payload.get("candidate", {})
        if not isinstance(candidate_payload, Mapping):
            raise ValueError("candidate must be an object")
        sections_payload = payload.get("sections", [])
        if not isinstance(sections_payload, Sequence) or isinstance(sections_payload, (str, bytes)):
            raise ValueError("sections must be an array")
        sections: list[CvDraftSection] = []
        for item in sections_payload:
            if not isinstance(item, Mapping):
                raise ValueError("a section must be an object")
            items_payload = item.get("items", [])
            if not isinstance(items_payload, Sequence) or isinstance(items_payload, (str, bytes)):
                raise ValueError("items must be an array")
            items: list[CvDraftItem] = []
            for raw in items_payload:
                if not isinstance(raw, Mapping):
                    raise ValueError("an item must be an object")
                status = raw.get("review_status", NEEDS_REVIEW)
                if status not in (NEEDS_REVIEW, APPROVED):
                    raise ValueError("invalid review_status")
                fact_ids = raw.get("approved_fact_ids", [])
                if not isinstance(fact_ids, Sequence) or isinstance(fact_ids, (str, bytes)):
                    raise ValueError("approved_fact_ids must be an array")
                items.append(
                    CvDraftItem(
                        item_id=str(raw["item_id"]),
                        text=str(raw["text"]),
                        approved_fact_ids=tuple(str(x) for x in fact_ids),
                        review_status=status,
                        heading=raw.get("heading"),
                        subheading=raw.get("subheading"),
                        period=raw.get("period"),
                        location=raw.get("location"),
                    )
                )
            sections.append(
                CvDraftSection(
                    section_id=str(item["section_id"]),
                    kind=str(item["kind"]),
                    title=str(item["title"]),
                    items=tuple(items),
                )
            )
        warnings = payload.get("warnings", [])
        if not isinstance(warnings, Sequence) or isinstance(warnings, (str, bytes)):
            raise ValueError("warnings must be an array")
        unmet = payload.get("unmet_requirements", [])
        if not isinstance(unmet, Sequence) or isinstance(unmet, (str, bytes)):
            raise ValueError("unmet_requirements must be an array")
        suggestions_payload = payload.get("contact_suggestions")
        if suggestions_payload is None:
            suggestions = ContactSuggestions()
        else:
            suggestions = ContactSuggestions.from_dict(suggestions_payload)
        return cls(
            cv_draft_version=str(payload.get("cv_draft_version", CV_DRAFT_VERSION)),
            target_job=TargetJob(title=target.get("title"), company=target.get("company")),
            candidate=CandidateContact.from_dict(candidate_payload),
            sections=tuple(sections),
            warnings=tuple(str(x) for x in warnings),
            unmet_requirements=tuple(str(x) for x in unmet),
            contact_suggestions=suggestions,
        )


def _normalise_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


_ACRONYMS = {
    "sql",
    "aws",
    "api",
    "ci",
    "cd",
    "ml",
    "ai",
    "nlp",
    "etl",
    "gcp",
    "azure",
    "gpu",
    "cpu",
    "ui",
    "ux",
    "qa",
    "hr",
    "it",
    "r",
    "c",
}


def _display_word(word: str) -> str:
    lowered = word.casefold()
    if lowered == "javascript":
        return "JavaScript"
    if lowered in _ACRONYMS:
        return lowered.upper()
    if not word:
        return word
    return word[0].upper() + word[1:]


def _display(value: str) -> str:
    return " ".join(_display_word(part) for part in value.split())


def _sentence(value: str) -> str:
    text = " ".join(value.split())
    if not text:
        return text
    if text[0].islower():
        text = text[0].upper() + text[1:]
    if text[-1].isalnum():
        text += "."
    return text


def _fact_text(fact: ApprovedFact) -> str:
    value = fact.value
    if fact.category is Category.SKILL:
        return _display(str(value.get("name", "")).strip())
    if fact.category is Category.LANGUAGE:
        level = value.get("stated_level")
        base = _display(str(value.get("language", "")).strip())
        return (
            f"{base} ({'Native' if str(level).casefold() == 'native' else str(level).upper()})"
            if level
            else base
        )
    if fact.category is Category.CERTIFICATION:
        return _display(str(value.get("name", "")).strip())
    if fact.category is Category.PROJECT:
        return _display(str(value.get("name", "")).strip())
    if fact.category is Category.EDUCATION:
        level = str(value.get("level", "")).strip()
        field_name = str(value.get("field", "")).strip()
        if field_name:
            return f"{_display(level)} in {_display(field_name)}"
        return _display(level)
    if fact.category is Category.EXPERIENCE:
        role = str(value.get("role", "")).strip()
        org = str(value.get("organization", "")).strip()
        if org:
            return f"{_display(role)} at {_display(org)}"
        return _display(role)
    return str(value)


def _relevance(fact: ApprovedFact, job: Any) -> int:
    score = 1
    fact_tokens = set(
        _normalise_token(_fact_text(fact) + " " + " ".join(e.quote for e in fact.evidence)).split()
    )
    job_tokens = set()
    for collection in (job.technologies, job.required, job.preferred, job.responsibilities):
        for item in collection:
            job_tokens.update(_normalise_token(item).split())
    for token in fact_tokens:
        if token and token in job_tokens:
            score += 2
    # Technology overlap is worth more.
    if fact.category is Category.SKILL:
        name = str(fact.value.get("name", "")).casefold()
        if name in {t.casefold() for t in job.technologies}:
            score += 4
    if fact.category is Category.PROJECT:
        for tech in job.technologies:
            if tech.casefold() in fact_tokens:
                score += 3
    if fact.category is Category.EXPERIENCE:
        role = str(fact.value.get("role", "")).casefold()
        for token in _normalise_token(role).split():
            if token in job_tokens:
                score += 2
    return score


def generate_cv_draft(
    profile: ApprovedProfile,
    job: Any,
    *,
    ollama: bool = False,
    source_response: Mapping[str, Any] | None = None,
) -> CvDraft:
    """Generate a deterministic CV draft from approved facts and a job posting.

    Contact details are never taken from the source automatically. When
    ``source_response`` is supplied, exact contact *suggestions* are attached
    to the draft so an editor can ask the candidate to confirm them.
    """
    suggestions = (
        extract_contact_suggestions(source_response)
        if source_response is not None
        else ContactSuggestions()
    )
    suggested_name = suggestions.by_field("full_name")
    warnings: list[str] = []
    if not profile.facts:
        warnings.append("No approved facts are available; nothing has been invented.")
    if not profile.candidate.full_name:
        if suggested_name is not None and suggested_name.selected:
            warnings.append(
                "A candidate name was found in the source documents; confirm or "
                "correct it before export."
            )
        else:
            warnings.append("Candidate full name is missing and must be supplied by the user.")
    if not profile.candidate.email and not profile.candidate.phone:
        suggested_contact = [
            item.selected
            for item in (suggestions.by_field("email"), suggestions.by_field("phone"))
            if item is not None and item.selected
        ]
        if suggested_contact:
            warnings.append(
                "Contact details were found in the source documents; confirm or "
                "correct them before export."
            )
        else:
            warnings.append("No candidate contact method is available.")

    facts = list(profile.facts)
    if not facts:
        return CvDraft(
            target_job=TargetJob(
                title=getattr(job, "title", None), company=getattr(job, "company", None)
            ),
            candidate=profile.candidate,
            sections=(),
            warnings=tuple(warnings),
            unmet_requirements=tuple(
                getattr(job, "required", ()) + getattr(job, "technologies", ())
            ),
            contact_suggestions=suggestions,
        )

    # Relevance ranking within each category.
    def ranked(category: Category) -> list[ApprovedFact]:
        items = [fact for fact in facts if fact.category is category]
        items.sort(key=lambda fact: (-_relevance(fact, job), facts.index(fact)))
        return items

    sections: list[CvDraftSection] = []
    item_counter = 0

    def next_id(prefix: str) -> str:
        nonlocal item_counter
        item_counter += 1
        return f"{prefix}_{item_counter:04d}"

    # Professional summary: only when supported by approved facts.
    experience_facts = ranked(Category.EXPERIENCE)
    skill_facts = ranked(Category.SKILL)
    if experience_facts and skill_facts:
        primary = experience_facts[0]
        skills = [_display(str(f.value.get("name", ""))) for f in skill_facts[:2]]
        contributions = [
            _sentence(e.quote.strip())
            for e in primary.evidence
            if re.match(
                r"^(Built|Documented|Developed|Implemented|Designed|Led|Tested|Reduced|Improved|Created|Maintained|Delivered)\b",
                e.quote.strip(),
                re.I,
            )
        ]
        if contributions:
            role = _display(str(primary.value.get("role", "")))
            text = f"{role} with experience in {' and '.join(skills)}. {contributions[0]}"
            sections.append(
                CvDraftSection(
                    "section_summary",
                    "summary",
                    "Professional Summary",
                    (
                        CvDraftItem(
                            next_id("item"),
                            text,
                            tuple(f.fact_id for f in [primary, *skill_facts[:2]]),
                        ),
                    ),
                )
            )

    # Experience.
    if experience_facts:
        items: list[CvDraftItem] = []
        for fact in experience_facts:
            role = str(fact.value.get("role", "")).strip()
            org = str(fact.value.get("organization", "")).strip()
            start = fact.value.get("start")
            end = fact.value.get("end")
            period = None
            if start or end:
                period = " - ".join(str(x) for x in (start, end) if x)
            # Provisional and approved facts may carry the full source line in
            # their evidence even when the structured value only has the role.
            # Preserve employer and dates from that evidence instead of dropping
            # them from the generated CV.
            if (not org or not period) and fact.evidence:
                parts = [part.strip() for part in str(fact.evidence[0].quote).split("|")]
                if not role and parts and parts[0]:
                    role = parts[0]
                if not org and len(parts) >= 2 and parts[1]:
                    org = parts[1]
                if not period and len(parts) >= 3 and parts[2]:
                    period = parts[2]
            display_role = _display(role) if role else None
            display_org = _display(org) if org else None
            subheading = display_org
            heading = display_role
            if display_role or display_org:
                text = " at ".join(x for x in (display_role, display_org) if x)
            else:
                text = _fact_text(fact)
            contribution_quotes = [
                _sentence(quote)
                for quote in dict.fromkeys(e.quote.strip() for e in fact.evidence)
                if re.match(
                    r"^(Built|Documented|Developed|Implemented|Designed|Led|Tested|Reduced|Improved|Created|Maintained|Delivered)\b",
                    quote,
                    re.I,
                )
            ]
            item_text = "; ".join(contribution_quotes) if contribution_quotes else text
            items.append(
                CvDraftItem(
                    item_id=next_id("item"),
                    text=item_text,
                    approved_fact_ids=(fact.fact_id,),
                    review_status=NEEDS_REVIEW,
                    heading=heading,
                    subheading=subheading,
                    period=period,
                )
            )
        sections.append(
            CvDraftSection(
                section_id="section_experience",
                kind="experience",
                title="Experience",
                items=tuple(items),
            )
        )
    else:
        warnings.append(
            "No approved experience facts are available; no experience has been invented."
        )

    # Projects.
    project_facts = ranked(Category.PROJECT)
    if project_facts:
        items = []
        for fact in project_facts:
            name = str(fact.value.get("name", "")).strip()
            display_name = _display(name)
            project_quotes = [
                _sentence(
                    re.sub(
                        r"^" + re.escape(name) + r"\s*[:–—-]\s*",
                        "",
                        e.quote.strip(),
                        flags=re.I,
                    )
                )
                for e in fact.evidence
            ]
            project_quotes = list(dict.fromkeys(project_quotes))
            item_text = "; ".join(project_quotes) if project_quotes else display_name
            items.append(
                CvDraftItem(
                    item_id=next_id("item"),
                    text=item_text,
                    approved_fact_ids=(fact.fact_id,),
                    review_status=NEEDS_REVIEW,
                    heading=display_name,
                )
            )
        sections.append(
            CvDraftSection(
                section_id="section_projects",
                kind="projects",
                title="Projects",
                items=tuple(items),
            )
        )

    # Education.
    education_facts = ranked(Category.EDUCATION)
    if education_facts:
        items = []
        for fact in education_facts:
            items.append(
                CvDraftItem(
                    item_id=next_id("item"),
                    text="; ".join(dict.fromkeys(e.quote.strip() for e in fact.evidence))
                    or _fact_text(fact),
                    approved_fact_ids=(fact.fact_id,),
                    review_status=NEEDS_REVIEW,
                )
            )
        sections.append(
            CvDraftSection(
                section_id="section_education",
                kind="education",
                title="Education",
                items=tuple(items),
            )
        )

    # Skills.
    if skill_facts:
        items = [
            CvDraftItem(
                item_id=next_id("item"),
                text=_display(str(fact.value.get("name", "")).strip()),
                approved_fact_ids=(fact.fact_id,),
                review_status=NEEDS_REVIEW,
            )
            for fact in skill_facts
        ]
        sections.append(
            CvDraftSection(
                section_id="section_skills",
                kind="skills",
                title="Skills",
                items=tuple(items),
            )
        )

    # Languages.
    language_facts = ranked(Category.LANGUAGE)
    if language_facts:
        items = [
            CvDraftItem(
                item_id=next_id("item"),
                text=_fact_text(fact),
                approved_fact_ids=(fact.fact_id,),
                review_status=NEEDS_REVIEW,
            )
            for fact in language_facts
        ]
        sections.append(
            CvDraftSection(
                section_id="section_languages",
                kind="languages",
                title="Languages",
                items=tuple(items),
            )
        )

    # Certifications.
    certification_facts = ranked(Category.CERTIFICATION)
    if certification_facts:
        items = [
            CvDraftItem(
                item_id=next_id("item"),
                text=_display(str(fact.value.get("name", "")).strip()),
                approved_fact_ids=(fact.fact_id,),
                review_status=NEEDS_REVIEW,
            )
            for fact in certification_facts
        ]
        sections.append(
            CvDraftSection(
                section_id="section_certifications",
                kind="certifications",
                title="Certifications",
                items=tuple(items),
            )
        )

    # Unmet requirements: job requirements not covered by any approved fact.
    def coverage_token(token: str) -> str:
        # A simple plural must not turn a covered requirement into a false gap.
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            return token[:-1]
        return token

    approved_tokens: set[str] = set()
    for fact in facts:
        approved_tokens.update(
            coverage_token(token)
            for token in _normalise_token(_fact_text(fact)).split()
        )
        for value in fact.value.values():
            if isinstance(value, str):
                approved_tokens.update(
                    coverage_token(token)
                    for token in _normalise_token(value).split()
                )
        for reference in fact.evidence:
            approved_tokens.update(
                coverage_token(token)
                for token in _normalise_token(reference.quote).split()
            )
    # Generated item text is source-backed too; including it avoids reporting
    # a gap when the supporting evidence is already visible in the draft.
    for section in sections:
        for item in section.items:
            approved_tokens.update(
                coverage_token(token)
                for token in _normalise_token(item.text).split()
            )
    unmet: list[str] = []
    seen_requirements: set[str] = set()

    def _add(requirement: str) -> None:
        key = _normalise_token(requirement)
        if not key or key in seen_requirements:
            return
        seen_requirements.add(key)
        unmet.append(requirement)

    for requirement in list(getattr(job, "required", ())) + list(getattr(job, "technologies", ())):
        req_tokens = {
            coverage_token(token)
            for token in _normalise_token(requirement).split()
        }
        if not req_tokens:
            continue
        if req_tokens & approved_tokens:
            # A shared meaningful token counts as covered.
            continue
        _add(requirement)
    for requirement in getattr(job, "preferred", ()):
        req_tokens = set(_normalise_token(requirement).split())
        if not req_tokens or (req_tokens & approved_tokens):
            continue
        _add(requirement)

    # Optional Ollama rewriting of the summary only, with strict fallback.
    if ollama:
        summary_section = next((s for s in sections if s.kind == "summary"), None)
        if summary_section and summary_section.items:
            item = summary_section.items[0]
            rewritten = _ollama_rewrite_summary(item.text, item.approved_fact_ids, profile)
            if rewritten is not None:
                new_item = CvDraftItem(
                    item_id=item.item_id,
                    text=rewritten,
                    approved_fact_ids=item.approved_fact_ids,
                    review_status=NEEDS_REVIEW,
                )
                sections = [
                    CvDraftSection(
                        section_id=s.section_id,
                        kind=s.kind,
                        title=s.title,
                        items=(new_item,) if s is summary_section else s.items,
                    )
                    if s is summary_section
                    else s
                    for s in sections
                ]

    return CvDraft(
        target_job=TargetJob(
            title=getattr(job, "title", None), company=getattr(job, "company", None)
        ),
        candidate=profile.candidate,
        sections=tuple(sections),
        warnings=tuple(warnings),
        unmet_requirements=tuple(unmet),
        contact_suggestions=suggestions,
    )


def _ollama_rewrite_summary(
    text: str, fact_ids: Sequence[str], profile: ApprovedProfile
) -> str | None:
    """Optional local-only rewrite. Returns None on any failure (fallback)."""
    fact_values = []
    for fact in profile.facts:
        if fact.fact_id in fact_ids:
            fact_values.append(fact.value)
    prompt = (
        "Rewrite the following professional summary in one sentence. "
        "Use only the facts provided. Return JSON with key 'text'.\n"
        f"Summary: {text}\nFacts: {fact_values}\n"
    )
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"}
    data = json.dumps(payload).encode("utf-8")
    try:
        request = urllib.request.Request(
            OLLAMA_URL, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    try:
        parsed = json.loads(raw)
        rewritten = parsed.get("response") if isinstance(parsed, dict) else None
        if isinstance(rewritten, str):
            rewritten = json.loads(rewritten)
        if not isinstance(rewritten, dict):
            return None
        candidate_text = rewritten.get("text")
        if not isinstance(candidate_text, str) or not candidate_text.strip():
            return None
        # Reject if it introduces tokens not present in the approved facts.
        approved_tokens = set()
        for value in fact_values:
            for item in value.values():
                if isinstance(item, str):
                    approved_tokens.update(_normalise_token(item).split())
        rewritten_tokens = set(_normalise_token(candidate_text).split())
        if not rewritten_tokens.issubset(approved_tokens | set(_normalise_token(text).split())):
            return None
        return candidate_text.strip()
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def edit_cv_item(draft: CvDraft, item_id: str, new_text: str) -> CvDraft:
    """Edit an item's text and revoke its approval."""
    new_sections: list[CvDraftSection] = []
    found = False
    for section in draft.sections:
        new_items: list[CvDraftItem] = []
        for item in section.items:
            if item.item_id == item_id:
                found = True
                new_items.append(
                    CvDraftItem(
                        item_id=item.item_id,
                        text=new_text,
                        approved_fact_ids=item.approved_fact_ids,
                        review_status=NEEDS_REVIEW,
                        heading=item.heading,
                        subheading=item.subheading,
                        period=item.period,
                        location=item.location,
                    )
                )
            else:
                new_items.append(item)
        new_sections.append(
            CvDraftSection(
                section_id=section.section_id,
                kind=section.kind,
                title=section.title,
                items=tuple(new_items),
            )
        )
    if not found:
        raise ValueError(f"unknown item {item_id!r}")
    return CvDraft(
        cv_draft_version=draft.cv_draft_version,
        target_job=draft.target_job,
        candidate=draft.candidate,
        sections=tuple(new_sections),
        warnings=draft.warnings,
        unmet_requirements=draft.unmet_requirements,
        contact_suggestions=draft.contact_suggestions,
    )


def approve_cv_item(draft: CvDraft, item_id: str) -> CvDraft:
    """Explicitly approve one item. Only an explicit call does this."""
    new_sections: list[CvDraftSection] = []
    found = False
    for section in draft.sections:
        new_items: list[CvDraftItem] = []
        for item in section.items:
            if item.item_id == item_id:
                found = True
                if not item.approved_fact_ids:
                    raise ValueError("an item without approved facts cannot be approved")
                new_items.append(
                    CvDraftItem(
                        item_id=item.item_id,
                        text=item.text,
                        approved_fact_ids=item.approved_fact_ids,
                        review_status=APPROVED,
                        heading=item.heading,
                        subheading=item.subheading,
                        period=item.period,
                        location=item.location,
                    )
                )
            else:
                new_items.append(item)
        new_sections.append(
            CvDraftSection(
                section_id=section.section_id,
                kind=section.kind,
                title=section.title,
                items=tuple(new_items),
            )
        )
    if not found:
        raise ValueError(f"unknown item {item_id!r}")
    return CvDraft(
        cv_draft_version=draft.cv_draft_version,
        target_job=draft.target_job,
        candidate=draft.candidate,
        sections=tuple(new_sections),
        warnings=draft.warnings,
        unmet_requirements=draft.unmet_requirements,
        contact_suggestions=draft.contact_suggestions,
    )


def update_candidate_contact(draft: CvDraft, contact: CandidateContact) -> CvDraft:
    """Replace the candidate contact details.

    This is an explicit user action, never an automatic fill. Review receipts
    bind the exact contact details of the draft, so any previously issued final
    confirmation stops matching after this change and must be given again.
    """
    if not isinstance(contact, CandidateContact):
        raise ValueError("contact must be a CandidateContact")
    return CvDraft(
        cv_draft_version=draft.cv_draft_version,
        target_job=draft.target_job,
        candidate=contact,
        sections=draft.sections,
        warnings=draft.warnings,
        unmet_requirements=draft.unmet_requirements,
        contact_suggestions=draft.contact_suggestions,
    )


def validate_export_eligibility(draft: CvDraft) -> list[str]:
    """Return blocking reasons; empty means export is allowed."""
    reasons: list[str] = []
    items = [item for section in draft.sections for item in section.items]
    if not items:
        reasons.append("the draft has no items")
    pending = [item.item_id for item in items if item.review_status != APPROVED]
    if pending:
        reasons.append(f"{len(pending)} item(s) are not approved")
    for item in items:
        if not item.approved_fact_ids:
            reasons.append(f"item {item.item_id} has no supporting approved facts")
    if not draft.candidate.full_name:
        reasons.append("candidate full name is missing")
    return reasons


def can_export(draft: CvDraft) -> bool:
    return not validate_export_eligibility(draft)


__all__ = [
    "APPROVED",
    "CV_DRAFT_VERSION",
    "CvDraft",
    "CvDraftItem",
    "CvDraftSection",
    "NEEDS_REVIEW",
    "TargetJob",
    "approve_cv_item",
    "can_export",
    "edit_cv_item",
    "generate_cv_draft",
    "update_candidate_contact",
    "validate_export_eligibility",
]
