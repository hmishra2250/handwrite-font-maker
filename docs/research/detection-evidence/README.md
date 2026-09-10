# Detection-quality pass — 2026-09-10

## What changed in the product

- **Transparent-image decoding:** frontend thresholding and backend image decoding composite onto white. Invisible black RGB pixels no longer become false ink. RGBA, grayscale-alpha, and palette transparency regressions fail before the backend fix and pass afterward.
- **Optional adaptive ink threshold:** local integral-mean thresholding, radius 12 / offset 18, runs in the browser without inference/API cost. Global/manual threshold remains the default. It is not a universal upgrade: sharp paper edges/texture can become ink and thick-stroke centers can disappear. The UI explicitly warns users to review these artifacts.
- **Accepted-mask vectorization:** guided builds now use Potrace `--turdsize 0`; template/legacy builds retain `4`. No new model, dependency, or automatic model promotion was introduced.

## Real exported-font evidence

[Before](fidelity-before/report.json) and [after](fidelity-after/report.json) use the **same accepted masks** and actual exported TTFs rendered by FreeType at 1024 px. The oak mask has four connected components and three holes. Before, its TTF retained only two holes; after, all three survive. A separate real-TTF regression proves a tiny dot and counter previously disappeared and now survive. Normalized outline IoU is ~0.977 maple, ~0.981 oak, ~0.978 fern; this is outline fidelity, **not segmentation accuracy**.

[New leaf probe](new-leaf-fidelity/report.json): both a GrabCut prediction and an EfficientSAM prediction from Mendeley image `23s` were exported as actual glyphs. Normalized outline IoU ~0.993 / ~0.991. This uses **predictions**, not the published reference mask, as font input. `G` / `M` are diagnostic mappings, not claims that the leaf resembles those letters.

[Browser canary](ink-browser-report.json): real adaptive browser extraction → mask acceptance/upload → Potrace/FontForge → downloaded and browser-loaded TTF (1,748 bytes), no browser errors. This controlled alpha/shadow/ring/dot fixture is **synthetic**, not an internet sample. The raw adaptive mask contained a paper-edge artifact. The canary removes it with three scripted eraser strokes through the real repair UI before acceptance. [Render comparison](ink-fidelity/U0041.png) verifies the repaired ring/dot, preserving both components and the hole. This demonstrates assisted correction, not automatic segmentation acceptance or measured human correction time.

## Corpus and boundaries

| Cohort | Acquired / evaluated | Evidence scope |
|---|---|---|
| Mendeley real leaves | 233 published photo/mask pairs acquired; fixed 72-image subset evaluated | Independent published masks; all boxes reference-derived, SlimSAM additionally receives one oracle keep point. Not autonomous object detection. |
| SmartDoc phone captures | 3 original clips; 24 sampled frames | Independent publisher page corners. Frames are correlated, not 24 independent capture sessions. |
| Historic handwritten letters | 5 source pages | Public-domain source records; qualitative ink comparisons only, no pixel reference masks. Not modern phone/pencil capture coverage. |
| Earlier nature/satellite fixtures | 8 source assets; 6 cases re-run | Qualitative leaf/fern/river stress probes. No semantic ground truth or accuracy claims. |

That is **107 evaluated image cases**, not 107 independent photos: 72 leaves + 24 video frames + 5 historical pages + 6 earlier nature cases. Downloaded originals/large predictions stay ignored under `output/`; manifests, attribution, and small evidence are retained.

### Paired leaf results

[Retained aggregate report](../real-object-evidence/summary.json), all 72 cases per method (zero execution failures; this is not a user acceptance rate):

| Method / prompt | Mean mask IoU | Boundary F1 | Exact component-and-hole counts |
|---|---:|---:|---:|
| GrabCut / oracle box | 0.9186 | 0.8306 | 26/72 |
| EfficientSAM / same oracle box | 0.9199 | 0.8517 | 31/72 |
| SlimSAM / oracle box + oracle keep point | 0.8996 | 0.7897 | 25/72 |

The two box-only methods are nearly tied in aggregate IoU; this does not justify making ML the default. On the small 12-image held-out subset, GrabCut IoU was 0.9334 versus EfficientSAM 0.8741. SlimSAM's 0.9491 held-out result is a **different prompt budget**, not a model ranking. Filename-bucket splits cannot guarantee specimen independence.

The delivered RGB images have a longest side of at most 300 pixels. **22/72 published masks have different dimensions** and are nearest-neighbor resized under an alignment assumption, not independently verified pixel registration. The report also provides the 50 same-dimension cases separately. Topology counts show that a good aggregate silhouette score does not guarantee all small details survive segmentation. Existing local timings were collected under concurrent CPU load, not a controlled latency or cloud-cost benchmark.

The five historic handwriting pages were also evaluated at a maximum side of **1024 pixels** (no upscaling), in addition to the retained 360-pixel visual panels. Fixed adaptive-window radius is measured in working pixels, so resolution matters; neither run has ground-truth masks or supports an accuracy claim. See [1024-pixel diagnostics](ink-real/diagnostics-1024.json).

### Sources / reproduction

- [Object source manifest](../object-sources.json), [paired benchmark evidence](../real-object-evidence/README.md). Primary source: [Mendeley Data, Multi_layer graph plant leaf segmentation](https://data.mendeley.com/datasets/46n94cngkx/1), Lyasmine ADADA, Idir Filali, Samia Bouzefrane, 2024, DOI 10.17632/46n94cngkx.1, **CC BY 4.0**. The new leaf glyph/render comparisons here are adaptations under that license.
- [Handwriting source manifest](../handwriting-sources.json), [ink comparisons](ink-real/README.md). Includes creator, original file URL, rights evidence, hash, and downloaded-derivative status. Ambiguous broad search hits were excluded; no paid stock images or user uploads were used.
- [SmartDoc results](../real-page-evidence/report.json). [Primary Zenodo record](https://zenodo.org/records/1230218), **CC BY 4.0**. Attribution: Burie, Chazalon, Coustaty, Eskenazi, Luqman, Mehri, Nayef, Ogier, Prum, Rusinol, *ICDAR2015 Competition on Smartphone Document Capture and OCR (SmartDoc)*, ICDAR 2015.
- [Earlier nature provenance/attribution](../nature-source-manifest.json). Oak/fern render evidence follows its recorded CC0 sources; the maple-derived measurements reference a CC BY-SA 3.0 asset. Source-image licenses are separate from the software license. No NASA/USGS endorsement is implied.

```sh
.venv/bin/python scripts/collect_object_samples.py --download
.venv/bin/python scripts/benchmark_real_objects.py
python3 scripts/collect_handwriting_samples.py --commons-target 5
node scripts/benchmark_real_ink.cjs
.venv/bin/python scripts/benchmark_real_pages.py --download
node scripts/smoke_ink_capture_browser.cjs  # local API 8011 / web 3011 running
# See verify_font_fidelity.py --help for accepted-mask -> actual-TTF comparisons.
```

## Honest remaining limitations

- SmartDoc's sampled pages cover only **9–14%** of each frame, below the product's **18% minimum page-area** rule: the initial pass had 23 rejections and one wrong suggestion; the [follow-on safety pass](../page-corner-evidence/README.md) now rejects all 24 originals and removes that wrong suggestion. This is a useful out-of-range stress test, **not in-spec detection accuracy**. Keep mandatory manual corner confirmation; do not loosen the detector based on this tiny shared-background corpus. More in-spec actual template phone captures and absent-page/distractor scenes are needed.
- Numeric filename buckets in the leaf dataset are not verified plant/session groups. The split reduces adjacent-file overlap but cannot prove independence. Label-resizing assumptions and equal-size subsets must remain visible in benchmark reporting.
- Rivers remain rejected experimental examples, not automatically usable letter extraction. No custom training or new segmentation model was justified by this pass.
- No human correction-time, willingness-to-pay, production cloud latency/cost, or Office compatibility study was performed. Existing local model timings are not production p95 or per-font unit economics.

## Verification

- Full Python suite: **151 passed / 31 PostgreSQL-dependent skips**. A separate isolated PostgreSQL16 run of the six database/security/project/worker modules passed **43 tests**, covering those database paths; the disposable container was then removed. These counts overlap and must not be summed as unique tests.
- Final targeted image decode/guided font/fidelity/page/nature regressions: **36 passed**. Object benchmark/integrity regressions: **21 passed**. Independent read-only review cleared the three reporting issues (failure denominators, oracle prompts, and corpus/split disclosure).
- Web: **118 tests passed**, typecheck and production build passed; lint **0 errors / 7 existing warnings**. Production-preview Chromium suite: **14 passed**. The assisted adaptive browser-to-font canary passed independently.
- Python compileall, JavaScript syntax checks, and `git diff --check` passed. No new dependencies, model weights, paid services, or production deployment were introduced.
