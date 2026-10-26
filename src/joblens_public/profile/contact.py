"""Evidence-grounded candidate contact suggestions.

Contact details are not candidate *facts*: they identify the person rather
than describe their professional history. They therefore never become profile
proposals, and they are never filled into a CV automatically. This module only
extracts the best supported *suggestions* from the retained source documents,
with the exact quotation and offsets of every value, so that an editor can ask
the candidate to confirm or correct them.

Rules enforced here:

* Every suggestion points at exact source text; the offsets always satisfy
  ``segment_text[start:end] == quote``.
* Consistent values across documents are deduplicated, keeping every source
  reference.
* A scalar field with conflicting values is reported as ``conflict`` with no
  selected value. One value is never picked arbitrarily.
* Missing values stay ``missing``. Nothing is invented.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .engine import USABLE_DOCUMENT_STATUSES
from .models import EvidenceReference, Support

#: Version of the contact-suggestion envelope.
CONTACT_SUGGESTIONS_VERSION = "0.1"

#: Contact fields, in display order.
CONTACT_FIELDS = (
    "full_name",
    "email",
    "phone",
    "location",
    "github",
    "linkedin",
    "website",
)

#: Fields that describe one value; more than one distinct value is a conflict.
SCALAR_FIELDS = frozenset({"full_name", "email", "phone", "location"})

#: Fields that may legitimately hold several values.
LINK_FIELDS = frozenset({"github", "linkedin", "website"})

SUPPORTED = "supported"
CONFLICT = "conflict"
MISSING = "missing"
_STATUSES = frozenset({SUPPORTED, CONFLICT, MISSING})

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<![\w/.\-])(?:\+?\(?\d[\d\s().\-]{4,}\d)(?![\w/.\-])")
_GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w.\-]+", re.IGNORECASE)
_LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/(?:in|pub)/[\w.\-%]+", re.IGNORECASE
)
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>()\"']+", re.IGNORECASE)
_LABEL_RE = re.compile(
    r"^\s*(?P<label>full\s+name|name|e-?mail|phone|mobile|telephone|tel|"
    r"location|address|based\s+in|github|linkedin|website|portfolio|web)\s*[:\-]\s*"
    r"(?P<value>\S.*?)\s*$",
    re.IGNORECASE,
)

#: Headings and role words that must never be mistaken for a person's name.
_NON_NAME_WORDS = frozenset(
    {
        "about",
        "academy",
        "analyst",
        "architect",
        "certifications",
        "contact",
        "consultant",
        "curriculum",
        "cv",
        "data",
        "degree",
        "developer",
        "director",
        "education",
        "engineer",
        "engineering",
        "experience",
        "full",
        "languages",
        "lead",
        "manager",
        "profile",
        "projects",
        "resume",
        "scientist",
        "senior",
        "skills",
        "software",
        "specialist",
        "summary",
        "vitae",
    }
)

#: Countries and regions accepted as the last part of a ``City, Country`` line.
_COUNTRY_NAMES = frozenset(
    {
        "argentina",
        "australia",
        "austria",
        "belgium",
        "brazil",
        "bulgaria",
        "canada",
        "chile",
        "china",
        "colombia",
        "croatia",
        "cyprus",
        "czech republic",
        "czechia",
        "denmark",
        "ecuador",
        "estonia",
        "finland",
        "france",
        "germany",
        "greece",
        "hungary",
        "iceland",
        "india",
        "indonesia",
        "ireland",
        "israel",
        "italy",
        "japan",
        "latvia",
        "lithuania",
        "luxembourg",
        "malaysia",
        "mexico",
        "netherlands",
        "new zealand",
        "norway",
        "peru",
        "philippines",
        "poland",
        "portugal",
        "romania",
        "singapore",
        "slovakia",
        "slovenia",
        "south africa",
        "south korea",
        "spain",
        "sweden",
        "switzerland",
        "taiwan",
        "turkey",
        "ukraine",
        "united arab emirates",
        "united kingdom",
        "united states",
        "uruguay",
        "vietnam",
    }
)

#: Two-letter country and state/region codes accepted after a comma.
_REGION_CODES = frozenset(
    {
        "ar",
        "at",
        "au",
        "be",
        "br",
        "ca",
        "ch",
        "cl",
        "cn",
        "co",
        "cz",
        "de",
        "dk",
        "es",
        "fi",
        "fr",
        "gr",
        "ie",
        "il",
        "in",
        "it",
        "jp",
        "kr",
        "mx",
        "nl",
        "no",
        "nz",
        "pe",
        "pl",
        "pt",
        "ro",
        "se",
        "sg",
        "tr",
        "uk",
        "us",
        "za",
        # US/Canadian state and province codes that commonly follow a city.
        "ab",
        "ak",
        "al",
        "az",
        "bc",
        "ct",
        "dc",
        "fl",
        "ga",
        "hi",
        "ia",
        "id",
        "ks",
        "ky",
        "la",
        "ma",
        "mb",
        "md",
        "me",
        "mi",
        "mn",
        "mo",
        "ms",
        "mt",
        "nb",
        "nc",
        "nd",
        "ne",
        "nh",
        "nj",
        "nl",
        "ns",
        "nt",
        "nv",
        "ny",
        "oh",
        "ok",
        "on",
        "or",
        "pa",
        "pe",
        "qc",
        "ri",
        "sc",
        "sd",
        "sk",
        "tn",
        "tx",
        "ut",
        "va",
        "vt",
        "wa",
        "wi",
        "wv",
        "wy",
        "yt",
    }
)


class ContactSuggestionError(ValueError):
    """Raised when a serialized contact-suggestion envelope is invalid."""


@dataclass(frozen=True)
class ContactValue:
    """One distinct value with every quotation that supports it."""

    value: str
    normalized: str
    evidence: tuple[EvidenceReference, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "normalized": self.normalized,
            "evidence": [item.as_dict() for item in self.evidence],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ContactValue":
        if not isinstance(payload, Mapping):
            raise ContactSuggestionError("a contact value must be an object")
        value = payload.get("value")
        normalized = payload.get("normalized")
        if not isinstance(value, str) or not value.strip():
            raise ContactSuggestionError("a contact value must be a non-empty string")
        if not isinstance(normalized, str):
            raise ContactSuggestionError("a contact normalized value must be a string")
        evidence_payload = payload.get("evidence")
        if not isinstance(evidence_payload, Sequence) or isinstance(
            evidence_payload, (str, bytes)
        ):
            raise ContactSuggestionError("a contact value needs an evidence array")
        evidence = tuple(_parse_evidence(item) for item in evidence_payload)
        if not evidence:
            raise ContactSuggestionError("a contact value needs at least one source reference")
        return cls(value=value, normalized=normalized, evidence=evidence)


@dataclass(frozen=True)
class ContactSuggestion:
    """The best supported values of one contact field.

    ``selected`` is set only when there is exactly one supported value (or one
    value for a link field). A conflict leaves it empty and lists every value
    that the sources state, so the editor can ask the candidate to choose.
    """

    field: str
    status: str
    selected: str | None = None
    values: tuple[ContactValue, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "status": self.status,
            "selected": self.selected,
            "values": [value.as_dict() for value in self.values],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ContactSuggestion":
        if not isinstance(payload, Mapping):
            raise ContactSuggestionError("a contact suggestion must be an object")
        field = payload.get("field")
        if field not in CONTACT_FIELDS:
            raise ContactSuggestionError(f"unknown contact field {field!r}")
        status = payload.get("status")
        if status not in _STATUSES:
            raise ContactSuggestionError(f"unknown contact status {status!r}")
        selected = payload.get("selected")
        if selected is not None and not isinstance(selected, str):
            raise ContactSuggestionError("selected must be a string or null")
        values_payload = payload.get("values", [])
        if not isinstance(values_payload, Sequence) or isinstance(
            values_payload, (str, bytes)
        ):
            raise ContactSuggestionError("contact values must be an array")
        values = tuple(ContactValue.from_dict(item) for item in values_payload)
        if status == MISSING and values:
            raise ContactSuggestionError("a missing contact field cannot carry values")
        if status != MISSING and not values:
            raise ContactSuggestionError("a present contact field needs a value")
        if selected is not None and selected not in {value.value for value in values}:
            raise ContactSuggestionError("selected must be one of the suggested values")
        if status == CONFLICT and selected is not None:
            raise ContactSuggestionError("a conflicting contact field cannot select a value")
        if status == SUPPORTED and field in SCALAR_FIELDS and len(values) != 1:
            raise ContactSuggestionError("a supported scalar contact field needs one value")
        return cls(field=field, status=status, selected=selected, values=values)


@dataclass(frozen=True)
class ContactSuggestions:
    """The contact suggestions of one extraction batch."""

    contact_suggestions_version: str = CONTACT_SUGGESTIONS_VERSION
    suggestions: tuple[ContactSuggestion, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "contact_suggestions_version": self.contact_suggestions_version,
            "suggestions": [item.as_dict() for item in self.suggestions],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ContactSuggestions":
        if not isinstance(payload, Mapping):
            raise ContactSuggestionError("contact suggestions must be an object")
        version = payload.get("contact_suggestions_version", CONTACT_SUGGESTIONS_VERSION)
        if version != CONTACT_SUGGESTIONS_VERSION:
            raise ContactSuggestionError(
                f"unsupported contact suggestions version {version!r}"
            )
        suggestions_payload = payload.get("suggestions", [])
        if not isinstance(suggestions_payload, Sequence) or isinstance(
            suggestions_payload, (str, bytes)
        ):
            raise ContactSuggestionError("suggestions must be an array")
        suggestions = tuple(
            ContactSuggestion.from_dict(item) for item in suggestions_payload
        )
        fields = [item.field for item in suggestions]
        if len(fields) != len(set(fields)):
            raise ContactSuggestionError("duplicate contact field")
        return cls(contact_suggestions_version=version, suggestions=suggestions)

    def by_field(self, field: str) -> ContactSuggestion | None:
        for item in self.suggestions:
            if item.field == field:
                return item
        return None

    def best(self) -> dict[str, str]:
        """Return only the unambiguous, user-confirmable values."""
        return {
            item.field: item.selected
            for item in self.suggestions
            if item.selected is not None
        }


def _parse_evidence(payload: Any) -> EvidenceReference:
    if not isinstance(payload, Mapping):
        raise ContactSuggestionError("evidence must be an object")
    try:
        support = Support(payload.get("support", Support.EXPLICIT_CLAIM.value))
    except ValueError as exc:
        raise ContactSuggestionError("unknown evidence support") from exc
    locator = payload.get("locator", {})
    if not isinstance(locator, Mapping):
        raise ContactSuggestionError("evidence locator must be an object")
    try:
        return EvidenceReference(
            document_id=str(payload["document_id"]),
            segment_index=int(payload["segment_index"]),
            locator=dict(locator),
            quote=str(payload["quote"]),
            start=int(payload["start"]),
            end=int(payload["end"]),
            support=support,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContactSuggestionError("malformed evidence reference") from exc


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    text: str


def _iter_lines(text: str) -> list[_Line]:
    lines: list[_Line] = []
    offset = 0
    for raw in text.splitlines(keepends=True):
        stripped = raw.rstrip("\r\n")
        leading = len(stripped) - len(stripped.lstrip())
        start = offset + leading
        end = offset + len(stripped.rstrip())
        if end > start:
            lines.append(_Line(start=start, end=end, text=text[start:end]))
        offset += len(raw)
    return lines


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t,;:-")


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalize_email(value: str) -> str:
    return value.strip().casefold()


def _normalize_phone(value: str) -> str:
    return re.sub(r"\D", "", value)


def _normalize_location(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _normalize_link(value: str) -> str:
    lowered = value.strip().casefold()
    lowered = re.sub(r"^https?://", "", lowered)
    lowered = re.sub(r"^www\.", "", lowered)
    return lowered.rstrip("/.,;:)]}")


def _looks_like_date_range(text: str) -> bool:
    """Reject year ranges and month/year ranges before treating text as a phone."""
    if len(re.findall(r"(?:19|20)\d{2}", text)) >= 2:
        return True
    return bool(
        re.fullmatch(
            r"\s*\d{1,2}\s*[/.-]\s*\d{4}\s*[-–—]\s*\d{1,2}\s*[/.-]\s*\d{4}\s*",
            text,
        )
    )


def _looks_like_name(text: str) -> bool:
    text = _clean(text)
    if not text or len(text) > 60:
        return False
    if any(character in text for character in ("@", "|", "·", "/", "\\", ":")):
        return False
    if any(character.isdigit() for character in text):
        return False
    words = text.split()
    if not 2 <= len(words) <= 5:
        return False
    if any(word.casefold() in _NON_NAME_WORDS for word in words):
        return False
    for word in words:
        if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ'’.\-]+", word):
            return False
        if not word[0].isupper():
            return False
    return True


def _looks_like_location(text: str) -> bool:
    text = _clean(text)
    if not text or len(text) > 80 or any(character.isdigit() for character in text):
        return False
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 2 or not all(parts):
        return False
    if not all(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ .'\-]+", part) for part in parts):
        return False
    region = parts[1].casefold()
    return region in _COUNTRY_NAMES or region in _REGION_CODES


def _extract_from_line(
    line: _Line,
) -> dict[str, list[tuple[str, str, int, int]]]:
    """Return ``field -> [(display, normalized, start, end)]`` for one line."""
    found: dict[str, list[tuple[str, str, int, int]]] = {}

    def add(field: str, display: str, normalized: str, start: int, end: int) -> None:
        if not display or not normalized:
            return
        found.setdefault(field, []).append((display, normalized, start, end))

    occupied: list[tuple[int, int]] = []

    for match in _EMAIL_RE.finditer(line.text):
        occupied.append((match.start(), match.end()))
        add(
            "email",
            _clean(match.group()),
            _normalize_email(match.group()),
            line.start + match.start(),
            line.start + match.end(),
        )

    for match in _PHONE_RE.finditer(line.text):
        if any(match.start() < end and start < match.end() for start, end in occupied):
            continue
        raw = match.group()
        if _looks_like_date_range(raw):
            continue
        digits = _normalize_phone(raw)
        has_separator = bool(re.search(r"[\s().\-]", raw)) or raw.strip().startswith("+")
        if not (7 <= len(digits) <= 15 and (has_separator or len(digits) >= 10)):
            continue
        occupied.append((match.start(), match.end()))
        add(
            "phone",
            _clean(raw),
            digits,
            line.start + match.start(),
            line.start + match.end(),
        )

    for match in _GITHUB_RE.finditer(line.text):
        if any(match.start() < end and start < match.end() for start, end in occupied):
            continue
        display = match.group().rstrip(".,;:)]}")
        occupied.append((match.start(), match.end()))
        add(
            "github",
            display,
            _normalize_link(display),
            line.start + match.start(),
            line.start + match.start() + len(display),
        )

    for match in _LINKEDIN_RE.finditer(line.text):
        if any(match.start() < end and start < match.end() for start, end in occupied):
            continue
        display = match.group().rstrip(".,;:)]}")
        occupied.append((match.start(), match.end()))
        add(
            "linkedin",
            display,
            _normalize_link(display),
            line.start + match.start(),
            line.start + match.start() + len(display),
        )

    for match in _URL_RE.finditer(line.text):
        if any(match.start() < end and start < match.end() for start, end in occupied):
            continue
        display = match.group().rstrip(".,;:)]}")
        normalized = _normalize_link(display)
        if normalized.startswith("github.com/") or normalized.startswith(
            "linkedin.com/"
        ):
            continue
        occupied.append((match.start(), match.end()))
        add(
            "website",
            display,
            normalized,
            line.start + match.start(),
            line.start + match.start() + len(display),
        )

    label_match = _LABEL_RE.match(line.text)
    if label_match:
        label = re.sub(r"\s+", " ", label_match.group("label").casefold())
        value = _clean(label_match.group("value"))
        value_start = line.start + label_match.start("value")
        if label in {"full name", "name"} and value and "@" not in value:
            add("full_name", value, _normalize_name(value), value_start, value_start + len(value))
        elif label in {"e-mail", "email"} and "@" in value:
            pass  # The address regex already captured it with exact offsets.
        elif label in {"location", "address", "based in"} and value:
            add(
                "location",
                value,
                _normalize_location(value),
                value_start,
                value_start + len(value),
            )
        elif label in {"github", "linkedin", "website", "portfolio", "web"} and value:
            normalized = _normalize_link(value)
            if normalized.startswith("github.com/"):
                field = "github"
            elif normalized.startswith("linkedin.com/"):
                field = "linkedin"
            else:
                field = "website"
            if not found.get(field):
                add(field, value, normalized, value_start, value_start + len(value))

    return found


def _evidence(
    document_id: str,
    segment_index: int,
    locator: Mapping[str, Any],
    quote: str,
    start: int,
    end: int,
) -> EvidenceReference:
    return EvidenceReference(
        document_id=document_id,
        segment_index=segment_index,
        locator=dict(locator),
        quote=quote,
        start=start,
        end=end,
        support=Support.EXPLICIT_CLAIM,
    )


def extract_contact_suggestions(
    response: Mapping[str, Any],
) -> ContactSuggestions:
    """Extract contact suggestions from a parser response.

    The function is pure and deterministic. Documents are visited in order, so
    the first-seen display form is stable. Only exact source substrings become
    values; nothing is derived or completed.
    """
    if not isinstance(response, Mapping):
        raise ContactSuggestionError("a parser response must be an object")

    values: dict[str, list[ContactValue]] = {field: [] for field in CONTACT_FIELDS}
    seen: dict[str, set[str]] = {field: set() for field in CONTACT_FIELDS}

    def add(field: str, display: str, normalized: str, evidence: EvidenceReference) -> None:
        if normalized in seen[field]:
            for index, existing in enumerate(values[field]):
                if existing.normalized == normalized:
                    values[field][index] = ContactValue(
                        value=existing.value,
                        normalized=existing.normalized,
                        evidence=existing.evidence + (evidence,),
                    )
                    return
        seen[field].add(normalized)
        values[field].append(
            ContactValue(value=display, normalized=normalized, evidence=(evidence,))
        )

    documents = response.get("documents", [])
    if not isinstance(documents, Sequence) or isinstance(documents, (str, bytes)):
        raise ContactSuggestionError("documents must be an array")

    for document in documents:
        if not isinstance(document, Mapping):
            continue
        if document.get("status") not in USABLE_DOCUMENT_STATUSES:
            continue
        document_id = str(document.get("document_id", ""))
        segments = document.get("segments", [])
        if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)):
            continue
        top_lines_seen = 0
        for segment_index, segment in enumerate(segments):
            if not isinstance(segment, Mapping):
                continue
            text = segment.get("text")
            locator = segment.get("locator", {})
            if not isinstance(text, str) or not isinstance(locator, Mapping):
                continue
            for line in _iter_lines(text):
                found = _extract_from_line(line)
                for field, items in found.items():
                    for display, normalized, start, end in items:
                        add(
                            field,
                            display,
                            normalized,
                            _evidence(
                                document_id,
                                segment_index,
                                locator,
                                text[start:end],
                                start,
                                end,
                            ),
                        )
                # Names and locations are only trusted near the top of a CV.
                if top_lines_seen < 4 and not found:
                    stripped = line.text.strip()
                    if _looks_like_name(stripped):
                        add(
                            "full_name",
                            stripped,
                            _normalize_name(stripped),
                            _evidence(
                                document_id,
                                segment_index,
                                locator,
                                text[line.start : line.end],
                                line.start,
                                line.end,
                            ),
                        )
                    elif _looks_like_location(stripped):
                        add(
                            "location",
                            stripped,
                            _normalize_location(stripped),
                            _evidence(
                                document_id,
                                segment_index,
                                locator,
                                text[line.start : line.end],
                                line.start,
                                line.end,
                            ),
                        )
                top_lines_seen += 1

    suggestions: list[ContactSuggestion] = []
    for field in CONTACT_FIELDS:
        field_values = tuple(values[field])
        if not field_values:
            suggestions.append(ContactSuggestion(field=field, status=MISSING))
            continue
        if field in SCALAR_FIELDS:
            if len(field_values) == 1:
                suggestions.append(
                    ContactSuggestion(
                        field=field,
                        status=SUPPORTED,
                        selected=field_values[0].value,
                        values=field_values,
                    )
                )
            else:
                suggestions.append(
                    ContactSuggestion(field=field, status=CONFLICT, values=field_values)
                )
            continue
        suggestions.append(
            ContactSuggestion(
                field=field,
                status=SUPPORTED,
                selected=field_values[0].value if len(field_values) == 1 else None,
                values=field_values,
            )
        )

    return ContactSuggestions(suggestions=tuple(suggestions))


__all__ = [
    "CONFLICT",
    "CONTACT_FIELDS",
    "CONTACT_SUGGESTIONS_VERSION",
    "ContactSuggestion",
    "ContactSuggestionError",
    "ContactSuggestions",
    "ContactValue",
    "LINK_FIELDS",
    "MISSING",
    "SCALAR_FIELDS",
    "SUPPORTED",
    "extract_contact_suggestions",
]
