# Image style, scaling and vectorization experiments

Date: 2026-09-10. Reproduce: `.venv/bin/python scripts/experiment_vector_styles.py`.

## What was actually run

One deliberately difficult **synthetic** 1024px colored shape with an internal hole,
3px dark strokes, a 5px stem and a detached seed. Two interpretations (solid
foreground and dark interior detail), four raster sizes (128/256/512/1024), three
Potrace settings (faithful/balanced/smooth): **24 actual SVG traces**, with Potrace
PGM raster proofs. Source/masks/SVG/PGM files are in `output/vector-styles/`;
[raw metrics](vector-style-experiment.json) and [contact sheet](vector-style-comparison.png)
are retained here. This is an engineering probe, not real-world quality validation.

GrabCut took **8.9237s** on the busy local development host. No trained model was
run. Do not advertise a 3-second latency claim from a planning target.

## Findings

At the balanced setting, silhouette IoU against the full-size accepted mask was
0.962/0.980/0.992/0.994 at 128/256/512/1024px. Dark-detail IoU was much worse:
0.097/0.193/0.623/0.669. Visual inspection confirms that low-resolution dark lines
fragment or disappear. Rasterized topology also changes, even at 1024px. Large
filled-area overlap can conceal broken small details, so IoU alone is inadequate.

The synthetic strokes intentionally include separated pieces and crossings;
raw topology counts include tiny artifacts and are diagnostic, not a claim that
every component is semantically meaningful. The accepted segmentation itself
is not a hand-labeled ground-truth mask. Vector metrics compare each trace to
its **style-specific accepted raster**, not segmentation accuracy against reality.

## Product decisions from this evidence

1. **Do not aggressively downscale first.** Bound uploads/decoded pixels, orient
   the source, select the region, preserve the accepted working mask up to the
   current 1024px limit, then fit vector outlines into the font's em square.
   Vector scaling is not the same as discarding image pixels.
2. Keep **Ink/detail** and **Object silhouette** distinct. Preserving photographic
   appearance is not achievable by silently turning every foreground pixel black.
   A later combined mode can mask the object first, then preserve chosen luminance
   detail inside it. Preview both interpretations before choosing.
3. Never automatically drop small components or fill counters. Generic denoising
   often damages fonts. Offer explicit, reversible corrections instead.
4. Trace simplification is a quality/complexity tradeoff, not always an improvement.
   Keep a conservative default and gate smoothing controls on preview tests.
5. Show actual generated fonts at small and display sizes, alongside the accepted
   mask. Small-size legibility, stroke continuity, counter preservation, curve
   complexity and correction time matter more than a visually smooth large SVG.
6. Photographic color/texture requires a separate color-font track (e.g. COLR/SVG
   formats and app-specific compatibility tests). Current outputs are monochrome
   outlines; no promise of retaining original color or every material texture.

## Experiments still required before “world-class” is a defensible claim

- Real pen, pencil, brush, leaf, thread and river-like shapes on multiple backgrounds.
- Controlled-sheet resolution: current canonical geometry is 150DPI (roughly 100px cell widths). Benchmark 300/600DPI extraction and fewer/larger cells per page before claiming fine texture fidelity; scaling low-resolution outlines to 1000UPM cannot recreate lost detail.
- Crop-at-source-resolution vs whole-image resizing; the current whole-image bound
  can erase a tiny subject inside a large photo. Guide users to fill the frame now.
- Partial transparency, gradients and anti-aliasing, threshold sensitivity and
  positive/negative correction brushes.
- Repeated phone/print tests across lighting, lens distortion and compression.
- Independent creators' judgments and measured time to satisfactory font.
- Actual Windows/macOS installation and Word/PowerPoint rendering tests.

The present alpha is a testable foundation, not completion of those experiments.

## Additional real-photograph probe

Used the [OpenCV sample fruit photograph](https://github.com/opencv/opencv/blob/4.x/samples/data/fruits.jpg)
for a local experiment selecting the orange wedge, not a claim about user-photo
accuracy. Two rectangle prompts × two styles produced four further SVG traces.
The source hash, exact rectangles and measurements are in
[real-object-probe.json](real-object-probe.json); see the
[mask comparison](real-object-comparison.png). The original photograph is not
added to the tracked product assets.

- Tight-box silhouette: **1 component, 2,872-byte SVG**.
- Tight-box preserved dark detail: **27 components, 44,620-byte SVG**—over 15× the
  outline size. This retains texture-like variation, but does not reproduce color.
- A looser box admitted stray background pieces (17 silhouette components rather
  than 1). User selection/correction matters even when the main subject is found.
- Local cutout times were **8.202s / 12.074s** on this busy host, not production p95.
- Visual inspection: the orange wedge is recognizable as a silhouette; the detail
  option is substantially more textured. Neither restores portions hidden behind
  the foreground lemon. No manually labeled ground truth was created, so no mask
  accuracy score is reported.

This strengthens the case for explicit style choice and reversible cleanup;
it does not justify claiming that arbitrary scenes or fine material textures
are solved. Current UI offers threshold detail and object silhouette separately;
combining a cutout with an interior-detail threshold remains a follow-up editor
feature after user validation.
