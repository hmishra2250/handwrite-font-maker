# Mobile product surface

Decision for private alpha: **one responsive web product, not three separate demos**.
The camera is an input to the same project and backend, not a separate font maker.

## Phone-first flow

1. Sign in and choose a character or a printed-sheet workflow.
2. Take a photo **or** choose an existing photo. Keep both entry points.
3. Review the actual extracted shape. Accept, redo or move to the next character.
4. Save the project; keep capture progress when opening account/settings.
5. Build and preview the font. Offer download and accurate installation help.

Advanced typography controls belong behind a disclosure, not above the camera.
Full-sheet capture remains useful for someone who already filled a template;
gallery uploads matter for leaves, rivers, artwork and previously scanned images.
Desktop is upload-only; do not offer laptop webcam capture.
Desktop uses the same account/project for larger previews and metric adjustments.
Users must create/open a saved project for durable continuation; a local draft
must not be described as automatically synchronized.

## What is implemented versus planned

- Implemented: responsive browser app, separate camera/gallery inputs, guided
  character loop, markerless full-sheet flow, server project persistence, local
  segmentation, downloadable desktop fonts.
- This redesign: capture-first navigation, focused sign-in, mobile layout,
  progressive disclosure, responsive browser regression tests.
- Next: trusted HTTPS alpha URL and hands-on iPhone Safari + Android Chrome
  capture tests; then installability metadata/icons and an honest Add to Home
  Screen guide. No offline promise until upload queues, session expiry, storage
  eviction and retry behavior are implemented and tested.
- Not implemented: native Android/iOS apps, native
  scanning APIs, offline builds, background mobile uploads or phone font-system
  integration. Avoid implying browser downloads install a font system-wide.

## Why web first

No app-store installation before the first capture, one set of fixes, one
backend and a single private-alpha distribution path. Test the key uncertainty—
can a real person produce a usable font from their phone?—before maintaining
multiple clients. This is a product recommendation, not evidence of demand.

HTML `capture="environment"` can request rear-camera input, but is a progressive
enhancement with differing browser behavior. Keep file upload available.
[MDN capture attribute](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/capture).

A custom live camera uses `getUserMedia`, which requires a secure context and
permission. Laptop `localhost` is not the phone's localhost; do not equate a
working desktop HTTP alpha with a real-phone camera deployment.
[MDN getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).

Home-screen installation can provide an app-like entry without a native rewrite.
Installation mechanisms differ across iOS and Android, so preserve a normal
browser path. [web.dev installation](https://web.dev/learn/pwa/installation).

## Gate for native investment

Consider a native client after real-device trials identify recurring blockers:
manual focus/exposure control or native document scanning, reliable offline
capture and background upload, system sharing integration, or proven repeat use
that benefits from store distribution. Prototype the blocking capability first;
do not ship an expensive wrapper that merely relocates the same poor interface.

## Acceptance evidence needed

- Real iPhone and Android camera/gallery permission, cancellation, rotate/EXIF,
  large photos and low-memory recovery.
- Interrupted upload, expired login, retry without duplicate accepted characters.
- Thumb-reachable accept/redo/next; no overflow at 360–430px; readable fields.
- Cross-device project continuation with a real saved project.
- Desktop installation/use check separate from font-file validity.

Reviewed 2026-09-11. Browser emulation verifies layout and uploaded-image behavior,
not camera hardware, native pickers, OS font installation or standalone-PWA quirks.

## Layout separation in the redesigned alpha

- Sign-in is a dedicated screen, not a form at the bottom of a landing page.
- Phone capture uses a compact header; desktop gets a persistent resource rail.
- Font metadata, character-set configuration, account limits and feedback are
  opt-in panels. They do not precede the primary camera/upload action.
- Pricing is a separate route, not an obstacle in the capture flow.
- No installation, PWA offline cache or native app is implied by this layout.

## Live camera implementation — 2026-09-11

Touch-first mobile browsers now have explicit live camera capture, rear-facing
preference, browser-exposed camera selection and native-picker fallback. Desktop
keeps upload only. Streams stop on close/capture/switch/hiding/unmount; no microphone
is requested and no background capture is promised. Captured frames are bounded
JPEG files handed to the existing extraction flow. Physical device/lens behavior
remains a manual acceptance gate. See [phone testing](PHONE-TESTING.md) for a LAN-only
HTTPS preview with a dedicated short-lived test CA; no PWA or public deployment is
implied.
