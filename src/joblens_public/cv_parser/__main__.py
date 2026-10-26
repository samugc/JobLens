"""Command-line entry point for local extraction.

Usage:
    PYTHONPATH=src python -m joblens_public.cv_parser cv.pdf cover.docx

Writes the JSON contract to stdout. Files are read locally; nothing is
uploaded and document contents are never written to a log.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import UploadDocument, extract_batch


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m joblens_public.cv_parser",
        description="Extract text and source locators from local PDF/DOCX CVs.",
    )
    parser.add_argument("files", nargs="+", metavar="FILE")
    args = parser.parse_args(argv)

    uploads: list[UploadDocument] = []
    for raw_path in args.files:
        path = Path(raw_path)
        try:
            uploads.append(UploadDocument(filename=path.name, data=path.read_bytes()))
        except OSError:
            print(f"{path.name}: could not read file", file=sys.stderr)
            return 1

    response = extract_batch(uploads)
    json.dump(response, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0 if response["batch"]["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
