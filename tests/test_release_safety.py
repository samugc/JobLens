import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Generic patterns keep the check useful without copying private contact data
# into the public snapshot. The patterns are assembled so this test file does
# not match itself when the tests directory is scanned.
SENSITIVE_PATTERNS = (
    re.compile("/" + r"Users/[^/\s]+"),
    re.compile("linkedin" + r"[.]com/in/", re.IGNORECASE),
    re.compile(r"\+\d{1,3}[\s.-]?\d{2,4}[\s.-]?\d{3,4}"),
    re.compile(r"NOT\s+AUTHORIZED", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
)
TEXT_SUFFIXES = {".py", ".json", ".md", ".html", ".css", ".js", ".mjs", ".svg", ".toml", ".txt"}


def text_files():
    roots = [
        ROOT / "data",
        ROOT / "web",
        ROOT / "src",
        ROOT / "docs",
        ROOT / "scripts",
        ROOT / "tests",
    ]
    for folder in roots:
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix in TEXT_SUFFIXES:
                yield path
    for name in ("README.md", "run_demo.py", "pyproject.toml", "LICENSE"):
        path = ROOT / name
        if path.exists():
            yield path


def test_no_private_contact_or_release_markers_are_in_the_snapshot():
    for path in text_files():
        text = path.read_text(encoding="utf-8")
        for pattern in SENSITIVE_PATTERNS:
            assert not pattern.search(text), (
                f"{pattern.pattern!r} found in {path.relative_to(ROOT)}"
            )


def test_ui_has_no_inline_scripts_or_styles():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "style=" not in html
    assert re.search(r"<script(?![^>]*\bsrc=)", html) is None
    assert re.search(r"<style\b", html) is None


def test_snapshot_does_not_contain_a_private_git_directory():
    assert not (ROOT / ".git").exists()


def test_readme_documents_the_synthetic_and_local_scope():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in ("synthetic", "local", "pytest", "Limitations", "screenshot"):
        assert phrase.casefold() in readme.casefold()


def test_readme_documents_source_only_packaging():
    readme = " ".join(
        (ROOT / "README.md").read_text(encoding="utf-8").casefold().split()
    )
    assert "wheel" in readme
    assert "not a supported installation method" in readme
    assert "does not include all runtime resources" in readme
    assert "python3 run_demo.py" in readme
