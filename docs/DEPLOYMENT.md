# Deploying the invite-only beta

## What this profile is—and is not

The deployment target is an **authenticated, invite-only beta**, not a paid public launch. Local mode remains available for development. Beta processing requires verified Supabase identity, an internal API credential, PostgreSQL ownership/quota records, private storage, a separate leased worker, and cleanup. A successful build is not evidence that a hosted deployment, payment account, backup restore, or Office installation has been tested.

No production account, domain, payment account, or provider spend was configured by this work. Billing is deliberately disabled: a durable **font project with rebuilds** is not the same thing as one build job. Charging per job would violate the proposed project pricing. See [pricing](PRICING-GTM.md) and [implementation plan](plans/DEPLOYABLE-BETA.md).

## Recommended topology

```text
Browser ── HTTPS ── Next (login, HttpOnly session, same-origin API)
                       │ private network + internal key + user access token
                       ▼
                   Python API ─── Supabase Auth (verify identity)
                       │
              PostgreSQL + private Storage
                       ▲                 ▲
                leased worker       retention cleanup
                one build/process   periodic retry sweep
```

The API is not a browser-public service. Service-role storage credentials are not user authorization. Next must not get database/service-role credentials in the browser bundle. Do not put these values in `NEXT_PUBLIC_*` variables.

## Fast path: one host + managed Supabase

1. Create/select the intended **staging** Supabase project. Disable public signups and provision the small invited test cohort through trusted administration. Grant each invited account the server-controlled `app_metadata.handwrite_beta = true` flag (not user-editable `user_metadata`). This release has password login, not self-service signup or a complete recovery/onboarding email product. Configure its rate limits and email/security settings. Use an isolated staging project for the canaries below.
2. Create a **private** `handwrite-font-jobs` bucket. This bucket holds both input images and generated font/artifact files: do not configure an image-only MIME allowlist that rejects TTF/OTF/SFD/JSON/ZIP. A 64 MiB bucket object limit accommodates bounded artifacts; the application separately enforces the smaller 15 MiB input-image limit, accepted image types, actual bytes, and pixels. Bucket limits are an additional boundary. Back up an existing database before migration.
3. Copy `.env.beta.example` to ignored `.env.beta`. Replace all placeholders. `SITE_URL` must be the exact HTTPS origin used by the browser. Generate a high-entropy `INTERNAL_API_KEY` and use the same value in Next and Python. Do not commit the environment file.
4. Load the environment and check it:

   ```sh
   set -a; . ./.env.beta; set +a
   .venv/bin/python scripts/deploy_preflight.py
   .venv/bin/python scripts/migrate.py
   .venv/bin/python scripts/deploy_preflight.py --check-services
   ```

   Preflight never provisions infrastructure or prints secret values. `--check-services` verifies the migration ledger and the bucket's private setting; it does **not** prove hosted login or font quality. Migrations are ordered, transactional, checksum-tracked, and protected by an advisory lock. `--check` checks without applying migrations.
5. Start the standalone beta stack (not a merge with local compose):

   ```sh
   docker compose --env-file .env.beta -f docker-compose.beta.yml up --build -d
   docker compose --env-file .env.beta -f docker-compose.beta.yml ps
   ```

   The migration service must complete before processing starts. Only Next binds a host port, at `127.0.0.1:3000`. Put your existing TLS reverse proxy/access gateway in front of it. Do not publish the API, database, or storage administration endpoint. Run the stack on a host with enough aggregate memory for all services—not just a 4 GB API allocation.
6. Complete the staging acceptance matrix below. Keep access restricted until every applicable row passes. A TCP/HTTP health response is not a generated-font canary.
7. Record the deployed image digests, schema ledger, environment revision (not secrets), operator, source backup, and rollback release. CI is provided in `.github/workflows/verify.yml`; it must run in your repository before being treated as evidence.

## ML choices and reproducible images

Models remain optional. Deterministic page extraction/GrabCut does not require ONNX weights. Object segmentation runs in the API, while the font-build worker only consumes accepted masks.

For the Compose profile, explicitly install the selected pinned checkpoints into `.models/` on the host, then mount read-only:

```sh
.venv/bin/python scripts/install_segmentation_model.py --model efficientsam --directory .models/efficientsam
# Optional point-guided alternative:
.venv/bin/python scripts/install_segmentation_model.py --model slimsam --variant fp32 --directory .models/slimsam
# Set INSTALL_ML=true in .env.beta and rebuild.
```

Alternatively build an immutable model image (useful for managed hosting without a model volume):

```sh
docker build -f Dockerfile.api --build-arg INSTALL_ML=true \
  --build-arg INSTALL_MODELS=efficientsam -t handwrite-api:beta-ml .
```

`INSTALL_MODELS` accepts `none`, `efficientsam`, `slimsam`, or `both`; downloads happen at **build time**, with pinned size/SHA-256 verification. Set the corresponding runtime directory to `/models/efficientsam` and/or `/models/slimsam`. Do not mount an empty directory over baked-in weights. Use `scripts/deploy_preflight.py --check-models` inside the configured image to verify files without running inference. Request handling never downloads models.

Local isolated peak RSS was about 1.39 GB EfficientSAM, 2.71 GB SlimSAM fp32, and 3.62 GB SlimSAM int8. These are not cloud/container sizing guarantees. Keep one inference process, allow headroom (the beta API profile has a 4 GB limit), test model switching and bursts, and monitor OOMs. SlimSAM int8 is **not** the recommended memory optimization. See [ML evidence](ML-SEGMENTATION.md).

## Render alternative

`render.yaml` now separates a public Next web service, **private** Python API, background font worker, and scheduled cleanup. Auto-deploy is off. It references paid instance types; importing the Blueprint can incur charges and was **not executed here**.

- Fill the same auth/internal-key values for each applicable service; backend-only credentials stay out of Next.
- Next constructs `WORKER_API_BASE_URL` from Render's private `hostport` reference.
- The API owns `preDeployCommand: python scripts/migrate.py`. Deploy the API/migrations before enabling the first worker/cleanup rollout. Later migrations must remain backward-compatible during rolling releases.
- Private services have TCP checks; `healthCheckPath` applies only to Render web services. Probe API `/readyz` internally and run a real canary separately.
- To enable ML, set the API service environment variables `INSTALL_ML=true`, `INSTALL_MODELS=efficientsam` (or `both`) and the runtime model directories. [Render translates Docker service environment variables into declared Docker build arguments](https://render.com/docs/docker); these toggles are not secrets. Only the API needs segmentation weights; the font worker consumes masks. Verify this image in staging before switching traffic. The default blueprint is deterministic-only.
- Cron cleanup runs every 15 minutes; access expiry is enforced by the application before the physical sweep. Monitor failures/backlog.

These fields were checked against [Render's Blueprint reference](https://render.com/docs/blueprint-spec) and [private-service documentation](https://render.com/docs/private-services); provider creation and rollout are still unverified. Detailed official references: [deployment research](research/deployment-references.md).

## Runtime contract

| Variable | Purpose |
|---|---|
| `DEPLOYMENT_MODE` | `local`, `invite_beta`, or `production`; beta/prod require secure configuration |
| `SITE_URL` | Exact browser origin; used by mutation CSRF checks |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Server-side Auth verification/login |
| `SUPABASE_SERVICE_ROLE_KEY` | Python-only privileged private-storage access |
| `INTERNAL_API_KEY` | At least 32 characters; random server-to-server credential |
| `DATABASE_URL` | Trusted backend PostgreSQL connection; not a browser role |
| `SUPABASE_STORAGE_BUCKET` | Private bucket, default `handwrite-font-jobs` |
| `PROCESS_JOBS_INLINE` | Must be `0` for beta/prod |
| `JOB_LEASE_SECONDS` | Default 60; heartbeat occurs before expiry |
| `JOB_TIMEOUT_SECONDS` | Default 600; whole build process group is killed at deadline |
| `JOB_MAX_ATTEMPTS` | Default 3; crash/timeout/transient network retries are bounded |
| `STORAGE_DELETE_GRACE_SECONDS` | Default 120; in-flight object tombstones are retried through job timeout + this grace |
| `DAILY_UPLOAD_LIMIT`, `DAILY_UPLOAD_BYTES_LIMIT` | Per-account resource limits; guided capture uploads both sources and masks |
| `DAILY_PREVIEW_LIMIT`, `DAILY_BUILD_LIMIT`, `ACTIVE_JOB_LIMIT` | Durable beta abuse/cost caps, **not purchased credits** |
| `BILLING_ENABLED` | Must remain false; paid processing is unavailable |

The starter quota is 150 uploads / 200 MiB / 120 previews / 5 builds per day, at most 2 active jobs. Tune only after observing actual users. These are cost safeguards, not a $3–$5 generation cost claim. API requests still need infrastructure concurrency/connection limits and hosted load testing.

## Staging acceptance matrix

| Check | Expected evidence |
|---|---|
| Login / refresh / logout | Real hosted invited account; cookies HttpOnly/Secure; no token in browser storage; logout and refresh verified |
| Unauthorized calls | Missing internal key/token rejected; wrong Origin rejected on mutations |
| Two-user isolation | A cannot read/write B's sources, masks, jobs, secondary guided glyphs, or artifacts |
| Font canaries | Real controlled page, markerless page, guided subset, and reviewed nature masks produce downloadable fonts |
| Queue recovery | Restart worker during build; reclaim expired lease; late attempt cannot publish visible artifacts |
| Timeout | Hung child + descendants killed; no partial font exposed; attempt budget honored |
| Quotas | Simultaneous requests cannot exceed active/daily limits; invalid references do not create jobs |
| Retention/deletion | Expired access denied immediately; abandoned uploads and failed-attempt artifacts cleaned; storage failure retried |
| Model limits | Correct explicit method; unavailable model is honest; bounded inference under actual host memory/concurrency |
| Data recovery | Restore backup into disposable staging and rerun canary; record recovery time |
| Office usability | Install/render in Windows/macOS Word and PowerPoint; embedding and shared-document behavior checked separately |

Local automated evidence lives in [validation](VALIDATION.md). Hosted-provider and Office checks must not be ticked based on unit tests.

## Operations and rollback

Run separate commands:

```sh
python -m handwrite_font_maker.web.server
python -m handwrite_font_maker.web.worker_loop
python -m handwrite_font_maker.web.cleanup --once
```

For an incident: stop new admission at the gateway, retain database and object backups, stop/restart workers safely, and redeploy the previous **schema-compatible** image. The migration runner refuses unknown newer migrations or modified applied checksums. It does not implement destructive down-migrations. Reverting to the old unauthenticated alpha is **not** a safe rollback behind a public endpoint.

Run `python scripts/ops_status.py` with the backend database environment for a read-only aggregate queue/lease/deletion snapshot. Monitor oldest queued job, active leases, attempt counts, failures, daily usage, storage deletion backlog, disk/memory pressure, and model latency. Log coarse errors/job IDs—not photographs, private glyph contents, bearer tokens, signed URLs, or service keys. A failed storage deletion is a retryable operations item, not permission to resume access. In-flight uploads/artifacts retain an independent deletion deadline through `JOB_TIMEOUT_SECONDS + STORAGE_DELETE_GRACE_SECONDS`; retries cannot erase that window. Storage failures back off from 5 seconds to 5 minutes. Physical removal is asynchronous and depends on a working scheduled cleanup service; do not promise immediate erasure.

## Local-only development

```sh
.venv/bin/pip install -e '.[test]'
# macOS: brew install potrace fontforge
DEPLOYMENT_MODE=local PROCESS_JOBS_INLINE=1 PORT=8000 \
  JOB_STORE_PATH=/tmp/handwrite-alpha-jobs.json LOCAL_OBJECT_ROOT=/tmp/handwrite-alpha-objects \
  .venv/bin/python -m handwrite_font_maker.web.server
cd web
WORKER_API_BASE_URL=http://127.0.0.1:8000 npm run dev -- --port 3001
```

The local `docker-compose.yml` now also exercises separate Postgres-backed processing. JSON storage and unauthenticated local mode are development conveniences, not a tenant boundary. Never expose the local profile publicly.

## Remaining public/paid launch gates

Hosted end-to-end acceptance, real-user capture quality/support measurements, operational restore/load evidence, actual merchant/tax/privacy/terms review, Office compatibility, and explicit project/domain/budget ownership remain launch gates. The saved project library and edit revisions are implemented, but are not a paid entitlement ledger. Self-service account recovery/onboarding and a verified checkout/webhook/credit/refund ledger are still required before charging. No subscriptions or fabricated checkout are presented as implemented.


## Saved-project MVP operations

Apply migrations `0005_projects.sql` and `0006_feedback.sql` through the existing migration runner before enabling this UI. Projects use owner-scoped PostgreSQL rows, optimistic revision checks, and a maximum of 10 live projects per account. Successful edits renew a seven-day inactivity window. Live project references retain accepted glyph masks and template sheets; original guided source photos and generated job artifacts still follow their separate 24-hour retention. Deleting a project must not delete objects referenced by another live project or job. A concurrent-tab conflict requires explicitly reopening the newer project; the client must never silently overwrite it.

Optional usage reporting is off by default and sends only allowlisted event names. These are account-linked daily counts, not anonymous tracking or verified external-app usage. `font_download_requested` measures a link click, not successful installation. Text feedback requires a separate consent checkbox; attachments are not accepted. The cleanup service removes expired feedback and daily counts after the 30-day window. `scripts/ops_status.py` exposes aggregate usage and feedback-topic counts without content or account IDs. No third-party analytics or automated email/support integration is included.

Local mode is single-user development, with atomic project JSON (`PROJECT_STORE_PATH`) and feedback JSON (`FEEDBACK_STORE_PATH`); it is not a substitute for authenticated hosted storage. Keep these files outside version control. Saved projects do not extend job download lifetimes: rebuild from retained masks if a previous build expired.

Staging acceptance additions: save five sample characters, reload and restore masks, adjust scale/spacing, rebuild and inspect the actual exported font; reopen the project in a second tab and verify revision conflicts; delete one of two projects sharing a mask and prove the survivor can still build; verify seven-day project and 30-day feedback cleanup. Download the ZIP, inspect its character map, and install one font format on a real supported OS/Office device. Hosted provider and Office acceptance remain unverified locally.
