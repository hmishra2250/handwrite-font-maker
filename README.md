# handwrite-font-maker

Convert a boxed handwriting specimen sheet into installable font files.

This pipeline is built for worksheet-style specimen sheets like these:

- `Screenshot_20250107_193344_Drive.jpg`
- `20250107_210655.jpg`

It handles the parts that usually make this annoying:

- detecting the printed grid automatically
- cleaning worksheet guide lines from each glyph
- smoothing the extracted bitmap before tracing
- vectorizing glyphs to Bezier SVG outlines with `potrace`
- generating `otf`, `ttf`, and editable `sfd` fonts with FontForge

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
  /home/himadri/Downloads/Screenshot_20250107_193344_Drive.jpg \
  --font-name HandwriteSheetOne \
  --family-name "Handwrite Sheet One" \
  --output-dir output/sheet-one

PYTHONPATH=src python3 -m handwrite_font_maker.cli build \
  /home/himadri/Downloads/20250107_210655.jpg \
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

## Notes On Curves

The traced SVGs use Bezier curves from `potrace`. FontForge then simplifies and rounds those outlines before writing both:

- `OTF`, which preserves cubic-style outlines through the CFF path
- `TTF`, which FontForge converts for broader app compatibility
