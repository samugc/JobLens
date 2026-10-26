"""Real PDF/DOCX -> extraction -> profile -> reconciliation acceptance."""
import json
import subprocess
from pathlib import Path

import pytest
import test_cv_profile_api
from cv_builders import make_docx, make_pdf

from joblens_public import webapp
from joblens_public.reconcile import reconcile_documents

app_server = test_cv_profile_api.app_server
ROOT = Path(__file__).resolve().parents[1]
LEVELS = ['a1', 'a2', 'b1', 'b2', 'c1', 'c2']
CASES = []
for left in LEVELS:
    for right in LEVELS:
        CASES.append((f'Languages\nEnglish ({left.upper()})',
                      f'Languages\nEnglish ({right.upper()})',
                      {'id': f'cefr-{left}-{right}', 'category': 'language', 'subject': 'english',
                       'relations': ['duplicate' if left == right else 'potentially_conflicting'],
                       'outcome': 'auto_consolidate' if left == right else 'recommend',
                       **({'kept': max(left, right, key=LEVELS.index)} if left != right else {})}))


def scenario(name, left, right, category, subject, relation, outcome=None, **extra):
    CASES.append((left, right, {'id': name, 'category': category, 'subject': subject,
                               'relations': relation.split('|'), 'outcome': outcome, **extra}))


scenario('non-comparable', 'Languages\nEnglish (native)', 'Languages\nEnglish (C1)',
         'language', 'english', 'potentially_conflicting', 'unresolved')
scenario('duplicate-skills', 'Skills\nPython, SQL', 'Skills\nPython, SQL',
         'skill', 'python', 'duplicate', 'auto_consolidate')
scenario('project-equivalent', 'Projects\nAtlas - built the ingestion pipeline',
         'Projects\nAtlas - built the ingestion pipeline', 'contribution', 'atlas',
         'duplicate', 'auto_consolidate')
scenario('project-complementary', 'Projects\nAtlas - a Django application for shops',
         'Projects\nAtlas - a Django application for shops with a React frontend',
         'project', 'atlas', 'complementary|more_specific|less_specific')
scenario('duration', 'Experience\nData Engineer | Acme Corporation | 2018-2020, 5 years',
         'Experience\nData Engineer | Acme Corporation | 2018-2020',
         'employment', 'data engineer', 'contradictory', 'unresolved',
         attributes=['start', 'end', 'duration_months'])
scenario('simultaneous', 'Experience\nData Engineer | Acme Corporation | 2019-2022',
         'Experience\nData Engineer | Acme Corporation | 2020-2023',
         'employment', 'data engineer', 'potentially_conflicting', 'unresolved')
scenario('progression', 'Experience\nData Engineer | Acme Corporation | 2016-2019',
         'Experience\nSenior Data Engineer | Acme Corporation | 2019-2022',
         'employment', 'data engineer', 'temporal_update', 'recommend')
scenario('education-compatible', 'Education\nBSc in Computer Science (2016-2019)',
         'Education\nBSc in Computer Science (2016-2019)',
         'education', 'computer science', 'duplicate', 'auto_consolidate')
scenario('education-incompatible', 'Education\nBSc in Computer Science (2016-2019)',
         'Education\nBSc in Computer Science (2017-2020)',
         'education', 'computer science', 'potentially_conflicting', 'unresolved')
scenario('metrics', 'Projects\nAtlas - reduced the processing time by 40%',
         'Projects\nAtlas - reduced the processing time by 10%',
         'achievement', 'atlas', 'contradictory', 'unresolved', attributes=['quantities'])
scenario('cross-category', 'Skills\nDjango', 'Projects\nAtlas - a Django application',
         'skill', 'django', 'complementary', crossCategory=True)


@pytest.mark.parametrize('left,right,spec', CASES, ids=[c[2]['id'] for c in CASES])
def test_real_reconciliation_pipeline(app_server, tmp_path, monkeypatch, capfd, left, right, spec):
    pdf, docx = tmp_path / 'synthetic.pdf', tmp_path / 'synthetic.docx'
    pdf.write_bytes(make_pdf([left.splitlines(), []]))
    # A non-BMP prefix in the same segment exercises code-point offsets.
    docx.write_bytes(make_docx([('😀 Synthetic source\n' + right, None)]))
    settings, result_file = tmp_path / 'case.json', tmp_path / 'result.json'
    settings.write_text(json.dumps(spec))
    calls = []

    def counted(payload):
        calls.append(payload)
        return reconcile_documents(payload)

    monkeypatch.setattr(webapp, 'reconcile_documents', counted)
    result = subprocess.run(
        ['node', str(ROOT / 'tests/ui/cv-reconciliation-integrated-http.mjs'),
         f'http://127.0.0.1:{app_server.server_port}', str(pdf), str(docx),
         str(settings), str(result_file)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(calls) == 1
    actual = json.loads(result_file.read_text())
    assert set(actual['request']) == {'job_id', 'documents'}
    expected = reconcile_documents({'schema_version': '1.1', **actual['request']}).as_dict()
    assert actual['report'] == expected
    captured = capfd.readouterr()
    assert captured.out == captured.err == ''


def source_body(count=1):
    return json.dumps({'job_id': 'job_synthetic', 'documents': [
        {'document_id': f'doc_{i}', 'index': i, 'filename': 'synthetic.pdf',
         'status': 'extracted', 'format': 'pdf',
         'segments': [{'text': 'Skills\nPython', 'locator': {'kind': 'page', 'page': 1}}]}
        for i in range(count)
    ]}).encode()


def request_report(server, body=None, headers=None, method='POST', path='/api/cv/reconciliations'):
    return test_cv_profile_api.request(
        server.server_port, method, path, source_body() if body is None else body,
        test_cv_profile_api.json_headers(server.server_port, **(headers or {})),
    )


@pytest.mark.parametrize('headers,expected', [
    ({'Origin': 'https://example.invalid'}, 403),
    ({'Host': 'example.invalid'}, 403),
    ({'X-JobLens-Request': ''}, 403),
    ({'X-JobLens-Request': 'wrong'}, 403),
    ({'Content-Type': 'text/plain'}, 415),
    ({'Content-Encoding': 'gzip'}, 415),
    ({'Transfer-Encoding': 'chunked'}, 400),
])
def test_reconciliation_security(app_server, headers, expected):
    assert request_report(app_server, headers=headers)[0] == expected


@pytest.mark.parametrize('body', [b'{', b'\xff', b'[]', b'{}', source_body(6),
                                b'{"job_id":"job","documents":[],"approved":true}'])
def test_reconciliation_rejects_invalid_sources(app_server, body):
    status, headers, raw = request_report(app_server, body)
    assert status == 400
    assert 'access-control-allow-origin' not in headers
    assert json.loads(raw)['error']['code'] in {'invalid_json', 'invalid_request'}


def test_reconciliation_size_and_methods(app_server):
    status, _, raw = request_report(app_server, b'', {'Content-Length': str(webapp.PROFILE_MAX_BODY + 1)})
    assert status == 413
    assert json.loads(raw)['error']['code'] == 'request_too_large'
    assert request_report(app_server, b'', method='GET')[0] == 405
    assert request_report(app_server, b'', method='OPTIONS')[0] == 403
    assert request_report(app_server, method='POST', path='/api/cv/reconciliations/approve')[0] == 404


def test_reconciliation_redacts_unexpected_errors(app_server, monkeypatch, capfd):
    def explode(_):
        raise RuntimeError('SYNTHETIC_SECRET_MARKER')
    monkeypatch.setattr(webapp, 'reconcile_documents', explode)
    status, _, raw = request_report(app_server)
    assert status == 500
    assert b'SYNTHETIC_SECRET_MARKER' not in raw
    captured = capfd.readouterr()
    assert captured.out == captured.err == ''


def test_reconciliation_static_allowlist(app_server):
    for path in ['/workspace/reconciliation-adapter.js', '/workspace/']:
        status, headers, _ = request_report(app_server, b'', method='GET', path=path)
        assert status == 200
        assert "connect-src 'self'" in headers['content-security-policy']
        assert headers['cache-control'] == 'no-store'
    for path in ['/workspace/fixtures/profile-reconciliation-synthetic.json',
                 '/workspace/fixtures/profile-reconciliation-source.json',
                 '/src/joblens_public/reconcile/engine.py',
                 '/workspace/../src/joblens_public/reconcile/engine.py']:
        assert request_report(app_server, b'', method='GET', path=path)[0] == 404


def test_a_project_contribution_keeps_its_text_and_its_technologies():
    """A contribution is a claim in its own right, not a bare project name."""
    report = reconcile_documents({
        'schema_version': '1.1',
        'documents': [{
            'document_id': 'doc_0', 'index': 0, 'filename': 'synthetic.pdf',
            'status': 'extracted', 'format': 'pdf',
            'segments': [{
                'text': 'Projects\nLedger - Automated the release pipeline using Docker\n',
                'locator': {'kind': 'page', 'page': 1},
            }],
        }],
    })
    contributions = [claim for claim in report.claims
                     if claim.category.value == 'contribution']
    assert len(contributions) == 1
    contribution = contributions[0]
    assert contribution.subject == 'ledger'
    assert contribution.attribute('text') == 'automated the release pipeline using docker'
    assert contribution.attribute_value('text') == 'Automated the release pipeline using Docker'
    assert contribution.attribute('technologies') == 'docker'
    assert contribution.attribute('quantities') is None
    assert contribution.qualifier == 'explicit_claim'


def two_document_body(left, right):
    return json.dumps({'job_id': 'job_synthetic', 'documents': [
        {'document_id': 'doc_0', 'index': 0, 'filename': 'left.pdf', 'status': 'extracted',
         'format': 'pdf',
         'segments': [{'text': left, 'locator': {'kind': 'page', 'page': 1}}]},
        {'document_id': 'doc_1', 'index': 1, 'filename': 'right.pdf', 'status': 'extracted',
         'format': 'pdf',
         'segments': [{'text': right, 'locator': {'kind': 'page', 'page': 1}}]},
    ]}).encode()


def test_the_served_report_carries_the_additive_fields(app_server):
    """The wire format names alternatives, qualifiers and the approval state."""
    status, _, raw = request_report(app_server, two_document_body(
        'Languages\nEnglish (C1)', 'Languages\nEnglish (B2)'))
    assert status == 200
    report = json.loads(raw)
    recommendations = [decision for decision in report['decisions']
                       if decision['outcome'] == 'recommend']
    assert recommendations
    for decision in recommendations:
        assert decision['alternative_claim_ids'], 'a recommendation keeps its alternatives'
        assert decision['merge_claim_ids'] == [], 'only auto_consolidate merges claims'
        assert decision['approval_state'] == 'not_approved'
    for consolidated in report['consolidated']:
        assert consolidated['approval_state'] == 'not_approved'
        assert consolidated['qualifiers']
    for claim in report['claims']:
        assert claim['qualifier'] in {'explicit_claim', 'keyword_mention'}
    assert all(decision['approval_state'] == 'not_approved'
               for decision in report['decisions'])
