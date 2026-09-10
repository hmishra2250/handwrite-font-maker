# Studio redesign validation — 2026-09-11

## Scope

Replaced the stacked demo/marketing layout with a focused sign-in and responsive
font studio. Kept authentication, contracts, segmentation, project persistence
and font generation intact. Pricing and account details no longer interrupt the
capture flow. No dependencies added.

Changed presentation: `web/app/page.tsx`, `session-gate.tsx`, `studio-chrome.tsx`,
`globals.css`, `upload-workbench.tsx`, `projects/project-manager.tsx`,
`onboarding/starter-sample.tsx`, `account-panel.tsx`, and pricing components.
Direction is recorded in root `DESIGN.md` and `docs/MOBILE-EXPERIENCE.md`.

## Evidence

- Frontend unit/API regression suite: **142 tests passed**, 19 files, maxWorkers=2.
- Studio browser suite: **15 tests passed**, including file upload, pixel-exact
  mask undo/reset, markerless confirmation, legacy mode, usable saved-project
  navigation, camera/gallery inputs, and phone layout.
- Real private-alpha browser suite with `ALPHA_E2E_ML=1`: **3 tests passed**,
  including login, actual worker font generation/download, EfficientSAM API
  inference, cross-user access denial, session revocation, pricing and layout.
- Additional isolated alpha layout rerun: **1 passed**; screenshots inspected
  at desktop 1440×1000 and phone 390×844. Camera button fully within the phone
  viewport, no horizontal overflow. Login screenshots also visually inspected.
- Typecheck passed; production build passed; lint passed with seven existing
  warnings (six image-element warnings and one PostCSS export warning).
- `git diff --check` passed.

The browser brush regression initially exposed stale absolute mouse coordinates
following scroll. The test now clicks canvas-relative positions and still checks
actual changed, undone and reset pixels. Navigation regression also checks that
opening Saved projects renders its controls, not merely the details attribute.

## Explicit gaps

Browser emulation is not a real iPhone/Android camera test. Trusted HTTPS alpha
hosting and physical-device camera/gallery/cancellation/rotation/retry tests remain
release gates for mobile claims. PWA installation, offline capture and native apps
are planned, not implemented. Payments remain disabled. This work does not establish
production deployment or Docker runtime validation.

Screenshots are local ignored artifacts under `.alpha/design-review/`; no session
cookies or test credentials are committed. Earlier alpha infrastructure changes
remain a separate, pre-existing uncommitted workstream.

## Follow-up: desktop upload / phone live camera — 2026-09-11

- Desktop capture is upload-only. Mobile camera is an explicit opt-in with rear
  preference, browser-exposed device selection, JPEG frame capture and native
  picker fallback. No additional package dependency.
- Frontend: **152 tests passed** (20 files), including 10 dedicated camera tests.
- Browser: **17 studio/camera tests passed** plus **3 real alpha tests passed**
  with EfficientSAM enabled. Camera tests use Chromium fake media, check the
  actual captured frame handoff and track release, and cover denied permission.
- Python phone-launcher/local-launcher: **7 tests passed**. The generated CA/leaf
  verified through OpenSSL; a mismatched IP was rejected. Expiry and IP are checked
  separately because OpenSSL does not combine those checks in one invocation.
- Typecheck, production build and lint passed (same seven pre-existing warnings).
- Viewed 390×844 live-camera modal screenshot; corrected a wrapping Close button.
- Started HTTPS preview on private LAN port 3443 alongside localhost:3001. Verified
  TLS with the dedicated CA (no certificate-verification bypass), authenticated
  account access, Secure/HttpOnly `__Host-` cookie, wrong-origin 403, and logged-out
  401. API listener remains 127.0.0.1:8000; no public tunnel or automatic CA trust.
- The phone preview uses `.next-phone`; Next may update generated route type imports
  and tsconfig includes when switching dev trees. Generated output is ignored.

Physical S23 Ultra/iPhone 14 Pro tests, actual lens enumeration, autofocus,
orientation, native pickers and device CA installation remain unverified. Instructions
and a manual acceptance checklist are in `docs/PHONE-TESTING.md`.

## Follow-up: dedicated public phone alpha — 2026-09-11

- Added `/mobile`, reusing the authenticated workbench without desktop navigation.
  The dedicated public preview redirects `/` here; normal local desktop is unchanged.
- Added `scripts/alpha_mobile.py`: private-alpha preflight, isolated production
  Next build, exact temporary HTTPS origin, loopback-only upstreams, process cleanup.
  No new application dependency or duplicate capture/ML API.
- Frontend: **155 tests passed** across 20 files. Python mobile/phone/local
  launcher checks: **12 passed**. Typecheck and production build passed; lint
  reported zero errors and the same seven existing warnings. Diff whitespace check passed.
- Public HTTPS browser canary: **1 passed** in Chromium mobile emulation, exercising
  unauthenticated 401, login, Secure/HttpOnly cookie, wrong-origin 403, actual
  synthetic camera frame capture, refinement, mask acceptance, real upload and
  worker job, downloaded TTF signature, logout and subsequent 401.
- The initial canary correctly hit the nearly-solid-mask rejection with Chromium's
  green-on-green test pattern. Updated the test to use the real threshold/invert
  controls before acceptance; it then passed. No extraction mock or bypass was used.
- Inspected the 390×844 camera modal screenshot, retained under ignored
  `.alpha/mobile-review/`. No credentials or cookies are stored in committed evidence.
- Public transport is a temporary Cloudflare Quick Tunnel, not production hosting.
  Physical S23 Ultra/iPhone 14 Pro lens selection, focus, rotation and native-picker
  behavior remain unverified. See `docs/MOBILE-PREVIEW.md` for start instructions.
