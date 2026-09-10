# River extraction experiment evidence

This directory records the bounded river/water extraction lane. Full crops, masks, contact sheets, and the rejected diagnostic font artifact are written under ignored `output/river-extraction/`.

Scope:

- Reuses attributed satellite fixtures from `docs/research/nature-source-manifest.json` and verifies local SHA-256, license, and origin before scoring.
- Fails closed: unverified sources are not scored.
- Compares the earlier broad `water-color` helper against seeded color-distance and benchmark-only seeded GrabCut alternatives.
- Uses explicit keep/exclude seed prompts and normalized rectangles. No ground-truth masks or accuracy claims are created for these real satellite photos.

## Latest correction

- Root visual review rejected the previous auto-selected Mississippi meander mask: it was a broad filled blob, not a narrow water trace.
- Numeric diagnostics are now triage only; font promotion requires `accepted_for_font_visual_reviewed`. No default case currently has that label.
- The generated `RiverGlyphs.ttf` is retained only as a rejected diagnostic artifact under ignored output, not as a successful river font.
- A single final narrower Mississippi channel attempt was run with visually placed keep/exclude seeds; it is reported as a candidate for human review, not accepted.
- Recommendation: no production integration yet. Treat seeded GrabCut/color masks as research-only until explicit visual review and product UX gates exist.

## Final visual review and diagnostic vector export

The narrower `meander_channel_trace_attempt` seeded-color mask is visibly closer to the main channel, unlike the rejected broad blob. It uses **9 keep + 7 exclude points**, a manually narrowed rectangle, LAB tolerance18, exclusion margin−8, morphological operations and component filtering. This is one deliberately guided refinement of an already-seen image, not an independent fifth satellite source, a generic preset, or semantic ground truth. Fine holes and side spurs remain; it is **not promoted as a production river feature**.

Root exported this candidate separately through the existing font pipeline only to inspect vector behavior (`output/river-channel-candidate/RiverChannelDiagnostic.ttf`). [Diagnostic comparison](channel-candidate-fidelity/U0053.png) / [report](channel-candidate-fidelity/report.json): normalized outline IoU **0.9367**; source1 component/12 holes versus actual1024px TTF raster1 component/10 holes. This proves a font can be generated, not lossless topology or segmentation correctness. The fidelity utility's generic “accepted mask” field names mean input-to-font mask here; no human user accepted it. The main experiment correctly reports no promoted font; this separate candidate export is diagnostic only.

## What remains to make rivers a product workflow

1. Let users define the exact channel/branch they want and place foreground/background guidance; keep the mask editor as the final authority. A river, its banks, nearby oxbows, and sediment plume are different targets.
2. Evaluate point/scribble-guided extraction on more independently reviewed channel masks, with the same interaction budget and measured correction effort. This single16-point refinement is not a usable default benchmark.
3. Add boundary/topology review before accepting a mask, then validate its small details after vector export. Avoid blanket smoothing, hole filling or largest-component removal in the core glyph path.
4. Only promote a dedicated method when the correction burden and failure rate are acceptable. Current GrabCut/ML defaults and UI are unchanged by this research lane.

## Sources and reproduction

Source attribution, URLs, licensing and hashes: [nature manifest](../nature-source-manifest.json). Mississippi images/adaptations: **USGS/NASA/Landsat7**, public-domain record, [source page](https://commons.wikimedia.org/wiki/File:Meandering_Mississippi_(5182095595).jpg). Other panels credit their corresponding manifest creators. No NASA/USGS endorsement implied.

These are rendered RGB images, including **false-color composites**, not calibrated multispectral band arrays. Do not compute or claim NDWI/MNDWI from the displayed colors: the original methods require particular green/NIR or infrared bands ([McFeeters1996](https://www.tandfonline.com/doi/abs/10.1080/01431169608948714), [Xu2006](https://www.tandfonline.com/doi/abs/10.1080/01431160600589179)). Existing [OpenCV GrabCut guidance](https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html) explains hard/probable mask labels; it does not establish water semantics.

```sh
# Existing attributed source images must already be downloaded.
.venv/bin/python scripts/experiment_river_extraction.py --methods water-color-frozen,seeded-color,seeded-grabcut
.venv/bin/python -m pytest tests/test_river_extraction.py tests/test_nature_experiments.py
```

The first full six-method/four-source run is retained as [rejected baseline](river-experiment-full-methods-rejected.json); the corrected deterministic rerun and one derived refinement are [separate evidence](river-experiment-report.json). Neither timings nor mask diagnostics are accuracy, cloud-cost, or human correction-time measurements.
