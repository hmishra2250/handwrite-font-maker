# Design

## Source of truth
- Status: Active for private alpha; 2026-09-10.
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
