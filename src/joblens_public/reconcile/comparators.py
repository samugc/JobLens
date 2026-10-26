"""The comparison framework used to relate two claims.

Comparisons are written as typed comparators registered for a pair of claim
categories. A comparator returns ``None`` when it has no opinion, and the
framework then falls back to the subject comparison. This keeps the reasoning
reusable: a new category adds a comparator, not another special case in a
growing conditional.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Sequence

from .models import Claim, ClaimCategory, Relation
from .text import normalise, role_titles

__all__ = [
    "Comparison",
    "Comparator",
    "compare_claims",
    "comparator_for",
    "register",
]


@dataclass(frozen=True)
class Comparison:
    """The result of comparing two claims."""

    relation: Relation
    attributes: tuple[str, ...] = ()
    reason: str = ""
    basis: str = "generic"

    def as_dict(self) -> dict[str, object]:
        return {
            "relation": self.relation.value,
            "attributes": list(self.attributes),
            "reason": self.reason,
            "basis": self.basis,
        }


Comparator = Callable[[Claim, Claim], Comparison | None]

_COMPARATORS: dict[tuple[ClaimCategory, ClaimCategory], Comparator] = {}


def register(
    left: ClaimCategory,
    right: ClaimCategory,
    comparator: Comparator,
) -> None:
    """Register a comparator for a pair of claim categories."""
    _COMPARATORS[(left, right)] = comparator


def comparator_for(
    left: ClaimCategory,
    right: ClaimCategory,
) -> Comparator | None:
    """Return the comparator for a pair of categories, if there is one."""
    comparator = _COMPARATORS.get((left, right))
    if comparator is not None:
        return comparator
    return _COMPARATORS.get((right, left))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(?:19|20)\d{2}", value)
    return int(match.group(0)) if match else None


def _period(claim: Claim) -> tuple[int | None, int | None]:
    return _year(claim.attribute("start")), _year(claim.attribute("end"))


def _overlaps(left: Claim, right: Claim) -> bool | None:
    """True when two periods overlap, ``None`` when a period is unknown.

    Two periods that only share a boundary year, such as 2018-2020 and
    2020-2022, do not overlap: that is a sequence, not a concurrency.
    """
    left_start, left_end = _period(left)
    right_start, right_end = _period(right)
    if left_start is None or right_start is None:
        return None
    left_end = left_end if left_end is not None else 9999
    right_end = right_end if right_end is not None else 9999
    return left_start < right_end and right_start < left_end


def _sequential(left: Claim, right: Claim) -> bool | None:
    """True when one period ends before or when the other starts.

    Two periods that share a boundary year, such as 2016-2019 and 2019-2022,
    are a sequence, not a concurrency.
    """
    left_start, left_end = _period(left)
    right_start, right_end = _period(right)
    if left_end is None or right_start is None:
        return None
    return left_end <= right_start


def _similar(left: str, right: str) -> bool:
    """True when two subjects look like the same entity but are not equal."""
    if left == right:
        return False
    shorter, longer = sorted((left, right), key=len)
    if not shorter:
        return False
    return longer.startswith(shorter) and len(longer) - len(shorter) <= 12


def _duration_months(claim: Claim) -> tuple[int | None, bool]:
    value = claim.attribute("duration_months")
    if value is None:
        return None, True
    try:
        months = int(float(value))
    except (TypeError, ValueError):
        return None, True
    exact = claim.attribute("duration_exact") != "at_least"
    return months, exact


def _span_months(claim: Claim) -> int | None:
    """The length of a stated period, in months, when the dates allow it."""
    start, end = _period(claim)
    if start is None or end is None:
        return None
    return max(0, (end - start) * 12)


def _same_values(left: Claim, right: Claim, names: Sequence[str]) -> bool:
    for name in names:
        if left.attribute(name) != right.attribute(name):
            return False
    return True


def _shared_identity(
    left: Claim,
    right: Claim,
    names: Sequence[str],
) -> list[str]:
    """The identity attributes both sources state, in the given order."""
    return [
        name
        for name in names
        if left.attribute(name) is not None and right.attribute(name) is not None
    ]


def _differing(
    left: Claim,
    right: Claim,
    names: Sequence[str],
) -> list[str]:
    """The attributes of ``names`` both state with different values."""
    return [name for name in names if left.attribute(name) != right.attribute(name)]


def _attribute_sets(left: Claim, right: Claim) -> tuple[set[str], set[str]]:
    return set(left.attribute_names()), set(right.attribute_names())


# ---------------------------------------------------------------------------
# Comparators
# ---------------------------------------------------------------------------


def _compare_skills(left: Claim, right: Claim) -> Comparison | None:
    if left.subject != right.subject:
        return None
    if left.qualifier != right.qualifier:
        # One source states the skill, the other only mentions it. They are
        # not the same claim, and a mention is never promoted to a claim.
        return Comparison(
            Relation.COMPLEMENTARY,
            ("name", "qualifier"),
            "one source states the skill explicitly and the other only mentions "
            "it, so the mention is not promoted to a claim",
            "skill",
        )
    left_level = left.attribute("proficiency")
    right_level = right.attribute("proficiency")
    if left_level == right_level:
        return Comparison(
            Relation.DUPLICATE,
            ("name",),
            "both sources state the same skill with the same stated proficiency",
            "skill",
        )
    if left_level and right_level:
        return Comparison(
            Relation.POTENTIALLY_CONFLICTING,
            ("proficiency",),
            "the sources state different proficiencies for the same skill",
            "skill",
        )
    return Comparison(
        Relation.MORE_SPECIFIC if left_level else Relation.LESS_SPECIFIC,
        ("proficiency",),
        "one source states a proficiency that the other does not",
        "skill",
    )


def _compare_languages(left: Claim, right: Claim) -> Comparison | None:
    if left.subject != right.subject:
        return None
    left_level = left.attribute("proficiency")
    right_level = right.attribute("proficiency")
    if left_level == right_level:
        return Comparison(
            Relation.DUPLICATE,
            ("name",),
            "both sources state the same language with the same stated level",
            "language",
        )
    if left_level and right_level:
        comparable = _is_cefr(left_level) and _is_cefr(right_level)
        return Comparison(
            Relation.POTENTIALLY_CONFLICTING,
            ("proficiency",),
            (
                "the sources state comparable CEFR levels for the same language"
                if comparable
                else "the sources state different, not comparable levels for the same language"
            ),
            "language",
        )
    return Comparison(
        Relation.MORE_SPECIFIC if left_level else Relation.LESS_SPECIFIC,
        ("proficiency",),
        "one source states a level that the other does not",
        "language",
    )


def _is_cefr(level: str) -> bool:
    return level.casefold() in {"a1", "a2", "b1", "b2", "c1", "c2"}


def _compare_employment(left: Claim, right: Claim) -> Comparison | None:
    if left.subject != right.subject:
        return None
    left_org = left.attribute("organization")
    right_org = right.attribute("organization")
    if not left_org or not right_org:
        # A position without an employer cannot be identified. The absence of
        # an employer is not evidence of a different employer, and the same
        # job title is not enough to merge two positions.
        return Comparison(
            Relation.UNCERTAIN,
            ("organization",),
            "at least one source does not state an employer, so the identity of "
            "the position cannot be established",
            "employment",
        )
    if left_org != right_org:
        if left_org and right_org and _similar(left_org, right_org):
            return Comparison(
                Relation.UNCERTAIN,
                ("organization",),
                "the organisation names are similar but not identical",
                "employment",
            )
        return Comparison(
            Relation.UNRELATED,
            ("organization",),
            "the same role is stated at different organisations",
            "employment",
        )

    duration_conflict = _duration_conflict(left, right)
    if duration_conflict is not None:
        return duration_conflict

    left_role = left.attribute("role")
    right_role = right.attribute("role")
    differing: list[str] = []
    for name in ("start", "end"):
        left_value = left.attribute(name)
        right_value = right.attribute(name)
        if left_value is not None and right_value is not None and left_value != right_value:
            differing.append(name)

    if differing:
        if _overlaps(left, right) is True:
            return Comparison(
                Relation.POTENTIALLY_CONFLICTING,
                tuple(differing),
                "the periods of the same position overlap",
                "employment",
            )
        if _sequential(left, right) is True or _sequential(right, left) is True:
            return Comparison(
                Relation.TEMPORAL_UPDATE,
                tuple(differing),
                "the periods do not overlap, so these are two stints of the same position",
                "employment",
            )
        return Comparison(
            Relation.POTENTIALLY_CONFLICTING,
            tuple(differing),
            "the sources state different dates for the same position",
            "employment",
        )

    if left_role != right_role:
        sequential = _sequential(left, right)
        if sequential is True:
            return Comparison(
                Relation.TEMPORAL_UPDATE,
                ("role", "start", "end"),
                "the roles differ and the periods do not overlap, so this is a progression",
                "employment",
            )
        return Comparison(
            Relation.COMPLEMENTARY,
            ("role",),
            "the sources state different roles without conflicting dates",
            "employment",
        )

    if _same_values(left, right, ("start", "end", "organization", "role")):
        left_attributes, right_attributes = _attribute_sets(left, right)
        if left_attributes == right_attributes:
            return Comparison(
                Relation.DUPLICATE,
                ("role", "organization", "start", "end"),
                "both sources state the same position with the same period",
                "employment",
            )
        if left_attributes < right_attributes:
            return Comparison(
                Relation.MORE_SPECIFIC,
                tuple(sorted(right_attributes - left_attributes)),
                "one source states more about the same position than the other",
                "employment",
            )
        if right_attributes < left_attributes:
            return Comparison(
                Relation.LESS_SPECIFIC,
                tuple(sorted(left_attributes - right_attributes)),
                "one source states more about the same position than the other",
                "employment",
            )
    return Comparison(
        Relation.COMPLEMENTARY,
        ("role", "organization"),
        "the sources state the same position with different supporting details",
        "employment",
    )


def _duration_conflict(left: Claim, right: Claim) -> Comparison | None:
    """Compare a stated duration with the period stated by the other source.

    Two sources that state the same duration agree with each other, even when
    that duration does not match their own dates. The internal
    inconsistency is reported separately, as a warning.
    """
    left_months, left_exact = _duration_months(left)
    right_months, right_exact = _duration_months(right)
    if left_months is not None and right_months is not None:
        if abs(left_months - right_months) >= 12:
            return Comparison(
                Relation.CONTRADICTORY,
                ("duration_months",),
                "the sources state different durations for the same position",
                "employment",
            )
        return None
    stated, exact, other_span = (
        (left_months, left_exact, _span_months(right))
        if left_months is not None
        else (right_months, right_exact, _span_months(left))
    )
    if stated is None or other_span is None:
        return None
    if abs(stated - other_span) >= 12:
        if exact:
            return Comparison(
                Relation.CONTRADICTORY,
                ("duration_months", "start", "end"),
                "the stated duration contradicts the stated period",
                "employment",
            )
        return Comparison(
            Relation.POTENTIALLY_CONFLICTING,
            ("duration_months", "start", "end"),
            "the stated duration does not match the stated period",
            "employment",
        )
    return None


def _compare_education(left: Claim, right: Claim) -> Comparison | None:
    if left.subject == "graduation" or right.subject == "graduation":
        return _compare_graduation(left, right)
    if left.subject != right.subject:
        return None
    left_level = left.attribute("level")
    right_level = right.attribute("level")
    identity = _shared_identity(left, right, ("institution", "start", "end"))
    differing = _differing(left, right, identity)
    if left_level == right_level:
        if not identity:
            # The same degree name without an institution or dates is not
            # enough to establish that the two statements are about the same
            # degree.
            return Comparison(
                Relation.UNCERTAIN,
                ("level", "field"),
                "the sources state the same degree name without an institution "
                "or dates, so the identity of the degree cannot be established",
                "education",
            )
        if differing:
            return Comparison(
                Relation.POTENTIALLY_CONFLICTING,
                tuple(differing),
                "the sources state the same degree with different dates or "
                "institutions",
                "education",
            )
        return Comparison(
            Relation.DUPLICATE,
            ("level", "field", *identity),
            "both sources state the same degree for the same subject with the "
            "same identity",
            "education",
        )
    sequential = _sequential(left, right)
    if sequential is True:
        return Comparison(
            Relation.TEMPORAL_UPDATE,
            ("level", "start", "end"),
            "the degrees differ and the periods do not overlap",
            "education",
        )
    if identity and not differing:
        return Comparison(
            Relation.CONTRADICTORY,
            ("level", "start", "end"),
            "the sources state two different degrees for the same subject in the "
            "same period",
            "education",
        )
    return Comparison(
        Relation.POTENTIALLY_CONFLICTING,
        ("level", "start", "end"),
        "the sources state different degrees for the same subject",
        "education",
    )


def _compare_degrees(left: Claim, right: Claim) -> Comparison | None:
    """A degree claim is only merged with the identity evidence it carries."""
    if left.subject != right.subject:
        return None
    identity = _shared_identity(left, right, ("institution", "start", "end"))
    if not identity:
        return Comparison(
            Relation.UNCERTAIN,
            ("level", "field"),
            "the sources state the same degree name without an institution or "
            "dates, so the identity of the degree cannot be established",
            "degree",
        )
    differing = _differing(left, right, identity)
    if differing:
        return Comparison(
            Relation.POTENTIALLY_CONFLICTING,
            tuple(differing),
            "the sources state the same degree with different identity evidence",
            "degree",
        )
    return Comparison(
        Relation.DUPLICATE,
        ("level", "field", *identity),
        "both sources state the same degree with the same identity",
        "degree",
    )


def _compare_graduation(left: Claim, right: Claim) -> Comparison | None:
    graduation, education = (left, right) if left.subject == "graduation" else (right, left)
    if education.subject == "graduation":
        return None
    year = _year(graduation.attribute("graduation_year"))
    if year is None:
        return None
    start, end = _period(education)
    if start is None and end is None:
        return None
    low = start if start is not None else end
    high = end if end is not None else start
    if low is None or high is None:
        return None
    if low <= year <= high:
        return Comparison(
            Relation.DUPLICATE,
            ("graduation_year", "start", "end"),
            "the stated graduation year falls inside the stated period",
            "education",
        )
    return Comparison(
        Relation.CONTRADICTORY,
        ("graduation_year", "start", "end"),
        "the stated graduation year falls outside the stated period",
        "education",
    )


def _compare_organizations(left: Claim, right: Claim) -> Comparison | None:
    if left.subject == right.subject:
        if _same_values(left, right, ("role", "start", "end")):
            return Comparison(
                Relation.DUPLICATE,
                ("name", "role"),
                "both sources state the same organisation with the same role",
                "organization",
            )
        sequential = _sequential(left, right)
        if sequential is True:
            return Comparison(
                Relation.TEMPORAL_UPDATE,
                ("role", "start", "end"),
                "the roles differ and the periods do not overlap",
                "organization",
            )
        return Comparison(
            Relation.COMPLEMENTARY,
            ("role",),
            "the sources state the same organisation with different roles or dates",
            "organization",
        )
    if _similar(left.subject, right.subject):
        return Comparison(
            Relation.UNCERTAIN,
            ("name",),
            "the organisation names are similar but not identical",
            "organization",
        )
    return None


def _compare_projects(left: Claim, right: Claim) -> Comparison | None:
    if left.subject != right.subject:
        return None
    left_description = left.attribute("description")
    right_description = right.attribute("description")
    if left_description and right_description and left_description != right_description:
        # The same name can be two different projects. Only an identical
        # description makes the two statements the same project.
        return Comparison(
            Relation.COMPLEMENTARY,
            ("description",),
            "the sources name the same project with different descriptions, so "
            "both descriptions are kept apart",
            "project",
        )
    if left_description != right_description:
        return Comparison(
            Relation.MORE_SPECIFIC if left_description else Relation.LESS_SPECIFIC,
            ("description",),
            "one source describes the project and the other only names it",
            "project",
        )
    if left.attribute("technologies") == right.attribute("technologies"):
        return Comparison(
            Relation.DUPLICATE,
            ("name", "technologies"),
            "both sources state the same project with the same description",
            "project",
        )
    return Comparison(
        Relation.COMPLEMENTARY,
        ("technologies",),
        "the sources name the same project with different technology lists",
        "project",
    )


def _compare_contributions(left: Claim, right: Claim) -> Comparison | None:
    if left.subject != right.subject:
        return None
    left_template = left.attribute("template")
    right_template = right.attribute("template")
    if left_template and left_template == right_template:
        differing: list[str] = []
        if left.attribute("quantities") != right.attribute("quantities"):
            differing.append("quantities")
        if left.attribute("technologies") != right.attribute("technologies"):
            differing.append("technologies")
        if not differing:
            return Comparison(
                Relation.DUPLICATE,
                ("text",),
                "both sources state the same responsibility",
                "contribution",
            )
        return Comparison(
            Relation.CONTRADICTORY,
            tuple(differing),
            "the sources state the same responsibility with different figures or "
            "technologies",
            "contribution",
        )
    return Comparison(
        Relation.COMPLEMENTARY,
        ("text",),
        "the sources state different responsibilities of the same project",
        "contribution",
    )


def _compare_achievements(left: Claim, right: Claim) -> Comparison | None:
    return _compare_contributions(left, right)


def _compare_certifications(left: Claim, right: Claim) -> Comparison | None:
    if left.subject != right.subject:
        if _similar(left.subject, right.subject):
            return Comparison(
                Relation.UNCERTAIN,
                ("name",),
                "the certification names are similar but not identical",
                "certification",
            )
        return None
    if left.attribute("issuer") != right.attribute("issuer"):
        return Comparison(
            Relation.COMPLEMENTARY,
            ("issuer",),
            "the sources state the same certification with a different issuer",
            "certification",
        )
    return Comparison(
        Relation.DUPLICATE,
        ("name", "issuer"),
        "both sources state the same certification",
        "certification",
    )


def _compare_technologies(left: Claim, right: Claim) -> Comparison | None:
    if left.subject != right.subject:
        return None
    if left.attribute("project") != right.attribute("project"):
        return Comparison(
            Relation.COMPLEMENTARY,
            ("project",),
            "the sources name the same technology in different projects",
            "technology",
        )
    return Comparison(
        Relation.DUPLICATE,
        ("name", "project"),
        "both sources name the same technology in the same project",
        "technology",
    )


def _compare_simple(left: Claim, right: Claim) -> Comparison | None:
    """Comparator for categories that only carry a name."""
    if left.subject != right.subject:
        return None
    return Comparison(
        Relation.DUPLICATE,
        ("name",),
        "both sources state the same entity",
        "generic",
    )


def _compare_skill_technology(left: Claim, right: Claim) -> Comparison | None:
    """A technology a project names also supports the matching skill claim."""
    skill, technology = (left, right) if left.category is ClaimCategory.SKILL else (right, left)
    if skill.subject != technology.subject:
        return None
    return Comparison(
        Relation.COMPLEMENTARY,
        ("name",),
        "a project names a technology that is also stated as a skill",
        "cross_category",
    )


def _compare_certification_skill(left: Claim, right: Claim) -> Comparison | None:
    """A certification title supports the skill it names."""
    certification, skill = (
        (left, right) if left.category is ClaimCategory.CERTIFICATION else (right, left)
    )
    if skill.subject not in certification.subject:
        return None
    return Comparison(
        Relation.COMPLEMENTARY,
        ("name",),
        "a certification title names the same technology as a stated skill",
        "cross_category",
    )


def _compare_employment_organization(left: Claim, right: Claim) -> Comparison | None:
    """The employment claim names the organisation the other claim is about."""
    employment, organization = (
        (left, right) if left.category is ClaimCategory.EMPLOYMENT else (right, left)
    )
    named = employment.attribute("organization")
    if not named or normalise(named) != organization.subject:
        return None
    return Comparison(
        Relation.COMPLEMENTARY,
        ("organization",),
        "the position names the organisation the other claim is about",
        "cross_category",
    )


def _compare_education_institution(left: Claim, right: Claim) -> Comparison | None:
    education, institution = (
        (left, right) if left.category is ClaimCategory.EDUCATION else (right, left)
    )
    named = education.attribute("institution")
    if not named or normalise(named) != institution.subject:
        return None
    return Comparison(
        Relation.COMPLEMENTARY,
        ("institution",),
        "the degree names the institution the other claim is about",
        "cross_category",
    )


def _compare_project_technology(left: Claim, right: Claim) -> Comparison | None:
    project, technology = (
        (left, right) if left.category is ClaimCategory.PROJECT else (right, left)
    )
    named = technology.attribute("project")
    if not named or normalise(named) != project.subject:
        return None
    return Comparison(
        Relation.COMPLEMENTARY,
        ("technologies", "project"),
        "the project names the technology the other claim is about",
        "cross_category",
    )


def _compare_project_contribution(left: Claim, right: Claim) -> Comparison | None:
    project, contribution = (
        (left, right)
        if left.category in {ClaimCategory.PROJECT, ClaimCategory.CONTRIBUTION}
        else (right, left)
    )
    named = contribution.attribute("project")
    if not named or normalise(named) != project.subject:
        return None
    return Comparison(
        Relation.COMPLEMENTARY,
        ("project",),
        "the responsibility belongs to the project the other claim is about",
        "cross_category",
    )


def _compare_employment_contribution(left: Claim, right: Claim) -> Comparison | None:
    """A responsibility that names the role supports the position."""
    employment, contribution = (
        (left, right)
        if left.category is ClaimCategory.EMPLOYMENT
        else (right, left)
    )
    role = employment.attribute("role")
    if not role:
        return None
    text = contribution.attribute_value("text") or ""
    titles = role_titles(text)
    if not titles:
        return None
    normalized_role = normalise(role)
    if normalized_role in titles or any(
        title in normalized_role for title in titles
    ):
        return Comparison(
            Relation.COMPLEMENTARY,
            ("role", "text"),
            "the responsibility names the role the position states",
            "cross_category",
        )
    return None


def _register_all() -> None:
    register(ClaimCategory.SKILL, ClaimCategory.SKILL, _compare_skills)
    register(ClaimCategory.LANGUAGE, ClaimCategory.LANGUAGE, _compare_languages)
    register(ClaimCategory.EMPLOYMENT, ClaimCategory.EMPLOYMENT, _compare_employment)
    register(ClaimCategory.EDUCATION, ClaimCategory.EDUCATION, _compare_education)
    register(ClaimCategory.ORGANIZATION, ClaimCategory.ORGANIZATION, _compare_organizations)
    register(ClaimCategory.PROJECT, ClaimCategory.PROJECT, _compare_projects)
    register(ClaimCategory.CONTRIBUTION, ClaimCategory.CONTRIBUTION, _compare_contributions)
    register(ClaimCategory.ACHIEVEMENT, ClaimCategory.ACHIEVEMENT, _compare_achievements)
    register(ClaimCategory.CONTRIBUTION, ClaimCategory.ACHIEVEMENT, _compare_contributions)
    register(
        ClaimCategory.CERTIFICATION,
        ClaimCategory.CERTIFICATION,
        _compare_certifications,
    )
    register(ClaimCategory.TECHNOLOGY, ClaimCategory.TECHNOLOGY, _compare_technologies)
    register(ClaimCategory.INSTITUTION, ClaimCategory.INSTITUTION, _compare_simple)
    register(ClaimCategory.DEGREE, ClaimCategory.DEGREE, _compare_degrees)
    register(ClaimCategory.SKILL, ClaimCategory.TECHNOLOGY, _compare_skill_technology)
    register(
        ClaimCategory.CERTIFICATION,
        ClaimCategory.SKILL,
        _compare_certification_skill,
    )
    register(
        ClaimCategory.EMPLOYMENT,
        ClaimCategory.ORGANIZATION,
        _compare_employment_organization,
    )
    register(
        ClaimCategory.EDUCATION,
        ClaimCategory.INSTITUTION,
        _compare_education_institution,
    )
    register(ClaimCategory.PROJECT, ClaimCategory.TECHNOLOGY, _compare_project_technology)
    register(
        ClaimCategory.PROJECT,
        ClaimCategory.CONTRIBUTION,
        _compare_project_contribution,
    )
    register(
        ClaimCategory.PROJECT,
        ClaimCategory.ACHIEVEMENT,
        _compare_project_contribution,
    )
    register(
        ClaimCategory.EMPLOYMENT,
        ClaimCategory.CONTRIBUTION,
        _compare_employment_contribution,
    )
    register(
        ClaimCategory.EMPLOYMENT,
        ClaimCategory.ACHIEVEMENT,
        _compare_employment_contribution,
    )


_register_all()


def compare_claims(left: Claim, right: Claim) -> Comparison:
    """Compare two claims and return the relationship between them."""
    if left.claim_id == right.claim_id:
        return Comparison(Relation.UNRELATED, reason="the same claim")
    comparator = comparator_for(left.category, right.category)
    if comparator is not None:
        result = comparator(left, right)
        if result is not None:
            return result
    if left.subject != right.subject:
        return Comparison(
            Relation.UNRELATED,
            reason="the claims are about different entities",
        )
    return Comparison(
        Relation.UNCERTAIN,
        reason="the claims share a subject but no typed comparator could relate them",
    )
