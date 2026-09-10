# Validation evidence and remaining launch gates

Date: 2026-09-10. This report distinguishes baseline, changed-code verification, and unverified production claims.

## Baseline before feature edits

- `npm ci`: installed checked-in lockfile; npm audit **14** vulnerabilities (**1 critical, 9 high, 3 moderate, 1 low**). Audit is dependency evidence, not proof of app exploitability.
- `npm test`: **25 passed** across 6 files.
- `npm run typecheck`: passed.
- `npm run lint`: passed with 2 warnings (raw image preview and anonymous PostCSS export).
- `npm run build`: passed under Next **16.2.4**.
- Initial `npm run test:e2e`: blocked by missing Chromium executable. Installed Playwright's existing required Chromium; rerun **13 passed** in 44.1s. This is the old demo/landing flow, not new real font capture evidence.
- Initial `.venv/bin/pytest -q`: **22 passed, 8 skipped, 1 failed, 1 error** before system font tools. Failure: missing potrace masked expected marker error. Error: accidentally collected `test_capture(image,params)` script helper. Installed existing required Potrace and FontForge. A baseline rerun excluding the accidentally collected helper completed 9 tests, including real full-font builds, before manual interruption at 898.39s while a later FontForge subprocess ran for several minutes. Observed test wall times: full synthetic build 117.04s, clean API build 132.86s, noisy API build 115.41s, warped API build 48.80s. This was a busy shared host, not a production performance benchmark; the full suite was **not** reported passed. Fresh changed-code checks follow below.

## Plan review

Independent Terra delivery review identified five blocking contract gaps: missing page identity, unpersisted accepted corners, unspecified mask/baseline coordinates, ambiguous public/private boundary and premature webfont-format claims. Final contract freeze in `PRODUCT-PLAN.md` resolves these. Reviewer recheck: no remaining fatal contract mismatch. This is an advisory direct-delivery review, not proof that implementation or production security is complete.

## Changed-code verification

Completed checks; final full-suite status is recorded separately below:

- Security dependency patch/pin pass: `npm ci --ignore-scripts && npm audit` **0 vulnerabilities**, no forced major migration or new feature dependency.
- `docker compose config --quiet`, Python compileall and `git diff --check`: passed at this checkpoint; rerun after final edits.
- Real localhost API canary: uploaded accepted PNG masks for A/i/O/g/-, created and reloaded a persisted guided job, downloaded actual TTF (2,172 bytes), loaded it through Pillow/FreeType and rendered a proof. **Succeeded in 3.187s** for five glyphs. Visual inspection confirmed A crossbar, i dot, O hole, g descender and dash. This is not a 94-glyph or real-user benchmark. Raw report: `research/guided-api-smoke.json`.

## Deployment verification

No public deployment performed. Environment inspection found no configured `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `RENDER_API_KEY`, `VERCEL_TOKEN`, `STRIPE_SECRET_KEY` or `WORKER_API_BASE_URL`. This does not prove no CLI account exists; it establishes this workspace is not configured for the intended live backend. Independent of credentials, public auth/ownership, quotas, durable workers, retention/deletion, payment entitlements and Office usability remain release gates.

## Performance/cost interpretation

`scripts/benchmark_font.py` measures a real local input, subprocess timing, CPU and output size; it does not establish cloud bills or p95. Its compute projection is explicitly hypothetical. Baseline full-font jobs on this shared host took substantially longer than the technical research's initial 5–30-second target. No sub-cent or latency promise is made from unmeasured assumptions.

The retained synthetic sample benchmark completed: **612.787s wall**, **59.85s parent+child CPU**, 94 Potrace calls totaling 3.00s wall, 2 FontForge calls totaling 527.95s wall, 94 nonempty glyphs, TTF 105,620 bytes / OTF 98,096 bytes. Raw report: `research/local-build-benchmark.json`. Builder execution began before pipeline edits; this is baseline evidence, not a new-path speed result. The report's $0.017771 compute figure is a hypothetical provisioned-resource calculation, **not an invoice**. It excludes all noncompute costs.


## Historical initial integration checkpoint

- Python suite excluding the two slow full-sheet font suites: **58 passed in 38.77s** (`pytest -q --ignore=tests/test_build_e2e.py --ignore=tests/test_e2e_api.py`). This includes guided font generation, foreground, contracts and alignment; it is not a full-suite pass.
- Foreground tests after extreme-aspect-ratio rejection: **11 passed in 5.66s**; no stretching of narrow images.
- Fresh localhost guided API after backend serialization changes: **5 glyphs, succeeded in 1.027s, TTF 2,172 bytes**, actual downloaded font loaded by FreeType. Single-run busy-host evidence, not production latency. `research/guided-api-smoke.json`.
- Actual object API canary: synthetic color image → `/capture/foreground` → accepted mask → upload → persisted guided job → downloaded TTF → FreeType proof: **succeeded in 1.317s, TTF 1,756 bytes**. Hole and detached dot assertions passed and rendered proof visually checked. `research/object-api-smoke.json`.
- Style experiment: **24 actual SVG/PGM traces**, 2 interpretations × 4 sizes × 3 tracing configurations; independent review reran it. [Results and limitations](research/vector-style-experiments.md).
- Review identified horizontal-stroke erasure, letterboxed corner coordinates, upstream upload errors, artifact casing, partial-font proof fallback and lint/test failures; fixes passed the bounded independent re-review and targeted regressions. Market positioning now limits current export claims to TTF/OTF.
- Earlier updated 94-glyph benchmark **failed structural validation**; do not use it as a speed/success result. Subsequent corrected full 94-glyph synthetic build succeeded with structural validation in **137.27s** on the busy host. Full-suite and later performance evidence are listed below.

- Real Chromium object journey against localhost Next3011/API8011: upload color source, select object method, extract, accept `A`, build, load actual FontFace, download TTF (**1,772 bytes**), type unsupported `B` and observe missing-character warning. **No browser page errors**. This is not a mocked API test. Evidence: `research/browser-object-smoke.json`; canary `scripts/smoke_capture_browser.cjs`.

## Previous private-alpha integration checks

**Result: local/private-alpha verification passed. Public SaaS release remains gated.**

- Frontend: **49 tests passed** across 9 files; typecheck passed; production build passed on Next16.3.4; lint **0 errors / 6 warnings** (raw preview images and PostCSS anonymous export); npm audit **0 reported vulnerabilities**. Audit is not a security guarantee.
- Standard Playwright Chromium suite: **13 passed**. An initial 12/13 run hit a stale generated Next dev route cache; clearing only generated cache restored `/help/install-fonts`. No source-route workaround was required.
- New full markerless regression: **1 passed in 7.02s**. Render quiet page with A/i/O/g/-, put on contrasting desk, detect corners, rectify/extract/build, assert exactly those five nonempty glyphs and load the real TTF in FreeType. This caught blank-cell guide contamination that isolated mask tests missed. Final template uses side ticks outside extraction regions, not interior writing lines.
- Fresh combined changed-path check: **36 passed in 27.52s** for diagnostics, guided masks, markerless alignment/build and capture contracts. Backend then added two actual-byte (forged size metadata) regressions: capture contracts **10 passed**, broader backend/alignment/guided/foreground set **47 passed**.
- Python compileall, `docker compose config --quiet` and `git diff --check`: passed. Docker configuration validation is not a container runtime/deployment test.
- A full run overlapping ongoing edits finished **74 passed / 2 failed in 695.43s**: its imported markerless code predated the side-tick fix, and one export picked up a rejected temporary OTF flag. This run is not acceptance evidence. After final freeze, targeted font/pipeline/capture checks passed **38 tests in 9.64s**. The fresh frozen full suite then passed **78 tests in 575.97s (9m35s), no failures or skips**. This is the final Python acceptance run, including both previously failing cases.

## Quality scope

Twenty-four synthetic style/resize/tracing experiments plus four real-photograph vector probes were run. They demonstrate tradeoffs, not segmentation accuracy on a representative corpus. Current exports are monochrome outlines; original photographic color/texture and automatic completion of missing letters are not implemented. At that earlier checkpoint learned segmentation candidates were research-only. The subsequent ML milestone below supersedes that limitation.

Real printer/phone captures, end-user acceptance, Windows/macOS Office installation/embedding, cloud p95/cost, database migration on staging and tenant security remain unverified. Local alpha success does not justify “world-class”, production-ready, revenue or universal compatibility claims.

## Font export profiling

A native process sample identified FontForge CFF generation/autohinting as the remaining dense-sheet hotspot. No controlled speedup is claimed from removing geometry cleanup. An OTF `no-hints` experiment produced unreadable output and was rejected; OTF uses default generation. TTF exports omit instructions, with structural validation rejecting unexpected instruction tables. See [official FontForge generate flags](https://fontforge.org/docs/scripting/python/fontforge.html). This display-font choice still needs small-size/Office rendering validation; it does not solve the CFF hotspot.

Final frozen full-sheet test durations on this host: clean 86.65s, noisy 166.31s, bright 125.64s, dark 18.16s, perspective 34.07s, combined distortions 25.59–26.47s; standalone synthetic build 75.55s. These are test durations on a shared development machine, not a controlled production latency distribution or an attributable before/after speedup.

A final independent read-only review found no P0/P1 in the bounded font-export, markerless-regression and reporting scope. This is not a comprehensive production security audit. Local preview was verified at `http://127.0.0.1:3011` (HTTP200); the Python worker runs on localhost8011.

## Local pretrained segmentation milestone

Two real optional CPU ONNX models are now integrated: EfficientSAM-Ti (`box-model`, genuine rectangle prompts) and SlimSAM-77 (`model`, keep/exclude points). Default Auto without keep points remains GrabCut. Explicit model requests never silently claim a classical result as ML. Runtime and model installation are optional, weights pinned/hash-verified, requests never download weights or transmit captures to an inference provider.

- Final Python suite: **121 passed in99.15s**, including the slow font suites and four atomic/hash-verified installer regressions. No failures or skips.
- Frontend integration before the final layout-only follow-up: **64 tests passed**, typecheck passed, production build passed, standard Chromium suite **14 passed**; lint **0 errors /6 existing warnings**, npm audit **0 reported vulnerabilities**. Final layout rechecks are recorded below.
- Real local API canaries: SlimSAM → accepted mask → persisted font job → downloaded TTF/FreeType **succeeded in3.805s,2,328bytes**; EfficientSAM **1.797s,2,408bytes**. Both assert a hole, detached dot and main shape. These are synthetic single-run canaries, not representative latency or photographic accuracy.
- Actual Chromium model flows, both families: point/box request, actual method/modelId, hole/dot/main-shape pixels, brush changes, exact undo/reset, accepted glyph, generated FontFace loaded, real TTF download. Classical flow separately rechecked to catch `modelId:null` compatibility. No page errors. Reports in [retained evidence](research/ml-evidence/README.md).
- Independent review caught the Next/Python box-point contract fork, initial canvas-load editing race and accepting a stale blob while async mask encoding was pending. Fixes reject invalid box prompts, guard stale loads/exports, disable acceptance during edits, and expose encoding errors rather than silently reusing old pixels. Targeted delayed/null-blob tests pass; focused reviewer recheck approved prior P1 fixes.
- Python compileall, `pip check`, `docker compose config --quiet` and `git diff --check` passed. **Container image/runtime test not performed:** Docker daemon socket unavailable. Compose validation is not deployment verification.

### Measured model tradeoffs

The five synthetic fixtures are diagnostic, not a representative accuracy corpus. SlimSAM receives reference-assisted keep/exclude clicks; EfficientSAM and GrabCut receive boxes only. The interior-detail reference intentionally differs from a silhouette, so aggregate scores are not universal model rankings.

| Path | Mean IoU | Boundary F1 | Exact topology | Isolated warm median | Peak process RSS |
|---|---:|---:|---:|---:|---:|
| GrabCut | 0.719877 | 0.838278 | 3/5 | Not part of isolated ML probe | Not measured here |
| SlimSAM fp32 | 0.715390 | 0.781824 | 3/5 | 1.8791s | 2.71GB |
| SlimSAM int8 | 0.693304 | 0.797468 | 1/5 | 1.9807s | 3.62GB |
| EfficientSAM-Ti box | 0.730246 | 0.865035 | 3/5 | 0.7055s | 1.39GB |

The isolated probes have only four calls (three warm) on a shared Mac, fixed2/1 ORT threads. They are not cloud p95/cost figures. Smaller quantized weights did not imply lower memory or faster inference; SlimSAM fp32 remains the experimental point-model default. EfficientSAM is an explicit alternative, not auto-promoted from five samples. Detailed metrics, failure masks and the qualitative-only fruits-photo probe are retained under `research/ml-evidence/`.

Rejected experiments: invalid SlimSAM box labels2/3 caused background/inverse selection; corrected to supported point prompts. Disabling ORT memory arenas reduced one observed peak but caused abnormal teardown; not shipped. Neither experiment is counted as success.

### Remaining north-star/launch work

The milestone does **not** complete universal object segmentation, photographic color/texture fonts, automatic alphabet/style completion, representative real-printer/phone validation, low-memory production serving, Office acceptance, auth/ownership, durable jobs, retention/deletion, billing/quotas or public deployment. Model switching/multi-worker resource ceilings and full session economics still require staging measurements. Current pricing remains a hypothesis: sell projects/revisions, reuse accepted masks, and meter segmentation attempts separately. No paid inference API, cloud deployment, ads or billing was activated.

### Final layout and frozen-build recheck

After the last layout fix, the production build passed again (including TypeScript); frontend unit suite **64 passed**, lint **0 errors /6 warnings**, and all **14 Chromium regressions passed** against the final production preview using a temporary no-webserver Playwright configuration. Real-model Chromium canaries against that production build passed for both model families, including actual400×400 source masks, hole/dot/main pixels, edit/undo/reset and downloaded fonts. Desktop1280px: mask frame/column right608.8px inside the card; mobile390px: frame/column right341px and document width390px, no horizontal overflow. Long model IDs wrap instead of expanding implicit grid tracks. The baseline guide now overlays only the canvas plane, not editing controls.

Local production-build preview is running at `http://127.0.0.1:3011`, connected to the localhost8011 Python worker with installed models. This is a local preview, not an externally deployed service. Current milestone changes are local/uncommitted; the earlier requested push remains the previous private-alpha commit.

## Invite-beta deployment and real-nature milestone (2026-09-10)

This section supersedes the earlier statements that auth/ownership, durable jobs, quotas, and cleanup were entirely unimplemented. It does **not** supersede the remaining hosted-provider, Office, billing, or real-printer validation gaps.

### Implemented boundaries

- Explicit fail-closed deployment modes; invite-only Supabase identity via server-controlled app metadata; HttpOnly/Secure cookies, exact-origin mutation checks, same-origin authenticated object proxy, no-store responses and noindex beta pages.
- PostgreSQL owner checks and deny-by-default RLS; serialized per-account upload/byte/preview/build/active-job caps; accepted uploads must be complete and owned. These are safety quotas, not billing credits.
- Separate bounded worker processes, leased claims/heartbeats, attempt budgets, transient failure retries, fenced artifact publication, attempt-scoped storage keys and cleanup-visible intent before upload.
- Additive checksum-tracked transactional migrations, preflight, aggregate operations status, non-root API image, standalone private Compose profile, Render private API/worker/cleanup blueprint, and CI definition.

### Actual-image experiments

Eight provenance-tracked real photographs/satellite images were sourced; six cases were executed with explicit crops/prompts and real optional model weights. The selected ornament font contains only three reviewed silhouettes: maple leaf (GrabCut), oak leaf (EfficientSAM), and fern (EfficientSAM). The TTF/OTF were generated and the actual TTF rendered through FreeType. River meander, delta, and braided-river probes failed review and were excluded. The satellite water-color helper remains an experiment, not a shipped feature. No automatic readable alphabet or photo-color/texture font is claimed. See [case report](research/nature-experiments.md) and [retained evidence/attribution](research/nature-evidence/README.md).

### Local runtime and remaining evidence gaps

- Actual isolated PostgreSQL → supervised subprocess → Potrace/FontForge canary generated TTF/OTF in one attempt and rendered the TTF. This uses local object storage, not hosted Supabase. [Report/proof](research/deployment-evidence/README.md).
- Production-build beta browser checked the real runtime login gate, unauthenticated/cross-origin rejection, no-store, noindex, and mobile width. Login/logout UI behavior used explicit mocks; it is not hosted identity verification.
- Docker Compose configurations validate. A real PostgreSQL16 container ran via the existing Colima context using an isolated tmpfs volume. Full API/web image builds were **not verified locally** because the existing Docker VM disk was full; no unrelated images, volumes, or cache were pruned. Added CI has not been run remotely.
- No cloud resources, domain, billing, paid inference, or advertisements were activated. Actual hosted login/refresh/storage canaries, restore/load testing, model switching memory ceilings, real printer/phone captures and Word/PowerPoint acceptance remain gates. The deployment runbook lists exact steps and test criteria. Code/configuration readiness is not a production-readiness guarantee.

### Final integration checks

- Frontend frozen suite: **90 passed** across 13 files; typecheck and production build passed; lint **0 errors / 6 existing warnings**. Final production-preview Chromium suite **14 passed (2.3s)**; beta browser gate/mobile check passed.
- Real browser → font journeys passed for GrabCut (TTF 1,772 bytes), EfficientSAM (2,432 bytes), and SlimSAM fp32 (2,328 bytes), with actual font loading, mask topology checks and repair/undo/reset. These are single synthetic canaries, not latency or accuracy benchmarks.
- Real PG owned-job worker canary: **one attempt**, TTF 1,744 bytes, OTF 1,848 bytes; final artifact access passed the tenant registry predicate and FreeType rendered the font.
- Actual migration runner applied all four migrations to isolated PostgreSQL, then `--check` passed; aggregate operations status ran successfully. Both Compose configs, Python compileall, pip check, and `git diff --check` passed. Frontend audit reported 0 vulnerabilities at this milestone (not a security guarantee).
- Independent read-only reviews found no remaining P0/P1 in the bounded worker/deploy and auth/tenant scopes. Tests caught and fixed staged artifact visibility, in-flight deletion deadlines surviving retry failures, concurrent one-shot upload admission, and logout refresh rotation/outage handling. A real browser canary also caught the local pseudo-user accidentally activating the PG tenant registry; local HTTP-created jobs now remain unowned and a regression locks this behavior.

- **Final frozen Python acceptance run: 155 passed in 117.43s, no failures or skips**, with `TEST_DATABASE_URL` pointing to isolated PostgreSQL16. This includes full-sheet font suites, auth/owner/quota/deletion tests, migration checks, leased worker recovery and the local HTTP pseudo-owner regression.
- Changes remain local/uncommitted. The local real-model preview was restored at `http://127.0.0.1:3011`; temporary fake-auth beta preview and disposable verification database were stopped after testing. This is not public deployment.

## Saved-project and usable-font MVP completion (2026-09-10)

### Shipped locally

- Owner-scoped saved projects with optimistic revisions, serialized/debounced autosave, uploaded-mask reuse, guided and template restore, ten-project cap and seven-day inactivity expiry. PostgreSQL cleanup protects shared live project/job inputs and purges expired project metadata. Historical owned job pointers remain valid project metadata after their separate 24-hour build lifetime; they do not grant expired artifact access.
- Five-character synthetic starter, target-glyph review, actionable heuristic warnings, and baseline/scale/spacing adjustments applied to actual exported outlines/advance widths. No generated missing alphabet or photo-texture font claim.
- Real ZIP download containing TTF/OTF, character map and rights/installation notes. Optional consent-based account-linked event counts and text-only feedback with bounded quotas and 30-day cleanup; no image attachments or third-party analytics.

### Final verification evidence

- **170 Python tests passed in256.91s, no failures or skips**, using isolated PostgreSQL16. Includes actual FontForge-exported metric/bounding-box checks, bundle contents/escaping, project owner/CAS/quota/ref-retention/deletion, historical job pointers, and feedback consent/quota/retention.
- **107 frontend tests passed** across16 files; typecheck and production build passed. Lint: **0 errors,7 warnings** (image elements used for capture/review and existing PostCSS export style). No new dependency was added for this MVP slice.
- **14 Chromium regressions passed** against the final production preview. Real guided canary: five PNG uploads, save/reload of five glyphs, A scale1.2/spacing0.1 saved and rebuilt, actual TTF2,552bytes, OTF2,700bytes and ZIP4,410bytes; rebuild made no additional mask uploads. Idle project revision stayed stable; no browser JavaScript errors; mobile document width390px. [Retained package, report and screenshots](research/mvp-evidence/README.md).
- Real unbuilt markerless **and** legacy sheet canaries: upload and autosave before any build, reload, decode restored photo, and verify the build control is enabled with saved input/corners. These prove persistence, not a new real-printer/phone font-quality benchmark.
- Final actual-model browser canaries passed for EfficientSAM (TTF2,432bytes) and SlimSAM fp32 (TTF2,356bytes): prompt extraction, counter/dot/main topology, brush, exact undo/reset, real font loading/download and390px layout. Synthetic canaries are not representative accuracy or latency measurements.
- All **six migrations** applied through the real runner to disposable PostgreSQL; subsequent checksum check and aggregate operations snapshot passed. Python compileall, pip check and `git diff --check` passed.
- Regression/review corrections include queued-project identity guards, latest revision chaining, no idle autosave loop, failed-create/hydration preservation, conditional mask-reference merging, replaced-sheet upload cancellation, build-time project-switch protection, and stale source/job response guards.

### Remaining gates

This is a verified local MVP implementation, not a public/paid deployment. Hosted Supabase auth/refresh/storage acceptance, cloud image/runtime and restore/load checks, real printer/phone captures, actual Word/PowerPoint installation/use, self-service account recovery, and a billing/entitlement/refund ledger remain outstanding. The prior Docker VM disk-space limitation is unchanged; unrelated Docker data was not pruned. No paid services, production resources, ads or checkout were activated. Changes remain local/uncommitted. The local preview is `http://127.0.0.1:3011`.

## Internet-sample detection-quality pass (2026-09-10)

- Collected 233 licensed paired leaf images; evaluated 72 with published masks and explicitly oracle-derived prompts. GrabCut/EfficientSAM mean IoU: **0.9186 / 0.9199**, insufficient evidence for an ML-default switch. 22 resized-mask pairs and unknown specimen grouping remain explicit caveats.
- Added 24 correlated SmartDoc phone frames (all below the product page-size constraint), five public-domain historical handwriting pages, and reran six attributed nature cases. Wrong/rejected page suggestions and failed river probes are retained, not counted as successes.
- Fixed alpha-to-white decoding and tiny accepted-detail loss during guided tracing. Added optional local adaptive ink thresholding, keeping global threshold as default and warning about paper-edge/texture artifacts. Actual exported oak font now retains all three accepted-mask holes; scripted browser repair/accept/build/download/font-load canary passed.
- **151 Python tests passed / 31 PostgreSQL-dependent skips** in the full run; a separate isolated PostgreSQL16 run passed **43 tests** across the six relevant modules, covering those database paths. Counts overlap. Final image/font/page/nature targeted rerun: **36 passed**; object benchmark/integrity suite: **21 passed**. Independent review cleared the bounded evaluation-reporting issues.
- **118 frontend tests passed** across 17 files; typecheck/build passed; lint **0 errors / 7 existing warnings**. **14 production-preview Chromium tests passed**. Python compileall, JavaScript syntax checks and diff whitespace checks passed.
- [Complete evidence, metrics, attribution and reproducible commands](research/detection-evidence/README.md). No dependencies/models/training/paid APIs added; no public deployment. In-spec printer/phone coverage, human correction burden, rivers, production unit economics and Office acceptance remain open. Existing uncommitted MVP work was preserved.

## Page-corner safety and river follow-on (2026-09-10)

### Implemented locally

- Automatic page candidates now require contour/quad fit, per-edge image support and plausible aspect. Duplicate candidates merge; similarly plausible separate pages reject. The18% automatic area minimum and mandatory manual confirmation remain unchanged.
- Late corner-detection responses and superseded uploads cannot overwrite the current sheet, edited/confirmed corners, or changed mode/project.
- River research now verifies source provenance before scoring and separates numeric diagnostics from explicit visual acceptance. The first broad meander blob was rejected. A16-point narrower seeded-color trace is diagnostic only; its actual TTF raster loses some tiny holes. No production river extraction claim or core segmentation default change.

### Fresh evidence

- Full Python run: **177 passed / 31 PostgreSQL-dependent skips** in433.17s. A separate disposable PostgreSQL16 run passed **43 tests**, covering the database paths skipped in the full run; the container was stopped/removed afterward. Final river/nature targeted tests after report/provenance corrections: **10 passed**. Page/alignment/API targeted suite: **48 passed**; markerless/guided font and page controls: **19 passed**. These test groups overlap; do not sum them as unique tests.
- Web: **121 passed** across17 files; typecheck and production build passed; lint **0 errors / 7 existing warnings**. Final production-preview Chromium suite: **14 passed**.
- Real browser → upload → API detection: controlled page accepted with200, ellipse rejected with400; build remained disabled until manual confirmation, manual fallback available after rejection, no page JavaScript errors. This is a synthetic control, not physical phone capture validation.
- Python compileall, JavaScript syntax checks and diff whitespace checks passed. Independent review cleared the bounded page, frontend async and river evidence/provenance lanes.

[Page before/after, attribution and caveats](research/page-corner-evidence/README.md); [river comparison, rejected outcomes and diagnostic vector proof](research/river-evidence/README.md). No public deployment, dependency/model addition, paid service or push; prior uncommitted work preserved. Current preview: http://127.0.0.1:3011.
