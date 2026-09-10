# ML foreground segmentation model selection — 10 September 2026

## Final decision after local measurements

Keep threshold and GrabCut as the inexpensive baselines. Add two explicit optional local paths: **EfficientSAM-Ti for real box prompts**, and **SlimSAM-77 fp32 for keep/exclude point prompts**. No automatic universal quality ranking is justified by the five-fixture probe.

The initial SlimSAM int8 preference was based on checkpoint size. Actual measurements reversed that preference: fp32 had lower peak RSS and slightly lower warm median in this environment. EfficientSAM was subsequently downloaded, graph-verified, benchmarked and integrated; it is no longer merely a future candidate. Final numbers and scope are recorded at the end and in the [runbook](../ML-SEGMENTATION.md).

The SlimSAM export exposes no `input_boxes`; invalid labels2/3 caused inverse/background selection in an early rejected experiment. The shipped path uses real keep/exclude points (labels1/0), while EfficientSAM uses supported box-corner embeddings. Neither auto-accepts a mask.

## Candidate evidence at selection time

Selection-result entries below record the preliminary investigation; final adoption is stated above.

| Package / checkpoint | Pinned version or revision | Download bytes | License evidence | Prompt / graph support | Maintenance / adoption evidence | Selection result |
|---|---:|---:|---|---|---|---|
| **Xenova/slimsam-77-uniform ONNX** | HF revision `5850ab45f587c112167512ffef949107115e26a0` | Quantized pair: `vision_encoder_quantized.onnx` 8,882,165 + `prompt_encoder_mask_decoder_quantized.onnx` 4,903,810 = **13,785,975 bytes**. Full FP32 pair: 39,833,906 bytes. | HF model card metadata says `license: apache-2.0`; base model `nielsr/slimsam-77-uniform`; base model card also says Apache-2.0. Original SlimSAM GitHub repository is detected by GitHub as Apache-2.0. | **Points only in exported graph:** encoder input `pixel_values float [batch,3,1024,1024]`; decoder inputs `input_points float [batch, point_batch, n, 2]`, `input_labels int64 [batch, point_batch, n]`, `image_embeddings`, `image_positional_embeddings`; no `input_boxes`. Preprocess: RGB, resize longest edge 1024, pad to 1024x1024, rescale 1/255, mean `[0.485,0.456,0.406]`, std `[0.229,0.224,0.225]`. | HF API on 2026-09-10: 54,006 downloads, 30 likes, last modified 2026-03-18. Upstream SlimSAM repo: 364 GitHub stars, pushed 2025-09-27. | **Best small dependency shape, but not box-ready.** Use only for experimental positive/negative click path after benchmark. |
| **Xenova/slimsam-50-uniform ONNX** | HF revision `3959c85fa93ab1c3dedd879c833aae1931961e19` | Quantized pair: 30,068,885 + 4,903,810 = **34,972,695 bytes**; FP32 pair is 112,786,946 bytes. | HF model card says Apache-2.0. | Same HF SAM shape family; likely same point/box split risk unless graph inspection proves `input_boxes`. | HF API: 464 downloads, last modified 2026-03-18. | Not preferred: bigger than SlimSAM-77 and no evidence it fixes rectangle prompting. |
| **EfficientSAM-Ti ONNX** | HF Space revision `d8dbb1eee73bfb3392aa6f6e8944aeb13f3f4036`; upstream repo head inspected `d525f622e6f640acf5a0fc37c7ca1f243da5bde0` | Separate ONNX pair: `efficientsam_ti_encoder.onnx` 24,799,761 + `efficientsam_ti_decoder.onnx` 16,565,728 = **41,365,489 bytes**; monolithic `efficientsam_ti.onnx` 41,365,520 bytes. | Upstream repo and HF Space metadata say Apache-2.0. | **Different model family from SlimSAM/SAM-HF export.** Official EfficientSAM source encodes labels `1` positive, `2` bbox top-left and `3` bbox bottom-right as first-class learned embeddings; padding is `-1`; app point-removal uses `0`. The pinned HF Space box UI forms two corner points and labels `[2,3]`. Preprocess source: input image tensor `[B,3,H,W]`, resize to 1024x1024 if needed, normalize with mean `[0.485,0.456,0.406]`, std `[0.229,0.224,0.225]`; HF Space first rescales longest edge to `input_size` before model call. Actual downloaded graph: encoder input `batched_images [batch,3,height,width]`; decoder inputs `image_embeddings`, `batched_point_coords [1,1,num_points,2] float`, `batched_point_labels float`, `orig_im_size int64[2]`; outputs `output_masks`, `iou_predictions`, plus extra low-res/logit tensor `onnx::Shape_1830`. | GitHub API: 2,493 stars, pushed 2024-12-24; HF Space: 81 likes, last modified 2024-01-12. | **Best actionable quality-comparison candidate** for real rectangle prompting under 100MB; direct ORT benchmark target after graph-signature confirmation. |
| **MobileSAM `mobile_sam.pt` + official ONNX export** | GitHub `master` head inspected `f706ad9c4eb7f219c00d9050e46328518ffb65d2`; weight blob `7ef2d090979fd9853adf17b7a99c8b94a1c5a6a7` | PyTorch checkpoint 40,728,226 bytes; exported ONNX decoder size must be produced locally. | Upstream repo is Apache-2.0. | Official export script exports the **prompt encoder + mask decoder**, not a standalone image encoder. Decoder inputs follow original SAM ONNX style: `image_embeddings`, `point_coords`, `point_labels`, `mask_input`, `has_mask_input`, `orig_im_size`; labels include 0/1/2/3 through original SAM-style prompt handling. Requires PyTorch to create embeddings unless a trusted encoder ONNX is separately adopted. | GitHub API: 5,866 stars, pushed 2026-05-05. README reports 9.66M parameters and an authors' Mac i5 CPU demo around 3s, but this is not this app's measurement. | Good model family, **not the no-PyTorch direct-ORT answer** from official artifacts alone. |
| **FastSAM** | Upstream repo checked 2026-09-10 | Checkpoints not selected. | Conflict: README says the model is Apache-2.0, but GitHub repository license is AGPL-3.0 and the project builds on Ultralytics/YOLOv8. | Prompting is post-processing over generated masks; not a SAM encoder/decoder drop-in. | High adoption (8,408 stars), but license/runtime risk for SaaS. | Exclude for this product unless counsel approves the dependency stack. |
| **onnx-community SlimSAM variant** | `onnx-community/slimsam-77-uniform` | N/A | N/A | Public HF API returned 401 / not accessible; model search on 2026-09-10 did not show a public onnx-community SlimSAM model. | N/A | Exclude until a public, inspectable artifact exists. |

## Local measurements

Environment: repository checkout, macOS 26.5 arm64, Python 3.14.7, `onnxruntime==1.29.0`, `numpy==2.5.3`, CPUExecutionProvider. These are smoke measurements, **not quality results**.

| Claim measured | Result |
|---|---|
| ORT Python 3.14 install | `onnxruntime==1.29.0` installed and imported successfully on CPython 3.14.7. |
| SlimSAM-77 quantized graph load | Encoder session init ~375ms; decoder init ~106ms in one run. |
| SlimSAM-77 graph signatures | Encoder input/output and decoder input/output matched the table above. |
| Dummy/real-image CPU latency | Encoder warm reps varied roughly 1.6s-8.6s depending run/session options; decoder roughly 70ms-520ms. A real-image smoke (`output/real-cutout-probe/fruits.jpg`, resized/padded to 1024) produced repeat encoder timings ~2.3s, 4.8s and decoder ~122ms, 125ms in the default run. |
| Memory warning | ORT process RSS during encoder runs reached multi-GB levels in local smoke. Measure in the final service process before adopting. |

## EfficientSAM-Ti actionable comparison target

Use this as the **non-SlimSAM quality comparison** if root wants a commercially usable prompted model under 100MB:

```text
https://huggingface.co/spaces/yunyangx/EfficientSAM/resolve/d8dbb1eee73bfb3392aa6f6e8944aeb13f3f4036/efficientsam_ti_encoder.onnx
sha256 84ed466ffcc5c1f8d08409bc34a23bb364ab2c15e402cb12d4335a42be0e0951
size 24,799,761 bytes

https://huggingface.co/spaces/yunyangx/EfficientSAM/resolve/d8dbb1eee73bfb3392aa6f6e8944aeb13f3f4036/efficientsam_ti_decoder.onnx
sha256 a62f8fa5ea080447c0689418d69e58f1e83e0b7adf9c142e2bd9bcc8045c0b11
size 16,565,728 bytes

Optional monolithic file for parity checks:
https://huggingface.co/spaces/yunyangx/EfficientSAM/resolve/d8dbb1eee73bfb3392aa6f6e8944aeb13f3f4036/efficientsam_ti.onnx
sha256 143c3198a7b2a15f23c21cdb723432fb3fbcdbabbdad3483cf3babd8b95c1397
size 41,365,520 bytes
```

Source-level prompt contract from official EfficientSAM code: `predict_masks(image_embeddings, batched_points, batched_point_labels, multimask_output, input_h, input_w, output_h, output_w)` rescales prompt coordinates from source `input_h`/`input_w` to 1024; max points are padded/truncated to six. The prompt encoder gives learned embeddings to label `1` positive points and box-corner labels `2`/`3`; invalid padding is `-1`. The HF Space uses labels `[2,3]` for box mode. This is stronger rectangle evidence than SlimSAM-77's HF SAM ONNX export.

**Do not double-normalize EfficientSAM-Ti.** The HF Space converts a PIL/NumPy RGB image with `torchvision.transforms.ToTensor()`, which produces CHW float data in `[0,1]`. Official `get_image_embeddings` calls `preprocess`; `preprocess` resizes to the encoder's 1024 square if shape differs, then subtracts ImageNet mean and divides by ImageNet std internally. The downloaded ONNX encoder graph matches this: first graph operations are dynamic `Resize` to `[1024,1024]`, then `Sub` by `[0.485,0.456,0.406]`, then `Div` by `[0.229,0.224,0.225]`. Feed raw RGB float `[0,1]`, not pre-normalized tensors.

**EfficientSAM-Ti decoder output is logits, resized to `orig_im_size`.** Official `predict_masks` interpolates low-resolution masks to requested output height/width and returns `output_masks` plus `iou_predictions`; the HF Space applies `sigmoid(predicted_logits) >= 0.5` outside the model. The downloaded decoder graph has a final `Resize` feeding `output_masks` and no `Sigmoid` operator, so thresholding belongs outside ORT. Use `orig_im_size=[height,width]` matching the coordinate space supplied to `batched_point_coords`.

## Prompting conclusion

For **Xenova/slimsam-77-uniform**, use this conservative interpretation:

- Supported: positive labels `1`, negative labels `0`, padding labels `-10` / `-1` as processor conventions require.
- Not supported as a real box prompt by this export: passing two corner coordinates with labels `2`/`3`. Graph inspection shows the point path only adds learned type embeddings for labels `0` and `1`; HF's separate `_embed_boxes` path adds the box-corner embeddings, but the ONNX decoder file has no `input_boxes` input.
- Product implication: a rectangle UI can seed a **derived point strategy** (for example center positive + several outside/edge negative points), but must not be described as a box-prompt SAM call unless a different graph with `input_boxes` is adopted.

## Preliminary recommendation (superseded by measured decision below)

**Use now:** keep GrabCut as the supported object-cutout path.

**Benchmark next:** EfficientSAM-Ti ONNX if the product needs a real box-prompt model under 100MB. Its public ONNX artifacts fit the size limit, official source has first-class labels `2`/`3` for bbox corners, and the pinned HF Space uses those labels in box mode; root confirmed actual ORT graph input/output names; CPU/RSS and quality measurement remain before implementation.

**Experimental flag only:** SlimSAM-77 quantized ONNX, pinned exactly below, for positive/negative click rescue after a failed GrabCut mask:

```text
https://huggingface.co/Xenova/slimsam-77-uniform/resolve/5850ab45f587c112167512ffef949107115e26a0/onnx/vision_encoder_quantized.onnx
sha256 cce23c7b2e5d4f330932738fb67ba518e04b0d99ccdd1cccd22a7da4e01f2971

https://huggingface.co/Xenova/slimsam-77-uniform/resolve/5850ab45f587c112167512ffef949107115e26a0/onnx/prompt_encoder_mask_decoder_quantized.onnx
sha256 cb90b279f549d2cab7fd6e20c38522438c65d84bdcca3d2a764cff7d857fdce2
```

## Risks and mitigations

- **Wrong foreground/background despite high IoU score** — Mitigation: never auto-accept; show mask preview; keep GrabCut and manual redo.
- **No true rectangle prompt in SlimSAM-77 ONNX** — Mitigation: either implement point-only UX or inspect EfficientSAM-Ti / MobileSAM original-SAM decoder artifacts for real box support.
- **CPU/RSS may exceed small worker budgets** — Mitigation: benchmark in a forked service process with final session options, p50/p95 latency and peak RSS before adding a runtime dependency.
- **License metadata is not legal advice** — Mitigation: preserve model cards, GitHub license texts and exact artifact SHAs in `NOTICE`/third-party inventory before shipping.

## Sources

- [Existing foreground extraction decision](foreground-segmentation.md) — current GrabCut baseline and promotion gates.
- [Xenova/slimsam-77-uniform model card](https://huggingface.co/Xenova/slimsam-77-uniform) and [HF model API](https://huggingface.co/api/models/Xenova/slimsam-77-uniform/revision/5850ab45f587c112167512ffef949107115e26a0?blobs=true) — ONNX files, sizes, LFS SHA256, base model and Apache-2.0 metadata.
- [nielsr/slimsam-77-uniform HF model API](https://huggingface.co/api/models/nielsr/slimsam-77-uniform/revision/main?blobs=true) — base safetensors SHA and Apache-2.0 metadata.
- [SlimSAM GitHub repository](https://github.com/czg1225/SlimSAM) and [GitHub license API](https://api.github.com/repos/czg1225/SlimSAM/license) — upstream project and Apache-2.0 license detection.
- [Hugging Face Transformers SAM source](https://github.com/huggingface/transformers/blob/main/src/transformers/models/sam/modeling_sam.py) — `_embed_points` labels 0/1 and separate `_embed_boxes` path.
- [EfficientSAM GitHub repository](https://github.com/yformer/EfficientSAM), [README](https://github.com/yformer/EfficientSAM/blob/main/README.md), [source model code](https://github.com/yformer/EfficientSAM/blob/main/efficient_sam/efficient_sam.py), [source decoder code](https://github.com/yformer/EfficientSAM/blob/main/efficient_sam/efficient_sam_decoder.py), [pinned HF Space app](https://huggingface.co/spaces/yunyangx/EfficientSAM/blob/d8dbb1eee73bfb3392aa6f6e8944aeb13f3f4036/app.py), and [HF Space API](https://huggingface.co/api/spaces/yunyangx/EfficientSAM/revision/d8dbb1eee73bfb3392aa6f6e8944aeb13f3f4036?blobs=true) — Apache-2.0 license, checkpoint/ONNX files, point/box labels, preprocessing and model sizes.
- [MobileSAM GitHub repository](https://github.com/ChaoningZhang/MobileSAM), [README](https://github.com/ChaoningZhang/MobileSAM/blob/master/README.md), and [official ONNX export script](https://github.com/ChaoningZhang/MobileSAM/blob/master/scripts/export_onnx_model.py) — Apache-2.0 license, checkpoint size, reported CPU demo, and ONNX decoder input contract.
- [FastSAM GitHub repository](https://github.com/CASIA-IVA-Lab/FastSAM) — README license statement, prompting modes and AGPL-3.0 repository license metadata.
- [onnxruntime PyPI](https://pypi.org/project/onnxruntime/) — current `onnxruntime==1.29.0` package and MIT license metadata.


## Final local-measurement override

The earlier quantized-only selection above was a preliminary file-size hypothesis, **not the final serving decision**. Actual isolated process tests with two ORT intra-op threads measured fp32 peak RSS2.71GB vs int8 3.62GB; warm medians over three repeated calls were1.88s vs1.98s. On the five synthetic fixtures, fp32 meanIoU0.715390/topology3of5 vs int8 0.693304/topology1of5. Therefore **fp32 is the explicit experimental learned rescue default**, not int8. Model download size does not predict activation memory or useful speed. Neither beats classical extraction across the supported tasks, so Auto without keep points remains classical with honest disclosure. These small local measurements are not production p95 or general accuracy claims. See [implementation/runbook](../ML-SEGMENTATION.md) and the final benchmark report.


### EfficientSAM measured decision

The second-family probe and actual local serving canary are now complete. EfficientSAM-Ti is implemented as an explicit optional `box-model`, not auto-promoted. Five-fixture meanIoU0.730246, boundaryF1 0.865035, topology3/5; the isolated four-call probe measured warm median0.7055s and peakRSS1,385,398,272bytes. This is encouraging for box-first capture, not a representative accuracy/cost guarantee. The runbook records methods, unequal prompt budgets, failure cases and promotion gates.
