# Page-corner safety and guided river extraction

2026-09-10 — bounded follow-on implementation, before tuning.

1. Freeze existing real page predictions and add deterministic, reference-centered crops as **derived constraint probes**, not new captures or independent held-out data. Keep originals and failures in reports. No lowering the 18% minimum page-area rule.
2. Add failing controlled regressions for non-quadrilateral distractors, absent/clipped pages and ambiguous multiple pages. Improve candidate support/geometry and ambiguity rejection without changing manual corner confirmation or template identity/orientation requirements.
3. Compare existing satellite-water heuristic against an explicit keep/exclude-seeded extraction experiment on the three attributed satellite scenes. Keep all outcomes; real scenes have no independent water masks. No blue/dark pixel rule is semantic water detection. Promote only if review supports a usable silhouette, not merely a nonempty mask.
4. Validate any accepted river silhouette through actual vector/font export; retain provenance and disclose prompts/manual intervention. No new dependencies, model training or paid inference.
5. Independent review, targeted tests and broader affected tests. Stop with evidence-backed shipped changes, reproducible experiments and explicit unsolved gates; never claim arbitrary river/page detection solved.

Owners: root benchmark/evidence/integration; beta_security page detector/regressions; ml_benchmark river experiments; deploy_references official constraints. Preserve unrelated uncommitted MVP work.

## Outcome

Page-corner safety and frontend async guards implemented and independently reviewed. [Before/after page evidence](../research/page-corner-evidence/README.md): curved/clipped/ambiguous controls rejected; derived-crop wrong suggestions3→0, above-.90-IoU suggestions13→15; all out-of-range originals now rejected. Manual confirmation preserved.

[River evidence](../research/river-evidence/README.md): four attributed satellite sources, six-method baseline, one manually guided derived refinement. Broad meander mask rejected despite numeric gates. A narrower seeded-color trace is closer visually but remains research-only (16 tailored points, topology/artifact limitations). Diagnostic actual-font export was checked, not promoted as a production river feature. No new dependencies or model training; no deployment.

Independent review cleared page detector, frontend async safety, and river provenance/promotion boundaries. Physical in-spec phone captures, independently reviewed channel masks and real-user correction burden remain explicit next gates.
