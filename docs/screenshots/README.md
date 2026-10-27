# Product screenshots

`product-upload.png` and `product-review.png` show the current local application:
the upload step and an editable review draft. Both were captured at 1440×1000
from the real backend using only the bundled fictional Alex Rivera documents and
the fictional sample posting. Extraction and drafting are real; nothing is
mocked. The review image shows an editable draft, not an exported PDF. No Safari
testing is implied.

Other images in this directory are historical `/demo/` captures and are not used
to represent the current main workflow.

## Regenerate

Start the app first, for example:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m joblens_public --port 8765
```

Then capture both images with headless Chrome:

```bash
JOBLENS_URL=http://127.0.0.1:8765/ node scripts/capture_screenshots.mjs
```

The script writes both PNGs into this directory. Set `CHROME_PATH` if Chrome or
Chromium is installed outside the default locations. A local capture failure is
usually a missing browser or a port mismatch; confirm `JOBLENS_URL` matches the
running server and retry with a current Chrome build.
