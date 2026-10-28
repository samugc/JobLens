"""Source-backed provisional drafting. Never creates ApprovedFact objects."""

from dataclasses import dataclass, field, replace

from .cv import generate_cv_draft
from .profile import build_profile_proposals
from .profile.approved import CandidateContact
from .reconcile import reconcile_documents


@dataclass(frozen=True)
class ProvisionalSource:
    facts: tuple
    candidate: CandidateContact = field(default_factory=CandidateContact)


@dataclass(frozen=True)
class ProvisionalFact:
    # Legacy generator field name; this is a source proposal, NOT an approval.
    fact_id: str
    category: object
    value: object
    evidence: tuple


def _starts_entry(quote: str, role: str) -> bool:
    """True when a quote is the role line that starts an entry, not a bullet."""
    if not role:
        return False
    cleaned = quote.strip().lstrip("-\u2022*\u2013\u2014 ").strip().casefold()
    if not cleaned.startswith(role):
        return False
    rest = cleaned[len(role):].lstrip()
    return not rest or rest[0] in "|:\u00b7-\u2013\u2014" or rest.startswith("at ")


def draft_from_source(source, job, *, trace=None, analysis=None):
    response = {"schema_version": "1.1", **source}
    profile = build_profile_proposals(response)
    report = reconcile_documents(response)
    documents = {d["document_id"]: d for d in source["documents"]}
    filenames = {
        document_id: str(document.get("filename") or f"document {index + 1}")
        for index, (document_id, document) in enumerate(documents.items())
    }

    def entry_line(e):
        text = documents[e.document_id]["segments"][e.segment_index]["text"]
        start = text.rfind("\n", 0, e.start) + 1
        end = text.find("\n", e.end)
        return text[start : end if end >= 0 else len(text)].strip()

    blocked = set()
    identity_only = set()
    for relation in report.relationships:
        left, right = report.claim(relation.left_claim_id), report.claim(relation.right_claim_id)
        # A title and contribution from identical source entries need no
        # cross-category inference. Preserve the entry, not a guessed relation.
        if (
            relation.relation.value == "uncertain"
            and {left.category.value, right.category.value} == {"project", "contribution"}
            and left.evidence
            and right.evidence
            and {entry_line(e) for e in left.evidence} == {entry_line(e) for e in right.evidence}
        ):
            identity_only.update((left.claim_id, right.claim_id))
            continue
        # Missing identity is not contradictory degree/role wording. Preserve
        # only the stated content, never infer that two jobs/awards are one.
        if (
            relation.relation.value == "uncertain"
            and left.category == right.category
            and left.category.value in ("employment", "education", "degree")
            and [(a.name, a.normalized) for a in left.attributes]
            == [(a.name, a.normalized) for a in right.attributes]
            and {a.name for a in left.attributes} <= {"role", "level", "field"}
        ):
            identity_only.update((left.claim_id, right.claim_id))
            continue
        if relation.relation.value not in {"equivalent", "duplicate", "complementary", "unrelated"}:
            blocked.update((relation.left_claim_id, relation.right_claim_id))
    for decision in report.decisions:
        if decision.outcome.value != "auto_consolidate":
            blocked.update(set(decision.keep_claim_ids + decision.merge_claim_ids) - identity_only)
    unsafe = [e for c in report.claims if c.claim_id in blocked for e in c.evidence]

    def overlaps(a, b):
        return (
            a.document_id == b.document_id
            and a.segment_index == b.segment_index
            and a.start < b.end
            and b.start < a.end
        )

    facts = []
    omitted = 0
    documents = {d["document_id"]: d for d in source["documents"]}
    for p in profile.proposals:
        created_fact_ids = []
        # Preserve the exact entry containing a role, including employer/dates.
        # This remains provisional evidence, never a new approved fact.
        if p.category.value in ("experience", "education"):
            expanded = []
            for e in p.evidence:
                text = documents[e.document_id]["segments"][e.segment_index]["text"]
                start = text.rfind("\n", 0, e.start) + 1
                end = text.find("\n", e.end)
                if end < 0:
                    end = len(text)
                expanded.append(replace(e, start=start, end=end, quote=text[start:end]))
            p = replace(p, evidence=tuple(expanded))
        # A bad reference does not invalidate independent, valid references.
        kept = tuple(e for e in p.evidence if not any(overlaps(e, bad) for bad in unsafe))
        if p.category.value == "skill":
            kept = tuple(e for e in kept if e.support.value == "explicit_claim")
        reason = "retained"
        if p.conflicts:
            kept = ()
            reason = "unresolved profile conflict"
        elif not kept:
            reason = (
                "no explicit skill claim"
                if p.category.value == "skill"
                else "all evidence overlaps unresolved contradictions"
            )
        if not kept:
            omitted += 1
        if trace is not None:
            trace.append(
                {
                    "proposal_id": p.proposal_id,
                    "category": p.category.value,
                    "value": dict(p.value),
                    "source_quotes": [e.quote for e in p.evidence],
                    "retained_quotes": [e.quote for e in kept],
                    "reason": reason,
                    "fact_ids": created_fact_ids,
                    "document_labels": [
                        filenames.get(document_id, document_id)
                        for document_id in sorted(
                            {e.document_id for e in p.evidence}
                        )
                    ],
                }
            )
        if not kept:
            continue
        if p.category.value == "experience":
            # Do not combine positions solely because their generic roles match.
            # A new entry starts at each source line that begins with the role;
            # the lines after it are that entry's contributions.
            role = str(p.value.get("role", "")).strip().casefold()
            groups: list[list] = []
            for e in kept:
                if not groups or _starts_entry(e.quote, role):
                    groups.append([e])
                else:
                    groups[-1].append(e)
            for index, refs in enumerate(groups):
                fact_id = p.proposal_id + ":entry:" + str(index)
                created_fact_ids.append(fact_id)
                facts.append(
                    ProvisionalFact(fact_id, p.category, p.value, tuple(refs))
                )
        else:
            created_fact_ids.append(p.proposal_id)
            facts.append(ProvisionalFact(p.proposal_id, p.category, p.value, kept))
    # Collapse identical entry wording while retaining every document citation.
    # Different contributions under a generic role remain separate entries.
    distinct = {}
    redundant_fact_ids = []
    for fact in facts:
        key = (
            fact.category.value,
            tuple(sorted(fact.value.items())),
            tuple(dict.fromkeys(e.quote.strip() for e in fact.evidence)),
        )
        if key in distinct:
            prior = distinct[key]
            redundant_fact_ids.append(fact.fact_id)
            distinct[key] = replace(prior, evidence=prior.evidence + fact.evidence)
        else:
            distinct[key] = fact
    facts = list(distinct.values())
    if not facts:
        raise ValueError(
            "No unambiguous professional information could be read. Try a text-based CV."
        )
    if trace is not None:
        quotes_by_fact = {
            fact.fact_id: [e.quote for e in fact.evidence] for fact in facts
        }
        for entry in trace:
            if not entry.get("fact_ids"):
                continue
            quotes: list[str] = []
            for fact_id in entry["fact_ids"]:
                for quote in quotes_by_fact.get(fact_id, ()):
                    if quote not in quotes:
                        quotes.append(quote)
            if quotes:
                entry["retained_quotes"] = quotes
    draft = generate_cv_draft(
        ProvisionalSource(tuple(facts)), job, ollama=False, source_response=response
    )
    draft = replace(
        draft, warnings=tuple(w.replace("approved", "source-backed") for w in draft.warnings)
    )
    evidence = {f.fact_id: [e.as_dict() for e in f.evidence] for f in facts}
    if analysis is not None:
        analysis["conflicts"] = [conflict.as_dict() for conflict in profile.conflicts]
        analysis["documents"] = dict(filenames)
        analysis["redundant_fact_ids"] = tuple(redundant_fact_ids)
    return draft, evidence, omitted
