# Handwrite Font Maker

Turn handwriting or user-selected handmade shapes into actual TTF/OTF fonts.
**Current release: integrated Next.js + Python/ML monorepo with a SQLite private-alpha profile and an optional Supabase/Postgres invite-beta profile. Paid checkout is not enabled.**

## Capture workflows

- **Markerless A4 sheet:** print `templates/v1/template-markerless.pdf` at 100%, write in the cells, photograph the entire flat sheet against a contrasting surface, and confirm four page corners. Template identity and upright orientation remain explicit; corners cannot correct paper curl.
- **Guided characters:** choose a letter and photograph/upload it. Compare automatic clean/soft SVG choices plus bounded optional object cutouts, accept a shape, then use previous/next/redo. Advanced correction controls expose masks and baseline adjustments. Only accepted characters become glyphs; missing letters are not AI-generated.
- **Legacy compatibility:** original four-ArUco-marker V1 templates remain supported separately.

The font pipeline preserves accepted monochrome masks, traces outlines with Potrace,
and builds/validates fonts with FontForge. Dots, holes and disconnected components
must not be discarded as generic background cleanup. Photographic color, complex
script shaping, automatic professional kerning and arbitrary-background accuracy
are not supported promises.

## Finish and resume a font

Create a saved project, then start with five characters (`ABCDE`) using your own captures or the clearly labeled synthetic sample. Accepted masks are uploaded once and reused for rebuilds. The project library restores masks, metadata, selected characters, and template sheet/corner state; concurrent edits produce a revision conflict instead of silent overwrites.

Review the target-glyph grid, adjust baseline, scale, and spacing, then rebuild to change the actual exported font. Download the ZIP with TTF/OTF, character map, and installation notes. Installing a font remains a user/OS action; the app does not silently install into Office.

Invite-beta projects expire after seven days without a successful edit (maximum ten live projects). Jobs and downloads have a separate 24-hour window. Optional account-linked usage counts and text feedback require consent and have a 30-day cleanup window. Feedback has no photo attachments and no third-party analytics are used. Capture photos themselves are stored privately for extraction. Local JSON storage is single-user development only.


## Deployment handoff: start here

**Recommended deployment: private alpha on one persistent Linux host.** The repo
contains the frontend, backend, worker, SQLite schema, model installer, templates,
API contracts and tests. It does **not** contain your production passwords, domain,
TLS certificates, live user database, uploaded photos or model binaries. An
operator supplies those using the steps below. Billing is deliberately disabled;
this is deployable invited-user software, not a ready-to-charge public launch.

### Repository / specification map

| Responsibility | Source of truth |
|---|---|
| Web UI, mobile camera, login and same-origin API | `web/app/`, `web/lib/` |
| Detection, segmentation, SVG tracing and font generation | `src/handwrite_font_maker/` |
| SQLite auth, quotas, projects, jobs, worker and cleanup | `src/handwrite_font_maker/web/` |
| API request/response contracts | [Alpha API](docs/ALPHA-API.md), `web/lib/contracts.ts`, `web/lib/capture-candidates.ts`, `web/lib/projects.ts` and matching backend validators/tests |
| Printable markerless/legacy sheets | `templates/v1/`, `web/public/template-*.pdf`, `src/handwrite_font_maker/template.py` |
| Product requirements and UI decisions | [Product plan](docs/PRODUCT-PLAN.md), [design contract](DESIGN.md) |
| Host/account/backup operations | [Private-alpha runbook](docs/PRIVATE-ALPHA.md) |
| Models, licenses, quality and limitations | [ML setup](docs/ML-SEGMENTATION.md), `licenses/`, [capture evidence](docs/research/capture-diagnostics.md) |
| Alternative managed PostgreSQL/Supabase deployment | [Invite-beta runbook](docs/DEPLOYMENT.md), `.env.beta.example`, `docker-compose.beta.yml` |
| Planned pricing—not active checkout | [Pricing strategy](docs/PRICING-STRATEGY.md) |

```text
Browser → HTTPS reverse proxy → Next.js web (host loopback port 3000)
                                  ↓ private Docker network + internal key + session
                              Python API → local optional ONNX segmentation
                                  ↓
                   SQLite + owner-scoped local object files
                                  ↑
                         font worker + cleanup loop
```

Segmentation runs in the **API**, not the font worker. The worker converts accepted
masks into fonts; Next.js does not need a GPU or model weights. Do not split SQLite
and its object directory across unrelated hosts or use ephemeral serverless disks.

### 1. Prerequisites and fresh clone

- Git access to this repository; Docker Engine with Compose v2 on a persistent
  host. Docker Desktop is suitable for a local rehearsal.
- Python **3.11+** on the host for bootstrap scripts (container uses Python 3.12).
  Host-only development also needs **Node 22**, `npm`, FontForge and Potrace;
  the Dockerfiles install their own runtimes/system tools.
- Internet access during dependency installation and explicit model downloads.
  No external inference service is required at runtime.
- A domain/DNS record pointing at the host, a TLS reverse proxy, and firewall
  access restricted to HTTPS plus your administrative access. Local rehearsal can
  use `http://localhost:3000`; phone camera access needs trusted HTTPS.
- **Sizing estimates, not a production benchmark:** start with 2–4 CPUs / 8 GB RAM
  for deterministic alpha; for both automatic ML alternatives start with 4+ CPUs /
  16 GB host RAM and an 8 GB API limit. Budget persistent disk for images, artifacts,
  container layers and backups; start with at least 20 GB free and monitor growth.
  Confirm actual peak memory/latency on your target host before inviting users.
  On macOS, check free space **inside Docker's VM as well as on the Mac**. Alpha
  container logs rotate at three 10 MB files per service; see the
  [disk-capacity and log-maintenance runbook](docs/PRIVATE-ALPHA.md#disk-capacity-and-container-logs).

```bash
git clone git@github.com:hmishra2250/handwrite-font-maker.git
cd handwrite-font-maker
python3 scripts/alpha_admin.py --init-env
```

The bootstrap creates ignored `.env.alpha` with permissions `0600`, a random
internal key, and **no user account**. It refuses to overwrite an existing file.
Edit that file with an editor; never paste it into an issue or commit it.

### 2. Required configuration and credentials

| Setting / credential | What to supply |
|---|---|
| `DEPLOYMENT_MODE` | Keep `private_alpha`; `local` bypasses the production auth profile and is not for public sharing. |
| `SITE_URL` | Exact browser origin, e.g. `https://fonts.your-domain.tld`, with no path or trailing slash; localhost HTTP only for private rehearsal. |
| `INTERNAL_API_KEY` | Generated by `--init-env`; a shared server-only random secret (minimum 32 characters), not a user's password. Keep the same value in web/API. Never use `NEXT_PUBLIC_` for secrets. |
| Invited user email + password | Provision in step 4. No built-in admin login, shipped password, public signup or recovery-email provider. Deliver initial credentials privately. |
| `ALPHA_DATABASE_PATH`, `LOCAL_OBJECT_ROOT` | Keep `/data/alpha.sqlite3` and `/data/objects` for Compose; the named volume persists them. Host-local scripts map these defaults to ignored `.alpha/`. |
| `WORKER_API_BASE_URL` | Keep `http://api:8000` for Compose. The host-local launcher sets loopback automatically. |
| `PROCESS_JOBS_INLINE`, `BILLING_ENABLED` | Keep both `0`; Compose forces the separate worker and disabled checkout. |
| Host / DNS / TLS access | Your SSH/deployment access, domain DNS access and certificate issuance/renewal setup; none belongs in Git. |
| Optional model settings | Step 3. No OpenAI, Hugging Face token, GPU, model API key or custom training is required for the pinned public weights. |
| Payment / Supabase keys | **Not required and must be unset for private alpha.** Supabase/Postgres credentials belong only to the separate beta profile. Payment integration is not implemented by adding a key. |

Quota and lease defaults are listed in `.env.alpha.example`: 300 uploads,
500 MiB uploaded bytes, 200 previews and 10 builds per owner/day, two active jobs,
60-second leases, 1200-second job timeout, three attempts. Automatic ink and object
stages each consume a preview allowance. These are abuse limits, not paid credits.

### 3. Models: deterministic-only or full optional ML

**Deterministic-only is the default:** leave `INSTALL_ML=false`. Ink extraction,
markerless page handling, bounded classical extraction, vector tracing and font
building work without model downloads. Unavailable ML choices fail visibly without
preventing users from accepting fast results.

To install **both** supported models on the host:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[ml,test]'
.venv/bin/python scripts/install_segmentation_model.py --model efficientsam --directory .models/efficientsam
.venv/bin/python scripts/install_segmentation_model.py --model slimsam --variant fp32 --directory .models/slimsam
```

Then set these values in `.env.alpha` **before building**:

```dotenv
INSTALL_ML=true
HANDWRITE_EFFICIENTSAM_MODEL_DIR=/models/efficientsam
HANDWRITE_MODEL_DIR=/models/slimsam
HANDWRITE_SEGMENTATION_VARIANT=fp32
ALPHA_API_MEMORY_LIMIT=8g
ALPHA_API_CPUS=4.0
```

Compose mounts `./.models` read-only at `/models`. Set the directory variables
explicitly: the in-container default `.models` location is not that mount. Host-only
runs should instead use absolute host paths such as `/path/to/repo/.models/slimsam`
and `/path/to/repo/.models/efficientsam`; `/models/...` is a container path.
Changing `INSTALL_ML` requires an image rebuild, not only a restart.

| Model | Pinned source revision | Purpose / license |
|---|---|---|
| EfficientSAM-Ti | HF Space `yunyangx/EfficientSAM` @ `d8dbb1eee73bfb3392aa6f6e8944aeb13f3f4036` | Box-guided object segmentation; Apache-2.0 license retained in `licenses/`. |
| SlimSAM | `Xenova/slimsam-77-uniform` @ `5850ab45f587c112167512ffef949107115e26a0` | Point-guided segmentation; Apache-2.0 license retained in `licenses/`. |

The installer verifies fixed file sizes and SHA-256 hashes from `MODEL_ASSETS` in
`segmentation.py` / `efficient_segmentation.py`, then installs atomically. Rerunning
it verifies existing files. `onnxruntime==1.29.0` is pinned by the `[ml]` extra.
Weights are intentionally not committed. Installer/download failure must be fixed,
not bypassed with an arbitrary checkpoint. Preserve model and system-tool licenses
when distributing images. See [model documentation](docs/ML-SEGMENTATION.md) for
exact resource evidence and the optional SlimSAM int8 comparison (not the default).

For an immutable image instead of mounted weights, `Dockerfile.api` also supports
`--build-arg INSTALL_ML=true --build-arg INSTALL_MODELS=both` (or either family).
This explicitly downloads verified weights **at build time**, not during requests.
Use a deployment definition without the Compose `.models:/models` bind mount so
it does not hide the baked-in files; keep the same runtime directory variables.
The standard alpha recipe above intentionally uses the host-mounted approach.

Automatic candidates run optional methods in isolated child processes with
25-second per-method deadlines. Both ML families may run concurrently; **the old
single-model 4 GB estimate is not enough to assume both fit**. Fast ink choices
remain usable while ML runs, fails or times out. Model accuracy is experimental.

### 4. Build, start and create the first login

```bash
python3 scripts/alpha_preflight.py --env-file .env.alpha --json
# -q validates without dumping the resolved environment/secrets into logs.
docker compose --env-file .env.alpha -f docker-compose.alpha.yml config -q
docker compose --env-file .env.alpha -f docker-compose.alpha.yml up --build -d
docker compose --env-file .env.alpha -f docker-compose.alpha.yml ps

# Interactive password prompt (12+ characters); nothing is placed in shell history.
docker compose --env-file .env.alpha -f docker-compose.alpha.yml exec api \
  python -m handwrite_font_maker.web.alpha_auth create-user --email founder@your-domain.tld
```

Alternatively add `--generate-password` to print a generated initial password once;
run that only in a private terminal, not a recorded CI job. To reset or disable an
account, use the same container command with `reset-password` or `disable-user`.
Reset/disable revokes sessions. Administration is a trusted host CLI, not a public
web admin endpoint. There is no application requirement that the login email be a
working inbox in this alpha (no signup/recovery mail is sent).

**Do not use the host `alpha_admin.py create-user` wrapper to provision Docker
accounts:** it writes the host `.alpha` database, not the Docker named volume.
For host-only development use that wrapper and `scripts/alpha-dev.sh` instead;
see the runbook. Do not run `docker compose down -v` on data you want to keep.

Compose uses `.env.alpha` for both interpolation and container environment. If you
use a different file, set `ALPHA_ENV_FILE=/absolute/path/to/file` **and** pass
`--env-file /absolute/path/to/file`; changing only one selects inconsistent config.

### 5. HTTPS, acceptance and operations

Keep the published web port on `127.0.0.1:3000`; configure your host TLS reverse
proxy to forward to it, preserving `Host` and setting `X-Forwarded-Proto: https`.
Use the exact same origin in `SITE_URL`. Publish only HTTPS (and an HTTP redirect /
certificate challenge if needed); do not expose port 8000, SQLite or model files.
Set a request body limit above the app's 15 MiB image maximum (e.g. 20 MiB), an
upstream timeout above the 40-second candidate proxy timeout (e.g. 60 seconds),
and login/password rate limiting at the trusted edge using the actual client IP.
Provision TLS/certificate renewal using your hosting provider's supported setup;
this repo does not provision a domain, reverse proxy, firewall or certificate.

Check internal readiness after start:

```bash
docker compose --env-file .env.alpha -f docker-compose.alpha.yml exec -T api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=5).read().decode())"
docker compose --env-file .env.alpha -f docker-compose.alpha.yml logs --tail=100 api worker cleanup web
```

Before inviting users, verify on **the target host**:

1. Anonymous `/api/account` is denied; invited login works; logout/revocation works.
2. Upload a handwriting photo and an object photo; see actual SVG choices; failed
   ML alternatives do not erase usable results. Try both model families explicitly
   if enabled—successful threshold fallback does not prove a model is installed.
3. Accept several glyphs, build a real font, download SVG/TTF/OTF/ZIP and inspect it.
   Save/reopen a project. Install the font and test it in your target Office app.
4. Open `/mobile` on the S23 Ultra/iPhone (trusted HTTPS), grant camera permission,
   test capture/retake/upload and camera switching. Emulation is not hardware proof.
5. Run a backup **and restore drill** using [the runbook](docs/PRIVATE-ALPHA.md#backup-and-restore).
   Back up SQLite and objects together in a maintenance window, encrypt backups,
   retain `.env.alpha` separately in your secret manager, and keep model manifests.
6. Confirm worker/cleanup stay running, disk/memory have headroom and expired data
   is inaccessible. Monitor logs, queued jobs, failed jobs, OOMs and free disk.

Updates: record `git rev-parse HEAD`, back up, `git pull --ff-only`, rerun preflight,
then `docker compose ... up --build -d` and repeat the canary. SQLite schema setup is
owned by `sqlite_store.py`; alpha does not run the Supabase migration command.
For rollback, retain the previous source/image revision and a matching data backup;
do not assume a future schema change is backward-compatible.

Optional `HANDWRITE_CAPTURE_DIAGNOSTICS_DIR` retains sensitive debugging records;
leave it unset normally. If enabled, supply a private writable persistent path
under `/data` in Docker and protect access. Records expire lazily after 24 hours
on a later capture, not through guaranteed timed deletion. This is not a permanent
user-facing history; see [diagnostic scope](docs/research/capture-diagnostics.md).

Troubleshooting: missing model → verify runtime, explicit directory, mount and
hashes; queued jobs → inspect worker/leases; rejected login/origin → check account
provisioning database, exact `SITE_URL` and TLS; missing data after redeploy → check
the Compose project/volume name; busy/timeouts → inspect API memory/CPU and quotas.
Never "fix" these by enabling anonymous local mode or exposing the Python API.

### What still needs operator/product work

The codebase cannot supply production credentials or target-host acceptance.
You must provide DNS/TLS, secure secret delivery, backups/monitoring and actual
printer/phone/Office tests. Public paid launch still needs a payment provider,
idempotent webhooks, project-credit ledger, refunds and production launch checks.
Photographic color/texture fonts, arbitrary-background accuracy, complete complex-
script shaping and automatic professional kerning are not implemented promises.


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

## Pricing strategy

The [current pricing recommendation](docs/PRICING-STRATEGY.md) applies a reviewed GitHub pricing skill to competitor evidence, project-based packaging and illustrative unit economics. It is a commercial experiment plan, not live billing.

## Run locally

Requirements: Python 3.11+, Node 22, Potrace and
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
Compare automatic SVG choices; use the reversible add/erase brush under Advanced correction tools when a mask needs manual correction.
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
# Real auth + SQLite + upload + worker integration with disposable accounts:
npm run test:e2e:alpha
```

Browser suites use dedicated test ports and isolated Next caches; do not reuse an existing server on those ports. The alpha suite provisions disposable accounts and needs no production credentials. The optional public-phone suite requires the explicitly provisioned private test login described in [mobile preview testing](docs/MOBILE-PREVIEW.md#automated-phone-canary).

CI (`.github/workflows/verify.yml`) includes Python/PostgreSQL tests, frontend checks, container builds and an isolated real-service alpha browser canary. CI execution on your repository is additional evidence, not assumed by these commands.

Actual font tests require the system tools and can take minutes. Evidence and
remaining gaps are tracked in [VALIDATION.md](docs/VALIDATION.md) and the
[deployment handoff evidence](docs/research/deployment-handoff-validation.md), not inferred
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

Auth/ownership, abuse quotas, durable workers and retention mechanisms are implemented.
Public launch still requires target-host security/restore acceptance, real billing
entitlements, and printer/phone/Office testing.
No production credentials, paid ads or public deployment are configured by this
alpha. Users must own or have permission to use uploaded artwork.

### Phone camera testing

The desktop studio accepts uploads; touch-first mobile browsers also offer a live
rear-camera flow. See [Phone testing](docs/PHONE-TESTING.md) to run the LAN-only HTTPS
preview alongside localhost, trust the dedicated test CA on personal devices, and
verify S23 Ultra/iPhone 14 Pro camera behavior. Physical-device support remains a
manual acceptance check; browser tests are not a substitute for hardware testing.

For a phone-only page on a temporary public HTTPS link (no local certificate setup),
see [Mobile preview](docs/MOBILE-PREVIEW.md). It uses the existing private-alpha API
and login, with a production-mode web server; it is not permanent hosting.
