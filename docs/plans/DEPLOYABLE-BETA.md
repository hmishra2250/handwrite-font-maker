# Deployable beta and nature-capture acceptance plan

## Requested outcome
Make remaining private-alpha infrastructure straightforward to deploy, and challenge extraction using real leaves, plants and satellite rivers. Preserve the existing uncommitted ML work. Execute local, reversible implementation/testing; do not create paid infrastructure, merchant accounts, ads, or deploy to an unspecified production project.

## Principles / decisions
- Identity is verified by Supabase Auth, not inferred from caller-supplied owner IDs or merely decoded JWTs.
- Deployable invite-only beta is the first operating profile; development remains explicit and localhost-only. Production settings fail closed. Paid mode must not masquerade as implemented if its ledger or provider verification is absent.
- Reuse Next/Python/Postgres/Supabase and existing mask/font contracts; do not add a queue service or retrain a model without evidence.
- Ownership, admission, lifecycle and cleanup are enforced server-side and tested against real local Postgres, not just mocks.
- Image experiments preserve source rights, disclose prompts/crops/corrections, record failures and distinguish qualitative review from labeled accuracy.

## Options
1. Shared staging password only: fastest, but no per-user isolation/metering/deletion and cannot safely graduate to multi-user use. Rejected as the sole architecture.
2. Invite-only authenticated multi-user beta on existing stack: chosen first deployment profile. Adds user ownership, quotas, durable jobs and cleanup; merchant/legal/real provider acceptance remains external.
3. Public subscriptions + large generative model: premature until real creator acceptance and cost; current pricing plan already favors one-off projects/packs first.

## Implementation stages / interface freeze
A. Identity and tenant boundary: deployment config validator; Next HttpOnly login/session/logout with CSRF protection; Python service credential + independently verified Supabase user; owner-scoped upload grants/jobs/object access; no client-selected bucket/path ownership. Per-user quota before uploads, previews and builds. No unauthenticated processing in production.
B. Durable job lifecycle: Postgres atomic claims; bounded retries and lease renewal/recovery; fencing prevents stale writes/publication; separate worker process; elapsed-time/CPU/memory/container limits. New migrations remain additive and tested on empty and existing-schema DB.
C. Retention and deletion: registered uploads (including abandoned), artifacts and jobs expire; access denied at expiry even before cleanup. Explicit authenticated delete request and retryable cleanup; avoid deleting sources still referenced by live jobs.
D. Deploy/operator path: all migrations applied, nonroot images, bounded containers, separate worker/cleanup commands, model-volume setup, fail-closed preflight, readiness checks, backup/rollback/operator instructions and CI tests. No free-tier RAM promise for ML.
E. Billing boundary: default invite-beta with enforced quotas and no fake checkout. After A-C are stable, implement project/packs test-mode checkout and idempotent signed-webhook ledger if the existing workbench can enforce stable project/revision semantics; otherwise make paid mode explicitly unavailable and document the exact unresolved boundary, not a placeholder advertised as working. Subscriptions are not the launch default.
F. Nature experiments: licensed leaves/plant/fern/satellite river corpus; deterministic/GrabCut/EfficientSAM/SlimSAM comparisons with recorded crop/points; preserve disconnected structures/holes; generate a real multi-character nature proof font where masks are usable. Rivers may need water/detail extraction rather than generic object silhouettes. No fabricated ground-truth or cherry-picked success rate.

## Pre-mortem and checks
1. Cross-user leakage via reused uploaded keys/artifact URLs: negative A/B tests for all endpoints, guided secondary glyphs and expiration; service key alone not sufficient user authorization.
2. Worker dies or stale lease overwrites new output: kill/reclaim/late-save tests, unique attempt artifact prefixes and transactional finalization; restart test against real Postgres.
3. Model mistakes background/water or costs explode: bounded source dimensions, durable quotas, single-flight model guard, worker time limits, recorded difficult examples, manual corrections remain authoritative.

## Acceptance evidence
- Existing Python/frontend/font/browser tests remain passing; new negative auth/ownership/expiry/quota tests.
- Real isolated Postgres tests: migrations, claims/recovery/fencing, duplicate admission, deletion retry and concurrent limits.
- Local container image build/runtime + ready-health check and safe deployment preflight; provider credentials not fabricated.
- Auth/provider billing mocks prove contracts only; actual hosted login/checkout/Office and merchant/legal review explicitly unverified until credentials/real clients exist.
- Provenanced real-image reports, inspectable contact sheets, saved masks/SVGs/TTF and typed proof, including failures and required corrections.
