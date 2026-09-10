# Ink Mask Qualitative Real-Source Panels

These panels compare the local deterministic `global` threshold with the explicit `adaptive` local-mean threshold on rights-clean historical handwriting sources. They are qualitative diagnostics only: there is no ground-truth mask and no accuracy claim.

Evaluator: `node scripts/benchmark_real_ink.cjs --max-side=360`. Panel layout is source, global mask, adaptive mask. Adaptive defaults are frozen at local radius 12 and offset 18.

## Caveats

- No ground-truth masks are available for these page photographs; foreground ratios and differing-pixel ratios are descriptive diagnostics, not scores.
- Historical scans include paper texture, bleed-through, ruled lines, shadows, and scanning artifacts; adaptive thresholding can reduce broad paper shadows but may also thicken strokes or catch page edges.
- These are full-page/document images, not controlled single-glyph capture photos.

## Sources and panels

### commons-001: Cesare Borgia, handwritten letter 2

- Panel: `commons-001-Cesare-Borgia-handwritten-letter-2-panel.png`
- Source file: `output/detection-sources/handwriting/commons-001-Cesare-Borgia-handwritten-letter-2.jpg`
- Source URL: https://commons.wikimedia.org/wiki/File:Cesare_Borgia,_handwritten_letter_2.jpg
- License/rights: Public domain
- Author/attribution: Cesare Borgia
- SHA-256: `2142d274b813b538be53c6e9f9da7e536c1b52a6d9698e59c506eb3a6baa79f8`
- Diagnostics: global foreground ratio 0.0965; adaptive foreground ratio 0.1463; differing-pixel ratio 0.0498

### commons-002: William Burnett Letter May 24, 1726

- Panel: `commons-002-William-Burnett-Letter-May-24-1726---NARA---193049-panel.png`
- Source file: `output/detection-sources/handwriting/commons-002-William-Burnett-Letter-May-24-1726---NARA---193049.jpg`
- Source URL: https://commons.wikimedia.org/wiki/File:William_Burnett_Letter_May_24,_1726_-_NARA_-_193049.jpg
- License/rights: Public domain
- Author/attribution: William Burnet
- SHA-256: `5791c889abf9942f8fe33ed929a73b8ebc11d4b7173420f5702c49915fed6088`
- Diagnostics: global foreground ratio 0.1155; adaptive foreground ratio 0.1424; differing-pixel ratio 0.0271

### commons-003: Annie Fields to Sarah Watson Dana, 26 March 1867 (afcfff9e-1414-44c2-84c3-98c42497f8ef)

- Panel: `commons-003-Annie-Fields-to-Sarah-Watson-Dana-26-March-1867-afcfff9e-1414-44c2-84c3-98c42497f8ef--panel.png`
- Source file: `output/detection-sources/handwriting/commons-003-Annie-Fields-to-Sarah-Watson-Dana-26-March-1867-afcfff9e-1414-44c2-84c3-98c42497f8ef-.jpg`
- Source URL: https://commons.wikimedia.org/wiki/File:Annie_Fields_to_Sarah_Watson_Dana,_26_March_1867_(afcfff9e-1414-44c2-84c3-98c42497f8ef).jpg
- License/rights: Public domain
- Author/attribution: Annie Fields (1834-1915)
- SHA-256: `e24b8c744cdea524efbc3220a4ba50aa90bc972ec0f45decec36761802154e8f`
- Diagnostics: global foreground ratio 0.0405; adaptive foreground ratio 0.0560; differing-pixel ratio 0.0155

### commons-004: Józef Chełmoński list 1859

- Panel: `commons-004-J-zef-Che-mo-ski-list-1859-panel.png`
- Source file: `output/detection-sources/handwriting/commons-004-J-zef-Che-mo-ski-list-1859.jpg`
- Source URL: https://commons.wikimedia.org/wiki/File:J%C3%B3zef_Che%C5%82mo%C5%84ski_list_1859.jpg
- License/rights: Public domain
- Author/attribution: Józef Chełmoński
- SHA-256: `3c0259504059de829cfffd6379f8deb1b07f9ed4eafcdccfbf00d8be8e68c1e0`
- Diagnostics: global foreground ratio 0.0688; adaptive foreground ratio 0.0887; differing-pixel ratio 0.0200

### commons-005: George Washington Letter to Mrs. Carroll November 22, 1789 - DPLA - 2a7955d332258a03f27b3868135ec92e (page 1)

- Panel: `commons-005-George-Washington-Letter-to-Mrs.-Carroll-November-22-1789---DPLA---2a7955d332258a03f27b386-panel.png`
- Source file: `output/detection-sources/handwriting/commons-005-George-Washington-Letter-to-Mrs.-Carroll-November-22-1789---DPLA---2a7955d332258a03f27b386.gif`
- Source URL: https://commons.wikimedia.org/wiki/File:George_Washington_Letter_to_Mrs._Carroll_November_22,_1789_-_DPLA_-_2a7955d332258a03f27b3868135ec92e_(page_1).gif
- License/rights: Public domain
- Author/attribution: Kennedy, John F. (John Fitzgerald), 1917-1963
- SHA-256: `a5f0cdbab6cdd6f86f03bf3c1938f3f72aa7ec5b6f4689be56a17ca4cc6524d7`
- Diagnostics: global foreground ratio 0.0769; adaptive foreground ratio 0.1251; differing-pixel ratio 0.0482


## Production-resolution follow-up

Root additionally ran all five sources at the app’s maximum working side (1024 px; smaller originals are not upscaled). See `diagnostics-1024.json`; the five retained panel PNGs above remain the clearly labeled 360 px comparison. Adaptive radius stays 12 working pixels, so these resolutions are separate qualitative conditions, not interchangeable scores. The evaluator now verifies each manifest image hash and never auto-includes unlisted cache files.
