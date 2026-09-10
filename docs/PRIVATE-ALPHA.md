# Private alpha runbook

Private alpha is the single-host, low-overhead alpha profile for invited users: one host, one
SQLite database, local object storage, local optional ONNX models, authenticated
Next.js frontend, internal-only Python API, one worker, and one cleanup loop. It
is not a public SaaS launch and it does not collect payment credentials.

## Architecture

- `web` is the only service published to the host, bound to `127.0.0.1:3000` by
  default. Put a TLS reverse proxy in front before sharing with real alpha users.
- `api` is exposed only on the Docker network at `http://api:8000` and serves
  `/readyz` for health checks.
- `worker` runs font builds out of process; `PROCESS_JOBS_INLINE=0` is required.
- `cleanup` deletes expired jobs/downloads/objects on the same local disk.
- `alpha-data` is shared by the Python services at `/data` and contains
  `/data/alpha.sqlite3` plus `/data/objects`.
- `.models` can be mounted read-only for optional local EfficientSAM/SlimSAM ONNX
  files. No cloud model API is part of the alpha profile.

See the [README deployment handoff](../README.md#deployment-handoff-start-here)
for a fresh-clone checklist, credentials matrix, model directories and sizing.
`INSTALL_ML=true` installs the runtime only; mount verified weights and explicitly
set `/models/...` directory variables. Default API limits are 4 GB / 2 CPUs for
deterministic use; for both concurrent model families, start with
`ALPHA_API_MEMORY_LIMIT=8g` and `ALPHA_API_CPUS=4.0` and measure target-host headroom.

## Configure

```bash
python3 scripts/alpha_admin.py --init-env
```

This creates `.env.alpha` with mode `0600` and a random `INTERNAL_API_KEY`; it
never overwrites an existing file and it does not create a user. Edit `SITE_URL`
for the target host before sharing externally. Keep these invariants:

- `DEPLOYMENT_MODE=private_alpha`
- `ALPHA_DATABASE_PATH=/data/alpha.sqlite3` in Docker
- `LOCAL_OBJECT_ROOT=/data/objects` in Docker
- `WORKER_API_BASE_URL=http://api:8000` in Docker
- `PROCESS_JOBS_INLINE=0`
- no `DATABASE_URL`, Supabase keys, Stripe keys, Paddle keys, or Lemon Squeezy keys

For host-local development, `scripts/alpha-dev.sh` loads `.env.alpha` without
shell evaluation and maps `/data/*` to `./.alpha/*` for the local processes.

## Preflight

```bash
python3 scripts/alpha_preflight.py --env-file .env.alpha --json
python3 scripts/alpha_preflight.py --env-file .env.alpha --check-paths --json
```

The path check is meant for host-local runs. In Docker, the named volume is
initialized from the image-owned `/data` directory so UID `10001` can write it.

## Run with Docker Compose

```bash
docker compose --env-file .env.alpha -f docker-compose.alpha.yml config -q
docker compose --env-file .env.alpha -f docker-compose.alpha.yml up --build
```

Open <http://localhost:3000>. The Python API is not published to the host. If you
need to inspect readiness, run it through Compose:

```bash
docker compose --env-file .env.alpha -f docker-compose.alpha.yml exec -T api \
  python - <<'PY'
import json, urllib.request
print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/readyz')), indent=2))
PY
```

## Run host-local dev

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
(cd web && npm ci)
./scripts/alpha-dev.sh --api-port 8000 --web-port 3000
```

The launcher starts API, worker, cleanup, and Next dev, and shuts every child down
on Ctrl-C. Use `--skip-worker` only when you are testing login/UI paths and do not
expect font builds to complete.

## Provision accounts

No user is auto-created and no default password exists. Run account commands only
on the trusted host with the alpha environment loaded.

Docker:

```bash
docker compose --env-file .env.alpha -f docker-compose.alpha.yml run --rm api \
  python -m handwrite_font_maker.web.alpha_auth create-user \
  --email founder@example.com --generate-password
```

Host-local wrapper (parses `.env.alpha` without shell evaluation, maps Docker
`/data/*` paths to `./.alpha/*`, and never copies the internal key onto the
command line):

```bash
python3 scripts/alpha_admin.py create-user --email founder@example.com --generate-password
```

Reset or disable access with the same wrapper:

```bash
python3 scripts/alpha_admin.py reset-password --email founder@example.com --generate-password
python3 scripts/alpha_admin.py disable-user --email founder@example.com
```

Reset and disable revoke active sessions.

## Reverse proxy and TLS

When this leaves your laptop, keep Compose bound to localhost and publish only the
reverse proxy. The proxy should:

1. terminate TLS for `SITE_URL=https://your-domain.example`,
2. forward only to `127.0.0.1:3000`,
3. set `X-Forwarded-Proto: https` and `Host`,
4. block direct access to API/container network ports, and
5. enforce normal upload/body limits above the app's 15 MiB image limit, and
6. rate-limit login/password endpoints by the actual client IP at the trusted proxy.
   Python sees only Next's internal connection; it intentionally does not trust
   arbitrary forwarded-IP headers or impose an attacker-exhaustible global lockout.

Do not expose a profile, account, upload, or API route on a public HTTP origin.

## Billing stance

The alpha catalog may show planned `$12` single-font and `$29` three-font offers,
but `BILLING_ENABLED=0` and checkout is fail-closed. Invited alpha users get free
operator-provisioned access. Add a real provider only after there is a project
credit ledger, webhook idempotency, refund handling, and merchant approval.

## Backup and restore

Use a short maintenance window so the SQLite snapshot and object files agree.
The commands below assume the default Compose project/volume name
`handwrite-font-maker_alpha-data`; substitute the actual volume if you set a
custom project name. Protect backups as credentials: they contain account data
and password hashes.

Backup:

```bash
umask 077
BACKUP_DIR="backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
docker compose --env-file .env.alpha -f docker-compose.alpha.yml stop web api worker cleanup
docker compose --env-file .env.alpha -f docker-compose.alpha.yml run --rm -T api \
  python - <<'PY'
import sqlite3
src = sqlite3.connect('/data/alpha.sqlite3')
dst = sqlite3.connect('/data/alpha-backup.sqlite3')
src.backup(dst)
dst.close(); src.close()
PY
docker run --rm -v handwrite-font-maker_alpha-data:/data -v "$PWD/$BACKUP_DIR:/backup" alpine \
  sh -c 'umask 077; cp /data/alpha-backup.sqlite3 /backup/alpha.sqlite3 && tar -C /data -czf /backup/objects.tgz objects'
docker compose --env-file .env.alpha -f docker-compose.alpha.yml up -d
```

Restore smoke (overwrites the current alpha data; rehearse on a separate test volume first):

```bash
docker compose --env-file .env.alpha -f docker-compose.alpha.yml stop web api worker cleanup
docker run --rm -v handwrite-font-maker_alpha-data:/data -v "$PWD/$BACKUP_DIR:/backup:ro" alpine \
  sh -c 'rm -f /data/alpha.sqlite3-wal /data/alpha.sqlite3-shm && cp /backup/alpha.sqlite3 /data/alpha.sqlite3 && rm -rf /data/objects && tar -C /data -xzf /backup/objects.tgz && chown -R 10001:10001 /data'
docker compose --env-file .env.alpha -f docker-compose.alpha.yml up -d
docker compose --env-file .env.alpha -f docker-compose.alpha.yml exec -T api \
  python - <<'PY'
import urllib.request
urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=5).read()
print('restore readiness smoke passed')
PY
```

Run a real login and a small five-glyph font canary after every restore drill.

## Alpha verification commands

The browser suite starts its own Next/Python/worker services on ports 3007/8007,
with temporary SQLite data and test-only accounts. Next uses `.next-alpha-e2e`, separate from the normal studio cache. If these ports are occupied, set `ALPHA_E2E_WEB_PORT` and `ALPHA_E2E_API_PORT` to unused ports for that run. It does not use or modify your
alpha accounts. Install the Python/web dependencies, FontForge, Potrace and
Playwright Chromium first, then run from the web package:

```bash
cd web
npm run test:e2e:alpha
```

To also exercise real local ML inference (no cloud API), install the `[ml]` extra
and the verified EfficientSAM weights using `scripts/install_segmentation_model.py`
into `.models/efficientsam`, then run:

```bash
cd web
ALPHA_E2E_ML=1 npm run test:e2e:alpha
```

The ML variant fails if inference does not return EfficientSAM output; it does not
accept a deterministic fallback as an ML pass.

That test is an integration canary; it complements, but does not replace, the
preflight and restore smoke checks above.

See [dated validation evidence](research/private-alpha-validation.md) for checks
actually completed and deployment acceptance gaps.

## Real-phone capture preview

Use [PHONE-TESTING.md](PHONE-TESTING.md) for the separate LAN-only HTTPS preview,
rear-camera checks, and S23 Ultra/iPhone 14 Pro test checklist. It keeps the Python
API private and leaves the normal localhost desktop studio available. The dedicated
local test CA is for personal testing only, not customer distribution.
