# Learned segmentation: installation, workflow and limits

This adds **actual local ONNX inference**, not a hosted model API or a mock. The models are experimental box- or point-guided alternatives alongside ink thresholding and GrabCut, not a replacement proven better on all glyphs.

## Install and run

```sh
.venv/bin/pip install -e '.[ml]'
.venv/bin/python scripts/install_segmentation_model.py --model efficientsam
.venv/bin/python scripts/install_segmentation_model.py --model slimsam
# Optional comparison variant; not the recommended default:
.venv/bin/python scripts/install_segmentation_model.py --variant all
```

Weights live in ignored `.models/slimsam/` and `.models/efficientsam/`. Set `HANDWRITE_EFFICIENTSAM_MODEL_DIR` for the latter. Set `HANDWRITE_MODEL_DIR` to an absolute model directory when starting from another working directory. `HANDWRITE_SEGMENTATION_VARIANT=fp32` is the default; `int8` is available for explicit evaluation. The installer pins repository revision, lengths and SHA-256 hashes and atomically installs only verified files. The API never downloads weights or sends captures to an external inference provider. Do not put private uploads in model caches or training corpora.

The optional Python dependency is `onnxruntime==1.29.0`. No PyTorch or custom training is required. For containers, build `Dockerfile.api` with `--build-arg INSTALL_ML=true`, explicitly install weights into a mounted model directory, and set `HANDWRITE_MODEL_DIR` there. Default container builds and HTTP requests never download models. An explicit `INSTALL_MODELS=efficientsam|slimsam|both` build argument enables verified build-time downloads; see [deployment](DEPLOYMENT.md#ml-choices-and-reproducible-images). Do not mount an empty host directory over baked-in `/models` files.

Model provenance: `Xenova/slimsam-77-uniform`, revision `5850ab45f587c112167512ffef949107115e26a0`; based on `nielsr/slimsam-77-uniform` and upstream SlimSAM. Model cards and upstream repository declare Apache-2.0; retained license at `licenses/SlimSAM-APACHE-2.0.txt`. See [checkpoint/source research](research/ml-model-selection.md) for URLs, exact graph inputs, hashes and license evidence. ONNX Runtime is MIT licensed. Conversion provenance is documented, not represented as Meta's original official ONNX export.

## Automatic guided choices (current default)

Uploading a guided character first requests `/api/capture/candidates` with `stage=ink`,
then `stage=objects`. The first stage detects dark/light polarity and returns clean
and softened SVG choices; a damaging adaptive result is excluded. The optional
stage tries bounded classical, box-model and point-model extraction. A generated
positive point is a heuristic—not a guarantee it selects the intended object.
Users select an SVG outline and accept its matching mask for font generation.
Individual methods can fail without discarding successful alternatives. Source,
settings and result diagnostics are described in [capture evidence](research/capture-diagnostics.md).
The advanced manual workflow below remains available for correction.

## Advanced guided workflow

1. Select a character and upload its source photograph.
2. Choose **object cutout** and a rectangle enclosing the intended shape.
3. For **AI box cutout (EfficientSAM)**, the rectangle is enough; keep/exclude points are not used. For **SlimSAM point cutout**, mark a **Keep object** point *on the material/stroke*, not in its hole. Mark additional detached parts as needed. **Exclude background** points help mark unwanted areas/counters. Maximum 16 points.
4. Choose Auto, SlimSAM point cutout, AI box cutout or Classical GrabCut. **Auto with no keep point uses bounded classical extraction: high-contrast threshold first, then capped GrabCut if needed. The returned method reports what actually ran.** With a keep point it attempts the installed model. Neither explicit learned option silently substitutes GrabCut.
5. Choose a silhouette or thresholded dark ink inside the cutout. Neither reproduces photographic color.
6. Review the actual mask, add/remove pixels with the brush, undo/reset corrections, adjust baseline and accept. Only accepted masks become font glyphs.
7. Build, type a proof using the actual generated font, and download TTF/OTF. Subsequent font builds use accepted masks; they do not rerun model inference for every unchanged character.

The pinned SlimSAM graph exposes **point prompts, not native boxes**. Rectangle coordinates restrict the result region but are not passed as invalid box-label embeddings. The separately installed EfficientSAM-Ti path uses genuine box-corner embeddings (labels2/3). Its encoder takes RGB0..1 and performs resize/normalization internally; the pinned decoder returns logits resized to the working image. Do not call this zero-click universal segmentation.

## HTTP contract

`POST /capture/foreground` (or the same-origin Next `/api/capture/foreground`):

```json
{
  "inputPhoto": {"objectKey": "jobs/.../source.png", "contentType": "image/png", "sizeBytes": 12345},
  "rectangle": [0.1, 0.1, 0.9, 0.9],
  "method": "model",
  "style": "silhouette",
  "threshold": 128,
  "points": [{"x": 0.35, "y": 0.4, "label": 1}, {"x": 0.5, "y": 0.5, "label": 0}]
}
```

Returns opaque PNG `maskDataUrl`, `width`, `height`, actual `method` (`threshold`, `grabcut`, `slimsam` or `efficientsam`), `modelId` (string for learned paths; null/omitted for classical), and `warnings`. Points are normalized in EXIF-oriented full-source space; label1 keeps and label0 excludes. Positive points must be within the rectangle. Style is `silhouette` or `ink`; threshold is an integer1..254. Invalid input fails before model work. Missing/corrupt runtime or weights fail explicit model requests with503; busy model requests get retryable503, not more competing inference. Auto fallback discloses why classical extraction was used.

For EfficientSAM, set `"method": "box-model"` and omit `points`. For classical extraction use `"method": "grabcut"`. Box-model is explicit-only; Auto never silently selects a different model family. The direct Python API rejects points on box-model; the UI omits them when switching from SlimSAM.

EfficientSAM provenance: author HF Space `yunyangx/EfficientSAM`, revision `d8dbb1eee73bfb3392aa6f6e8944aeb13f3f4036`, encoder+decoder41,365,489bytes; retained upstream license at `licenses/EfficientSAM-APACHE-2.0.txt`. Both families use fixed local graph files, not remote Python model code.

## Resource boundary

CPU sessions use two intra-op threads and one inter-op thread. The manual foreground path admits one inference request at a time. Automatic candidate extraction admits one object-stage request but runs its classical/EfficientSAM/SlimSAM methods in separate concurrent subprocesses, each with a 25-second deadline. A process-local model lock is not a cross-process memory limit. Source decoding and output dimensions are bounded; output masks retain the full working-image frame up to1024px longest side. Model files are small, but activations are not: local isolated probes peaked at about **1.39GB RSS for EfficientSAM,2.71GB for SlimSAM fp32 and3.62GB for SlimSAM int8**. Do not deploy on a512MB/1GB worker or infer memory requirements from download size. A 4 GB single-model measurement is not a safe aggregate allocation for the current concurrent automatic candidates. For both families, start with an 8 GB API limit and 16 GB host RAM as a planning estimate, then measure actual peak memory and latency under the target workload. Alpha exposes `ALPHA_API_MEMORY_LIMIT` / `ALPHA_API_CPUS`; other profiles need equivalent resource overrides. These are not universal fit guarantees.

Warm medians across only three repeat calls were about0.71s EfficientSAM,1.88s SlimSAM fp32 and1.98s SlimSAM int8 on the shared Mac development host. These are not p95, mobile performance, cloud invoices or accuracy metrics. A memory-arena-disabled experiment reduced RSS but exited abnormally during teardown; it was **rejected**, not shipped as an optimization.

Model extraction occurs per attempted capture, separately from vector/font rebuilding. Meter failed attempts, free previews, correction effort and support—not just successful font exports. The alpha/beta profiles implement capture/build abuse quotas and login gating. This ML milestone does not implement paid billing or a project-credit ledger; public paid access remains subject to the SaaS launch gates.

## Reproduce verification

```sh
.venv/bin/pytest tests/test_segmentation.py tests/test_segmentation_benchmark.py tests/test_web_capture_contracts.py
.venv/bin/python scripts/benchmark_segmentation.py
.venv/bin/python scripts/measure_ml_runtime.py --variant fp32
.venv/bin/python scripts/smoke_object_capture.py --method model --output-dir output/ml-api-smoke
.venv/bin/python scripts/smoke_object_capture.py --method box-model --output-dir output/efficientsam-api-smoke
.venv/bin/python scripts/measure_ml_runtime.py --model efficientsam
# Five-fixture second-family comparison:
.venv/bin/python scripts/benchmark_efficientsam.py --install
```

The synthetic benchmark includes deliberately difficult masks and reference-assisted click prompts for SlimSAM. That is a best-case interaction probe, not unassisted accuracy or representative creator validation. All reported failures and unsupported production claims must remain visible in the validation report.


## Measured quality, not a universal winner

Five synthetic fixtures measured thin strokes, holes, detached parts, low-contrast clutter and interior detail. The detail target intentionally differs from a silhouette; aggregate IoU therefore is not a general-purpose accuracy score. SlimSAM received reference-assisted keep/exclude clicks, whereas GrabCut and EfficientSAM received boxes only. Prompt budgets are not equal.

| Method | Mean IoU | Boundary F1 | Exact component+hole topology |
|---|---:|---:|---:|
| GrabCut | 0.719877 | 0.838278 | 3/5 |
| SlimSAM fp32 | 0.715390 | 0.781824 | 3/5 |
| SlimSAM int8 | 0.693304 | 0.797468 | 1/5 |
| EfficientSAM-Ti box | 0.730246 | 0.865035 | 3/5 |

EfficientSAM preserved detached material better in this small probe; low-contrast counters and background mistakes still occurred. SlimSAM helped one low-contrast case but lost some fine detail. No automatic model ranking/promotion, “any object” promise or custom training is justified by these samples. One real fruits photograph was inspected qualitatively, without ground truth. See retained reports under `research/ml-evidence/`; none is a representative creator acceptance set.

Next promotion gate: independently labeled, permissioned phone-photo captures across backgrounds/materials, with equal human interaction budgets, correction time and failure categories. Require actual Windows/macOS Office use and staging resource/security checks before paid launch. Color/texture fonts and style completion remain separate unimplemented research, not effects of segmentation.
