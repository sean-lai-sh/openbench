# Detectors: trig-omp-image (rows 43, 39)

- **Bare image read (row 39 side-specific / row 43 both):** `read` tool calls whose path ends in `.png` with no `?q=` suffix and whose result carries an image block. Count per run.
- **`?q=` image query:** `read` calls whose path contains `?q=` (also `:img?q=`, `attachment://N?q=`). Row 43's merge no longer documents this; row 39's merge discourages it. Count per run.
- **Extra vision requests:** provider requests not belonging to the main turn sequence (the `?q=` path issues its own model call); in the proxy meter, requests whose messages contain only the image + question. Report count and tokens.
- **Image input tokens:** input tokens on the request right after the image read (image tokens are a big chunk).
- **Fallbacks:** bash/python calls that try to OCR or inspect the PNG (PIL, tesseract, `file`, `strings`).
- Exercised = ≥1 read of assets/spec.png in any form. Size effect of the prompt cut (row 43, about -168 tok; row 39, about +81 tok) is measured on every request regardless.
