# Product screenshots

The script targets `product-upload.png` and `product-review.png` for the current local application.
These captures are not included yet: Chrome did not expose its debugging endpoint
in the preparation environment. No outdated screenshot is used in the main README.
Capture with the server running: `JOBLENS_URL=http://127.0.0.1:8767/ node scripts/capture_screenshots.mjs`.
The script uses headless Chrome and only bundled fictional Alex Rivera documents
and the fictional sample posting; extraction and drafting use the real backend.
The review image shows an editable draft, not an exported PDF.
Other images in this directory are historical `/demo/` screenshots and are not
used to represent the current main workflow. No Safari testing is implied.
