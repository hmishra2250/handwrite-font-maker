# Detection quality: internet evidence and bounded improvements

Date: 2026-09-10. Protocol frozen before evaluation; completion evidence appended below.

## Goal and boundaries
Improve the existing deterministic handwriting/page and optional local ML object paths using real, provenance-tracked public sources. Target 100–150 distinct source images where licensing and acquisition permit; report actual counts, not augmented-image counts. Preserve current project, ownership, mask editing, font export, and deployment contracts. No paid APIs, custom training, or additional dependencies. Satellite rivers stay experimental.

## Protocol (freeze before evaluation)
1. Record direct asset and primary source URLs, creator/license evidence, byte hashes, image dimensions, and annotation origin. Keep downloaded originals ignored; retain manifests and small attributed evidence only.
2. Distinguish published independent masks (quantitative), unannotated photos (qualitative), and synthetic/composited stress cases (controlled tests). Predictions are never ground truth. Historical scans are not smartphone capture evidence.
3. Assign development/held-out splits before tuning. Group by plant/session/document when provenance exposes groups; explicitly disclose unknown grouping and resulting leakage risk. Never count variants as independent originals.
4. Compare like prompt budgets: box-only methods separately from point-assisted methods. Record reference-derived prompts as oracle assistance, not autonomous detection. Freeze thresholds before held-out evaluation. Preserve failures in denominators.
5. Measure mask IoU/boundary F1/topology where labels support these. No accuracy/acceptance-rate claims from qualitative diagnostics. Measure local timings separately from cloud cost; do not fabricate correction time, paid conversions, or p95 from tiny samples.
6. Reproduce observed failure classes in regression tests before narrowly editing production. Favor cheap deterministic fixes over additional models. Do not automatically promote a model based on one dataset.
7. Verify mask-to-vector/font behavior with actual Potrace/FontForge exports and renders. Run targeted tests, then Python/web checks as affected. Independent review checks evaluation integrity and production changes.

## Stop condition
A reproducible downloaded corpus and baseline, evidence-backed bounded fixes (or explicit no-change decision where evidence is insufficient), real-font verification, a limitations/backlog report, and no unsupported production-readiness claim. Complete-phone-photo coverage, human correction burden, and cloud cost remain explicit gaps if not measured.

## Bounded pass outcome

Completed the reproducible baseline and three narrow fixes: white-composited transparency, optional browser adaptive thresholding, and guided Potrace detail preservation. [Evidence and limitations](../research/detection-evidence/README.md) include source attribution, paired metrics, actual exported-font renders, and verification.

Acquired 233 paired leaf images, three phone-video clips, and five historic handwritten pages; re-used eight previously attributed nature assets. Evaluated a fixed 72-leaf subset, 24 correlated video frames, five historic pages and six nature cases: **107 cases, not 107 independent images**. The desired 100–150 distinct-image evaluation target was not reached; no extra variants were counted to inflate it.

No ML-default promotion or page-area relaxation: current evidence does not justify either. Rivers remain experimental. Next quality gates are in-spec template phone photos across varied surfaces/lighting, representative faint/colored/pencil captures with independent masks, and user-drawn prompts/correction-time studies. Hosted cost and Office acceptance remain unmeasured.
