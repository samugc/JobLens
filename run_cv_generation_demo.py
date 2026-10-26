#!/usr/bin/env python3
"""Deterministic CV generation demo (no Ollama, no network)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from profile_fixtures import make_document, make_response  # noqa: E402

from joblens_public.cv import generate_cv_draft  # noqa: E402
from joblens_public.jobs import parse_job_posting  # noqa: E402
from joblens_public.profile import build_profile_proposals  # noqa: E402
from joblens_public.profile.approved import build_approved_profile  # noqa: E402
from joblens_public.profile.review import (  # noqa: E402
    APPROVE,
    ReviewAction,
    apply_review_action,
    initial_review_state,
)

CV1 = """Skills
Python, SQL

Experience
Data Engineer | Acme Corporation | 2019-2022

Projects
Ledger - a Django application that reduced costs by 30%

Education
BSc in Computer Science, University of Manchester (2016-2019)

Languages
English (C1)

Certifications
AWS Certified Solutions Architect
"""

CV2 = """Skills
Python, Docker

Experience
Senior Data Engineer | Acme Corporation | 2022-present

Projects
Ledger - a Django application that reduced costs by 30%

Education
MSc in Data Science, University of Manchester (2019-2021)
"""

JOB_TEXT = """Senior AI Engineer

Required
Python
SQL
Docker
Kubernetes
5+ years experience

Preferred
AWS

Responsibilities
Build and deploy machine learning pipelines

About
We are a fast-growing AI company.
"""


def main() -> int:
    documents = [
        make_document("doc_0", CV1, index=0),
        make_document("doc_1", CV2, index=1),
    ]
    response = make_response(documents, job_id="job_demo")
    envelope = build_profile_proposals(response)
    state = initial_review_state(envelope)
    for proposal in state.proposals:
        state = apply_review_action(state, ReviewAction(APPROVE, proposal.proposal_id))
    profile = build_approved_profile(envelope, state, source_response=response)
    job = parse_job_posting(JOB_TEXT, title="Senior AI Engineer", company="Acme AI")
    draft = generate_cv_draft(profile, job)
    print(json.dumps(draft.as_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
