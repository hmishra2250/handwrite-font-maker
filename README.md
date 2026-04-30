# handwrite-font-maker

Convert a marker-based handwriting specimen sheet into installable font files.

The V1 flow is now built around a print-and-photo template:

1. Generate a print-ready PDF template.
2. Print it at 100% scale, write one character per cell, and photograph the page with a phone.
3. Build a font from the photo.

The template has four ArUco corner markers and one QR metadata block. The build pipeline uses those markers to rectify the phone photo before extracting cells, instead of relying on brittle grid-line counting.

## What it handles

- ArUco marker detection at all four page corners
- perspective correction / homography for phone photos
- QR metadata decoding for layout version + character map
- data-defined layout instead of hard-coded grid order
- guide-line-aware glyph cleanup
- soft glyph quality warnings without blocking structurally valid builds
- vectorizing glyphs to Bezier SVG outlines with `potrace`
- generating `otf`, `ttf`, and editable `sfd` fonts with FontForge
- validating generated OTF/TTF files by reopening them with FontForge

## Repository Samples

Tracked V1 sample assets are marker-template based:

- `sample-output/template-v1/template-v1.pdf` — print-ready blank template
- `sample-output/template-v1/template-v1-preview.png` — preview of the designed template
- `sample-input/template-v1-synthetic-filled.png` — synthetic filled template for smoke tests and demos

The old pre-marker grid worksheet samples were removed because the current V1 pipeline intentionally requires ArUco markers and QR metadata.

## Dependencies

Python:

- Python 3.11+
- `numpy`
- `Pillow`
- `opencv-python-headless`
- `reportlab`
- `qrcode[pil]`

System tools:

- `potrace`
- `fontforge`

Optional verification/preview tooling:

- ImageMagick (`convert`)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
```

## Usage

### 1. Generate the printable template

```bash
handwrite-font-maker generate-template \
  --output output/template-v1.pdf \
  --paper-size A4 \
  --layout default-v1
```

Print the PDF at **100% scale**. Disable “fit to page” / “shrink to printable area”. All four corner markers and the QR block must remain visible in the phone photo.

### 2. Build a font from a phone photo

```bash
handwrite-font-maker build /path/to/filled-template-photo.jpg \
  --font-name MyHandwriting \
  --family-name "My Handwriting" \
  --output-dir output/my-handwriting
```

Run directly from source without installing:

```bash
PYTHONPATH=src python3 -m handwrite_font_maker.cli generate-template \
  --output output/template-v1.pdf

PYTHONPATH=src python3 -m handwrite_font_maker.cli build /path/to/filled-template-photo.jpg \
  --font-name MyHandwriting \
  --family-name "My Handwriting" \
  --output-dir output/my-handwriting
```

## Output

Each successful build writes:

- `<font-name>.otf`
- `<font-name>.ttf`
- `<font-name>.sfd`
- `rectified-template.png` — debug overlay on the rectified page
- `work/manifest.json`
- `work/bitmaps/*.pbm`
- `work/svg/*.svg` for non-empty glyphs

The JSON printed by the CLI includes output paths and any soft warnings.

## Hard failures

The build fails with a clear error when structural correctness is not proven:

- any required ArUco corner marker is missing
- QR metadata cannot be decoded or is not recognized
- homography reprojection error is too high (`>= 5px`)
- extracted cell count does not match the QR character map
- generated OTF or TTF cannot be reopened by FontForge

## Soft warnings

The build continues, but reports warnings, when glyph ink coverage looks suspicious:

- `< 1.5%` dark-pixel coverage: likely empty glyph
- `> 60%` dark-pixel coverage: likely smudge or guide-line bleed
- more than 5 likely-empty glyphs: summary re-shoot suggestion

This is intentional: tiny punctuation can be valid, so subjective glyph quality does not block an otherwise structurally valid font.

## Layout

The default V1 layout is data-defined in `src/handwrite_font_maker/layout.py` and covers printable non-space ASCII characters:

- `A-Z`
- `a-z`
- `0-9`
- punctuation including `{ } @ # $ ~ ^ _` and backtick

Space is synthesized separately by the font builder.

## Testing

Run the full test suite:

```bash
.venv/bin/pytest -q
```

The test suite generates synthetic marker templates, fills glyph cells, applies perspective/noise/brightness/rotation/missing-marker fixtures, and runs a full synthetic font build when `potrace` and `fontforge` are available.

## V2 runway

Object-character fonts are intentionally out of V1 implementation scope. The intended V2 seam is a new ingestion path that produces one grayscale crop per character from rough-cropped object photos, then feeds the same bitmap → potrace → FontForge pipeline. Candidate segmentation approaches include GrabCut first and SAM-style segmentation later if quality requires it.
