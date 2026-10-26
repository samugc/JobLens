"""Real extraction -> Python profile -> JS adapter/review integration."""
import subprocess
from pathlib import Path

import test_cv_mount
from cv_builders import make_docx, make_pdf
from profile_fixtures import full_cv

app_server = test_cv_mount.app_server
ROOT = Path(__file__).resolve().parents[1]


def test_real_profile_flow_and_local_review(app_server, tmp_path, capfd):
    text = full_cv().replace(
        'CV Evidence Workspace - a local HTTP transport',
        'CV Evidence Workspace - a mobile app for synthetic reviews')
    pdf = tmp_path / 'synthetic-phase2.pdf'
    docx = tmp_path / 'synthetic-phase2.docx'
    # A blank second page produces a genuine partial parser document.
    pdf.write_bytes(make_pdf([text.splitlines(), []]))
    alternate = text.replace('Python, SQL', '😀 Python, SQL').replace(
        'English (C1)', 'English (B2)').replace(
        'CV Evidence Workspace - a mobile app for synthetic reviews',
        'CV Evidence Workspace - a CLI tool for synthetic reviews')
    docx.write_bytes(make_docx([(line, None) for line in alternate.splitlines()]))
    result = subprocess.run(
        ['node', str(ROOT / 'tests/ui/cv-profile-integrated-http.mjs'),
         f'http://127.0.0.1:{app_server.server_port}', str(pdf), str(docx)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    print(result.stdout)
