# Handwrite Font Maker

Turn handwriting or user-selected handmade shapes into actual TTF/OTF fonts.
**Current release: local capture app + invite-only beta deployment profile. Not a paid/public SaaS launch.**

## Capture workflows

- **Markerless A4 sheet:** print `templates/v1/template-markerless.pdf` at 100%, write in the cells, photograph the entire flat sheet against a contrasting surface, and confirm four page corners. Template identity and upright orientation remain explicit; corners cannot correct paper curl.
- **Guided characters:** choose a letter, photograph/upload it, inspect an ink/detail mask or experimental object cutout, set the baseline, accept, and use previous/next/redo. Only accepted characters become glyphs; missing letters are not AI-generated.
- **Legacy compatibility:** original four-ArUco-marker V1 templates remain supported separately.

The font pipeline preserves accepted monochrome masks, traces outlines with Potrace,
and builds/validates fonts with FontForge. Dots, holes and disconnected components
must not be discarded as generic background cleanup. Photographic color, complex
script shaping, automatic professional kerning and arbitrary-background accuracy
are not supported promises.

## Finish and resume a font

Create a saved project, then start with five characters (`ABCDE`) using your own captures or the clearly labeled synthetic sample. Accepted masks are uploaded once and reused for rebuilds. The project library restores masks, metadata, selected characters, and template sheet/corner state; concurrent edits produce a revision conflict instead of silent overwrites.

Review the target-glyph grid, adjust baseline, scale, and spacing, then rebuild to change the actual exported font. Download the ZIP with TTF/OTF, character map, and installation notes. Installing a font remains a user/OS action; the app does not silently install into Office.

Invite-beta projects expire after seven days without a successful edit (maximum ten live projects). Jobs and downloads have a separate 24-hour window. Optional account-linked usage counts and text feedback require consent and have a 30-day cleanup window. No photo attachments or third-party analytics are used. Local JSON storage is single-user development only.

## Deploy the invite beta

Start with [the deployment runbook](docs/DEPLOYMENT.md) and `.env.beta.example`.
The beta profile separates authenticated Next/Python APIs, owner-scoped PostgreSQL
records, a leased worker, private storage, and retention cleanup. Use
`docker-compose.beta.yml` or the staged Render blueprint; public signup and billing
remain disabled. Hosted provider acceptance and Office checks are still required.

The [real nature-photo experiment](docs/research/nature-experiments.md) compares
leaf, oak, fern, and satellite-river captures. Reviewed leaf/fern masks become real
ornament-font glyphs; rejected river/delta results are retained rather than sold as
successful extraction. These examples do not synthesize a readable alphabet.

The [internet-sample detection-quality report](docs/research/detection-evidence/README.md)
records paired leaf benchmarks, handwriting comparisons, actual font-detail fixes,
and remaining page/river limitations. Adaptive ink thresholding is optional;
ML extraction is not universally better than the deterministic path.
The [follow-on page-corner safety pass](docs/research/page-corner-evidence/README.md)
rejects weak/ambiguous outlines and protects manual edits from late detection responses.

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
DEPLOYMENT_MODE=local HOST=127.0.0.1 PORT=8000 JOB_STORE_PATH=/tmp/handwrite-jobs.json \
LOCAL_OBJECT_ROOT=/tmp/handwrite-objects PROCESS_JOBS_INLINE=1 \
.venv/bin/python -m handwrite_font_maker.web.server
```

```bash
cd web
DEPLOYMENT_MODE=local WORKER_API_BASE_URL=http://127.0.0.1:8000 npm run dev -- --port 3000
```

Open http://localhost:3000. Without a configured worker the UI reports unavailable
builds; it does not simulate successful font downloads. Alternatively use
`docker compose up --build`; published development ports bind to localhost.

## Optional local ML cutouts

The app includes two **real, optional pretrained ONNX models** alongside deterministic ink extraction and GrabCut:
- **AI box cutout (EfficientSAM):** select a rectangle; no point prompts required.
- **SlimSAM point cutout:** add keep/exclude clicks for ambiguous shapes.

```sh
.venv/bin/pip install -e '.[ml]'
.venv/bin/python scripts/install_segmentation_model.py --model efficientsam
.venv/bin/python scripts/install_segmentation_model.py --model slimsam
```

Models run locally; weights are explicitly installed, pinned and hash-verified.
Review the mask and use the reversible add/erase brush before accepting a glyph.
Neither model guarantees arbitrary-background accuracy or preserves photographic color.
See [setup, resource requirements and limitations](docs/ML-SEGMENTATION.md).

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
