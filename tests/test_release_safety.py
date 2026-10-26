import io
import re
import runpy
import tarfile
from pathlib import Path

import pytest

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
            matches = list(pattern.finditer(text))
            matches = [
                m
                for m in matches
                if not m.group().lower().endswith(
                    ("@example.com", "@example.org", "@example.net", "@example.test")
                )
            ]
            assert not matches, (
                f"{pattern.pattern!r} found in {path.relative_to(ROOT)}"
            )


def test_ui_has_no_inline_scripts_or_styles():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "style=" not in html
    assert re.search(r"<script(?![^>]*\bsrc=)", html) is None
    assert re.search(r"<style\b", html) is None


def test_git_metadata_does_not_reference_the_private_repository():
    git_path = ROOT / ".git"
    if not git_path.exists():
        return
    if git_path.is_file():
        marker = git_path.read_text(encoding="utf-8").strip()
        if not marker.startswith("gitdir:"):
            return
        git_dir = (ROOT / marker.split(":", 1)[1].strip()).resolve()
    else:
        git_dir = git_path
    config = git_dir / "config"
    if not config.exists():
        return
    assert "joblens-research" not in config.read_text(encoding="utf-8").casefold()


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


def _release_inspector():
    return runpy.run_path(str(ROOT / "scripts" / "inspect_release_archive.py"))


def _write_tar(path, relative_paths):
    with tarfile.open(path, "w") as handle:
        for relative in relative_paths:
            data = b"test"
            info = tarfile.TarInfo("joblens_public-1.0.0/" + relative)
            info.size = len(data)
            handle.addfile(info, io.BytesIO(data))


def test_manifest_and_ci_use_the_shared_archive_safety_rules():
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    for excluded in (
        "evaluation/results.json",
        "docs/final-stabilization-report.md",
        "docs/integrated-release-report.md",
        "docs/release-qa-report.md",
    ):
        assert f"exclude {excluded}" in manifest
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "python scripts/inspect_release_archive.py dist" in workflow
    assert "evaluation/results.json" not in workflow.split("Inspect release archive", 1)[1]


def test_archive_inspector_accepts_only_the_two_approved_samples(tmp_path):
    inspector = _release_inspector()
    clean = tmp_path / "joblens_public-1.0.0.tar.gz"
    _write_tar(
        clean,
        (
            "README.md",
            "evaluation/README.md",
            "web/samples/alex-rivera-cv.pdf",
            "web/samples/alex-rivera-cv-2.docx",
        ),
    )
    result = inspector["inspect_archive"](clean)
    assert result["approved_samples"] == [
        "web/samples/alex-rivera-cv-2.docx",
        "web/samples/alex-rivera-cv.pdf",
    ]


@pytest.mark.parametrize(
    "forbidden",
    (
        "evaluation/results.json",
        "docs/release-qa-report.md",
        ".release-preparation/public-files.txt",
        ".integration-verification/scratch.json",
    ),
)
def test_archive_inspector_rejects_generated_or_private_entries(tmp_path, forbidden):
    inspector = _release_inspector()
    archive = tmp_path / "joblens_public-1.0.0.tar.gz"
    _write_tar(
        archive,
        (
            "web/samples/alex-rivera-cv.pdf",
            "web/samples/alex-rivera-cv-2.docx",
            forbidden,
        ),
    )
    with pytest.raises(inspector["ArchiveInspectionError"]):
        inspector["inspect_archive"](archive)


def test_archive_inspector_rejects_samples_in_the_wheel(tmp_path):
    inspector = _release_inspector()
    wheel = tmp_path / "joblens_public-1.0.0-py3-none-any.whl"
    import zipfile

    with zipfile.ZipFile(wheel, "w") as handle:
        handle.writestr("joblens_public/__init__.py", "")
        handle.writestr("web/samples/alex-rivera-cv.pdf", b"test")
    with pytest.raises(inspector["ArchiveInspectionError"]):
        inspector["inspect_archive"](wheel)
