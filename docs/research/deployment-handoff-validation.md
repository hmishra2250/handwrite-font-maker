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

## Container rehearsal completed after storage cleanup

The initial build stopped while installing FontForge/Potrace with
`E: You don't have enough free space in /var/cache/apt/archives/.`
The host had free space, but Colima's 60 GiB Docker disk was full. After authorized
cache/unused-image cleanup, the same Compose build completed without resizing or
restarting the shared VM. No existing Docker volumes, containers, source changes,
uploads, credentials or model files were deleted.

Cleanup included the regenerable npm cache, unused Docker build cache and selected
images not referenced by any container. A stopped unrelated container's
12,972,626,967-byte JSON log was archived privately (1,166,389,934-byte gzip), checked
with `gzip -t`, and cleared only after rechecking that the container remained
stopped and the log size had not changed. Its container and data volumes were
preserved. Colima's disk size remains 60 GiB.

Fresh container verification on **Linux aarch64, Python 3.12 and Node 22**:

- All four default Compose images built successfully: web, API, worker and cleanup.
- The isolated `hfm-handoff-check` stack started on loopback port 3308 with a new
  volume and throwaway accounts; API `/readyz` passed.
- The existing real-service browser suite ran against the production Docker web
  image, not Next development mode: **3 passed in 52.7 seconds**. It exercised
  login, automatic SVG selection, worker-generated TTF download/signature,
  persisted projects, cross-account denial, logout/session revocation, disabled
  billing and desktop/mobile layouts.
- The Python images also built successfully with `INSTALL_ML=true` and ONNX Runtime
  **1.29.0**. Both EfficientSAM-Ti and SlimSAM fp32 model pairs were verified inside
  the non-root API container through the read-only model mount.
- A stopped-stack SQLite online-backup snapshot plus object archive was restored
  into a **separate newly created volume**. SQLite integrity checks passed;
  all eight original object-file SHA-256 hashes, the original project/job IDs and
  both account IDs were preserved.
- Against the restored volume and ML-enabled image, the same browser suite passed
  again: **3 passed in 1.7 minutes**, including the optional explicit EfficientSAM
  inference assertion (`ALPHA_E2E_ML=1`) and a new real font build. This does not
  claim a new SlimSAM quality benchmark or native-phone acceptance.
- Compose now limits each alpha service's JSON logs to three 10 MB files.
  Both rendered configuration and all four actual container logging settings
  were checked. This limit does not bound database/object/model/cache storage.
- Handoff regression tests: **3 passed**; `git diff --check` passed.

The ignored local evidence is in `.alpha/deploy-docker-build.log`,
`.alpha/deploy-docker-ml-build.log`, `.alpha/deploy-docker-e2e.log`,
`.alpha/deploy-docker-ml-restore-e2e.log` and `.alpha/deploy-docker-backup/`.
The test credentials, backup and screenshots are private local artifacts, not
part of the repository. The existing source-mode alpha/phone previews were not
reconfigured. Linux amd64 builds and the eventual production host remain separate
operator acceptance checks.

After verification, only this rehearsal's containers/network and two explicitly
identified throwaway volumes were removed. The built images and private backup
were retained; the existing source alpha still returned HTTP 200.

The prior source-mode production HTTPS canaries, real font inspection and ML
limitations are documented separately in [capture diagnostics](capture-diagnostics.md).
A new `alpha-e2e` CI job now runs the real-service canary on a fresh Linux runner;
its remote result must be checked after push.

Physical phones, printing, Office installation, production TLS/proxy, production-host
backup recovery and paid checkout remain target/operator acceptance work, not
inferred successes. The isolated local container restore above is not a production
disaster-recovery certification.
