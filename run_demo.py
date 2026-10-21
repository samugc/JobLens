#!/usr/bin/env python3
"""One-command local demo: python3 run_demo.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from joblens_public.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["--open", *sys.argv[1:]]))
