# Two-minute demo (actual pipeline)

This demo uses two fictional CVs and a fictional posting. It runs the real local
HTTP pipeline: upload → extraction → grounded draft → human confirmation → PDF
and DOCX export. Nothing below is a pre-recorded output.

## Before the clock starts

From the source checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/make_synthetic_cvs.py
```

Start the app:

```bash
python run_demo.py --port 8767
```

`run_demo.py` opens `http://127.0.0.1:8767/`. If the browser does not open,
navigate there manually. Keep the terminal visible for the "Stop with Ctrl+C"
line, but do not show request logs; the app intentionally does not log CV text.

## 0:00–0:20 — Show the local boundary

Say: “The app binds to loopback, processes the documents in memory, and makes
no external data requests. This is a synthetic demo; no real CV is used.”

Point at the page footer or `http://127.0.0.1:8767/api/status` if useful.

## 0:20–0:45 — Upload two fictional CVs

Upload:

- `.integration-verification/demo-input/alex-rivera-cv.pdf`
- `.integration-verification/demo-input/alex-rivera-notes.docx`

Wait for “Documents read.” The two files deliberately overlap and disagree:
one says English C1, the other B2; both mention Project Boreal, but their Atlas
details conflict.

## 0:45–1:05 — Paste the posting and generate

Open `.integration-verification/demo-input/job-posting.txt`, copy the text, and
paste it into the posting box. Select **Generate my CV**.

## 1:05–1:30 — Explain one grounded inclusion

Point at an experience or summary line that contains **Python**, **REST APIs**
or **automated tests**. Say:

> “This line is here because the source CV contains that exact claim. The
> evidence panel keeps the source quotation and location, so this is not a
> model invention.”

Open **Why this content?** and point at the matching included decision, its
source document and job requirement. If the UI shows **View original wording**,
open it briefly and close it.

## 1:30–1:45 — Explain one unsupported requirement

Point at the unmet-requirements area. Say:

> “Kubernetes is requested by the posting but is not supported by either CV.
> JobLens reports it as a gap and does not add it to the candidate’s skills.”

Do not claim that every possible unsupported claim is caught; this is a
bounded, rule-based check.

## 1:45–2:00 — Review and export real files

The supported full name is prefilled from the CVs; add a fictional e-mail
(for example, `alex@example.com`) if you want to export. Edit one wording
detail if you want to show that the confirmation is invalidated, then confirm
the exact final content and select **Download PDF** and **Download DOCX**.

Open both files. Say:

> “Both files come from the same reviewed draft. The PDF is rendered by
> ReportLab and the DOCX by python-docx; the content is the reviewed content,
> not a static asset.”

Stop the server with `Ctrl+C`.

## Reset

The demo inputs are written under `.integration-verification/demo-input/`,
which is git-ignored. Delete that directory if you want a clean demo. Do not
delete the owner’s other files.
