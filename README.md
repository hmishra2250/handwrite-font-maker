# Handwrite Font Maker

Turn handwriting or user-selected handmade shapes into actual TTF/OTF fonts.
**Current release: local/private alpha, not a production-ready paid SaaS.**

## Capture workflows

- **Markerless A4 sheet:** print `templates/v1/template-markerless.pdf` at 100%, write in the cells, photograph the entire flat sheet against a contrasting surface, and confirm four page corners. Template identity and upright orientation remain explicit; corners cannot correct paper curl.
- **Guided characters:** choose a letter, photograph/upload it, inspect an ink/detail mask or experimental object cutout, set the baseline, accept, and use previous/next/redo. Only accepted characters become glyphs; missing letters are not AI-generated.
- **Legacy compatibility:** original four-ArUco-marker V1 templates remain supported separately.

The font pipeline preserves accepted monochrome masks, traces outlines with Potrace,
and builds/validates fonts with FontForge. Dots, holes and disconnected components
must not be discarded as generic background cleanup. Photographic color, complex
script shaping, automatic professional kerning and arbitrary-background accuracy
are not supported promises.

## Run locally

Requirements: Python3.11+, Node compatible with the pinned Next release, Potrace and
FontForge. On macOS the existing system dependencies can be installed with
`brew install potrace fontforge`.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
cd web && npm ci && cd ..
```

In separate terminals:

```bash
HOST=127.0.0.1 PORT=8000 JOB_STORE_PATH=/tmp/handwrite-jobs.json \
LOCAL_OBJECT_ROOT=/tmp/handwrite-objects PROCESS_JOBS_INLINE=1 \
.venv/bin/python -m handwrite_font_maker.web.server
```

```bash
cd web
WORKER_API_BASE_URL=http://127.0.0.1:8000 npm run dev -- --port 3000
```

Open http://localhost:3000. Without a configured worker the UI reports unavailable
builds; it does not simulate successful font downloads. Alternatively use
`docker compose up --build`; published development ports bind to localhost.

## CLI

```bash
# Quiet markerless A4 PDF; omit --markerless for the legacy template
.venv/bin/handwrite-font-maker generate-template \
  --markerless --output output/template.pdf

# Suggest corners, then inspect/confirm before using them
.venv/bin/handwrite-font-maker detect-corners photo.jpg
.venv/bin/handwrite-font-maker rectify-template photo.jpg \
  --alignment page --corners '[[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]]' \
  --output output/rectified.png

# Build the markerless sheet after inspecting the detected corners
.venv/bin/handwrite-font-maker build photo.jpg \
  --alignment page --corners '[[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]]' \
  --font-name MyHandwriting --family-name 'My Handwriting' \
  --output-dir output/my-handwriting
```

Omit `--alignment page` for the legacy marked-sheet build. Corner values above
are illustrative, not coordinates to reuse for every photograph. Guided font
builds use the web/API capture contract; see the
final interface section in [the product plan](docs/PRODUCT-PLAN.md).

## Verify

```bash
.venv/bin/pytest -q
cd web
npm run lint && npm run typecheck && npm test && npm run build
npx playwright install chromium
npm run test:e2e
```

Actual font tests require the system tools and can take minutes. Evidence and
remaining gaps are tracked in [VALIDATION.md](docs/VALIDATION.md), not inferred
from a successful file download.

```bash
# Run against the localhost API above; creates test uploads/jobs
.venv/bin/python scripts/smoke_capture_api.py --help
# Synthetic style/resize/vector experiments, actual SVG + raster proofs
.venv/bin/python scripts/experiment_vector_styles.py
```

## Product and launch decisions

- [Detailed engineering/product plan](docs/PRODUCT-PLAN.md)
- [Pricing, unit economics, acquisition and SEO](docs/PRICING-GTM.md)
- [Competitor research](docs/research/market.md)
- [Technical research](docs/research/technology.md)
- [Foreground segmentation/model comparison](docs/research/foreground-segmentation.md)
- [Deployment and production security gates](docs/DEPLOYMENT.md)
- [Design contract](DESIGN.md)

Public launch remains gated on auth/ownership, quotas, durable workers, enforced
deletion/retention, billing entitlements and real printer/phone/Office testing.
No production credentials, paid ads or public deployment are configured by this
alpha. Users must own or have permission to use uploaded artwork.
