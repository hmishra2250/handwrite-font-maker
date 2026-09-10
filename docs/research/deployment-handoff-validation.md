# Deployment handoff validation — 2026-09-11

## Scope

Audited the README against the private-alpha Compose file, Dockerfiles, environment
example, account CLI, preflight, model manifests, API contracts and runbooks.
The README is now the entry point for a fresh operator: prerequisites, modes,
credentials, model installation/mounts, resource sizing, provisioning, TLS,
readiness, acceptance, backups, upgrades and remaining paid-launch work.

The commit also includes the previously implemented private-alpha and automatic
vector-candidate work needed by these instructions. Model binaries, live accounts,
credentials, source photos and test captures are deliberately not included.

## Verified in this handoff pass

- A new isolated environment was generated using `alpha_admin.py --init-env`;
  permissions are private and the existing alpha environment was not overwritten.
- Preflight passed for the generated environment; placeholder credentials fail
  closed in the environment-example tests.
- Docker Compose configuration validated without printing resolved secrets.
  The 8 GB / 4 CPU API override, internal-only API and loopback web binding were
  checked against Compose's rendered JSON.
- Both existing local fp32 model pairs were verified by the documented installer:
  EfficientSAM-Ti (41,365,489 bytes) and SlimSAM (39,833,906 bytes), using pinned
  SHA-256 and size manifests. This was local integrity verification, not a new
  external download or a new model-quality benchmark.
- Full Python suite: **246 passed, 31 skipped**, in 427.65 seconds. Optional
  integrations were not all configured in this run; the skips are not passes.
- Additional handoff/admin/preflight/launcher regression set: **25 passed**,
  including document links, private build-context exclusions and resource knobs.
- Full frontend unit suite: **168 passed**. Typecheck passed; lint reported
  **zero errors, eight existing image/PostCSS warnings**.
- Standard desktop/mobile browser suite: **17 passed** in 34.7 seconds, including camera release/denial recovery, brush undo/reset, template flows and mobile overflow.
- Updated real-service alpha browser suite: **3 passed** in 29.1 seconds, including automatic SVG selection, login, SQLite/project persistence, real worker TTF generation and ownership/session checks. Browser-test caches are isolated from running development/phone previews.
- Staged files were checked against local secret values and private artifact paths;
  no matches were staged. `.dockerignore` now also excludes `.alpha`, backups and
  phone/E2E build outputs, not just Git credentials/model caches.

## Container rehearsal blocked by local capacity

An isolated Compose image build was attempted with a throwaway environment/project.
It stopped while installing FontForge/Potrace because Docker reported:

```text
E: You don't have enough free space in /var/cache/apt/archives/.
```

No unrelated Docker images, volumes or caches were pruned. This failure does not
establish a code/package failure, but it means a **fresh complete Docker build,
container startup and target-volume restore drill are not verified in this pass**.
Run the README recipe on a host with sufficient free Docker storage before real
user rollout. A config/preflight pass is not a substitute for this check.

The prior source-mode production HTTPS canaries, real font inspection and ML
limitations are documented separately in [capture diagnostics](capture-diagnostics.md).
A new `alpha-e2e` CI job now runs the real-service canary on a fresh Linux runner;
its remote result must be checked after push.

Physical phones, printing, Office installation, production TLS/proxy, backup restore
and paid checkout remain target/operator acceptance work, not inferred successes.
