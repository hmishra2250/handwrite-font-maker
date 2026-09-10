# Technology Research: Handwrite Font Maker

**Implementation boundary:** Alpha ships validated TTF/OTF only. WOFF/WOFF2 recommendations below are future roadmap, not a currently available output.

**Request type:** Comprehensive technical research (official-docs-first, version/date-aware).
**Access date for live sources:** 2026-09-10.
**Firecrawl path:** Firecrawl search was run first and returned official OpenCV 4.13 ArUco documentation in `.firecrawl/search-opencv-official.json`; broader multi-domain primary-source collection then used direct web/cURL fallback for FontForge, Potrace, WOFF2, Microsoft Office, model pricing, and SAM sources.
**Local context inspected:** `pyproject.toml`, `web/package.json`, `README.md`, and `tests/CAPTURE_TEST_REPORT.md` only. The repo currently has a Python/OpenCV/Pillow/ReportLab core, system `potrace` + `fontforge`, a Next.js web UI, and tests showing an ArUco/fixed-grid baseline rather than true markerless flat-paper capture.

## Direct Answer

The best end-to-end stack for this product is **deterministic computer vision + manual correction + deterministic font engineering**, with **selective ML only as an optional rescue path** for difficult object/leaf uploads or non-paper backgrounds. Do **not** make a VLM or custom-trained segmentation model part of the default per-font path.

Recommended default pipeline:

1. **Markerless flat paper capture**: detect a page quadrilateral using OpenCV threshold/edges/contours; present four draggable corners whenever confidence is low or the page is not flat. Keep ArUco as an internal QA/template option, not the only user path.
2. **Perspective rectification**: compute homography from the four page corners and warp to a canonical template size.
3. **Cell/glyph extraction**: use the template grid, but fix the current crop/guide/baseline mismatch. A robust font needs per-cell baseline, x-height/cap-height, ascender/descender zones, side bearings, and advance-width inference, not just binary masks.
4. **Mask cleanup**: for pen handwriting, use grayscale normalization, guide-line removal, adaptive/Otsu thresholding, morphology, connected-component filtering, and contour sanity checks.
5. **Vectorization**: use Potrace/SVG paths or OpenCV contours, but post-process outlines: orientation, simplify, remove overlaps, add extrema/rounding where needed, and validate glyph/font output.
6. **Font generation**: generate desktop **TTF/OTF** with FontForge; generate **WOFF2** separately for web with fontTools or a WOFF2 encoder. Use TTF/OTF for Word/PowerPoint; WOFF2 is for web delivery, not Office installation.
7. **Human correction loop**: show a proof sheet and editable preview before final download. The cheapest robustness improvement is UI correction, not per-upload AI.

Guided labeled one-character uploads for pens/leaves/objects should be treated as a **separate “single glyph / icon glyph” workflow**: the user picks the Unicode/label, the app extracts a mask from one image, lets the user erase/restore/refine, then runs the same vector/font QA. Pens can stay deterministic; leaves/objects may benefit from optional SAM-style segmentation only when deterministic foreground extraction fails.

## Official Docs Evidence

### Computer vision and page/glyph extraction

- OpenCV 4.13.0 ArUco documentation: https://docs.opencv.org/4.13.0/d5/dae/tutorial_aruco_detection.html
  Establishes that ArUco detection returns marker IDs and four corners; its detection process uses adaptive thresholding, contours, square-candidate filtering, perspective normalization, Otsu thresholding, and dictionary/error-correction checks. The page says compatibility is OpenCV >= 4.7.0.
- OpenCV 4.13.0 geometric transforms: https://docs.opencv.org/4.13.0/da/d54/group__imgproc__transform.html
  Establishes `getPerspectiveTransform` and `warpPerspective` for mapping a source quadrilateral to a destination quadrilateral/canonical image.
- OpenCV 4.13.0 thresholding tutorial: https://docs.opencv.org/4.13.0/d7/d4d/tutorial_py_thresholding.html
  Establishes simple thresholding, adaptive thresholding, and Otsu thresholding; adaptive thresholding is specifically useful when illumination varies across the sheet.
- OpenCV 4.13.0 structural analysis/contours: https://docs.opencv.org/4.13.0/d3/dc0/group__imgproc__shape.html
  Establishes `findContours` for binary images and notes binary masks can be produced via thresholding/adaptive thresholding/Canny/etc.
- OpenCV license, 4.x branch: https://raw.githubusercontent.com/opencv/opencv/4.x/LICENSE
  OpenCV 4.x is Apache License 2.0.

### Raster-to-vector and font generation

- Potrace homepage/man page/version/license: https://potrace.sourceforge.net/ and https://potrace.sourceforge.net/potrace.1.html
  Potrace 1.16 transforms bitmaps into vector graphics, supports SVG/PDF/EPS/PostScript and other backends, exposes options such as speckle suppression (`--turdsize`) and curve optimization tolerance, and is GPL-2.0-or-later with a separate proprietary “Potrace Professional” option.
- Potrace README: https://potrace.sourceforge.net/README
  Documents GPL-2.0-or-later license, author/copyright, algorithm docs, and trademark policy.
- FontForge Python scripting docs, 20251009 documentation: https://fontforge.org/docs/scripting/python/fontforge.html
  Establishes Python scripting for importing outlines, simplifying glyphs, correcting contour direction, removing overlaps, validating glyphs/fonts, and generating font files.
- FontForge license: https://raw.githubusercontent.com/fontforge/fontforge/master/LICENSE
  FontForge as a whole is GPL-3.0-or-later; most historical parts are under a revised BSD license, but distribution of the FontForge executable/package should be treated as GPL-compliance work.
- fontTools `ttLib`: https://fonttools.readthedocs.io/en/latest/ttLib/index.html
  Establishes fontTools as a library for reading/writing/manipulating OpenType and TrueType fonts, including TrueType-flavored `glyf`, CFF/CFF2, color, static, and variable fonts.
- fontTools WOFF2 docs: https://fonttools.readthedocs.io/en/latest/ttLib/woff2.html
  Establishes `fontTools.ttLib.woff2.compress(input_file, output_file, ...)` for compressing OpenType fonts to WOFF2 and `decompress` for reverse conversion.
- fontTools `cu2qu`: https://fonttools.readthedocs.io/en/latest/cu2qu/index.html
  Establishes cubic-to-quadratic curve conversion for TrueType-outline generation when needed.
- fontTools license: https://raw.githubusercontent.com/fonttools/fonttools/main/LICENSE
  fontTools is MIT-style licensed.
- W3C WOFF2 Recommendation: https://www.w3.org/TR/WOFF2/
  Current W3C Recommendation dated 2024-08-08. WOFF2 is a web-font packaging/compression format designed for lower bandwidth and fast decompression, not a replacement for desktop-installed TTF/OTF.
- Google WOFF2 reference implementation license: https://raw.githubusercontent.com/google/woff2/master/LICENSE
  Permissive license for the reference implementation.

### OpenType, Office, and portability

- Microsoft OpenType OS/2 `fsType` field: https://learn.microsoft.com/en-us/typography/opentype/spec/os2#fstype
  `fsType` encodes font embedding licensing rights: installable, restricted, preview/print, editable, no-subsetting, and bitmap-only restrictions. Applications that support embedding must respect these bits.
- Microsoft OpenType font file specification: https://learn.microsoft.com/en-us/typography/opentype/spec/otff
  Establishes the OpenType container context for TTF/OTF outputs.
- Microsoft Support, install custom fonts for Office: https://support.microsoft.com/en-us/office/fonts/download-and-install-custom-fonts-to-use-with-office
  Office uses fonts installed through the operating system. Windows installs via the system fonts UI; macOS uses Font Book. Custom fonts installed on one computer will not display identically on another unless installed or embedded; Office may substitute Times New Roman/defaults.
- Microsoft Support, embedding custom fonts: https://support.microsoft.com/en-us/office/fonts/benefits-of-embedding-custom-fonts
  Word/PowerPoint can embed fonts in supported desktop versions, but not all TrueType fonts can be embedded; font creators set embeddability; Microsoft recommends OpenType `.otf` or TrueType `.ttf` and avoiding PostScript `.pfb/.pfm`. Subsetting reduces file size but limits later editing.
- Microsoft Support, Manage Fonts in Windows: https://support.microsoft.com/en-us/windows/experience/personalization/manage-fonts-in-windows
  Windows can install `.ttf` and `.otf` files from Settings/right-click install; not all apps support custom fonts.

### ML/VLM evidence and pricing

- Meta SAM 2 README: https://raw.githubusercontent.com/facebookresearch/sam2/main/README.md
  SAM 2 is a promptable segmentation model for images/videos; SAM 2.1 checkpoints were released 2024-09-30; code requires Python >=3.10, PyTorch >=2.5.1, TorchVision >=0.20.1; it provides image predictors and automatic mask generation.
- Meta SAM 2 license: https://raw.githubusercontent.com/facebookresearch/sam2/main/LICENSE
  Apache License 2.0.
- Ultralytics README/license: https://raw.githubusercontent.com/ultralytics/ultralytics/main/README.md and https://raw.githubusercontent.com/ultralytics/ultralytics/main/LICENSE
  Ultralytics YOLO supports segmentation tasks, but the open-source package is AGPL-3.0 with a commercial Enterprise License option. Avoid by default for a proprietary web product unless legal/product intentionally accepts AGPL or buys a license.
- OpenAI API pricing: https://developers.openai.com/api/docs/pricing.md
  Accessed 2026-09-10. Prices per 1M tokens include `gpt-5-mini` standard at `$0.25` input / `$2.00` output and `gpt-5-nano` at `$0.05` input / `$0.40` output. The page directs vision-cost estimation to the image input cost calculator.
- OpenAI images/vision guide: https://developers.openai.com/api/docs/guides/images-vision.md
  Establishes that vision-capable language models can analyze images via Responses/Chat Completions, while image generation/editing is a separate image-model/tool workflow.
- Gemini Developer API pricing: https://ai.google.dev/gemini-api/docs/pricing
  Accessed 2026-09-10. Gemini 2.5 Flash-Lite standard paid tier is `$0.10`/1M input tokens for text/image/video and `$0.40`/1M output tokens; Gemini 2.5 Flash is `$0.30`/1M input tokens for text/image/video and `$2.50`/1M output tokens. Free-tier data may be used to improve Google products; paid tier says no.
- Google Cloud Run pricing: https://cloud.google.com/run/pricing
  Accessed 2026-09-10. Useful benchmark rates: active CPU around `$0.000024` per vCPU-second, memory around `$0.0000025` per GiB-second, requests around `$0.40` per million; L4 GPU no-zonal-redundancy around `$0.0001867` per second in listed tables. Region/consumption-model differences apply.

## Version Note

- Local Python manifest pins `opencv-python-headless>=4.13,<5`; OpenCV docs used are 4.13.0.
- FontForge docs fetched are labeled 20251009 documentation.
- Potrace upstream current homepage version is 1.16, released 2019-09-17.
- WOFF2 latest W3C Recommendation is dated 2024-08-08.
- AI model pricing and model names are especially volatile; the figures above are live-source values accessed on 2026-09-10 and must be refreshed before committing product pricing.

## Recommended Technical Architecture

### 1. Capture and corner correction

**Default UX:** “Upload or photograph a flat page, then confirm corners.” Use markerless detection first, but always expose four-corner manual correction. This is the correct economic tradeoff: deterministic quadrilateral detection is cheap and fast, while the occasional manual adjustment prevents expensive AI retries.

Implementation guidance:

- Downsample image for fast page detection, retain full-resolution image for extraction.
- Normalize illumination: grayscale, blur/denoise, adaptive threshold or edge detection.
- Find candidate page contours with `findContours`, approximate polygons, score by area, convexity, aspect ratio, edge proximity, and rectangularity.
- If score is below threshold, show draggable corners immediately.
- Rectify using `getPerspectiveTransform` + `warpPerspective` to a canonical template coordinate system.
- Add flatness guidance: local tests already show page bend/barrel distortion is the main failure mode; the app should tell users to flatten the page, not hide this as an “AI” problem.

### 2. Template, labels, crops, and baselines

The repo audit notes a guide/crop/baseline mismatch. Fix this before adding ML.

A robust font needs explicit template geometry:

- Cell outer bounds.
- Safe writing box.
- Baseline, x-height, cap-height, ascender, descender.
- Left/right side-bearing zones.
- Per-glyph Unicode/name mapping.
- Per-cell mask crop that does **not** include label text, guide marks, or neighboring cells.

For one-character uploads, the label comes from the user rather than a sheet cell; use the same internal glyph record: `{label, unicode, raw_image, mask, contours, metrics, corrections}`.

### 3. Glyph-mask extraction

For handwriting with dark pen on white paper, keep the deterministic baseline:

- White-balance/illumination normalization.
- Remove template guide lines by subtracting a known blank-template mask after rectification, or by ignoring guide zones.
- Adaptive threshold for uneven lighting; Otsu/global threshold for clean cells.
- Morphological open/close tuned to stroke width.
- Connected components: remove specks, retain plausible stroke components, preserve dots for `i`, `j`, punctuation, and diacritics.
- Optional per-glyph “ink amount” warning for blank/too-light/too-heavy cells.

For leaves/objects:

- First try deterministic foreground extraction if captured on a simple background.
- If the object has complex texture or background, offer interactive segmentation (manual brush or optional SAM 2 local inference) as a rescue/editing step.
- Do not auto-convert photographic texture into a text font; convert to a high-contrast silhouette/icon glyph unless the product explicitly supports color fonts later.

### 4. Contours and font robustness

The success criterion is not “we got masks”; it is “the font renders acceptably in browsers, Word, PowerPoint, and PDF export.” Add a font QA stage:

- Vectorize masks to paths with Potrace or OpenCV contours.
- Normalize contours into font units-per-em.
- Correct winding direction: external contours clockwise, holes counter-clockwise per FontForge tooling.
- Remove overlaps/intersections where possible.
- Simplify without destroying handwriting character; keep a max error/tolerance setting.
- Add extrema and round coordinates when appropriate for TrueType/OTF output.
- Compute advance width and side bearings from the extracted ink bounds plus user-selected style presets.
- Validate every glyph and whole font before generating final files.
- Render a proof sheet after generation, not just before generation.

### 5. Output formats

- **TTF**: primary desktop output for Microsoft Office and broad OS installability. If using cubic paths, convert to quadratic or let FontForge generate appropriate TrueType output; validate.
- **OTF**: acceptable desktop output and recommended by Microsoft alongside TTF for embedding, but test Office behavior on Windows/Mac.
- **WOFF2**: web output only. Generate from a valid TTF/OTF via fontTools/WOFF2. Do not present WOFF2 as an Office-installable format.
- **SFD/UFO/debug artifacts**: keep for reproducibility and support, but do not require users to understand them.

## Deterministic vs Segmentation ML vs VLM vs Custom Training

| Approach | Best use | Technical fit | Unit economics | License/compliance | Recommendation |
|---|---|---|---|---|---|
| Deterministic CV + manual correction | Page corners, rectification, pen glyph masks, contour/font generation | Excellent for fixed templates, flat paper, dark ink, user-confirmed corners | Near-zero variable cost; CPU only | OpenCV Apache-2.0; fontTools MIT; Potrace/FontForge GPL obligations if distributed | **Default path** |
| Deterministic + interactive UI correction | Low-confidence corners, bad crops, missing dots, baseline/spacing tuning | Excellent; turns failures into user-editable state | Cheapest robustness lever; support cost lower than opaque AI failures | No additional model/license risk | **Must-have** |
| Promptable segmentation ML (SAM 2) | Leaves/objects, complex backgrounds, optional mask refinement | Good for object masks; overkill for standard pen handwriting | Local CPU/GPU cost; GPU can be cheap per active second but operationally more complex | SAM 2 Apache-2.0; PyTorch stack operational weight | **Optional rescue feature** |
| YOLO/Ultralytics custom segmentation | Repeated known object classes, large labeled dataset, automated production segmentation | Not needed for handwriting template; dataset burden high | Training + labeling dominates; inference may be cheap after deployment | AGPL-3.0 unless Enterprise license | **Avoid by default** |
| VLM per upload | Explaining failures, maybe detecting “page is curled” or “wrong photo” | Weak for precise masks/contours; not deterministic; hard to guarantee geometry | Token-priced; cheap per call but not cheaper than deterministic CPU and adds latency/privacy variability | Provider terms/data controls; pricing volatile | **Use only for optional diagnostics, not masks** |
| Custom training | If measured deterministic+SAM cannot hit quality targets at scale | Premature until real failure corpus exists | Upfront dataset/labeling/eval cost far exceeds deterministic path | Depends on framework/model | **Defer** |

## Measured-vs-Assumed Unit Cost Model

### Measured in this repo now

From `tests/CAPTURE_TEST_REPORT.md`:

- 30 synthetic mobile-capture tests.
- 26 passed / 4 failed = 86.7% pass rate for the current ArUco/homography baseline.
- Reprojection error: min 0.00 px, max 3.75 px among passes, mean 0.40 px, threshold 5.00 px.
- Main failures: page bend/barrel distortion and combinations of tilt + bend + rotation.

This is a measurement of marker-based rectification robustness, **not** a full production unit-cost benchmark and not proof of markerless detection quality.

### Assumptions to benchmark next

Instrument and record per stage:

- `upload_decode_ms`
- `page_detect_ms`
- `manual_correction_rate`
- `rectify_ms`
- `cell_extract_ms`
- `mask_cleanup_ms`
- `vectorize_ms`
- `font_build_ms`
- `font_validate_ms`
- `proof_render_ms`
- `retry_rate`
- `support_rate`

Initial hypothesis was **5–30 seconds per full font**, but the leader's subsequent local baseline checks observed **49–133 seconds** for completed synthetic full-build tests and a later build exceeded several minutes on a busy shared host. The hypothesis is **not established**. See `../VALIDATION.md`; add subprocess bounds and measure controlled production-sized samples before any latency/pricing promise.

### Derived variable cost, CPU deterministic path

Using Cloud Run reference rates accessed 2026-09-10 (`$0.000024`/vCPU-second, `$0.0000025`/GiB-second, `$0.40`/1M requests), approximate cost:

`cost_per_job = (vCPU_seconds * 0.000024) + (GiB_seconds * 0.0000025) + 0.0000004 + storage/bandwidth`

Examples:

- 5 vCPU-s + 1 GiB for 5 s: about `$0.00013` plus storage/bandwidth.
- 15 vCPU-s + 2 GiB for 15 s: about `$0.00044` plus storage/bandwidth.
- 30 vCPU-s + 2 GiB for 30 s: about `$0.00087` plus storage/bandwidth.

These active-compute examples are below one cent, but do **not** establish actual end-to-end cost. Subprocess startup, retries, free previews, idle hosting and support must be measured; the product plan reserves $0.10/build provisionally.

### Optional local ML/SAM cost

If SAM 2 is used selectively for objects/leaves:

- Cloud Run listed L4 GPU rate example: `$0.0001867`/second before regional/instance/minimum-billing caveats.
- A 3-10 second GPU segmentation rescue would be roughly `$0.00056-$0.00187` GPU time, but real cost depends on cold starts, batching, model load time, and always-on/min-instance strategy.
- CPU-only SAM may avoid GPU ops but can increase latency and CPU seconds; benchmark with real object images.

Conclusion: optional ML can still be economically viable if invoked for a minority of uploads, but it should not be on the default pen-font path.

### VLM cost and why it is not the default

Approximate token-priced VLM diagnostics using live prices:

- OpenAI `gpt-5-mini`: `$0.25`/1M input tokens and `$2.00`/1M output tokens.
- Gemini 2.5 Flash-Lite: `$0.10`/1M text/image/video input tokens and `$0.40`/1M output tokens.

A single diagnostic call with a few thousand image/input tokens and a short text output can be sub-cent. But it does not produce deterministic, auditable masks or contours, and it adds privacy, latency, and price-volatility concerns. Use VLMs for optional user-facing explanations such as “page is curled,” “corner is cropped,” or “too little contrast,” not for primary extraction.

### Pricing implication

Do not force a `$3-$5` per-font price from compute economics. The variable compute cost target is closer to fractions of a cent for deterministic jobs. Product price should be derived from:

- User value and willingness to pay.
- Human-support burden.
- Storage/retention policy.
- Abuse/spam controls.
- Payment fees.
- Retry/correction rate.
- Font quality expectations.

The technical optimum is a cheap deterministic baseline with paid upgrades, not AI-per-upload processing.

## Microsoft Word/PowerPoint Font Install and Embed Limitations

- Office does not “install into Word/PowerPoint.” Fonts are installed into the OS, then Office sees them.
- On another computer, custom fonts may substitute unless the recipient installs the font or the document embeds it.
- Word/PowerPoint can embed fonts in supported desktop versions, including current Microsoft 365/2024/2021 variants, but embedding depends on the font’s `fsType` rights.
- If this app generates user-owned fonts, set `fsType` to **installable embedding** unless the product has a reason to restrict embedding.
- “Embed only characters used” reduces file size but limits later editing; recommend embedding all characters for editable shared documents.
- Use `.ttf` or `.otf`; avoid PostScript `.pfb/.pfm`.
- WOFF2 is for web delivery via CSS and should not be positioned as the Office portability format.
- Test on Windows Office and Mac Office separately. Microsoft’s support page says Mac Word/PowerPoint versions can embed fonts, but real-world behavior can still differ by font file, embedding bits, and Office version.

## License and Distribution Caveats

- **OpenCV**: Apache-2.0; suitable for proprietary server/client use with notice obligations.
- **fontTools**: MIT-style; suitable for proprietary use with notice obligations.
- **SAM 2**: Apache-2.0; suitable if operational burden is acceptable.
- **Potrace**: GPL-2.0-or-later unless using the commercial Potrace Professional license. Calling a system binary inside a SaaS backend is different from distributing a combined product, but shipping a Docker image/appliance containing Potrace requires GPL compliance. Get legal review if distributing binaries/containers to customers.
- **FontForge**: as a whole GPL-3.0-or-later. Same caveat: SaaS subprocess use is lower risk than distributing a packaged proprietary product with FontForge, but Docker/customer distribution needs license compliance.
- **Ultralytics**: AGPL-3.0 open-source path; avoid in proprietary default architecture unless buying an enterprise license or intentionally open-sourcing compatible server code.
- **Generated fonts**: the user’s handwriting/object image likely belongs to the user, but the app should include terms confirming the user has rights to upload source images and generate fonts from them.

## Gaps / Ambiguity Flags

- Markerless page detection has not been measured in the repo; current evidence is ArUco-based.
- Full font-build latency and success rate are not measured in the current research pass.
- Real Office embedding behavior should be validated with generated fonts on Windows and macOS.
- FontForge/Potrace licensing impact depends on deployment/distribution model; this is technical research, not legal advice.
- AI prices and model names can change; refresh pricing before launch/pricing decisions.

## Reusable Takeaway

Build the product around **deterministic markerless page rectification with four-corner correction, deterministic mask extraction, careful font-metric/outline QA, and TTF/OTF + WOFF2 outputs**. Add SAM-style segmentation only for optional object/leaf rescue workflows and VLM only for diagnostics. The economic winner is not “AI fonts at $3-$5”; it is a CPU-cheap, correction-friendly font pipeline whose quality comes from geometry, metrics, validation, and preview/edit UX.
