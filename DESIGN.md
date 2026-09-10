# Design

## Source of truth
- Status: Active for private alpha; refreshed 2026-09-11.
- Surfaces: existing Next landing page, sheet workbench, new guided capture, installation help.
- Evidence: `web/app/page.tsx`, `upload-workbench.tsx`, `globals.css`; `docs/PRODUCT-PLAN.md`, research. No existing design document/reference screenshot supplied.

## Brand
- Calm, tactile and practical; keep the existing cream/ink/teal palette.
- Trust comes from real masks, real font previews, honest supported limits and clear retry errors.
- Avoid generic AI claims, fake testimonials, fake prices/checkout, fake one-click installation, unfounded privacy/retention claims.

## Product goals
- Two obvious ways to supply real glyphs; recoverable capture and usable desktop export.
- Non-goals: full vector editor, photo-style synthesis, custom training, professional multilingual typography in alpha.
- Success: accepted glyph → generated typed proof → font download → actual use.

## Personas and jobs
- Nontechnical handwriting users and independent lettering/craft creators.
- Phone camera for capture; desktop for Office installation; cross-device continuation later.

## Information architecture
- Landing/workbench: sheet vs guided modes; install help accessible after output and from navigation.
- Capture → correct → build/proof → download/use. Do not hide the primary action under marketing content.

## Design principles
- Preserve user work on retry and navigation; redo only the selected glyph.
- Show what will be generated, what's missing and what the tool cannot infer.
- Prefer existing simple components; no new component system.

## Visual language
- Reuse `globals.css` tokens and existing typography, spacing, rounded surfaces.
- A large current-character label, mask preview and captured-character grid are functional imagery.
- Reserve image dimensions; motion nonessential, respect reduced motion.

## Components
- Reuse upload, error/status and artifact patterns.
- Add mode chooser, four-corner editor with keyboard/numeric alternative, guided character picker, threshold/invert/baseline controls, previous/next/redo, accepted mask grid, help.
- Separate loading/empty/failed/accepted states; disabled actions explain prerequisites.

## Accessibility
- WCAG 2.2 AA target, not a certification claim; labels, visible focus, no color-only state.
- Touch targets ≥44px; corner entry must work without dragging.
- Error/status announcements via live regions; meaningful image alt; keyboard navigation.

## Responsive behavior
- 360px phone through desktop. Stack preview and controls on small screens; avoid horizontal scrolling.
- Native file/camera capture fallback; no hover-only controls.

## Interaction states
- Loading: bounded progress, stop double submits, no invented precision.
- Empty: show how to capture, not a fake artifact.
- Error: retain files/captures where safe, recover selected glyph.
- Success: generated-font proof and explicit partial-character notice.
- Offline/slow: show failure with retry; don't silently replace with demo success.

## Content voice
- “Character”, “page corners”, “font file”; explain “glyph” only in advanced details.
- “Use in Word/PowerPoint” opens accurate instructions, not a claim that the browser installs fonts.

## Implementation constraints
- Existing Next/React/Tailwind, no new dependency unless separately justified/authorized.
- Bounded image previews, object URL cleanup; backend authoritative input checks.
- Unit interaction tests, desktop/mobile browser checks, screenshot review before claiming UX complete.

## Open questions
- Production domain/payment account/spending authority: deployment gate, not a reason to block local capture implementation.
- Full Office cross-platform usability: empirical release test, not inferable from a valid file alone.

## Studio redesign decision — 2026-09-11

The previous implementation violated the information hierarchy above: a landing
page, pricing cards, account limits and all capture controls appeared in one long
screen. The user explicitly rejected that layout. This section supersedes the
old landing/workbench composition, not its backend or capture behavior.

- **Primary surface:** a working font studio, not a marketing landing page.
  Logged-out users see a compact sign-in and clearly illustrative type specimen.
  Logged-in users go directly to capture. Pricing has its own route; account
  settings and feedback are secondary disclosures, not hurdles before capture.
- **Desktop:** a narrow persistent resource sidebar, compact session bar, then
  project/capture workspace. Capture is the focal area; progress/output stays in
  a quieter adjacent area. No oversized hero before the tools.
- **Phone:** compact navigation and one-column capture. Take photo and Upload
  file are primary entry points; accept/redo/next remain near the current image.
  Secondary metadata and advanced adjustments use disclosures. Preserve all
  work when opening settings, changing capture mode or retrying an image.
- **Visual language:** warm off-white canvas, white work surfaces, dark ink,
  restrained forest/teal highlights, fine rules, 10–16px functional radii.
  Strong type hierarchy, ample space around the image rather than every card.
  Georgia italic specimen is decorative, explicitly not a generated user font.
- **Navigation:** Studio; saved projects in the workspace; template downloads;
  installation help; pricing. No dead tabs or fabricated dashboard statistics.
- **Performance:** no new component or icon dependencies, no decorative raster
  downloads, no native app wrapper in this change. Reuse the current web app.
- **Accessibility:** base resets belong to Tailwind's base layer so they do not
  override utility spacing/colors; visible focus; 44px controls; at least 16px
  mobile form text; reduced motion; semantic disclosures and real labels.

### Implementation and regression plan

1. Keep the existing tested capture/auth/API logic; replace the page composition
   and session presentation. Move account and feedback to opt-in panels.
2. Simplify workbench presentation with progressive disclosure and concise copy;
   do not remove capture modes, mask corrections, project persistence or proof.
3. Replace outdated marketing-copy browser assertions with studio hierarchy,
   keyboard/disclosure/state-preservation and mobile-overflow assertions.
4. Run unit/type/lint checks, real alpha browser flow and desktop/mobile screenshot
   review. Do not claim real-device camera testing from browser emulation.

### Platform assumption / open question

Deliver one mobile-first web product first, not separate desktop/mobile demos.
Native iOS/Android builds are deferred until real-device capture trials identify
specific blockers or repeat-use demand. A localhost URL is not a shareable phone
alpha; a trusted HTTPS deployment is a separate required test/release gate.

## Phone camera decision — 2026-09-11

Desktop is upload-only: do not offer laptop webcam capture. Touch-first mobile
browsers get an explicit Take photo action alongside upload. Opening it requests
a rear-facing live camera, with only browser-exposed devices in the camera selector.
Never identify physical zoom lenses by device order or pretend every hardware lens
is accessible. No audio, no camera on page load, and no background recording.
Stop streams on close, capture, switch, tab hiding and unmount. Preserve the existing
extraction/review flow after capture. Permission/HTTPS failures retain native-camera
fallback and gallery upload. Native applications remain deferred.

## Dedicated mobile test entry — 2026-09-11

`/mobile` is a focused phone-sized capture surface, not a second product or new
backend. Reuse the session gate, account controls and extraction/build workbench.
Omit desktop resource navigation and login artwork on this route. The normal `/`
studio remains intact. Public testing uses production-mode Next behind temporary
HTTPS, with existing private-alpha login and exact-origin protection; no exposed dev
server and no direct internet route to the ML worker.

## Automatic letter choices — 2026-09-11

- Operate mode, scoped to guided capture; retain the existing visual identity.
- Upload/capture automatically creates fast light/dark-aware letter candidates,
  then tries bounded object cutouts. Show actual traced SVGs, not the internal
  raster mask, as the normal review surface. Users choose visual results.
- Keep fast candidates usable during optional extraction. A slow/missing model
  must not remove a usable result, stall acceptance, or overwrite another letter.
- Hide algorithm controls, baseline line and brush tools under Advanced. Preserve
  manual correction; do not silently remove dots, holes or disconnected strokes.
- Reject obviously unusable candidates; show concise retry/failure information
  without presenting internal algorithms as required user knowledge.
- Capture provenance remains linked to source and output during local diagnosis.
  This is not a claim of production capture-history retention/deletion support.
- Acceptance evidence: polarity/hole regressions, hard subprocess deadlines,
  stale-response tests, authenticated real-image upload→candidate→font flow,
  SVG path checks and a phone viewport review.
