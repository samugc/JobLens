"""Public synchronous API for CV export."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .adapter import adapt_draft, validate_export
from .errors import DestinationError, InvalidDraftError
from .models import CanonicalDraft
from .render_docx import render_docx, render_docx_bytes
from .render_pdf import render_pdf, render_pdf_bytes
from .utils import ensure_extension, safe_filename


def _adapt(draft: Any) -> CanonicalDraft:
    try:
        canonical = adapt_draft(draft)
    except Exception as exc:
        # Preserve our error types; wrap others.
        from .errors import CvExportError

        if isinstance(exc, CvExportError):
            raise
        raise InvalidDraftError(str(exc)) from exc
    return canonical


def _validate(
    draft: CanonicalDraft, evidence_support: Any, allow_unverified: bool
) -> None:
    try:
        validate_export(
            draft, evidence_support=evidence_support, allow_unverified=allow_unverified
        )
    except Exception as exc:
        from .errors import CvExportError

        if isinstance(exc, CvExportError):
            raise
        raise InvalidDraftError(str(exc)) from exc


def _open_destination(destination: Any, *, default_name: str, ext: str):
    """Return a usable path/bytes target. Handles str/Path/file-like."""
    if hasattr(destination, "write"):
        return destination
    if isinstance(destination, (str, os.PathLike)):
        path = Path(destination)
        # If a directory is given, create a safe filename inside it.
        if path.exists() and path.is_dir():
            path = path / ensure_extension(safe_filename(default_name), ext)
        elif (not path.exists()) and str(destination).endswith(("/", os.sep)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path = path / ensure_extension(safe_filename(default_name), ext)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        return path
    raise DestinationError(f"unsupported destination type: {type(destination)!r}")


def export_cv_pdf(
    draft: Any,
    destination: Any,
    *,
    page_size: str = "A4",
    evidence_support: Any = None,
    allow_unverified: bool = False,
    filename: str | None = None,
) -> Any:
    """Export a CvDraft to a PDF file. Returns the destination path (or buffer)."""
    canonical = _adapt(draft)
    _validate(canonical, evidence_support, allow_unverified)
    target = _open_destination(
        destination,
        default_name=filename or canonical.candidate.full_name or "cv",
        ext=".pdf",
    )
    try:
        if hasattr(target, "write"):
            render_pdf(canonical, target, page_size=page_size)
            target.flush() if hasattr(target, "flush") else None
            return target
        render_pdf(canonical, target, page_size=page_size)
        return Path(target)
    except Exception as exc:
        from .errors import CvExportError

        if isinstance(exc, CvExportError):
            raise
        raise RuntimeError(f"PDF rendering failed: {exc}") from exc


def export_cv_docx(
    draft: Any,
    destination: Any,
    *,
    evidence_support: Any = None,
    allow_unverified: bool = False,
    filename: str | None = None,
) -> Any:
    canonical = _adapt(draft)
    _validate(canonical, evidence_support, allow_unverified)
    target = _open_destination(
        destination,
        default_name=filename or canonical.candidate.full_name or "cv",
        ext=".docx",
    )
    try:
        if hasattr(target, "write"):
            render_docx(canonical, target)
            target.flush() if hasattr(target, "flush") else None
            return target
        render_docx(canonical, target)
        return Path(target)
    except Exception as exc:
        from .errors import CvExportError

        if isinstance(exc, CvExportError):
            raise
        raise RuntimeError(f"DOCX rendering failed: {exc}") from exc


def export_cv_pdf_bytes(
    draft: Any,
    *,
    page_size: str = "A4",
    evidence_support: Any = None,
    allow_unverified: bool = False,
) -> bytes:
    canonical = _adapt(draft)
    _validate(canonical, evidence_support, allow_unverified)
    try:
        return render_pdf_bytes(canonical, page_size=page_size)
    except Exception as exc:
        from .errors import CvExportError

        if isinstance(exc, CvExportError):
            raise
        raise RuntimeError(f"PDF rendering failed: {exc}") from exc


def export_cv_docx_bytes(
    draft: Any,
    *,
    evidence_support: Any = None,
    allow_unverified: bool = False,
) -> bytes:
    canonical = _adapt(draft)
    _validate(canonical, evidence_support, allow_unverified)
    try:
        return render_docx_bytes(canonical)
    except Exception as exc:
        from .errors import CvExportError

        if isinstance(exc, CvExportError):
            raise
        raise RuntimeError(f"DOCX rendering failed: {exc}") from exc


# Backwards/alternate names.
export_pdf = export_cv_pdf
export_docx = export_cv_docx