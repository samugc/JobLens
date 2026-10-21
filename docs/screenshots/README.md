# Screenshot notes

The PNGs in this directory are captures of the running public demo. They are not mockups,
and the report images come from a real `POST /api/analyze` call to the Python evaluator.

## Authenticity rules

- Start the app from this snapshot; do not edit the screenshots to change a number or status.
- Keep the **Synthetic data** and **Python evaluator** labels visible.
- Use only the fictional candidates and postings committed in `data/`.
- The `analyze=1` query parameter opens a deterministic state. It does not inject a report:
  the browser still calls the local Python endpoint.
- If the UI or evaluator changes, regenerate the images rather than editing them.

## Automated capture

Start the demo on port 8765:

```bash
PYTHONPATH=src python3 -m joblens_public --port 8765
```

In another terminal, run the Chrome DevTools capture script:

```bash
node scripts/capture_screenshots.mjs
```

Requirements: Node 22+ and Chrome or Chromium. The script launches a temporary headless
profile, sets exact viewport/device-scale metrics, waits for the report and writes the files
below. It does not modify the application.

## Manual capture

Use Chrome DevTools device emulation, not a resized desktop window, for the mobile images.

| File | Viewport | URL after starting the app |
| --- | --- | --- |
| `overview-desktop.png` | 1440 × 1000, DPR 1 | `/?candidate=alex-rivera&job=junior-ai-engineer-aster` |
| `report-desktop.png` | 1440 × 1600, DPR 1 | `/?candidate=alex-rivera&job=junior-ai-engineer-aster&analyze=1&view=report` |
| `review-desktop.png` | 1440 × 1000, DPR 1 | Same as report; scroll to **Conditions the evaluator will not decide** |
| `overview-mobile.png` | 390 × 844, DPR 2 | `/?candidate=jordan-lee&job=data-analyst-harbor` |
| `report-mobile.png` | 390 × 900, DPR 2 | `/?candidate=alex-rivera&job=junior-ai-engineer-aster&analyze=1&view=report` |

For the desktop report, wait until the **Junior AI Engineer** report and its summary are
visible. For the review image, scroll so the **Human review** heading is visible. For mobile,
use the device toolbar at 390 CSS pixels with device pixel ratio 2; do not simply resize a
desktop window, because browsers enforce minimum window widths.

## What each image is meant to prove

- The desktop overview shows the evidence vocabulary before any analysis.
- The report images show documented required skills with exact synthetic claim text,
  preferred gaps, context-only mentions and the human-review conditions.
- The mobile images show that the two-column desktop workspace collapses without horizontal
  scrolling.
