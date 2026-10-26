# Synthetic release evaluation

This directory is a small, reproducible QA suite for JobLens 1.0. It runs the
real local HTTP server and the real PDF/DOCX pipeline. It does not call a model,
does not use a real CV, and does not reuse a static generated document.

## Run it

From the source checkout, with the development dependencies installed:

```bash
python -m evaluation.run_evaluation --output evaluation/results.json
```

The command prints a summary and writes machine-readable results to
`evaluation/results.json`. Exit status is non-zero if any scenario fails a hard
check. That generated file is local output; it is explicitly excluded from the
public source distribution.

The suite uses the synthetic builders in `tests/` and the same local server as
the application. Keep the source tree; a wheel does not contain `web/` or
`data/`.

## What is covered

There are 20 scenarios. Each one builds fictional PDF/DOCX bytes at run time,
uploads them over HTTP, posts a fictional job description, drafts, confirms and
exports. The sparse-document scenario expects a fail-closed rejection instead of
an invented draft.

| Area | Scenario IDs |
| --- | --- |
| Overlapping CVs | `overlap_alex` |
| Complementary experience | `complementary_experiences` |
| Conflicting qualifications | `conflicting_qualifications` |
| Missing contacts | `missing_contacts` |
| Conflicting contacts | `conflicting_contacts` |
| Repeated projects | `repeated_projects` |
| Different postings | `job_python`, `job_javascript` |
| Unsupported technologies | `unsupported_technologies` |
| Malicious posting text | `malicious_posting` |
| Sparse document | `sparse_document` |
| Multi-page / detailed | `detailed_multipage` |
| Long export content | `long_export_content` |
| Unicode content | `unicode_content` |
| Missing optional sections | `missing_optional_sections` |
| Edited and reconfirmed | `edited_reconfirmed` |
| Review enforcement | `edited_without_reconfirm`, `unconfirmed_export`, `forged_approval`, `stale_session` |

## Hard checks versus metrics

Hard checks are assertions: expected source-backed text appears in both
exports, forbidden/conflicting/unsupported text does not, exports succeed where
expected, and invalid review receipts are rejected. A failed hard check fails
the run.

The JSON report also contains quantitative metrics. They describe only these
synthetic scenarios:

- **Supported fact preservation** — expected source-backed strings present in
  both PDF and DOCX.
- **Unsupported/forbidden insertion** — expected absent strings or patterns
  present in either export.
- **Conflict omission** — disputed terms absent from both exports.
- **Supported requirement recall** — scenario-labelled requirements present in
  the export.
- **Unsupported requirement leakage** — scenario-labelled absent requirements
  present in the export.
- **PDF/DOCX parity** — token Jaccard similarity between extracted PDF and DOCX
  text.
- **Review enforcement** — invalid export attempts rejected.
- **Unmet-requirement contradiction** — a reported gap whose text already
  appears in the generated CV. This is a soft quality metric, not an
  export-safety check.

These are not a global hallucination rate, not an ATS score, and not a
benchmark against other tools. They are regression evidence for this fixture
set.

## Reporting

`results.json` contains the scenario-level checks, the aggregate metrics, and
any hard failures. Do not edit the JSON by hand. Re-run the command instead.

These fixtures are regression evidence for this synthetic set, not a public
benchmark or a claim about real-world CV quality.
