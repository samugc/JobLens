"""CLI: run the evidence-quality research cases and write a JSON report."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from evaluation.support import LocalServer

from .cases import (
    ACHIEVEMENT_DEVELOPMENT,
    ACHIEVEMENT_HOLDOUT,
    COVERAGE_DEVELOPMENT,
    COVERAGE_HOLDOUT,
)
from .harness import (
    aggregate,
    run_achievement_case,
    run_coverage_case,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split",
        choices=("development", "holdout", "all"),
        default="development",
    )
    parser.add_argument("--label", required=True, help="Result label, e.g. baseline")
    parser.add_argument("--output-dir", default="evaluation/research/results")
    args = parser.parse_args()

    achievement_cases = []
    coverage_cases = []
    if args.split in ("development", "all"):
        achievement_cases.extend(ACHIEVEMENT_DEVELOPMENT)
        coverage_cases.extend(COVERAGE_DEVELOPMENT)
    if args.split in ("holdout", "all"):
        achievement_cases.extend(ACHIEVEMENT_HOLDOUT)
        coverage_cases.extend(COVERAGE_HOLDOUT)

    achievements = []
    coverage = []
    with LocalServer() as server:
        for case in achievement_cases:
            achievements.append(run_achievement_case(server, case))
        for case in coverage_cases:
            coverage.append(run_coverage_case(server, case))

    metrics = aggregate(achievements, coverage)
    report = {
        "label": args.label,
        "split": args.split,
        "metrics": metrics,
        "achievement_cases": [asdict(case) for case in achievements],
        "coverage_cases": [asdict(case) for case in coverage],
    }
    output = Path(args.output_dir) / f"{args.label}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"JobLens evidence-quality research ({args.split}, label={args.label})")
    print(f"achievement cases ok: {metrics['achievement_cases_ok']}/{metrics['achievement_cases']}")
    print(
        "achievement checks: "
        f"{metrics['achievement_checks_passed']}/{metrics['achievement_checks']}"
    )
    print(f"requirements: {metrics['requirements']}")
    print(f"3-class correct: {metrics['state_correct']}/{metrics['requirements']}")
    print(f"unsafe cover: {metrics['unsafe_cover']}")
    print(
        "recall covered/partial/uncovered: "
        f"{metrics['covered_recalled']}/{metrics['covered_requirements']}, "
        f"{metrics['partial_recalled']}/{metrics['partial_requirements']}, "
        f"{metrics['uncovered_recalled']}/{metrics['uncovered_requirements']}"
    )
    print(f"importance correct: {metrics['importance_correct']}/{metrics['importance_checks']}")
    print(f"duplicate gap entries: {metrics['duplicate_gap_entries']}")
    print(f"report support false claims: {metrics['report_support_false_claims']}")
    print(f"report support missing: {metrics['report_support_missing']}")
    print(f"report/coverage inconsistent: {metrics['coverage_report_inconsistent']}")
    print(f"errors: {metrics['errors']}")
    print(f"report: {output}")
    failed = (
        metrics["achievement_cases_ok"] != metrics["achievement_cases"]
        or metrics["errors"]
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
