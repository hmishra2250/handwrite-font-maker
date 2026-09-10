# Optional model provenance

No weights are committed or downloaded during inference. Installation is explicit.

- **SlimSAM:** upstream https://github.com/czg1225/SlimSAM; conversion https://huggingface.co/Xenova/slimsam-77-uniform at `5850ab45f587c112167512ffef949107115e26a0`; base https://huggingface.co/nielsr/slimsam-77-uniform. Upstream license text retained as `SlimSAM-APACHE-2.0.txt` (GitHub license blob `261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64`). Model/base cards declare Apache-2.0. Converted export is point-prompt only, not the original SAM box API.
- **EfficientSAM:** upstream https://github.com/yformer/EfficientSAM; author Space https://huggingface.co/spaces/yunyangx/EfficientSAM at `d8dbb1eee73bfb3392aa6f6e8944aeb13f3f4036`. Upstream license retained as `EfficientSAM-APACHE-2.0.txt` (GitHub license blob `261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64`). Space metadata also declares Apache-2.0.
- Model binaries are unmodified. Integration/preprocessing code in this repository is separate; exact binary sizes and SHA-256 values are pinned in `segmentation.py` and `efficient_segmentation.py` and independently checked at install/load.
- Optional ONNX Runtime 1.29.0 uses its package-distributed MIT license. Preserve package license notices in distributed runtimes.

Evidence checked 2026-09-10. This inventory records upstream declarations, not legal advice or a guarantee concerning rights in user-uploaded artwork.
