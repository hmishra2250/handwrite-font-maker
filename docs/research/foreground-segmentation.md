# Foreground extraction decision — 10 September 2026

> Historical baseline research. The subsequent local ML milestone installed and benchmarked EfficientSAM-Ti and SlimSAM, and added reversible mask brushing. See the [current ML runbook](../ML-SEGMENTATION.md) and [measured selection](ml-model-selection.md); statements below about unimplemented brushes/models describe the earlier checkpoint.

## Decision

Ship two explicit tools, not a claim to segment everything perfectly:

- **Ink:** browser threshold/invert on a plain contrasting surface.
- **Object cutout (experimental):** user rectangle → bounded CPU GrabCut → inspect the black/white mask → accept/redo → existing font pipeline. No downloaded model or inference bill. This is classical image segmentation, not semantic recognition or generative AI. Textured backgrounds, reflections, similarly colored objects and thin branches remain failure cases.

The mask accepted by the user is the exact uploaded mask. Never automatically keep only the largest component, fill holes or apply destructive morphology: these can delete an i dot, punctuation, separated leaves or an O counter. Selection cannot determine the user's intended letter; the user supplies its label.

[OpenCV's interactive GrabCut documentation](https://docs.opencv.org/4.13.0/d8/d83/tutorial_py_grabcut.html) describes rectangle initialization, background outside the rectangle, and foreground/background correction strokes. Current implementation bounds the longest image side to 1,024 and uses five iterations. Brush corrections are a next iteration, not currently implemented.

## Model shortlist, with evidence boundaries

These are upstream reports, **not measurements on this app**, and their datasets/hardware are not comparable. Smaller does not establish more accurate on handwriting or leaves.

| Candidate | Primary evidence | Product decision |
|---|---|---|
| MobileSAM | [Official repo](https://github.com/ChaoningZhang/MobileSAM): 9.66M parameters, point/box prompts, reported ~12ms GPU pipeline and ~3s on authors' Mac i5; ONNX export; Apache-2.0 repository. | First small prompted-model benchmark candidate. Verify exact encoder/decoder export coverage, checkpoint provenance/license and modern runtime compatibility before shipping. Browser demos are not proof of low-end-phone performance. |
| EfficientSAM | [Official repo](https://github.com/yformer/EfficientSAM): tiny/small checkpoints, point prompts and separate encoder/decoder ONNX examples; Apache-2.0 repository. | Compare against MobileSAM on the same image set; don't invent CPU latency or artifact size. Pin/check downloaded weights and notices separately. |
| EdgeSAM | [Official repo](https://github.com/chongzhou96/EdgeSAM) reports 9.6M parameters and 38.7 FPS on iPhone 14 for its benchmark. [S-Lab license](https://raw.githubusercontent.com/chongzhou96/EdgeSAM/master/LICENSE) restricts default use to non-commercial purposes and directs commercial users to contact contributors. | Technically interesting, excluded from paid SaaS adoption without commercial permission. |
| SAM 2.1 tiny | [Meta repo](https://github.com/facebookresearch/sam2): 38.9M parameters; 91.2 FPS on A100 with compiled PyTorch/CUDA; code/checkpoints Apache-2.0. | Quality/reference baseline, not evidence of cheap CPU or mobile latency. Video tracking capacity is unnecessary for still-character capture. |
| SAM 3 / 3.1 | [Meta repo](https://github.com/facebookresearch/sam3) adds text/exemplar concepts, lists Python3.12+/PyTorch2.7+/CUDA12.6+ prerequisites, gated checkpoint access, and March2026 SAM3.1 tracking update. [Custom SAM license](https://raw.githubusercontent.com/facebookresearch/sam3/main/LICENSE). | Newer does not mean smaller. Not the default CPU still-image tool; review exact license/access requirements before any adoption. |
| BiRefNet lite | [Author model card](https://huggingface.co/ZhengPeng7/BiRefNet_lite) and [official implementation](https://github.com/ZhengPeng7/BiRefNet). Automatic dichotomous foreground extraction; MIT metadata/code. | Evaluate for isolated main-subject cutouts, not choosing one specific river/leaf among many. Alpha matting and binary glyph masks have different objectives. Check exact checkpoint and exported model license/quality; no third-party conversion size treated as an official guarantee. |

No new ML runtime, model weights, paid API or custom training has been added. These are candidates, not an implemented AI fallback.

## Promotion test before adding a model

1. Collect a consented, versioned benchmark: 50 ink/pencil captures, 50 isolated objects, 50 difficult scenes (shadows, same-color background, thin stems, holes, separated pieces). Do not use private uploads for training without consent.
2. Hand-label intended masks and letter membership; split by creator/camera/background, not near-duplicate images.
3. Compare threshold, GrabCut, MobileSAM, EfficientSAM and one automatic cutout model. Run identical resize and prompts. Record mask IoU, boundary quality, dot/hole preservation and human correction time; generic COCO scores are insufficient.
4. Measure cold/warm p50/p95 latency, peak resident memory, model download bytes, mobile memory/thermal behavior, and failure/retry rate on the actual selected deployment hardware.
5. Proposed gates (targets, not results): >90% acceptance after at most one correction in supported plain-background scenes; no regression on disconnected parts; warm p95 <3 seconds per image; <$0.01 active processing per image; CPU memory within the chosen worker's measured budget. Revisit targets with user tests.
6. Account for 94 glyphs × attempts. At $0.01 per rescue and two attempts per glyph, model processing alone reaches $1.88/font; do not multiply a single-image demo into a misleading font-cost promise.
7. Only adopt a pinned commercially usable checkpoint if reduction in correction/support cost justifies download/runtime complexity. Add bounded positive/negative correction strokes before contemplating custom training.

## Quiet template decision

1.15pt = 1.15/72 inch ≈ 0.406mm; at 300DPI it spans about 4.79 pixels, and at 150DPI about 2.40 pixels. It is not intrinsically invisible to a camera. Contrast, blur, printer behavior and thresholding determine its effect.

Prefer no interior grid/guide strokes in extracted regions. Minimal external labels/cell cues can remain human-readable and be excluded using known template geometry. Four page corners establish the plane, not template identity, upright orientation, print scale or absence of paper curl. Retain explicit A4/version selection and corner confirmation. Final print legibility and real capture quality require actual printer/phone tests, not just synthetic renders.
