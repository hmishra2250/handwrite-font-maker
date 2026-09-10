# Deployment References: Supabase Auth/Storage, Stripe Checkout/Webhooks, Postgres Job Leases

Retrieved: 2026-09-10. Scope: official/primary docs only, for the current repo stack: Next.js `16.3.4`, `@supabase/supabase-js` `2.105.1`, Python `psycopg[binary]>=3.2`, and direct Stripe HTTP API requests (no new dependency recommendation).

Local evidence cache:

- Firecrawl/Supabase/Postgres/Next cache: `.firecrawl/deployment-references/*.md`
- Stripe official Markdown cache fetched from `docs.stripe.com/*.md`: `.firecrawl/deployment-references/stripe-*-curl.md`
- Local Next package docs: `web/node_modules/next/dist/docs/01-app/03-api-reference/...`

## 1. Supabase email/password auth and server verification

Primary docs:

- Supabase password auth: <https://supabase.com/docs/guides/auth/passwords> (`.firecrawl/deployment-references/supabase-auth-passwords.md`)
- Supabase JS `signInWithPassword` / `getSession` / `getUser` reference: <https://supabase.com/docs/reference/javascript/auth-getuser> (`.firecrawl/deployment-references/supabase-js-getuser.md`)
- Supabase SSR client/cookie guide for Next.js: <https://supabase.com/docs/guides/auth/server-side/creating-a-client?framework=nextjs&queryGroups=framework> (`.firecrawl/deployment-references/supabase-nextjs-ssr.md`)
- Supabase HttpOnly cookie troubleshooting: <https://supabase.com/docs/guides/troubleshooting/how-do-i-make-the-cookies-httponly-vwweFx> (`.firecrawl/deployment-references/supabase-troubleshooting-httponly-cookies.md`)
- Supabase cookie Max-Age troubleshooting: <https://supabase.com/docs/guides/troubleshooting/should-i-set-a-shorter-max-age-parameter-on-the-cookies-8sbF4V> (`.firecrawl/deployment-references/supabase-troubleshooting-cookie-max-age.md`)
- Next.js `cookies()` API: <https://nextjs.org/docs/app/api-reference/functions/cookies> and local `web/node_modules/next/dist/docs/01-app/03-api-reference/04-functions/cookies.md`

Implementation contract:

1. Email/password login uses `supabase.auth.signInWithPassword({ email, password })`. Supabase documents that email authentication is enabled by default and that hosted projects default to email confirmation before sign-in. The method logs in an existing user with email/password or phone/password and intentionally does not distinguish “account does not exist” from “wrong password” style failures.
2. Treat browser/client auth data as session transport, not authorization proof. Supabase documents that `getSession()` loads directly from storage such as local storage or cookies; if that storage is request cookies/headers, its values may be unauthentic. Do **not** authorize from decoded client claims or from `getSession().session.user` in server code.
3. For server authorization, call `supabase.auth.getUser(accessToken?)` when the task requires server-confirmed identity. Supabase documents that `getUser()` fetches the user record from the Auth server and validates the access-token JWT server-side. `getClaims()` is faster and signature-validating for asymmetric keys, but Supabase's cookie Max-Age troubleshooting page explicitly says only `getUser()` verifies whether the session is still valid server-side or the user logged out server-side.
4. Access tokens are JWTs with configurable expiry. Supabase documents that refresh tokens never expire and can be used only once. Rotate refresh/session cookies immediately after any refresh and handle concurrent refresh races.
5. If the app uses the Supabase browser client as documented by `@supabase/ssr`, do **not** force Supabase-managed cookies to `HttpOnly`: Supabase says this is not necessary and that browser-side code needs access to the refresh token to maintain a browser session. If this project intentionally chooses server-only, HttpOnly session cookies, route all auth refresh/storage calls through server Route Handlers/Server Actions and do not expect the browser Supabase client to maintain the session directly.
6. Next.js `cookies()` is async in this repo's Next 16 docs. It can read incoming cookies in Server Components and read/write outgoing cookies in Server Functions or Route Handlers. Cookie `.set` supports `secure`, `httpOnly`, `sameSite`, `path`, `maxAge`, etc.; HTTP cannot set cookies after streaming starts.

Suggested server-only cookie shape if implementing custom HttpOnly cookies:

- `__Host-hfm-access`: access token; `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, short `Max-Age` no longer than JWT expiry.
- `__Host-hfm-refresh`: refresh token; `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, longer `Max-Age` aligned with desired browser session UX.
- Do not set `Domain` on `__Host-` cookies. Treat `Max-Age` only as browser transport lifetime; `getUser()` remains the server-side authority for current validity.
- On refresh, write both new cookies atomically in the Route Handler response; if refresh fails, clear both cookies and require login.

Pitfalls:

- Never accept a client-supplied `user_id`; derive it from `getUser()` on the server.
- Never authorize from `jwtDecode`, `atob`, or `getSession().session.user` in server code.
- Refresh tokens are one-time-use, so parallel requests can race. Serialize refresh per session where possible, or make refresh idempotent from the app's point of view by retrying once after reading the newest cookies.
- Avoid caching responses that carry `Set-Cookie`; Supabase warns cached SSR responses with refreshed tokens can leak sessions between users.

## 2. Supabase Storage signed URLs and ownership

Primary docs:

- Storage access control: <https://supabase.com/docs/guides/storage/security/access-control> (`.firecrawl/deployment-references/supabase-storage-access-control.md`)
- Storage ownership: <https://supabase.com/docs/guides/storage/security/ownership> (`.firecrawl/deployment-references/supabase-storage-ownership.md`)
- Serving private assets / signed URLs: <https://supabase.com/docs/guides/storage/serving/downloads> (`.firecrawl/deployment-references/supabase-storage-serving-downloads.md`)

Implementation contract:

1. Use private buckets for user handwriting uploads and generated font artifacts unless an artifact is intentionally public.
2. Storage uploads require RLS policies on `storage.objects`; by default Supabase Storage does not allow uploads without RLS policies.
3. Ownership is assigned automatically when creating buckets/objects as an authenticated user; the owner is derived from the JWT `sub` claim and stored in `owner_id`. Supabase says `owner` is deprecated; use `owner_id`.
4. Ownership alone is not access control. Enforce access with RLS policies or server code. Policy patterns from Supabase docs include comparing `owner_id` to `auth.uid()::text` and restricting inserts by bucket and first folder component.
5. Generate signed URLs only server-side, after `getUser()` verifies the caller and after the server verifies ownership/authorization for the object path. A private bucket object can be served by a server-created, time-limited signed URL or by authenticated object endpoint plus Authorization header.
6. Supabase signed URLs use a Storage-specific internal signing key, separate from Auth JWT signing keys. Auth key rotation/revocation does not invalidate already-created signed URLs; they remain valid until their expiry. Keep signed URL TTLs short for private assets.

Pitfalls:

- Do not use the service key from browser/client code. Supabase says service keys bypass RLS and should not be shared publicly.
- Objects created with `service_key` or from the Dashboard may not have owner set. If the server uses service role for uploads, explicitly store/verify ownership in application tables or object metadata/path conventions before generating signed URLs.
- Do not assume deleting/revoking a Supabase Auth session revokes signed URLs; the Storage signed URL remains valid until expiry.

## 3. Stripe Checkout creation over HTTP

Primary docs:

- Create Checkout Session: <https://docs.stripe.com/api/checkout/sessions/create> (`.firecrawl/deployment-references/stripe-create-curl.md`)
- Checkout Session object: <https://docs.stripe.com/api/checkout/sessions/object> (`.firecrawl/deployment-references/stripe-object-curl.md`)
- Idempotent requests: <https://docs.stripe.com/api/idempotent_requests> (`.firecrawl/deployment-references/stripe-idempotent_requests-curl.md`)

Implementation contract:

1. Create Checkout Sessions server-side with `POST https://api.stripe.com/v1/checkout/sessions` using the Stripe secret key. Stripe's example sends form-encoded parameters including `success_url`, `line_items[0][price]`, `line_items[0][quantity]`, and `mode=payment`.
2. For one-time payments, `mode=payment`; `line_items` is required for `payment` and `subscription` modes. Use server-owned Stripe Price IDs and quantities computed/validated server-side; do not trust client-supplied amount or price IDs unless mapped through your own allowlist.
3. Use `client_reference_id` and/or `metadata` to carry internal IDs such as `user_id`, `job_id`, `order_id`, or `cart_id`. Keep metadata non-sensitive.
4. Use an `Idempotency-Key` header for `POST` creation retries. Stripe saves the first status/body for a key, including failures; keys are up to 255 characters, should be high entropy, and may be pruned after at least 24 hours. Reusing a key with different parameters errors.
5. Store the returned Checkout Session `id` and `url`; redirect the user to `url` or return it to the client. Fulfillment still waits for a verified webhook, not the browser success redirect.

Pitfalls:

- Do not create fulfillment state from the `success_url` page; the user may never return, and delayed payment methods may complete later.
- Use one idempotency key per logical create attempt, such as `checkout:{order_id}:{version}`. Do not use personal data like email as the idempotency key.

## 4. Stripe webhook verification and event semantics

Primary docs:

- Webhooks guide: <https://docs.stripe.com/webhooks> (`.firecrawl/deployment-references/stripe-webhooks-curl.md`)
- Signature troubleshooting/raw body: <https://docs.stripe.com/webhooks/signature> (`.firecrawl/deployment-references/stripe-signature-curl.md`)
- Event object: <https://docs.stripe.com/api/events/object> (`.firecrawl/deployment-references/stripe-event-object-curl.md`)
- Event types: <https://docs.stripe.com/api/events/types> (`.firecrawl/deployment-references/stripe-types-curl.md`)
- Refunds: <https://docs.stripe.com/refunds> (`.firecrawl/deployment-references/stripe-refunds-curl.md`)
- Next.js Route Handlers: <https://nextjs.org/docs/app/api-reference/file-conventions/route> and local `web/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/route.md`

Implementation contract:

1. Webhook Route Handler must accept `POST`, read raw bytes/string before JSON parsing, and verify the `Stripe-Signature` header against the endpoint secret (`whsec_...`). Next's Route Handler docs show webhook handlers using `await request.text()`. Stripe warns that whitespace changes, JSON parsing, key reordering, or encoding changes will fail verification.
2. Manual verification contract from Stripe docs:
   - Parse `Stripe-Signature`, keeping timestamp `t` and `v1` signatures; ignore non-`v1` schemes.
   - Build `signed_payload = timestamp + "." + raw_request_body`.
   - Compute HMAC-SHA256 using the endpoint signing secret as key and `signed_payload` as message.
   - Compare using constant-time comparison.
   - Enforce timestamp tolerance; Stripe libraries default to 5 minutes and warn not to set tolerance `0` because that disables recency checks. Keep server time synced with NTP.
3. Store `event.id` with a unique constraint before performing side effects. Stripe's Event object documents `id` as the unique identifier and `type` as the event type. Return `2xx` quickly after durable acceptance; defer long work to a local job table.
4. Fulfill paid one-time Checkout orders on verified `checkout.session.completed` only after checking the session's `payment_status`. Stripe says `payment_status` is one of `paid`, `unpaid`, or `no_payment_required` and can be used to decide fulfillment. For this product, create/enable paid work only when `payment_status === "paid"` unless a no-payment-required path is explicitly supported.
5. For delayed payment methods, also handle `checkout.session.async_payment_succeeded` / `checkout.session.async_payment_failed` if those payment methods are enabled; otherwise keep allowed payment methods narrow.
6. Refunds are separate from Checkout completion. Stripe says refunds can be full/partial after successful payment; you cannot refund more than the original charge; refund events include `refund.created`, `refund.updated`, `refund.failed`, and `charge.refunded` (including partial refunds). Listen to refund events to update entitlement/order state. Do not infer refunds solely from `checkout.session.completed`.

Pitfalls:

- Do not JSON-parse the webhook body before signature verification.
- Do not use the Dashboard endpoint secret for Stripe CLI forwarded events or vice versa; Stripe says these `whsec_` secrets differ.
- Automatic retries and manual resends can duplicate delivery. The database `event.id` uniqueness check is required even with HMAC verification.
- Stripe generates a new timestamp/signature on retries, so app idempotency must be based on event/session/payment IDs, not signature values.

## 5. Postgres `SKIP LOCKED` leases, fencing, and psycopg transactions

Primary docs:

- PostgreSQL `SELECT` locking clause: <https://www.postgresql.org/docs/current/sql-select.html> (`.firecrawl/deployment-references/postgres-select-skip-locked.md`)
- PostgreSQL explicit locking: <https://www.postgresql.org/docs/current/explicit-locking.html> (`.firecrawl/deployment-references/postgres-explicit-locking.md`)
- Psycopg transaction management: <https://www.psycopg.org/psycopg3/docs/basic/transactions.html> (`.firecrawl/deployment-references/psycopg-transactions.md`)

Implementation contract:

1. Use Postgres row locks for queue claiming, not for the whole OCR/font-generation workload. PostgreSQL says `FOR UPDATE` locks selected rows against concurrent updates/deletes/row-locking until the current transaction ends. It also says `SKIP LOCKED` skips rows that cannot be immediately locked, gives an inconsistent view, and is suitable for queue-like tables rather than general-purpose reads.
2. Claim jobs in a short transaction: select eligible rows with `FOR UPDATE SKIP LOCKED`, update their lease fields, and commit. Example shape:

   ```sql
   with candidate as (
     select id
     from jobs
     where status = 'queued'
        or (status = 'processing' and lease_until < now())
     order by created_at, id
     for update skip locked
     limit $1
   )
   update jobs j
      set status = 'processing',
          lease_token = gen_random_uuid(),
          lease_until = now() + interval '5 minutes',
          attempt = attempt + 1,
          updated_at = now()
     from candidate
    where j.id = candidate.id
   returning j.id, j.lease_token, j.attempt;
   ```

3. Use fencing on every later worker update. Include both `id` and `lease_token` (or a monotonic attempt/version) in `WHERE` clauses:

   ```sql
   update jobs
      set status = 'completed', lease_until = null, updated_at = now()
    where id = $1 and lease_token = $2;
   ```

   If `rowcount == 0`, the worker lost the lease and must stop writing results.
4. Extend leases with the same fencing predicate (`where id = $1 and lease_token = $2`) before long processing stages. Choose lease durations longer than normal heartbeat intervals but short enough for recovery after worker death.
5. Use existing `psycopg` (`psycopg[binary]>=3.2` in `pyproject.toml`). Psycopg documents that even a simple `SELECT` starts a transaction by default and can leave connections idle-in-transaction; prefer `autocommit=True` plus explicit `with conn.transaction():` blocks for atomic claim/finish steps, or commit/rollback immediately.

Pitfalls:

- `SKIP LOCKED` does not make fair scheduling guarantees; enforce deterministic `ORDER BY created_at, id`, but understand locked rows are skipped and may be claimed later.
- Do not keep a transaction open during OCR, image processing, font generation, uploads, or Stripe calls. Row locks release only at transaction end and long transactions cause contention/idle-in-transaction problems.
- At `READ COMMITTED`, PostgreSQL documents possible ordering surprises with `ORDER BY` plus locking under concurrent updates. For queues this is usually acceptable; do not use this pattern for user-visible sorted reads.
- Use a unique constraint for `stripe_event_id` and/or `checkout_session_id` in fulfillment tables so webhook retries cannot enqueue duplicate work.

## 6. Cross-service deployment invariants

- Server trust boundary: server derives `user_id` only from Supabase `getUser()`; server derives paid entitlement only from verified Stripe webhooks; server derives storage access only from DB/object ownership checks.
- Client can initiate login, upload selection, and checkout redirects, but cannot assert identity, price, paid status, job ownership, or artifact path ownership.
- Durable processing path: verified webhook inserts/updates an order and enqueues a job in the same Postgres transaction; workers claim with `SKIP LOCKED`, process outside the claim transaction, and write completion only with lease fencing.
- Private artifact serving path: request -> `getUser()` -> DB/object ownership check -> short-lived Supabase signed URL -> return URL. Never return service-role credentials or public bucket URLs for private files.

## 7. Render Blueprint service types for invite-beta deployment

Primary docs:

- Blueprint specification: <https://render.com/docs/blueprint-spec> (`.firecrawl/deployment-references/render-blueprint-spec.md`)
- Private services: <https://render.com/docs/private-services> (`.firecrawl/deployment-references/render-private-services.md`)
- Private network: <https://render.com/docs/private-network> (`.firecrawl/deployment-references/render-private-network.md`)
- Web services: <https://render.com/docs/web-services> (`.firecrawl/deployment-references/render-web-services.md`)
- Background workers: <https://render.com/docs/background-workers> (`.firecrawl/deployment-references/render-background-workers.md`)
- Cron jobs: <https://render.com/docs/cronjobs> (`.firecrawl/deployment-references/render-cronjobs.md`)
- Docker on Render: <https://render.com/docs/docker> (`.firecrawl/deployment-references/render-docker.md`)
- Health checks: <https://render.com/docs/health-checks> (`.firecrawl/deployment-references/render-health-checks.md`)
- Environment variables / groups: <https://render.com/docs/configure-environment-variables> and Blueprint env sections (`.firecrawl/deployment-references/render-env-vars.md`, `.firecrawl/deployment-references/render-blueprint-spec.md`)
- Deploy/pre-deploy command semantics: <https://render.com/docs/deploys#pre-deploy-command> (`.firecrawl/deployment-references/render-deploys.md`)
- Free instance limits: <https://render.com/docs/free> (`.firecrawl/deployment-references/render-free.md`)

Current official field facts:

1. Blueprint service `type` is one of `web`, `pserv`, `worker`, `cron`, or `keyvalue`; `pserv` is the private service type and `worker` is the background worker type.
2. `runtime: docker` tells Render to build from a Dockerfile. For Docker services, use `dockerfilePath`, `dockerContext`, and optional `dockerCommand`; non-Docker `buildCommand`/`startCommand` are not the Docker path.
3. `healthCheckPath` is **web services only**. Render health docs say private services only support default TCP checks; therefore do not put `healthCheckPath` on the private Docker API or workers.
4. Private services are not publicly reachable and do not get an `onrender.com` subdomain. Other Render services in the same workspace/region can reach them over the private network. Background workers can send private-network requests but cannot receive inbound private-network traffic.
5. Render Blueprints can expose a private service host/port to another service with `fromService` and `property: host`, `port`, or `hostport`. `hostport` is specifically documented for connecting to a web/private service over the private network.
6. `envVarGroups` can be declared top-level and attached to each service with `- fromGroup: group-name`. Environment groups cannot use `sync: false` and cannot reference service properties; keep secrets that require dashboard entry as service-level `envVars` with `sync: false` or enter them manually.
7. `preDeployCommand` runs after build and before deploy, is recommended for database migrations, runs on a separate instance from the running service, cannot persist filesystem changes into the deployed instance, has no attached persistent disk access, times out after 30 minutes, and if it fails the deploy fails while the previous successful deploy keeps running. It is available for paid web services, private services, and background workers.
8. Free instances are only supported for Static Site, Web Service, Postgres, and Key Value. Other service types do not support Free instances. Private services and background workers therefore need a paid compute plan; current private/worker plan IDs start at `0.5c-512mb`. For invite-beta ML processing, do not set ML API/worker/cleanup to `free`.
9. For Docker-based services, Render automatically translates service environment variables into Docker build arguments available during image build, and also exposes them as runtime environment variables. Therefore a Dockerfile with `ARG INSTALL_ML` and `ARG INSTALL_MODELS` can be configured from `render.yaml` service-level `envVars` using the same keys. Do not use this mechanism for secrets, because Render warns sensitive build args can be included in the generated image; `INSTALL_ML=true` and `INSTALL_MODELS=efficientsam` are non-secret build toggles.

Exact `render.yaml` field examples for invite-beta shape. Command names below are illustrative placeholders for service roles; use the repo/runbook's actual commands when finalizing `render.yaml`:

```yaml
# render.yaml fragment; fill sync:false values in Render Dashboard on initial Blueprint creation.
envVarGroups:
  - name: handwrite-invite-beta-shared
    envVars:
      - key: NODE_ENV
        value: production
      - key: PYTHONUNBUFFERED
        value: "1"
      - key: HFM_ENV
        value: invite-beta
      - key: HFM_PUBLIC_BASE_URL
        value: https://handwrite-font-maker.onrender.com

services:
  # Public Next.js frontend. Only public web service gets an HTTP healthCheckPath.
  - type: web
    name: handwrite-font-maker-web
    runtime: node
    rootDir: web
    plan: 0.5c-512mb
    buildCommand: npm ci && npm run build
    startCommand: npm run start -- -H 0.0.0.0 -p ${PORT:-10000}
    healthCheckPath: /
    envVars:
      - fromGroup: handwrite-invite-beta-shared
      - key: NEXT_PUBLIC_SUPABASE_URL
        sync: false
      - key: NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
        sync: false
      - key: HFM_API_SCHEME
        value: http
      - key: HFM_API_HOSTPORT
        fromService:
          name: handwrite-font-maker-api
          type: pserv
          property: hostport

  # Private Docker API. No onrender.com URL and no healthCheckPath; Render uses TCP checks.
  - type: pserv
    name: handwrite-font-maker-api
    runtime: docker
    plan: 1c-2g
    dockerfilePath: ./Dockerfile.api
    dockerContext: .
    dockerCommand: handwrite-font-web-api --host 0.0.0.0 --port 10000
    preDeployCommand: ./scripts/render_migrate.sh
    envVars:
      - fromGroup: handwrite-invite-beta-shared
      - key: DATABASE_URL
        sync: false
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: STRIPE_SECRET_KEY
        sync: false
      - key: STRIPE_WEBHOOK_SECRET
        sync: false
      # Non-secret Docker build toggles: Render exposes envVars as build args for runtime: docker.
      - key: INSTALL_ML
        value: "true"
      - key: INSTALL_MODELS
        value: efficientsam

  # Continuous ML/job worker: polls DB/queue; can call private API/DB but receives no inbound traffic.
  - type: worker
    name: handwrite-font-maker-worker
    runtime: docker
    plan: 1c-2g
    dockerfilePath: ./Dockerfile.api
    dockerContext: .
    dockerCommand: handwrite-font-maker worker
    maxShutdownDelaySeconds: 300
    envVars:
      - fromGroup: handwrite-invite-beta-shared
      - key: DATABASE_URL
        sync: false
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: HFM_API_HOSTPORT
        fromService:
          name: handwrite-font-maker-api
          type: pserv
          property: hostport
      # Set these on every Docker service whose image must include ML deps/models.
      - key: INSTALL_ML
        value: "true"
      - key: INSTALL_MODELS
        value: efficientsam

  # Periodic cleanup. Use cron if cleanup is periodic/bounded; command must exit.
  - type: cron
    name: handwrite-font-maker-cleanup
    runtime: docker
    plan: 0.5c-512mb
    schedule: "17 */6 * * *"
    dockerfilePath: ./Dockerfile.api
    dockerContext: .
    dockerCommand: handwrite-font-maker cleanup --expired-leases --old-artifacts
    envVars:
      - fromGroup: handwrite-invite-beta-shared
      - key: DATABASE_URL
        sync: false
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
```

Render-specific pitfalls for the runbook/compose mapping:

- Keep migrations in exactly one `preDeployCommand` to avoid concurrent migration races across web/API/worker deploys. Prefer the private API service as the migration owner if it is the service that owns backend schema compatibility.
- If the API must be reachable by the Next web service only, make it `type: pserv`, not `type: web`. Render private services receive private-network traffic; background workers do not.
- Use `fromService.property: hostport` for the internal API address when possible; have the app combine it with `HFM_API_SCHEME=http` if it needs a URL. Avoid hard-coding internal hostnames unless the hostname is confirmed; Render documents stable internal hostnames and Blueprints can reference the current service property directly.
- Do not set `plan: free` for private API, background worker, or cleanup cron. Free is unsupported for private/worker/cron service types, and Free web services spin down on idle.
- If the private API exposes `/healthz`, it is still useful for manual/internal checks, but Render's Blueprint `healthCheckPath` field will not apply to `pserv`.
- For current Dockerfiles that declare `ARG INSTALL_ML=false` and `ARG INSTALL_MODELS=none`, put `INSTALL_ML: "true"` and `INSTALL_MODELS: efficientsam` in the `envVars` of each Docker service whose build should include EfficientSAM. Because each Render Docker service builds its own image, setting the keys on the API does not automatically set them on the worker or cleanup service.
