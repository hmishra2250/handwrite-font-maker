# Repository audit — 10 September 2026

Read-only parallel Terra audits of the Python font pipeline and web/product infrastructure, followed by leader-run baseline checks. This describes the starting revision, not a claim that the issues are fixed.

## What exists

- `src/handwrite_font_maker/rectify.py`: four ArUco marker correspondence points produce a homography; remaining marker corners support a reprojection check. There is no page-outline or manual-corner path.
- `src/handwrite_font_maker/extract.py`: extraction returns known schema cell rectangles, not inferred character segmentation.
- `src/handwrite_font_maker/pipeline.py`: grayscale thresholding, guide removal, PBM-to-SVG via potrace, manifest creation and FontForge invocation.
- `scripts/fontforge_build.py`: actual OTF/TTF/SFD output, not a mocked builder. Space is synthesized.
- `scripts/fontforge_validate.py`: currently validates only that FontForge can open outputs. This does not establish correct character mapping, baseline, descenders, bearings or interoperability.
- `web/app/upload-workbench.tsx`: camera/file inputs, upload/create/poll/download flow. No individual-character workspace.
- `web/app/api/`: Next.js proxies Python or silently chooses canned demo behavior when the worker is absent.
- `src/handwrite_font_maker/web/`: JSON/Postgres jobs, local/Supabase objects and a real worker.
- `Dockerfile.api`, `Dockerfile.web`, `render.yaml`, `docker-compose.yml`: deployment scaffolding, not a production readiness guarantee.

## Ranked risks

| Priority | Finding | Consequence / required response |
|---|---|---|
| P0 | No user ownership/auth, quotas, billing or abuse controls in public job/object routes | Do not expose as an unrestricted paid SaaS; add scoped ownership, signed capabilities and resource limits first. |
| P0 | npm audit on the checked-in lockfile reports 14 vulnerable packages (1 critical, 9 high, 3 moderate, 1 low) | Inspect current advisories and update/test before public deployment; audit severity is not itself proof of exploitability in this application. |
| P0 | `PostgresJobStore.get()` reconstructs artifacts without download URLs | Refresh private signed URLs on authorized status reads; test the persisted live-mode path. |
| P0 | Retention metadata is not deletion enforcement; migration has no storage bucket/policies/cleanup | Do not advertise automatic deletion until object and row cleanup is implemented and tested. |
| P1 | Cropping and printed guide coordinate systems disagree | Lock baseline/descender tests before correcting shared geometry. |
| P1 | `_remove_full_width_horizontal_runs` can erase real horizontal strokes | Guided object/character masks must not reuse template guide removal blindly. |
| P1 | Inline daemon threads and JSON store do not provide a durable queue | A restart can lose running work; use atomic claims, leases/retry and idempotent publishing. |
| P1 | Demo URLs reference missing public artifacts | Explicitly label demo behavior; never report a fake successful conversion as real. |
| P1 | `tests/test_30_synthetic_captures.py::test_capture` is a script helper accidentally collected by pytest | Rename the helper or correctly parameterize; keep report generation separate from unit discovery. |

## Baseline evidence

Leader installed the existing declared Python/npm dependencies and existing system tools, without changing manifests:

- Frontend: **25 tests passed**, typecheck passed, lint passed with **2 warnings** (raw preview image and anonymous PostCSS export).
- Production Next.js build: **passed**, version reported `16.2.4`.
- Python before system tools: **22 passed, 8 skipped, 1 failed, 1 error**. Error: missing `image` fixture in the accidentally collected helper. Failure: missing potrace masked the expected missing-marker error.
- Full font checks after system-tool installation and browser e2e results are recorded in the implementation verification report when available.
- Checked-in synthetic report: **26/30** alignment cases pass. This is not real-user font usability evidence, and does not validate markerless capture.

## Scope implication

Keep the existing ArUco path as a compatibility option. Build explicit, versioned markerless controlled-page and guided-character inputs, not a silent guess about the letter in every arbitrary image. Prioritize mask correction and font metrics over adding a general-purpose VLM. Treat public launch as a separate security/payment/retention acceptance gate.
