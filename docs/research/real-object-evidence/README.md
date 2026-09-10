# Real object segmentation evidence

This directory records the reproducible real-object benchmark source and lightweight evidence. Full downloaded images, masks, model predictions, and contact sheets are intentionally kept under ignored `output/detection-sources/objects/`.

Primary source selected for the first cohort:

- **Mendeley Data**: "Multi_layer graph plant leaf segmentation", DOI `10.17632/46n94cngkx.1`.
- **License**: CC BY 4.0 as reported by the Mendeley public API.
- **Paired data**: the dataset description states 233 RGB leaf images and a `mask` folder with ground-truth masks.
- **Archive bound**: `Plant_Leaf_Segmentation.rar`, 19,481,164 bytes, SHA-256 `a654735869f8e0b77ca485bccdd2e1c3f2cf261e98b2c6af3dcf4758bf1dbb65`.

Run `scripts/collect_object_samples.py --download` to recreate the ignored local sample manifest, then run `scripts/benchmark_real_objects.py` to score GrabCut, EfficientSAM, and SlimSAM where local model weights/runtime are available.

## Latest local run

- Collected 72 selected paired samples from 233 available pairs into ignored `output/detection-sources/objects/manifest.json`.
- Split: 60 dev / 12 heldout using filename-bucket groups because plant/session IDs were not available in the archive metadata; biological-specimen leakage cannot be ruled out.
- 22 of 72 selected samples have published mask dimensions that differ from the paired RGB image and are scored with nearest-neighbor mask resizing; metrics are also summarized separately for `same-dimensions` and `resized-published-mask`.
- Full predictions and comparison sheet are ignored artifacts under `output/detection-sources/objects/`. The tracked `summary.json` captures source, integrity, and aggregate metrics without copying the licensed image corpus.

## Validation and interpretation

Final object benchmark plus shared metric regressions: **21 passed**. Manifest loading requires hashes, recorded dimensions, annotation origin, unique sample IDs, and valid split/group fields before scoring. Headline means include failed runs as zero; successful-only means are separate.

All three methods receive **reference-mask-derived oracle boxes**. SlimSAM additionally receives a reference-assisted keep point; it is not prompt-equivalent to the box-only comparison. No model was promoted from this cohort. See the [complete detection report](../detection-evidence/README.md) for comparative metrics, source attribution, actual-font checks and limitations. Reaggregation used cached predictions, retaining original inference timings; those timings were recorded under concurrent CPU load and are not controlled latency/cost measurements.
