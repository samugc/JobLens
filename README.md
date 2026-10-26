# JobLens — Turn multiple CVs into one truthful resume tailored to a specific job

Upload your existing PDF/DOCX CVs, paste a job posting, review a tailored draft,
and download a real PDF or DOCX. Everything runs locally. No account, cloud model,
LinkedIn connection or Ollama installation is required. Contact details found in
your CVs are prefilled as editable provisional values, and “Why this content?”
explains the actual inclusion, omission and conflict decisions.

## Start locally

Python **3.11+** and a source checkout are required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m joblens_public --port 8767
```

Open **http://127.0.0.1:8767/**. On Windows, activate `.venv\Scripts\activate`
and use `python run_demo.py --port 8767` instead of the environment-variable command.
Stop the server with Ctrl+C. The app binds to loopback only; do not deploy this local
application behind a public proxy.

The source launcher `python3 run_demo.py --port 8767` is also supported after installing
the dependencies. A wheel is **not a supported installation method**: it
**does not include all runtime resources** (`web/` and `data/`). Keep the source tree.
Runtime dependencies are pypdf, ReportLab and python-docx; pytest and Ruff are development tools.

## Use it

1. Upload **1–5 PDF/DOCX CVs**. Reading starts automatically.
2. Paste the full posting from LinkedIn, Indeed or any careers page.
3. Select **Generate my CV**.
4. Review the prefilled contact details, edit the wording, remove unwanted entries or reorder sections.
5. Confirm the exact final content, then select **Download PDF** or **Download DOCX**.

Supported contact values are filled into editable fields but remain provisional until you
confirm the exact CV. Conflicting values are never chosen automatically: the field stays
empty, shows the alternatives and their source quotations, and asks you to enter the right
value. Missing details also stay empty. The full name is required before confirmation.

Contradictory or uncertain details are omitted with a notice. Missing job requirements
appear outside the CV. They never become candidate skills. Original quotations remain
available through “View original wording.” The optional advanced evidence tools at
`/workspace/` retain the detailed profile and consistency review, including explicit
private profile save/import. They are not required for the main journey.

## What makes it different

- **Evidence provenance:** source document, paragraph/page, exact quotation and Unicode offsets.
- **Conservative consolidation:** compatible proposals merge; disputed details are omitted from automatic drafting.
- **Provisional first:** extraction and reconciliation do not create approvals. A deterministic generator ranks source-backed information against the pasted posting.
- **Provisional contact prefill:** supported name, e-mail, phone, location, GitHub, LinkedIn and portfolio values are applied to editable fields. Conflicts are never selected, missing values stay empty, and final confirmation covers the contact details.
- **Explainable decisions:** “Why this content?” reports real backend counts, includes, omissions, conflicts, alternatives, source documents and unmet job requirements. It uses no invented percentages.
- **Human confirmation:** a process-local signature binds confirmation to the exact CV, including contact details and section order. Editing invalidates it.
- **Stale-response safety:** editing, reordering, removing an item, generating again or selecting **Start over** makes any in-flight confirmation or download response obsolete, so an old reply cannot restore confirmation or trigger an old file.
- **Honest edits:** changed wording requires explicit candidate attestation. It is not relabelled as verified documentary evidence.
- **Real exports:** one single-column, A4-friendly template, rendered with ReportLab and python-docx. Text is selectable; internal IDs and review warnings are excluded.

No model is used by the web flow. An optional local Ollama rewriting adapter exists in
the Python library, but is not enabled by the main application and is not required.
Deterministic drafting and local LLM rewriting are separate capabilities.

## Privacy and security

Documents and decisions are processed in memory. No request bodies or CV text are logged.
The application makes no external data requests. Static files use an explicit allowlist;
source files, fixtures and private profiles cannot be fetched through application routes.
Requests enforce loopback Host, same Origin, a request marker and size/time limits.
PDF/DOCX downloads use fixed safe filenames and `Cache-Control: no-store`.

Save personal files **outside this repository**. Downloaded files and advanced exported
profiles are private, unencrypted files under your control; a portable profile includes
source text. Reloading clears browser state. Restarting the server invalidates review
receipts; regenerate, or reimport and explicitly revalidate an advanced profile.

A valid source quote proves provenance, not real-world truth. JobLens does not verify
credentials or employment. Candidate attestation remains the candidate's responsibility.

## Architecture

```text
Browser → local HTTP → PDF/DOCX extraction → proposals + deterministic reconciliation
                     → provisional job-tailored draft → exact-content confirmation
                     → validated in-memory PDF/DOCX rendering
```

See [the HTTP and review contract](docs/release-architecture.md). The earlier synthetic
job-analysis demo remains available at `/demo/`, and its API endpoints remain supported.
Existing screenshots in `docs/screenshots/` depict that historical demo, not the new main UI.

## Tests and synthetic demonstration

The only publishable PDF/DOCX samples are `web/samples/alex-rivera-cv.pdf`
and `web/samples/alex-rivera-cv-2.docx`. Both contain fictional Alex Rivera
data and power **Try a sample** through the real backend. Other CVs, profiles
and generated exports must stay outside the public source release.


```bash
python -m pytest -q -p no:cacheprovider
node --test tests/ui/*.test.mjs
python -m pytest tests/test_simple_flow.py -q -p no:cacheprovider
PYTHONPATH=src python3 -m evaluation.run_evaluation --output evaluation/results.json
ruff check .
```

`tests/test_integrated_release.py` runs two fictional CVs through the real local HTTP
pipeline with all seven contact fields, a conflicting-contact case and an unsupported
Kubernetes requirement. It confirms the exact draft, inspects the actual PDF and DOCX
content and hyperlinks, and verifies that editing a contact invalidates the export.
`tests/test_simple_flow.py` starts the real server and runs the main-page controller
against a DOM test double, including stale confirmation replies after an edit and after
**Start over**. These are automated tests, not manual browser tests.

The synthetic evaluation covers 20 scenarios, including PDF/DOCX token parity, conflict
omission, review enforcement and unsupported-requirement leakage. Metrics describe this
fixture set only; they are not a hallucination rate or an ATS benchmark. Output is written
only to ignored `.integration-verification/` and `evaluation/results.json`. No real
personal documents are included. Node is needed for integration tests, not to run the app.

## Limitations

- Text-based PDF and DOCX only; no OCR. Complex columns, tables and unusual layouts need careful review.
- Extraction uses a bounded English vocabulary and may omit information. No automatic translation.
- No scraping, LinkedIn account connection, cloud hosting, database or background persistence.
- Conservative omission may discard useful ambiguous information. Check the sources before adding it yourself.
- One export template is provided. No fidelity to an unavailable LaTeX reference is claimed.
- Contact prefill is a suggestion layer over bounded extraction. It is not identity verification; review every field. A field with conflicting or multiple values stays empty for you to resolve.
- Decision explanations are plain-English renderings of deterministic generation rules. They are not model reasoning, confidence estimates or proof that a claim is true.
- The preview is an editable content view, not a pixel-identical pagination simulator for Word/PDF.
- Signatures validate the current local process and exact reviewed content, not the identity of the human making a declaration.
- A wheel is **not a supported installation method**. The built wheel **does not include all runtime resources** (`web/` and `data/`) and the launcher fails with `No candidate banks found`; use the source checkout and `python3 run_demo.py`.
- Safari upload/download acceptance remains a manual release check.

## License

MIT; see [LICENSE](LICENSE). Owner approval is required before publication. This checkout
is a release candidate, not a published package. Third-party dependencies retain their own licenses.

### Fact-preservation demonstration

`tests/fact_preservation_fixtures.py` contains two small fictional Alex Rivera CVs
and a separate richer Morgan Example case. These are equivalent textual fixtures
for the reported manual scenario, not byte-identical copies of the original PDFs.

Run `python -m pytest tests/test_fact_preservation.py -q -p no:cacheprovider`.
The real HTTP pipeline creates PDF/DOCX inputs and outputs under ignored
`.integration-verification/fact-preservation/`, together with a source/selection/
export trace. The small case retains Python, education and separate supported
Software Engineer contributions while omitting disputed English levels and Atlas
content. The richer case exercises employer, dates, project details and metrics.
AWS certification alone is not treated as a practical AWS skill.
