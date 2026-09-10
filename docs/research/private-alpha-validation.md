# Private-alpha validation — 2026-09-11

## Scope

Assembled the existing Next frontend and Python font/segmentation backend into an
explicit single-host `private_alpha` profile: SQLite persistence, local private
objects, a leased worker, cleanup, operator-created accounts, opaque revocable
sessions, account limits, planned pricing and a fail-closed checkout boundary.
Existing anonymous local and Supabase/Postgres modes remain separate.

## Executed evidence

- Targeted Python integration/regression suite: **94 passed**. Includes alpha
  auth/HTTP, SQLite stores, provisioning/preflight, existing beta isolation,
  worker lifecycle, projects, feedback, web contracts, capture and static
  boundaries. Postgres regressions used a disposable PostgreSQL 16 instance;
  they were not skipped. Command:

  ```bash
  TEST_DATABASE_URL=<disposable-postgres-url> .venv/bin/python -m pytest \
    tests/test_alpha_auth.py tests/test_alpha_sqlite.py \
    tests/test_alpha_admin.py tests/test_alpha_preflight.py \
    tests/test_beta_security.py tests/test_beta_isolation_edges.py \
    tests/test_worker_lifecycle.py tests/test_projects.py tests/test_feedback.py \
    tests/test_web_contracts.py tests/test_web_capture_contracts.py \
    tests/test_web_static_boundaries.py -q
  ```

- `cd web && ALPHA_E2E_ML=1 npm run test:e2e:alpha`: **2 passed** against real
  Next, Python HTTP API, SQLite and leased worker. Tested sign-in, HttpOnly/token
  boundaries, bad-origin rejection, browser mask capture and upload, an actual
  FontForge/Potrace TTF export (validated file signature), persisted project,
  other-account denial, logout/replayed-session denial and disabled checkout.
  Optional ML step performed **real local EfficientSAM ONNX inference** through
  the authenticated API and required its model identity and PNG mask response.
  This is an inference/integration canary on a synthetic glyph, not a new broad
  segmentation-quality benchmark on natural scenes.
- `cd web && npm run test:e2e`: **14 passed**, including markerless/legacy/guided
  navigation, brush edits, install help and mobile layout regression checks.
- `cd web && npm test`: **138 passed in 19 files**. Covers auth/cookies,
  pricing/account contracts and duplicate completed-job React-key regression.
- `cd web && npm run lint`: **0 errors, 7 existing warnings** (image elements
  and anonymous PostCSS export).
- Final `npm run build` and `npm run typecheck`: **passed**. Production Next
  output includes the authenticated API routes, workspace and pricing page.
  Python compile checks and `git diff --check` also passed.
- Final alpha-only Python rerun after launcher/preflight fixes: **29 passed**,
  including `tests/test_alpha_dev.py`. Preflight with actual generated local
  config and writable-path probes passed; Compose `config --quiet` passed.
- A real temporary account was provisioned through `alpha_admin.py`, then
  `alpha-dev.sh` started API/worker/cleanup/Next. API and web readiness passed;
  SIGTERM exited gracefully (143) with both service ports closed. Throwaway
  account/data were removed; no default account was left behind.
- Independent bounded reviews covered Python auth, SQLite tenant/worker stores,
  and the frontend auth/proxy boundary. Findings were fixed with regressions;
  this is not a comprehensive external security audit.

## Deployment acceptance still required

- **Not deployed to a public host.** Set the real HTTPS origin, reverse-proxy
  client-IP rate limiting, backups and account provisioning on the chosen host.
- Docker Compose configuration was validated. A full container image build and
  running-stack/restore drill were **not** completed: the available Docker VM
  reported `No space left on device`. No unrelated Docker data was deleted.
  Local real-service integration was used instead; it does not prove container
  permissions, resource sizing or production reverse-proxy behavior.
- Paid checkout is deliberately unavailable. No cards are collected and no paid
  entitlement is granted. A provider integration, verified/idempotent webhooks,
  transactional credit/reservation/refund ledger and merchant acceptance tests
  remain necessary before billing can be enabled.
- No load/soak test, full multilingual font guarantee or full-suite Python
  claim is made here. Size the single-host resources against the expected
  invited cohort, particularly for optional ML and large glyph sets.
