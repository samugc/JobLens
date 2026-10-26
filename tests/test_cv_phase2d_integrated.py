"""Phase 2D live integration, using only generated synthetic documents."""
import subprocess
from pathlib import Path

import test_cv_mount
from cv_builders import make_docx, make_pdf
from profile_fixtures import full_cv

app_server = test_cv_mount.app_server
ROOT = Path(__file__).resolve().parents[1]


def test_phase2d_actual_adapters_and_engine(app_server, tmp_path, capfd):
    text = full_cv().replace(
        'CV Evidence Workspace - a local HTTP transport',
        'Project Atlas - a reporting dashboard for synthetic sales\n'
        'Project Beacon - a mobile app for synthetic reviews')
    alternate = text.replace('Python, SQL', '😀 Python, SQL').replace(
        'English (C1)', 'English (B2)').replace(
        'a reporting dashboard for synthetic sales',
        'a reporting dashboard written in Python').replace(
        'a mobile app for synthetic reviews', 'a CLI tool for synthetic reviews')
    pdf, docx = tmp_path / 'synthetic.pdf', tmp_path / 'synthetic.docx'
    pdf.write_bytes(make_pdf([text.splitlines(), []]))
    docx.write_bytes(make_docx([(line, None) for line in alternate.splitlines()]))
    result = subprocess.run(
        ['node', str(ROOT / 'tests/ui/cv-phase2d-integrated-http.mjs'),
         f'http://127.0.0.1:{app_server.server_port}', str(pdf), str(docx)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    captured = capfd.readouterr()
    assert captured.out == captured.err == ''
    print(result.stdout)
