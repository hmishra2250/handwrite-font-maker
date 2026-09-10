# Local alpha capture diagnosis — 2026-09-11

The saved phone upload was a light A on a dark background. Its original capture
settings and returned mask were not persisted, so the previous extraction cannot
be reconstructed exactly. A 200 response established completion, not quality.

Local reproduction (not the user's recorded choices): at a 1024px maximum side,
threshold 170/dark ink selected 97.35% of pixels; light ink selected 2.64%. An
explicit crop around A with inverted Otsu threshold preserved the inner hole and
ran in about 2.5ms including PNG writing. A broad diagnostic GrabCut rectangle
[.1,.1,.9,.9] took 28.1s. Neither that rectangle nor that method is asserted to be
the user's original choice. The UI default rectangle is [.12,.12,.88,.88].

The current pipeline traces masks to SVG with Potrace and imports outlines into
font files. The editor shown before build is a raster mask, not the final vector.
A vector-first review and downloadable glyph SVGs remain separate product work;
this diagnostic change does not implement those features or automatic polarity.

## Opt-in host-local capture records

Set HANDWRITE_CAPTURE_DIAGNOSTICS_DIR to an absolute private directory (0700) to
record authorized, validated foreground API calls. Disabled by default. Enabled
for this local test under ignored `.alpha/capture-diagnostics`.

Each capture gets a random directory with a 0600 record.json and, on success,
mask.png. The record includes source object reference/SHA-256, hashed owner ID,
submitted rectangle/method/style/threshold/points, start time, elapsed time,
HTTP status, actual method/model/warnings and mask SHA-256. It is written before
processing, and again before sending the HTTP response, including error responses.
Headers, cookies, passwords and arbitrary extra request fields are not recorded.
Unauthenticated/unauthorized or invalid requests are not recorded. No public
endpoint exposes the diagnostic directory. The original stays in existing
owner-scoped object storage; its retention is not extended by this feature.

Records older than 24 hours are removed when the next capture begins. This is
lazy cleanup, not a periodic expiration guarantee: remove the local diagnostic
directory after the test session. Do not enable this debug feature as a substitute
for a production, owner-authorized capture history with retention/deletion rules.

Browser-only choices (current character, baseline, local threshold/invert, brush
edits) are not sent by the existing foreground request and are NOT captured by
this change. A complete versioned capture/project contract must include these
explicitly, along with source orientation, effective settings/defaults and
pipeline version. Do not claim that every frontend option is persisted yet.

Validation: 25 targeted Python tests cover diagnostic recording, success/failure
endpoint integration, existing capture contracts, private permissions, retention
sweep and opt-out. Restored source download was verified over the authenticated
public HTTPS object route with matching bytes. The local API was restarted with
recording enabled; the public tunnel URL and user sessions were preserved.

## Automatic vector choices — 2026-09-11 follow-up

The earlier limitations above describe the diagnostic-only version. Guided uploads
now request fast `ink` candidates, then optional `objects` candidates. The normal
review shows traced SVGs and SVG downloads; technical correction controls are
collapsed. Selecting a candidate uses its exact binary mask for font building.
A new photo/character or acceptance cancels stale UI requests, so late results
cannot replace the next letter. Manual edits invalidate the selected SVG.

### Same-photo findings and fixes

The retained white A on a black screen previously spent 417.8 seconds in native
GrabCut. It was a segmentation delay, not a font-build delay. Treating that photo
as dark ink also selected almost the entire background.

- Border/Otsu polarity detection now handles light-on-dark and dark-on-light.
- Clean and softened masks keep the A's enclosed counter. In the final local
  candidate smoke, both true SVG choices were ready in 0.496 seconds (backend
  processing only, not upload/network time).
- Adaptive thresholding eroded this letter; the disagreement check excluded it.
- Classical high-contrast extraction reports its actual method (`threshold`),
  rather than claiming it used GrabCut. Ambiguous GrabCut work uses a killable
  child, a 512px work image, and a four-second default deadline.
- Optional classical / EfficientSAM / SlimSAM attempts run concurrently in
  separate killable processes, capped at 25 seconds each. EfficientSAM's broad
  box selected the background in the real-image matrix and was rejected.
  SlimSAM produced a usable A in an isolated smoke, but cold runs are variable.
  Both ML attempts hit the deadline in the final concurrent smoke under local
  load. This is not evidence that either model works reliably for every image.
  Existing fast choices remain usable while these attempts run or fail.
- Potrace uses Bezier paths (`alphamax=.9`, `opttolerance=.15`), not embedded
  raster images. No hole filling or largest-component deletion is applied.
  Photographic margins are cropped and the mask is placed on a useful font-size
  canvas without resampling strokes. Default placement assumes a baseline of
  0.8; punctuation, lowercase proportions and descenders still need review.

### What is retained now

Authorized candidate requests record source reference/hash, character, baseline,
local threshold/polarity settings, requested methods/style, ROI, every generated
mask and SVG, failures, actual method/model, processing version, vector settings,
and explicit original/processing/normalized coordinate frames. Arbitrary fields,
cookies and secrets remain excluded. These are private diagnostic records with
the same opt-in and lazy 24-hour cleanup limitations described above—not a
permanent owner-facing history. Browser brush strokes and the final selection
are not a complete persisted event log; avoid claiming all UI state is saved.

Private image evidence lives under `.alpha/extraction-matrix/` and
`.alpha/candidate-validation/`, excluded from version control.

### Verification evidence

- Python: 84 targeted tests passed across candidates, diagnostic records, capture
  HTTP contracts, foreground extraction and segmentation; source compilation passed.
- Frontend: full suite 164 passed before the final API-hardening additions;
  the final candidate/workbench focused run passed 53 tests (including nine API
  boundary tests). Typecheck passed. Lint had zero errors and eight existing
  image/PostCSS warnings. No new dependencies were installed.
- Public HTTPS Playwright: real retained photo → automatic choices → select
  Softer edges → download actual SVG → Accept A → worker builds TTF → authenticated
  download → logout/401. Passed in 38.6s. Also exercised secure/HttpOnly cookies,
  anonymous gating, bad-origin rejection, camera access and no horizontal overflow.
- Separate synthetic camera capture → manual correction → font build canary passed
  in 14.6s. These are Chromium mobile-emulation checks, not physical iPhone/Android
  tests.
- FontForge inspection of the downloaded real-photo TTF: two contours (including
  the counter), 43 off-curve control points, approximately 698 font units tall in
  a 1000-em font. This confirms a useful-size curved outline, rather than an
  embedded bitmap or a tiny letter surrounded by photographic margins.
- Visual inspection of the real-photo mobile screenshot confirmed clean outline
  cards and the enclosed counter. A wrapping Retake label was corrected afterward;
  the final preview is rebuilt and the real-photo canary rerun before handoff.

Final rebuilt HTTPS preview canary also passed in 22.5s. That run returned both
classical threshold and SlimSAM object-stage candidates in 12.279s, while the
fast stage took 0.114s. This confirms ML can work here, but does not erase the
earlier cold-run timeouts. Added a pure binary white-on-black regression for
Otsu's zero threshold edge case; the final targeted Python run passed 84 tests.
