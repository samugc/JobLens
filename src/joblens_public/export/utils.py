"""Shared helpers: filenames, fonts, text normalisation."""

from __future__ import annotations

import os
import re
import unicodedata

SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str, *, default: str = "cv", max_length: int = 120) -> str:
    """Return a filesystem-safe filename stem (no extension)."""
    if not isinstance(name, str) or not name.strip():
        name = default
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = SAFE_FILENAME_RE.sub("_", name).strip("._-")
    if not name:
        name = default
    if len(name) > max_length:
        name = name[:max_length].rstrip("._-") or default
    return name


def ensure_extension(filename: str, ext: str) -> str:
    ext = ext if ext.startswith(".") else "." + ext
    if not filename.lower().endswith(ext.lower()):
        filename = filename + ext
    return filename


def page_size_from_name(name: str):
    from reportlab.lib.pagesizes import A4, LETTER

    key = (name or "A4").strip().upper().replace(" ", "").replace("-", "")
    if key in ("A4",):
        return A4
    if key in ("LETTER", "USLETTER", "US_LETTER", "ANSILETTER"):
        return LETTER
    raise ValueError(f"unsupported page size {name!r}")


def resolve_system_font() -> tuple[str, str | None]:
    """Return (reportlab_font_name, ttf_path_or_None).

    Prefers a Unicode-capable system font; falls back to Helvetica.
    """
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return ("CvUnicode", path)
    return ("Helvetica", None)


def register_reportlab_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    name, path = resolve_system_font()
    if path is not None:
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            # Bold/italic variants best-effort.
            bold_path = path.replace("Regular", "Bold").replace(".ttf", ".ttf")
            if os.path.isfile(bold_path) and bold_path != path:
                try:
                    pdfmetrics.registerFont(TTFont(name + "-Bold", bold_path))
                except (OSError, ValueError, RuntimeError):
                    # Best-effort only; fall back to base font.
                    pass
            return name
        except (OSError, ValueError, RuntimeError):
            return "Helvetica"
    return "Helvetica"


def split_text_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return url
    if "://" not in url and not url.startswith("mailto:"):
        if "@" in url and "." in url:
            return "mailto:" + url
        return "https://" + url
    if not url.lower().startswith(('https://', 'http://', 'mailto:')):
        raise ValueError('Only HTTP, HTTPS and email contact links are supported')
    return url


def link_label(url: str) -> str:
    url = (url or "").strip()
    low = url.lower()
    if "github.com" in low:
        return "GitHub"
    if "linkedin.com" in low or "linkedin" in low:
        return "LinkedIn"
    if "mailto:" in low:
        return url.replace("mailto:", "")
    return url


def clean_period(period: str | None) -> str | None:
    if period is None:
        return None
    period = " ".join(str(period).split())
    if not period:
        return None
    # Normalise common separators.
    period = period.replace("--", "–")
    return period