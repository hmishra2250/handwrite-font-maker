# Local ML evidence — 2026-09-10

These are development-host observations, not a production acceptance corpus or cloud bill.

- `slimsam-benchmark.json` / `slimsam-comparison.png`: five deterministic labeled synthetic cases; GrabCut box prompts vs SlimSAM fp32/int8 **reference-assisted** keep/exclude prompts. Do not compare these as equal human interaction budgets. Interior-detail target intentionally differs from silhouette.
- `efficientsam-benchmark.json` / `efficientsam-comparison.png`: same five fixtures, GrabCut vs genuine EfficientSAM-Ti boxes (no ground-truth clicks). Different run/time from SlimSAM comparison. One fruits photograph is qualitative-only, no ground-truth accuracy score.
- `*-runtime.json`: four calls in one isolated process per model, fixed CPU threads, repeated synthetic source. Peak RSS covers that process; warm median has only three observations. No p95/cloud-cost claim. Switching model families and multi-worker memory need separate deployment tests.
- `*-api-smoke.json`: actual HTTP image upload, segmentation using local pretrained weights, hole/detached-dot/main-shape assertions, accepted-mask upload, persisted job, downloaded TTF and Pillow/FreeType proof.
- `*-browser-smoke.json`: actual Next/Python browser interaction and generated FontFace, not mocked model results. Browser correction checks and box coordinates are specified in `scripts/smoke_ml_capture_browser.cjs`.

Reproduce from repository root using commands in `docs/ML-SEGMENTATION.md`. Detailed per-case fixture/mask paths in JSON refer to the corresponding generated `output/segmentation-benchmark` or `output/efficientsam-benchmark` folder; regenerate to inspect all intermediate images. Selected contact sheets/reports are retained here without committing checkpoints or private photos.

Rejected experiments: SlimSAM box labels2/3 do not address real box embeddings in the pinned export; memory-arena-disabled ORT sessions exited abnormally during teardown and were not adopted. Failure cases remain in the scores and contact sheets, not removed to improve averages.
