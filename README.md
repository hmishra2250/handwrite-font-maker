# handwrite-font-maker

Convert a handwriting specimen sheet into installable font files (OTF/TTF).

1. Print the template, write one character per cell with a dark pen.
2. Photograph the page with your phone.
3. Upload the photo and download your font.

## Repository structure

```
templates/v1/              Printable template (PDF, PNG, B&W reference)
samples/
  input/                   Filled template photos for testing
  output/v1-synthetic/     Example generated font
src/handwrite_font_maker/  Core Python library
  web/                     HTTP API server (job processing)
web/                       Next.js frontend
tests/                     Python test suite
scripts/                   Utility scripts (FontForge, Gemini)
supabase/migrations/       Database schema
```

## How it works

The template has four ArUco corner markers (DICT_4X4_50). The pipeline:

1. Detects markers and computes a homography to rectify the photo
2. Extracts each cell using the grid geometry
3. Cleans guide lines, thresholds to binary, vectorizes with potrace
4. Generates OTF/TTF/SFD fonts with FontForge

Detection is robust to: perspective warp, B&W printing, mobile camera noise,
uneven lighting, JPEG compression (quality 30), and partial shadow.

## Dependencies

Python 3.11+, `numpy`, `Pillow`, `opencv-python-headless`, `reportlab`.
System: `potrace`, `fontforge`.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[test]'
```

## Usage

### Generate the template

```bash
handwrite-font-maker generate-template --output templates/v1/template.pdf
```

Print the PDF at **100% scale** (no fit-to-page). Keep all four corner markers visible.

### Build a font

```bash
handwrite-font-maker build photo.jpg \
  --font-name MyHandwriting \
  --family-name "My Handwriting" \
  --output-dir output/my-handwriting
```

### Local development (Docker Compose)

```bash
docker compose up -d          # postgres + python api + next.js
open http://localhost:3000     # web UI
```

Or run services individually:

```bash
# Terminal 1: Python API
DATABASE_URL=postgresql://handwrite:handwrite@localhost:5433/handwrite_fonts \
LOCAL_OBJECT_ROOT=/tmp/objects PROCESS_JOBS_INLINE=1 \
.venv/bin/python -m handwrite_font_maker.web.server

# Terminal 2: Next.js
cd web && npm run dev -- -p 3001
```

## Testing

```bash
.venv/bin/pytest -q           # Python tests (31 tests)
cd web && npm test            # Frontend tests
```

## Output

Each build produces: `<name>.otf`, `<name>.ttf`, `<name>.sfd`,
`rectified-template.png` (debug overlay), and `work/manifest.json`.

## Deployment

- **Vercel**: `web/` Next.js frontend
- **Render**: Python API from `Dockerfile.api`
- **Supabase**: Postgres + Storage (or use local Postgres + file storage)
