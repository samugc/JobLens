#!/usr/bin/env python3
"""Inspect built distributions for publication-safety failures.

This is intentionally a small, dependency-free checker. It is used by CI after
``python -m build`` and by the release tests, so the same rules protect local
builds and CI builds.

The source distribution must contain exactly the two approved synthetic sample
documents and none of the generated/local-only artifacts. The wheel is
code-only: it must not contain any PDF or DOCX at all.
"""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

APPROVED_SAMPLES = frozenset(
    {
        "web/samples/alex-rivera-cv.pdf",
        "web/samples/alex-rivera-cv-2.docx",
    }
)

# These names must never enter an artifact, regardless of the archive prefix.
FORBIDDEN_RELATIVE_PATHS = frozenset(
    {
        "evaluation/results.json",
        "docs/final-stabilization-report.md",
        "docs/integrated-release-report.md",
        "docs/release-qa-report.md",
    }
)

FORBIDDEN_PARTS = (
    ".release-preparation",
    ".integration-verification",
    "__pycache__",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
)

FORBIDDEN_SUFFIXES = (
    ".env",
    ".venv",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".pyc",
    ".log",
)


class ArchiveInspectionError(AssertionError):
    """Raised when an archive violates the public packaging policy."""


def _normalized(name: str) -> str:
    return name.replace("\\", "/").lower()


def _archive_names(archive: Path) -> list[str]:
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive) as handle:
            return handle.getnames()
    if archive.suffix == ".whl" or archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as handle:
            return handle.namelist()
    raise ArchiveInspectionError(f"{archive}: unsupported archive type")


def _is_forbidden(name: str) -> bool:
    if any(part in name for part in FORBIDDEN_PARTS):
        return True
    if name.endswith(FORBIDDEN_SUFFIXES):
        return True
    return any(
        name == relative or name.endswith("/" + relative)
        for relative in FORBIDDEN_RELATIVE_PATHS
    )


def inspect_archive(archive: Path) -> dict[str, object]:
    """Validate one built archive and return a small summary.

    Raises ``ArchiveInspectionError`` with the first offending members.
    """

    archive = Path(archive)
    names = _archive_names(archive)
    lowered = [_normalized(name) for name in names]
    is_sdist = archive.name.endswith(".tar.gz")
    found_samples: set[str] = set()
    hits: list[str] = []

    for name in lowered:
        if _is_forbidden(name):
            hits.append(name)
        if not name.endswith((".pdf", ".docx")):
            continue
        approved = next(
            (
                sample
                for sample in APPROVED_SAMPLES
                if name == sample or name.endswith("/" + sample)
            ),
            None,
        )
        if approved is None or not is_sdist:
            hits.append(name)
        else:
            found_samples.add(approved)

    if hits:
        raise ArchiveInspectionError(
            f"{archive}: forbidden entries {sorted(set(hits))[:10]}"
        )
    if is_sdist and found_samples != set(APPROVED_SAMPLES):
        missing = sorted(set(APPROVED_SAMPLES) - found_samples)
        raise ArchiveInspectionError(f"{archive}: missing approved samples {missing}")

    return {
        "archive": str(archive),
        "members": len(names),
        "approved_samples": sorted(found_samples),
    }


def inspect_dist(dist: Path) -> list[dict[str, object]]:
    """Validate every supported archive in ``dist``."""

    archives = sorted(
        path
        for path in Path(dist).glob("*")
        if path.name.endswith(".tar.gz") or path.suffix == ".whl"
    )
    if not archives:
        raise ArchiveInspectionError(f"{dist}: no release artifacts were built")
    return [inspect_archive(archive) for archive in archives]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    dist = Path(args[0]) if args else Path("dist")
    try:
        results = inspect_dist(dist)
    except (ArchiveInspectionError, OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"archive inspection failed: {error}", file=sys.stderr)
        return 1
    for result in results:
        print(
            f"{result['archive']}: {result['members']} entries; "
            f"approved samples={result['approved_samples']}"
        )
    print("archive inspection passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
