"""Evidence-first matching between an attested CV fact bank and a posting.

This is coverage of *documented* requirements, not a probability of hiring.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .extraction import (
    BENEFIT_HEADING_RE,
    PREFERRED_CUES,
    PREFERRED_SECTION_RE,
    REQUIRED_CUES,
    REQUIRED_SECTION_RE,
    SKILL_ALIASES,
    extract_job_posting,
    is_benefit_text,
)


def _mentions(text: str, aliases: tuple[str, ...]) -> bool:
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(alias.casefold()) + r"(?![a-z0-9])",
                  text.casefold()) is not None
        for alias in aliases
    )



# Section labels found in real job descriptions. A heading marks the employer's
# stated preference, not independent proof that every item is a hard blocker.
_REQUIRED_HEADING_EN = re.compile(
    r"^(?:must[- ]haves?|required (?:qualifications|(?:technical |core )?skills)|"
    r"key qualifications|qualifications(?:\s+and\s+requirements)?|"
    r"(?:what you(?:['’]ll| will)? bring)|about you|"
    r"(?:here are some of the things )?(?:we are|we're) looking for|"
    r"minimum requirements|"
    r"experience with (?:the )?(?:following|below) tech stack is required|"
    r"essential .*\(must[- ]have\)|"
    r"you(?:['’]ll| will) need to have)"
    r"\s*(?::\s*(.*))?$", re.I
)
_PREFERRED_HEADING_EN = re.compile(
    r"^(?:nice[- ]to[- ]haves?(?:\s+skills)?|bonus points if you|"
    r"bonus qualifications|preferred qualifications)"
    r"\s*(?::\s*(.*))?$", re.I
)


_REQUIRED_HEADING_ES = re.compile(
    r"^(?:requisitos(?:\s+(?:m[ií]nimos|obligatorios))?|"
    r"imprescindible|conocimientos obligatorios)\s*(?::\s*(.*))?$", re.I
)
_PREFERRED_HEADING_ES = re.compile(
    r"^(?:valorable|se valorar[aá]|deseable|requisitos deseables)"
    r"\s*(?::\s*(.*))?$", re.I
)
_PREFERRED_WORDS = PREFERRED_CUES + (
    "valorable", "se valorará", "se valorara", "deseable", "preferible"
)
_REQUIRED_WORDS = REQUIRED_CUES + (
    "imprescindible", "obligatorio", "obligatoria", "se requiere",
    "necesario", "necesaria"
)
_NOT_REQUIRED = re.compile(
    r"\b(?:not required|not mandatory|not necessary|no requirement for|"
    r"no es (?:necesario|necesaria|obligatorio|obligatoria)|"
    r"no se requiere)\b", re.I
)


def _cue_type(clause: str) -> str | None:
    lower = clause.casefold()
    if _NOT_REQUIRED.search(lower):
        return "mentioned"
    preferred = any(cue in lower for cue in _PREFERRED_WORDS)
    required = any(cue in lower for cue in _REQUIRED_WORDS) or bool(
        re.search(r"\b(?:requires?|must know|must be proficient in)\b", lower)
    )
    if preferred and required:
        return "mentioned"  # Conflicting labels need review.
    if preferred:
        return "preferred"
    if required:
        return "required"
    return None


def _triage_skills(description: str) -> dict[str, set[str]]:
    """Classify explicit requirement scopes; do not count incidental technology.

    A single ambiguous clause is left as 'mentioned'. Mixed comma clauses
    are separated only if every component has its own qualification cue.
    """
    grouped: dict[str, set[str]] = {
        "required": set(), "preferred": set(), "mentioned": set()
    }
    section = "mentioned"
    benefit_section = False
    # Headings sometimes begin after introductory prose on the same line:
    # "We use AWS. Requirements:\nPython". Split only at punctuation
    # followed by a recognized heading; leave other prose untouched.
    heading = (
        r"(?:requirements?|required(?:\s+(?:skills|qualifications))?|"
        r"preferred(?:\s+(?:skills|qualifications))?|nice[- ]to[- ]have|"
        r"minimum qualifications|essential|must[- ]haves?|"
        r"benefits?(?:\s+(?:include|includes|including))?|"
        r"perks?(?:\s+(?:include|includes|including))?|"
        r"what we offer|we offer|training(?: and development)?|"
        r"requisitos(?:\s+\w+)?|"
        r"valorable|deseable|requisitos deseables)"
    )
    description = re.sub(
        r"(?<=[.!?])\s+(?=" + heading + r"\s*:)",
        "\n",
        description,
        flags=re.IGNORECASE,
    )
    for raw_line in re.split(r"[\n•]+", description):
        line = raw_line.strip().lstrip("-* ").strip()
        if not line:
            continue
        for pattern, category, is_benefit in (
            (BENEFIT_HEADING_RE, "mentioned", True),
            (PREFERRED_SECTION_RE, "preferred", False),
            (_PREFERRED_HEADING_EN, "preferred", False),
            (_PREFERRED_HEADING_ES, "preferred", False),
            (REQUIRED_SECTION_RE, "required", False),
            (_REQUIRED_HEADING_EN, "required", False),
            (_REQUIRED_HEADING_ES, "required", False),
        ):
            match = pattern.fullmatch(line)
            if match is None:
                continue
            section = category
            benefit_section = is_benefit
            if re.match(r"^(responsibilities|about the role)\b", line, re.I):
                section = "mentioned"
                benefit_section = False
            line = (match.group(1) or "").strip()
            break

        for clause in re.split(r"(?<=[.!?])\s+|[;]", line):
            chunk = clause.strip()
            if not chunk:
                continue
            segments = [chunk]
            comma_parts = [item.strip() for item in chunk.split(",") if item.strip()]
            if len(comma_parts) > 1 and all(
                _cue_type(part) is not None for part in comma_parts
            ):
                segments = comma_parts
            for part in segments:
                if benefit_section or is_benefit_text(part):
                    category = "mentioned"
                else:
                    category = _cue_type(part) or section
                skills = {
                    canonical for canonical, aliases in SKILL_ALIASES.items()
                    if _mentions(part, aliases)
                }
                # "Azure, AWS or GCP" is a choice, not three obligations.
                # Defer the group rather than inventing separate skill blockers.
                if len(skills) > 1 and re.search(r"\b(?:or|o|either)\b", part, re.I):
                    grouped["mentioned"].update(skills)
                    continue
                grouped[category].update(skills)

    grouped["preferred"] -= grouped["required"]
    grouped["mentioned"] -= grouped["required"] | grouped["preferred"]
    return grouped


def _explicit_negative(text: str, aliases: tuple[str, ...]) -> bool:
    """Conservative guard against common negative evidence assertions.

    This is not a general natural-language negation resolver. Ambiguous
    phrasing must be reviewed instead of counted as documented experience.
    """
    for alias in aliases:
        pattern = re.escape(alias.casefold())
        if re.search(
            r"\b(?:no|without|lack of|lacking|not experienced in|no experience with|"
            r"sin experiencia (?:en|con)|sin conocimientos (?:de|en))\s+"
            r"(?:practical\s+|professional\s+)?"
            + pattern + r"(?![a-z0-9])",
            text.casefold(),
        ):
            return True
    return False


REVIEW_REQUIREMENTS: tuple[tuple[str, str], ...] = (
    ("education", r"\b(?:bachelor'?s?|master'?s?|ph\.?d\.?|university degree|"
                  r"grado universitario|titulaci[oó]n universitaria)\b"),
    ("work_authorization", r"\b(?:right to work|work authorization|"
                           r"visa sponsorship|work permit|permiso de trabajo)\b"),
    ("production_experience", r"\b(?:production experience|"
                              r"deployed (?:models?|systems?) to production|"
                              r"experiencia en producci[oó]n)\b"),
    ("onsite_or_relocation", r"\b(?:on[ -]?site|in[ -]?office|presencial|"
                           r"relocat(?:ion|e)|reubicaci[oó]n)\b"),
)


def _review_requirements(description: str, location: str = "") -> list[dict[str, str]]:
    """Surface potentially decisive non-skill conditions without deciding eligibility."""
    items = []
    review_text = f"{description}\n{location}".strip()
    for line in re.split(r"[\n•]+", review_text):
        for part in re.split(r"(?<=[.!?])\s+|[;]", line):
            if not re.search(r"\b(?:or|o|either)\b", part, re.I):
                continue
            alternatives = sorted(
                skill for skill, aliases in SKILL_ALIASES.items()
                if _mentions(part, aliases)
            )
            if len(alternatives) > 1:
                items.append({
                    "category": "alternative_skill_choice",
                    "status": "manual_review",
                    "trigger": " / ".join(alternatives),
                    "reason": "Skills are presented as options, not all simultaneously mandatory.",
                })
    for kind, pattern in REVIEW_REQUIREMENTS:
        match = re.search(pattern, review_text, re.IGNORECASE)
        if match:
            items.append({
                "category": kind,
                "status": "manual_review",
                "trigger": match.group(0),
                "reason": "Requirement, strength and candidate evidence need human review.",
            })
    return items


def _bank_rows(bank: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(bank["facts"])
    for section, fixed in bank.get("fixed_sections", {}).items():
        for row in fixed:
            rows.append({**row, "kind": section})
    return rows


def _match_one(skill: str, facts: list[dict[str, Any]]) -> dict[str, Any]:
    aliases = SKILL_ALIASES[skill]
    explicit: list[dict[str, str]] = []
    indirect: list[dict[str, str]] = []
    for row in facts:
        if row.get("attested_by_user") is False:
            continue
        name = str(row.get("title", "") or row.get("id", ""))
        claim = str(row.get("text", "") or row.get("title", "")).strip() or name
        # A tag is an indexing hint; it is not proof that the skill was used.
        claim_text = " ".join(str(row.get(k, "")) for k in ("text", "title"))
        mentions_text = _mentions(claim_text, aliases) and not _explicit_negative(
            claim_text, aliases
        )
        mentions_tag = any(str(tag).casefold() == skill for tag in row.get("tags", []))
        if mentions_text:
            explicit.append({"id": str(row["id"]), "source": str(row["source"]),
                             "label": name, "claim": claim})
        elif mentions_tag and not _explicit_negative(claim_text, aliases):
            indirect.append({"id": str(row["id"]), "source": str(row["source"]),
                             "label": name, "claim": claim})
    if explicit:
        return {"requirement": skill, "status": "documented",
                "evidence": explicit[:5], "basis": "explicit claim"}
    if indirect:
        return {"requirement": skill, "status": "partial",
                "evidence": indirect[:5], "basis": "metadata tag only; verify claim"}
    return {"requirement": skill, "status": "not_documented", "evidence": [],
            "basis": "not found in attested bank; does not prove lack of ability"}


def evaluate_real_fit(
    bank: dict[str, Any], posting: dict[str, Any],
    selected_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Build an auditable diagnostic; never reinterpret CV selection as qualifications.

    The supported skill vocabulary is intentionally narrow. Items that cannot be
    extracted require manual review and must not be counted as covered.
    """
    description = str(posting.get("description", ""))
    if not description.strip():
        raise ValueError("Job posting needs a description")
    for row in _bank_rows(bank):
        if row.get("attested_by_user") is False:
            raise ValueError("Real-fit assessment requires an attested bank")
    job = extract_job_posting(
        title=str(posting.get("title", "")),
        company=str(posting.get("company", "")),
        location=str(posting.get("location", "")),
        description=description,
    )
    facts = _bank_rows(bank)
    categories = _triage_skills(description)
    required = [_match_one(s, facts) for s in sorted(categories["required"])]
    preferred = [_match_one(s, facts) for s in sorted(categories["preferred"])]
    mentioned = [_match_one(s, facts) for s in sorted(categories["mentioned"])]
    reviews = _review_requirements(description, str(posting.get("location", "")))
    if job.years_required is not None:
        reviews.append({
            "category": "experience_duration", "status": "manual_review",
            "trigger": str(job.years_required),
            "reason": "Check type, duration and eligibility; never infer years from tags.",
        })

    def coverage(items: list[dict[str, Any]]) -> dict[str, Any]:
        documented = sum(x["status"] == "documented" for x in items)
        return {"documented": documented, "total_extracted": len(items),
                "ratio": round(documented / len(items), 3) if items else None}

    visible: dict[str, Any] | None = None
    if selected_ids is not None:
        visible = {"required": [], "preferred": []}
        for key, items in (("required", required), ("preferred", preferred)):
            for item in items:
                chosen = [ref for ref in item["evidence"]
                          if ref["id"] in selected_ids]
                visible[key].append({
                    "requirement": item["requirement"],
                    "in_selected_cv": bool(chosen),
                    "evidence": chosen,
                })

    return {
        "schema_version": 1,
        "role": {"title": job.title, "company": job.company},
        "required": required,
        "preferred": preferred,
        "mentioned": mentioned,
        "required_coverage": coverage(required),
        "preferred_coverage": coverage(preferred),
        "experience": {
            "years_required": job.years_required,
            "status": "manual_review" if job.years_required is not None else "not_specified",
            "reason": "Duration and type of experience cannot be verified from skill tags.",
        },
        "seniority": job.seniority,
        "selected_cv_coverage": visible,
        "manual_review_requirements": reviews,
        "fit_assessment": {
            "status": (
                "EVIDENCE_GAPS" if any(row["status"] != "documented" for row in required)
                else "REVIEW_REQUIRED" if reviews or not required
                else "SKILL_COVERAGE_ONLY"
            ),
            "note": (
                "A documented skill is not proof of professional depth or overall "
                "eligibility. Review unextracted mandatory requirements manually."
            ),
        },
        "limitations": [
            "Only explicit/section-scoped requirements count toward required coverage.",
            "Unclassified technology mentions require review; they are not mandatory.",
            "Skills connected by 'or' are surfaced as alternatives for manual review.",
            "Coverage applies only to skills recognized by the current extractor.",
            "A missing bank claim is not proof of missing ability.",
            "Evidence is owner-attested, not independently verified.",
            "Tag-only matches are partial, not documented qualifications.",
            "No hiring probability or ATS score is inferred.",
            "Review degree requirements, exclusions and non-skill duties manually.",
        ],
    }


def report_markdown(report: dict[str, Any]) -> str:
    title = report["role"]["title"] or "Untitled role"
    company = report["role"]["company"] or "Unknown company"
    lines = [f"# Real fit · {title} @ {company}", "",
             "This report measures documented evidence, not hiring probability.", ""]
    for heading, key in (("Required skills", "required"), ("Preferred skills", "preferred"),
                         ("Mentioned without clear requirement", "mentioned")):
        tally = report.get(key + "_coverage")
        ratio = (f'{tally["documented"]}/{tally["total_extracted"]} explicitly documented'
                 if tally and tally["total_extracted"] else "No mandatory/optional tally for this group")
        lines.extend([f"## {heading}", ratio, ""])
        for item in report[key]:
            refs = "; ".join(
                f'{r["id"]} ({r["source"]}): {r.get("claim", "")}'
                for r in item["evidence"]
            )
            lines.append(f'- **{item["requirement"]}**: {item["status"]} — '
                         f'{refs or item["basis"]}')
        lines.append("")
    exp = report["experience"]
    lines += ["## Experience", f'Required years: {exp["years_required"]}',
              f'Status: {exp["status"]} — {exp["reason"]}', ""]
    lines += ["## Overall assessment",
              report["fit_assessment"]["status"],
              report["fit_assessment"]["note"], "",
              "## Other conditions needing review", ""]
    for item in report["manual_review_requirements"]:
        lines.append(f'- {item["category"]}: {item["trigger"]} — {item["reason"]}')
    lines.append("")
    if report["selected_cv_coverage"] is not None:
        lines += ["## Evidence appearing in selected CV", ""]
        for group in ("required", "preferred"):
            for item in report["selected_cv_coverage"][group]:
                lines.append(f'- {group}: {item["requirement"]}: '
                             f'{"yes" if item["in_selected_cv"] else "not selected"}')
        lines.append("")
    lines += ["## Limitations", ""]
    lines += ["- " + note for note in report["limitations"]]
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], destination: str | Path) -> None:
    folder = Path(destination)
    if folder.exists() and any(folder.iterdir()):
        raise ValueError("Report destination must be empty; do not overwrite")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "match_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (folder / "MATCH_REPORT.md").write_text(report_markdown(report), encoding="utf-8")
