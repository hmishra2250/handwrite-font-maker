# Learned segmentation delivery plan

## Outcome and boundaries
Advance the existing private alpha to actual local pretrained segmentation, with measured limitations, optional installation, explicit fallback and user correction. Do not equate a learned cutout with complete alphabet synthesis, color fonts, production security or universal scene accuracy.

## Decisions and alternatives
- Preserve exact user-approved black/white masks, source coordinates, holes and disconnected pieces. No automatic largest-component or hole-filling cleanup.
- Keep threshold and GrabCut as inexpensive baselines. Benchmark a small commercially usable prompted SAM-family ONNX checkpoint locally; larger SAM/GPU or training work needs evidence that the small model plus corrections is inadequate.
- Optional, pinned CPU runtime and checkpoint hashes; install models explicitly, never download code/weights inside upload requests. No paid provider calls or user-image transmission.
- Offer auto, explicit model and classical selection. The selected SlimSAM export uses keep/exclude POINTS, not native boxes. Auto without keep points uses classical segmentation and explains how to try the model. Auto may fall back only with a visible reason; explicit model failures never masquerade as ML success.
- Add EfficientSAM-Ti as explicit `box-model` after the independent-family benchmark; do not promote it silently in Auto.
- Preserve conservative working resolution; separate silhouette from ink detail inside a cutout. Let users add/remove accepted-mask pixels and undo corrections.

## Delivery lanes
1. Official checkpoint/runtime/license selection and provenance.
2. Reproducible synthetic ground-truth benchmark plus clearly labeled qualitative real photographs; compare segmentation, boundaries, small components/counters and CPU timing.
3. Local runtime, safe download/install, concurrency and input limits; no network inference.
4. HTTP/UI integration, actual method disclosure, style selection and reversible mask correction.
5. Unit/contract tests, real-model benchmark, actual HTTP → accepted mask → font and browser proof. Promote based on measured evidence, not model name or advertised GPU throughput.

## Failure scenarios and checks
- Model loses dots/counters: benchmark topology; show original/result and allow corrections; retain ink/classical alternatives.
- Model unavailable, corrupt, busy or too expensive: fail safely, bounded resource use and explicit fallback; test missing/corrupt assets without downloading in tests.
- Stale asynchronous result overwrites newer artwork/corrections: invalidate stale responses and test source/method/character changes; accepted glyphs stay authoritative.

## Completion criteria
Actual pretrained weights run locally; reproducible comparison metrics and proofs retained; selected model works through the app and exports real fonts; fallback is honest; edit/undo works; existing capture contracts remain functional. Real-user/printer/Office acceptance and public SaaS gates remain separate outstanding stages.

## Delivered checkpoint

Both model families, verified installation, HTTP/UI contracts, reversible mask editing and actual generated-font browser proofs are implemented. Final evidence:121 Python tests,64 frontend tests,14 Chromium regressions; both models tested through real capture-to-TTF flows on desktop/mobile. See [validation](VALIDATION.md). The subsequent stage is representative creator/printer/Office acceptance and production SaaS hardening, not a claim that the north star is already complete.
