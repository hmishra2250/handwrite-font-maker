# Deployment and production readiness

## Current safety boundary

The new capture implementation is a **private alpha**. Run on localhost or behind an access-controlled staging gateway. This repository is not yet a tenant-isolated paid SaaS: do not expose unauthenticated upload, object or font-build endpoints publicly. A public marketing site does not make the processing backend production-ready.

No production account, domain, payment account or spend has been configured by this work. No live checkout, ad campaign or public font-processing deployment is implied by build/test success.

## Local development

Install the existing declared Python dependencies in a virtualenv and system Potrace/FontForge. Then:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
# macOS system tools (Linux image installs these through apt):
brew install potrace fontforge
JOB_STORE_PATH=/tmp/handwrite-alpha-jobs.json \
LOCAL_OBJECT_ROOT=/tmp/handwrite-alpha-objects \
PROCESS_JOBS_INLINE=1 PORT=8000 \
.venv/bin/python -m handwrite_font_maker.web.server
# separate terminal:
cd web
npm ci
WORKER_API_BASE_URL=http://127.0.0.1:8000 npm run dev -- --port 3001
```

JSON job storage is a local/dev option, not a production persistence/queue guarantee. Without `WORKER_API_BASE_URL`, legacy demo mode does not convert user handwriting. New capture workflows must show a missing-backend error rather than manufacture a successful font.

## Environment contract

| Setting | Purpose | Secret? |
|---|---|---|
| `WORKER_API_BASE_URL` | Next server → Python base URL; local uploads/downloads use the same-origin Next object proxy | No; local worker hostname need only be reachable by the Next server |
| `DATABASE_URL` | Postgres connection | Yes |
| `SUPABASE_URL` | Supabase project | No |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only storage privilege | **Yes; never NEXT_PUBLIC** |
| `SUPABASE_STORAGE_BUCKET` | Private bucket name | No |
| `JOB_STORE_PATH`, `LOCAL_OBJECT_ROOT` | Development file paths | No |
| `PORT`, `HOST` | Python bind; default localhost, explicitly `HOST=0.0.0.0` inside an access-controlled container | No |
| `PROCESS_JOBS_INLINE` | Development inline processing | No; not a durable production queue |

Consult server code for any added host/size/timeout settings; set container listen host explicitly when binding on all container interfaces is needed. Binding all interfaces inside a container does not itself provide authentication.

## Staging checklist (not yet complete)

1. Select the existing or new **staging** Vercel/Render/Supabase project IDs and budget. Reuse approved existing projects; never guess the owner's production account.
2. Build immutable Python and Next images; audit existing package vulnerabilities and test the lockfile under the deployment Node/Python versions.
3. Back up the database; apply `supabase/migrations/` in order to staging only. Verify old jobs still deserialize and new capture config survives reload. Record migration version and rollback constraints.
4. Provision a **private** object bucket, owner-scoped paths and appropriate RLS/authorization. The service-role key bypasses RLS: app-layer ownership checks remain required.
5. Add an access-controlled gateway/private networking in front of processing services. A secret frontend URL is not access control. Avoid browser-direct private-worker URLs unless deliberately exposed through an authenticated upload capability/proxy.
6. Configure a durable worker with atomic claims, leases, retry/idempotency and resource ceilings. Inline daemon threads can die on restart and are not the production worker plan.
7. Verify one real legacy sheet, one markerless sheet and one guided partial font; reload jobs from Postgres before checking private artifact downloads.
8. Test expiry/deletion, signed-link timeout, malformed/oversized/overpixel images, unauthorized cross-project access, concurrency, restart during build and dependency outage.
9. Payment test mode only: actual merchant eligibility, webhook signatures, idempotency, checkout-to-project entitlement, credit reservation/refund and successful artifact access. Do not put secret checkout logic in browser state.
10. Observe latency, CPU/RSS, retry rate and support minutes; compare to the pricing reserve rather than inferring cost from one local benchmark.

## Public launch hard gates

- [ ] Real auth/project ownership with cross-tenant negative tests.
- [ ] Authenticated server-to-server API or private network; browser-safe scoped upload/download capabilities.
- [ ] Rate limits, quotas and bounded CPU/memory/subprocess runtime, including free previews.
- [ ] Storage isolation and actual retention/deletion enforcement, including abandoned uploads.
- [ ] Durable job retry/lease recovery and idempotent artifact publication.
- [ ] Billing and project-credit ledger, verified webhook/idempotency/refund tests.
- [ ] Merchant/tax/privacy/terms review for the actual business and supported countries.
- [ ] Generated fonts installed/rendered in Windows and macOS Word/PowerPoint; embedding/sharing tested separately.
- [ ] Real-user acceptance corpus; measured cost, support and refund targets.
- [ ] Explicit production project/domain/budget and rollback owner.

These are not checked merely because unit tests pass. Keep the service private until they are verified.

## Rollback and operations

Deploy immutable versions; keep previous image + frontend release. Before a schema change, snapshot database and document whether rollback requires migration reversal or simply redeploying compatible old code. Retain no failed-job input longer than the declared retention window. Pause new builds on systemic errors; preserve paid entitlements; never retry paid provider actions without idempotency.

Log job IDs, stage durations and coarse failure codes. Do not log handwriting photographs, private font contents, signed URLs, database passwords or service-role tokens. Alert on queue age, build failures, overspend/abuse, disk pressure and deletion backlog. Validate health with a real bounded canary font in staging, not `/healthz` alone.
