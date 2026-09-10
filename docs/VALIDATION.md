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


## Latest integration checkpoint

- Python suite excluding the two slow full-sheet font suites: **58 passed in 38.77s** (`pytest -q --ignore=tests/test_build_e2e.py --ignore=tests/test_e2e_api.py`). This includes guided font generation, foreground, contracts and alignment; it is not a full-suite pass.
- Foreground tests after extreme-aspect-ratio rejection: **11 passed in 5.66s**; no stretching of narrow images.
- Fresh localhost guided API after backend serialization changes: **5 glyphs, succeeded in 1.027s, TTF 2,172 bytes**, actual downloaded font loaded by FreeType. Single-run busy-host evidence, not production latency. `research/guided-api-smoke.json`.
- Actual object API canary: synthetic color image → `/capture/foreground` → accepted mask → upload → persisted guided job → downloaded TTF → FreeType proof: **succeeded in 1.317s, TTF 1,756 bytes**. Hole and detached dot assertions passed and rendered proof visually checked. `research/object-api-smoke.json`.
- Style experiment: **24 actual SVG/PGM traces**, 2 interpretations × 4 sizes × 3 tracing configurations; independent review reran it. [Results and limitations](research/vector-style-experiments.md).
- Review identified horizontal-stroke erasure, letterboxed corner coordinates, upstream upload errors, artifact casing, partial-font proof fallback and lint/test failures; fixes passed the bounded independent re-review and targeted regressions. Market positioning now limits current export claims to TTF/OTF.
- Earlier updated 94-glyph benchmark **failed structural validation**; do not use it as a speed/success result. Subsequent corrected full 94-glyph synthetic build succeeded with structural validation in **137.27s** on the busy host. Full-suite and later performance evidence are listed below.

- Real Chromium object journey against localhost Next3011/API8011: upload color source, select object method, extract, accept `A`, build, load actual FontFace, download TTF (**1,772 bytes**), type unsupported `B` and observe missing-character warning. **No browser page errors**. This is not a mocked API test. Evidence: `research/browser-object-smoke.json`; canary `scripts/smoke_capture_browser.cjs`.

## Final integration checks

**Result: local/private-alpha verification passed. Public SaaS release remains gated.**

- Frontend: **49 tests passed** across 9 files; typecheck passed; production build passed on Next16.3.4; lint **0 errors / 6 warnings** (raw preview images and PostCSS anonymous export); npm audit **0 reported vulnerabilities**. Audit is not a security guarantee.
- Standard Playwright Chromium suite: **13 passed**. An initial 12/13 run hit a stale generated Next dev route cache; clearing only generated cache restored `/help/install-fonts`. No source-route workaround was required.
- New full markerless regression: **1 passed in 7.02s**. Render quiet page with A/i/O/g/-, put on contrasting desk, detect corners, rectify/extract/build, assert exactly those five nonempty glyphs and load the real TTF in FreeType. This caught blank-cell guide contamination that isolated mask tests missed. Final template uses side ticks outside extraction regions, not interior writing lines.
- Fresh combined changed-path check: **36 passed in 27.52s** for diagnostics, guided masks, markerless alignment/build and capture contracts. Backend then added two actual-byte (forged size metadata) regressions: capture contracts **10 passed**, broader backend/alignment/guided/foreground set **47 passed**.
- Python compileall, `docker compose config --quiet` and `git diff --check`: passed. Docker configuration validation is not a container runtime/deployment test.
- A full run overlapping ongoing edits finished **74 passed / 2 failed in 695.43s**: its imported markerless code predated the side-tick fix, and one export picked up a rejected temporary OTF flag. This run is not acceptance evidence. After final freeze, targeted font/pipeline/capture checks passed **38 tests in 9.64s**. The fresh frozen full suite then passed **78 tests in 575.97s (9m35s), no failures or skips**. This is the final Python acceptance run, including both previously failing cases.

## Quality scope

Twenty-four synthetic style/resize/tracing experiments plus four real-photograph vector probes were run. They demonstrate tradeoffs, not segmentation accuracy on a representative corpus. Current exports are monochrome outlines; original photographic color/texture and automatic completion of missing letters are not implemented. Learned segmentation candidates were researched, not installed or benchmarked here.

Real printer/phone captures, end-user acceptance, Windows/macOS Office installation/embedding, cloud p95/cost, database migration on staging and tenant security remain unverified. Local alpha success does not justify “world-class”, production-ready, revenue or universal compatibility claims.

## Font export profiling

A native process sample identified FontForge CFF generation/autohinting as the remaining dense-sheet hotspot. No controlled speedup is claimed from removing geometry cleanup. An OTF `no-hints` experiment produced unreadable output and was rejected; OTF uses default generation. TTF exports omit instructions, with structural validation rejecting unexpected instruction tables. See [official FontForge generate flags](https://fontforge.org/docs/scripting/python/fontforge.html). This display-font choice still needs small-size/Office rendering validation; it does not solve the CFF hotspot.

Final frozen full-sheet test durations on this host: clean 86.65s, noisy 166.31s, bright 125.64s, dark 18.16s, perspective 34.07s, combined distortions 25.59–26.47s; standalone synthetic build 75.55s. These are test durations on a shared development machine, not a controlled production latency distribution or an attributable before/after speedup.

A final independent read-only review found no P0/P1 in the bounded font-export, markerless-regression and reporting scope. This is not a comprehensive production security audit. Local preview was verified at `http://127.0.0.1:3011` (HTTP200); the Python worker runs on localhost8011.
