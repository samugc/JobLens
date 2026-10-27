# JobLens 1.0 release checklist

Use this checklist from a clean source checkout. Do not copy private CVs,
generated exports, `.env` files or `.integration-verification/` into the
release tree.

## 1. Source tree and license

- [ ] `LICENSE` is the intended MIT license for the owner.
- [ ] `README.md` describes the source-checkout installation, not a wheel.
- [ ] `pyproject.toml` declares Python `>=3.11` and the runtime dependencies.
- [ ] No fabricated endorsements, user counts, ATS guarantees or benchmark
      claims appear in README, docs or screenshots.
- [ ] `docs/screenshots/` distinguishes the two current-product captures from
      the historical `/demo/` images.

## 2. Clean environment

- [ ] Create a fresh virtual environment with Python 3.11+ and run the suite.
      CI currently exercises Python 3.11 and 3.13; 3.12 is not tested by CI but
      is not declared incompatible.
- [ ] Run `python -m pip install -e '.[dev]'`.
- [ ] Run `python -m ruff check .`.
- [ ] Run `python -m pytest -q -p no:cacheprovider`.
- [ ] Run `node --test tests/ui/*.test.mjs`.
- [ ] Run `python -m pytest tests/test_integrated_release.py -q -p no:cacheprovider`.
- [ ] Run `python -m pip_audit` after upgrading `setuptools` if the environment
      ships an affected build tool.
- [ ] Start `python run_demo.py --port 8767` and verify `/api/status` and `/`.
- [ ] Run `python -m evaluation.run_evaluation --output evaluation/results.json`.

## 3. Main-flow smoke test

- [ ] Generate the fictional demo files with
      `python scripts/make_synthetic_cvs.py`.
- [ ] Upload both fictional files through the browser.
- [ ] Paste the fictional posting and generate.
- [ ] Confirm that supported facts appear and that a requested but unsupported
      skill (Kubernetes) is reported as a gap, not added to the CV.
- [ ] Confirm that supported name, e-mail and location values are prefilled,
      that GitHub/LinkedIn/portfolio values appear when unique, and that a
      conflicting contact field stays empty with its alternatives shown.
- [ ] Open **Why this content?** and confirm that counts, explanations,
      alternatives and source documents come from the backend decision report.
- [ ] Edit an item, confirm the exact final content, and export both formats.
- [ ] Open the PDF and DOCX and inspect selectable text, page count and contact
      details.
- [ ] Attempt an export after editing without re-confirming; it must be
      rejected.
- [ ] Change a contact after confirmation; it must invalidate the export until
      reconfirmed.
- [ ] Restart the server and attempt to reuse an old receipt; it must be
      rejected.
- [ ] Start over or regenerate while a confirmation/export is in flight; the
      stale response must not restore confirmation or start an old download.

## 4. Privacy and security

- [ ] The public source contains exactly two approved synthetic documents:
      `web/samples/alex-rivera-cv.pdf` and
      `web/samples/alex-rivera-cv-2.docx`. No other PDF/DOCX is publishable.
      Ignored verification output must remain outside the publication inventory.
- [ ] No `.env`, `private/`, `uploads/`, `profiles/`, `exports/`, private keys
      or personal profile JSON are tracked.
- [ ] `.gitignore` still covers generated documents, profiles, `.env`,
      verification scratch and virtual environments.
- [ ] Request bodies and CV text are not logged.
- [ ] The app binds to loopback and rejects non-loopback Host, cross-origin and
      missing request-marker requests.
- [ ] Upload limits and timeouts are tested: 5 documents, 10 MiB per file,
      25 MiB batch, 200k text characters, 100 PDF pages, 20k DOCX paragraphs.
- [ ] No cloud model or analytics request is made by the main flow. The
      optional library-level Ollama adapter is not enabled by the web app.
- [ ] Job-posting text cannot add candidate facts; the malicious-posting
      scenario passes.

## 5. Archive

- [ ] Build a source archive and wheel only from a clean tree:
      `python -m build --sdist --wheel --outdir dist`.
- [ ] The source archive includes `web/`, `data/`, `docs/`, `tests/`,
      `evaluation/` and `scripts/`, plus exactly the two reviewed demo assets
      `web/samples/alex-rivera-cv.pdf` and `web/samples/alex-rivera-cv-2.docx`.
      It excludes generated `evaluation/results.json`, every other PDF/DOCX,
      `.env`, virtual environments, caches and `.integration-verification/`.
- [ ] The wheel is not advertised as a supported installation. It does not
      include `web/` or `data/`.
- [ ] Inspect `tar -tzf` and `unzip -l`; no personal filenames, paths or CV
      content are present, and the only document files are the two reviewed
      sample assets above.
- [ ] Calculate and record SHA-256 checksums for the published artifacts.

## 6. Publication gate

- [ ] Owner approves publication.
- [ ] CI is green on the supported Python versions.
- [ ] The release report records GO/NO-GO and any accepted limitations.
- [ ] Do not publish if a P0 safety or privacy issue is open.
- [ ] Do not claim zero hallucinations, hiring outcomes or ATS performance.

## Rollback

If a published archive contains private data, remove the artifact immediately,
rotate any exposed credentials, and publish a corrected archive with a new
version. Do not rewrite a public history silently.
