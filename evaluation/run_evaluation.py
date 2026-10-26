"""CLI: run the synthetic release evaluation and write a JSON report.

Usage:
    python evaluation/run_evaluation.py [--output evaluation/results.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .harness import run_all


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="evaluation/results.json",
        help="Where to write the JSON report (default: evaluation/results.json)",
    )
    args = parser.parse_args()
    report = run_all()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    metrics = report["metrics"]
    print("JobLens synthetic release evaluation")
    print(f"scenarios: {metrics['scenarios_ok']} ok, "
          f"{metrics['scenarios_expected_error']} expected error, "
          f"{metrics['scenarios_failed']} failed")
    print(f"supported fact preservation: {metrics['supported_fact_preserved']}"
          f"/{metrics['supported_fact_expected']}")
    print(f"forbidden/unsupported insertions: {metrics['unsupported_or_forbidden_insertions']}"
          f"/{metrics['unsupported_or_forbidden_checks']} checks")
    print(f"conflict omission: {metrics['conflict_terms_omitted']}"
          f"/{metrics['conflict_terms_checked']}")
    print(f"supported requirement recall: {metrics['supported_requirements_present']}"
          f"/{metrics['supported_requirements_checked']}")
    print(f"unmet-requirement contradictions: {metrics['unmet_requirements_present_in_cv']}"
          f"/{metrics['unmet_requirements_checked']} reported gaps already in CV")
    print(f"PDF/DOCX mean token Jaccard: {metrics['pdf_docx_mean_token_jaccard']}")
    print(f"review enforcement: {metrics['review_attempts_rejected']}"
          f"/{metrics['review_attempts']}")
    print(f"report: {output}")
    return 0 if metrics["scenarios_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
