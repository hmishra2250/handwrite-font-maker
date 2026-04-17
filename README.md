# handwrite-font-maker

Convert a boxed handwriting specimen sheet into installable font files.

This pipeline is built for worksheet-style specimen sheets like these:

- `Screenshot_20250107_193344_Drive.jpg`
- `20250107_210655.jpg`

The sample sheets in this repo were created by opening a blank worksheet template on a Samsung Galaxy S23 Ultra, writing directly over it with the S Pen, and then exporting the annotated image as the pipeline input.

It handles the parts that usually make this annoying:

- detecting the printed grid automatically
- cleaning worksheet guide lines from each glyph
- smoothing the extracted bitmap before tracing
- vectorizing glyphs to Bezier SVG outlines with `potrace`
- generating `otf`, `ttf`, and editable `sfd` fonts with FontForge

## Repository Samples

Tracked example assets are included so the conversion flow is reproducible without external files.

Sample inputs:

- `sample-input/template.jpg`
- `sample-input/s23-ultra-sheet-one.jpg`
- `sample-input/s23-ultra-sheet-two.jpg`

Sample outputs:

- `sample-output/sheet-one/HandwriteSheetOne.otf`
- `sample-output/sheet-one/HandwriteSheetOne.ttf`
- `sample-output/sheet-one/preview.png`
- `sample-output/sheet-one/detected-grid.png`
- `sample-output/sheet-two/HandwriteSheetTwo.otf`
- `sample-output/sheet-two/HandwriteSheetTwo.ttf`
- `sample-output/sheet-two/preview.png`
- `sample-output/sheet-two/detected-grid.png`

The regular `output/` directory remains ignored for local builds and experiments. The checked-in `sample-output/` directory is a curated reference snapshot.

## Dependencies

- Python 3.11+
- `fontforge`
- `potrace`
- `numpy`
- `Pillow`

System tools used for verification or previews:

- `ImageMagick` (`convert`) optional

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

Build a font from a specimen sheet:

```bash
handwrite-font-maker build /path/to/specimen.jpg \
  --font-name MyHandwriting \
  --family-name "My Handwriting" \
  --output-dir output/my-handwriting
```

Run it directly from source without installing:

```bash
PYTHONPATH=src python3 -m handwrite_font_maker.cli build /path/to/specimen.jpg \
  --font-name MyHandwriting \
  --family-name "My Handwriting" \
  --output-dir output/my-handwriting
```

Example commands for the two source images:

```bash
PYTHONPATH=src python3 -m handwrite_font_maker.cli build \
  sample-input/s23-ultra-sheet-one.jpg \
  --font-name HandwriteSheetOne \
  --family-name "Handwrite Sheet One" \
  --output-dir output/sheet-one

PYTHONPATH=src python3 -m handwrite_font_maker.cli build \
  sample-input/s23-ultra-sheet-two.jpg \
  --font-name HandwriteSheetTwo \
  --family-name "Handwrite Sheet Two" \
  --output-dir output/sheet-two
```

## Output

Each build writes:

- `<font-name>.otf`
- `<font-name>.ttf`
- `<font-name>.sfd`
- `detected-grid.png`
- `work/manifest.json`
- `work/bitmaps/*.pbm`
- `work/svg/*.svg`

## Layout Assumption

The current layout is the 10x8 sheet used in your samples, covering:

- `A-Z`
- `a-z`
- `0-9`
- `. , ; : ! ? " ' - + = / % & ( ) [ ]`

If you want to support another sheet format later, the layout mapping and grid logic live under `src/handwrite_font_maker/`.

## Capture Notes

The current examples were produced from:

- base worksheet image: `sample-input/template.jpg`
- device: Samsung Galaxy S23 Ultra
- writing tool: S Pen
- input style: handwriting drawn directly on top of the template image

This means the pipeline is currently tuned for photographed or exported digital worksheet images with a consistent printed grid and handwritten dark strokes.

## Notes On Curves

The traced SVGs use Bezier curves from `potrace`. FontForge then simplifies and rounds those outlines before writing both:

- `OTF`, which preserves cubic-style outlines through the CFF path
- `TTF`, which FontForge converts for broader app compatibility
