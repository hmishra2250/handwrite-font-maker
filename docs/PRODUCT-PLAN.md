# Handwrite Font Maker — product, engineering and launch plan

**Date:** 10 September 2026. **Status:** research-grounded plan; implementation and release gates tracked separately. Prices, times and funnel thresholds below are recommendations/experiments, not observed business results.

## Executive decision

Build **“Your handwriting and handmade shapes, as a font you can actually type with.”** Two inputs, one font-engineering pipeline:

1. **Controlled sheet:** download a versioned printable page, write labeled characters, photograph it flat, detect/confirm the four page corners, correct perspective, review glyphs.
2. **Guided characters:** select a character, photograph/upload its handwriting or object shape against a contrasting background, adjust foreground extraction, accept, previous/next/redo, then build a partial or complete font.

Default to deterministic CPU processing. Do not train a model, use a VLM as a pixel-mask generator, or synthesize missing letters for the first release. Keep old ArUco templates as an explicit compatibility mode, not a requirement for new users. No-marker capture still needs known page geometry and user-confirmed orientation: four corners do not identify a template, reading direction, or a curled surface.

**Packaging update:** [Pricing/GTM decisions](PRICING-GTM.md) supersedes the initial rebuild allowance below and defines project credits, one-off packs and repeat-creator subscription beta.

**Business recommendation:** free truthful preview; **$9.99 one-off export**, **$4.99 limited launch-price experiment**, later **$24.99 / 3 projects** if repeat usage warrants it. No subscription until retention supports one. User keeps rights to their inputs; do not manufacture an “ownership upgrade” for their handwriting.

## Evidence and confidence

- [Repository audit](research/repository-audit.md): real ArUco/OpenCV/Potrace/FontForge pipeline, fixed 94-character layout, incomplete font validation, no guided flow or paid-SaaS security boundary. Confidence high from source + baseline checks.
- [Market landscape](research/market.md): current primary-source feature/pricing comparison, including Calligraphr, YourFonts, Fontself, Glyphr, Birdfont and emerging AI tools. Competitor pricing is evidence of offers, not sales or willingness-to-pay measurements.
- [Technical research](research/technology.md): primary-source geometry/segmentation/font/Office/model/license evidence. Compute projections remain unmeasured assumptions until instrumented builds complete.
- Initial ICP, countries, price elasticity, CAC and SEO priorities are hypotheses. Do not invent keyword volumes or promise income/ranking.

## Product boundary: what “any object” means

For v1 an object is a **user-chosen silhouette assigned to a character**. A leaf photographed as `A` becomes the shape typed by `A`; it need not look like a conventional A. A river image can supply a user-selected silhouette if the user has image rights and can isolate it. We do not automatically understand which river/letter they intended, reconstruct an alphabet from one logo, remove arbitrary busy backgrounds perfectly, preserve photographic color in a monochrome font, or perform cursive handwriting recognition.

Supported launch scope: print-style Latin/ASCII, digits and punctuation, mono-color outlines, TTF/OTF, partial fonts clearly labeled with missing characters. Do not claim connected-script shaping, Arabic/Indic coverage, multilingual diacritics, professional kerning, variable/color fonts or universal app compatibility yet.

## Experience and onboarding

### First-use flow

- Landing page shows the two real modes, a concrete specimen and desktop-font outcome; no account wall before trying a private preview.
- Explain constraints *before* capture: flat page; full border visible; known template; correct paper size; upright orientation; dark ink/contrasting background; no glossy glare. Native camera capture plus file upload; JPEG/PNG/WebP initially, actionable HEIC guidance.
- Sheet flow: explicit legacy vs markerless selection; automatic candidate corners plus manual ordered four-corner correction; retain input on errors; do not silently accept a dubious rectangle.
- Guided flow: choose character set or a small partial font; character picker; previous/next/redo without losing other glyphs; current mask preview, invert/threshold and baseline adjustment; show captured/missing count.
- Proof: type a phrase, inspect sample words with ascenders/descenders/punctuation and missing glyph notices. Preview must use the generated font, not a system-font mock.
- Export: one obvious TTF download, optional OTF; “Use in Word”, “Use in PowerPoint”, “Use on my website” help. No fake one-click OS install.
- Errors preserve accepted glyphs and identify recoverable input errors vs missing backend dependencies. No paid charge on failed builds. Include limited rebuilds of the same project, not unlimited free compute.

### Adoption / “UAU”

Treat the user's UAU request as user acquisition, activation and usage instrumentation, not a known standardized metric. Define activation as **first accepted glyph + successful typed proof**, and completed value as **export + successful installation/use confirmation**. A downloadable font alone is insufficient evidence that the customer succeeded.

## Architecture and contracts

Keep Python/OpenCV/Pillow/ReportLab + Potrace/FontForge and Next.js; no speculative dependency rewrite. See `DESIGN.md` for UI contract.

- Capture inputs normalize into labeled glyph masks with source provenance and explicit metrics.
- Sheet alignment has explicit `markers`, `page`, and manual-corner controls. Validate corners: exactly four finite distinct in-bounds points in TL/TR/BR/BL order, convex non-self-intersecting quad, adequate area. Reject ambiguous/small/border-clipped candidates; never call the zero residual of a four-point homography independent confidence.
- Preserve EXIF orientation before computing/displaying coordinates. Limit image pixels and decoded dimensions as well as compressed bytes.
- Geometry is shared between template generation and extraction. Preserve dots, accents, holes, punctuation and true horizontal strokes; template-specific guide removal must not run on independent object masks.
- Guided inputs preserve a stable character label, image reference, threshold/inversion and baseline choice. Build only explicitly supplied glyphs, plus space and a real `.notdef` fallback.
- Font QA verifies expected cmap, nonempty contours, horizontal strokes, holes, usable advances, consistent ascent/descent, metadata, embeddability and a rendered proof. FontForge load success alone is insufficient.
- Reuse existing artifact publishing. Re-sign private download URLs when reading persisted jobs rather than relying on transient in-memory URLs.
- Add capture configuration as a versioned JSON value on job persistence with a forward migration; old jobs default to the legacy sheet path. JSON dev storage remains local-only.
- Worker production design: atomic queue claims, bounded concurrent jobs, job leases/retry, timeouts for subprocesses, idempotent publication, resource limits and observable stage durations. Current inline threads are not a durable production queue.

### First implementation milestone: private alpha

Implement the real capture-to-font primitives, wire both modes, keep compatibility, tests, installation help and launch documentation. This milestone is **not** permission to expose an unauthenticated compute service, enable payments or advertise production readiness.

Parallel Terra ownership:

| Lane | Owns | Depends on / acceptance |
|---|---|---|
| Rectification/template | `rectify.py`, `template.py`, optional shared geometry helpers, CLI, new alignment tests/template assets | Explicit markerless quadrilateral/manual path; legacy default remains valid; markerless PDF contains no ArUco squares; reject invalid quads. |
| Glyph/font pipeline | `pipeline.py`, new glyph helper module, `scripts/fontforge_*`, glyph/font tests | Guided labeled raster input, deterministic mask settings, no template-guide erosion of objects, correct metrics, stronger output validation; extend `build_font` with alignment options. |
| Backend integration | Python `web/`, persistence migration, API/worker tests | Validated capture payload and bounded image refs survive JSON/Postgres reconstruction; worker dispatches both modes; private artifact URLs restored on reads. |
| Frontend | Next app/components/contracts/routes/tests except package files | Two modes, manual corners, guided previous/next/redo/preview/build, honest demo/backend state, installation help; no placeholder output. |
| Dependency safety | `web/package.json`, `web/package-lock.json` only | Inspect current upstream advisories, minimum compatible fixes, pin resolved versions instead of latest, rerun checks. No new feature dependencies. |
| Leader | docs, design, integration and final evidence | Resolve interface mismatches, run full test/build/browser pipeline, report real deploy gate. |

The reviewed, implemented interface is specified in **Contract freeze after independent review** below. Earlier draft threshold/corner payloads are not accepted API contracts.

### Next milestone: secure closed beta

- Authentication/session ownership or cryptographic project capabilities; never authorize by a guessable object path. Browser never receives service-role credentials.
- Restrict Python service to authenticated server-to-server requests/private network; bind local tools to localhost. Rate-limit upload/build, reserve per-owner credits, prevent arbitrary object access, cap total glyph bytes/pixels and build duration, no shell interpolation.
- Private bucket provisioning, RLS on browser-accessible data, signed uploads/downloads with short expiry, object-key ownership, image magic-byte checks, EXIF stripping, deletion/expiry enforcement including abandoned uploads, backups policy and deletion request handling.
- Durable worker and Postgres migration/rollback tests; retry only safe stages; distinguish active job capacity from HTTP server concurrency.
- Billing provider available to the business's actual domicile/account, test-mode checkout/webhook signature validation, idempotent event handling, server-side entitlement reconciliation, tax/refund terms. US Stripe rates below are a benchmark, not a claim that this business can onboard with US terms.
- Observability: request/job IDs, stage timing, masked error taxonomy, CPU/RSS, retry rate, refund/support rate; no raw handwriting in analytics/error logs.
- Public beta remains blocked until these controls and hostile tests pass.

### Later differentiated capabilities

- User mask brush/crop/restore, baseline/spacing editor, glyph variants and ligatures, multi-page charset packages, extended Latin, WOFF2 export (requires approved encoder dependency), project save/resume and selective glyph re-export.
- Interactive SAM-style segmentation for hard backgrounds, gated by opt-in and cost caps. Evaluate pretrained checkpoint license, latency and real image masks first. No custom training until a consented failure dataset shows a persistent gap.
- Optional DOCX/PPTX starter documents that reference the font and accurately explain embedding; cross-platform installation checks. Color-object fonts and connected scripts are separate research/product tracks.

## Pricing and unit economics

[PRICING-GTM.md](PRICING-GTM.md) is the single packaging/economics source of truth:
$9.99 one-off, $24.99/3-project pack, bounded $4.99 launch experiment, and repeat-creator
subscription hypotheses. Each project includes an initial export plus 10 successful
rebuilds over 30 days; failed processing is not charged. These are planned entitlements,
not currently implemented checkout features.

Forecast full utilization as well as typical usage. At the illustrative $0.10/build
reserve, 11 exports cost $1.10/project before storage, free previews, support, refunds,
payment fees, taxes and acquisition. At $9.99, illustrative fees $0.59 + compute $1.10
+ storage/free preview $0.20 + support $0.50 + refund reserve $0.30 leave **$7.30**
pre-CAC/fixed-cost/tax contribution. All costs here are assumptions, not invoices.
Five minutes of support instead of one adds $2; 94 paid model rescues may dominate
compute. Measure actual stage timings, failed/free projects and support minutes.

A hypothetical $50/month fixed allocation costs $5/order at 10 orders versus $0.05
at 1,000. Cheap processing alone does not prove profitability. `CAC = CPC / paid
conversion`; for example $0.30 clicks at 3% conversion cost $10 per paid order.
Do not scale acquisition without measured contribution margin.

## GTM and SEO execution

### Positioning and ICP

Primary wedge: independent lettering/craft creators and personal-handwriting users who want printable, installable output without learning a font editor. Secondary experiments: teachers (adult purchasers, not child accounts), invitation makers, indie game/UI display-font creators. Avoid professional type-family and enterprise exclusivity claims.

### Geography

Start English-language organic outreach globally and **one paid country cohort at a time**. Suggested first paid cohort US; compare UK/Canada/Australia after enough events. Separate India creator/price experiment from US instead of blending conversions; payment availability and tax obligations follow seller domicile, not audience location. No state/city precision targeting without data. These are hypotheses, not proven regional demand. Localized countries only after their glyph coverage, help and checkout are supported.

### Funnel and first 30 days

1. Days 1–7: recruit 10–15 adult creator testers through relevant communities/own network with permission; observe capture→proof→install, get rights to display examples, measure support time. No unsolicited mass messaging.
2. Days 8–14: fix the top failure classes; publish real before/after cases and installation help. Offer a bounded discounted beta only after secure billing/export exists.
3. Days 15–21: launch three factual landing/help pages and 3–5 short demonstrations (pen, marker, arranged leaves) with visible final typed text. Partner with a few small lettering educators/creators; disclose incentives.
4. Days 22–30: if quality and margin gates pass, run an owner-approved $100–$200 capped search experiment over 7–14 days; exact/phrase high-intent keywords only, no automatic spend now. Evaluate event counts and confidence intervals; small cohorts are directional, not proof.

### Keyword/page map

| Intent | Page | Seeds / content |
|---|---|---|
| Make handwriting usable | `/handwriting-to-font` | turn handwriting into a font; create font from handwriting; scan handwriting to TTF; show real workflow + supported charset |
| Guided handmade glyphs | `/image-to-font` | create font from drawings; convert character images to font; object alphabet maker; explicitly explain every glyph must be supplied |
| Install and use | `/help/install-fonts`, later app-specific help | use my handwriting in Word; install custom font PowerPoint; install TTF Windows/Mac |
| Compare alternatives | later `/compare/calligraphr` | Calligraphr alternative; factual dated limits/prices, no trademark confusion or copied content |

Do not target “identify font from image,” “AI complete alphabet from logo,” or “free font downloads” as if our MVP solves them. Initial negative candidates: font identifier, font finder, DaFont, Google Fonts download, keyboard fonts. Evaluate actual search terms rather than blanket-excluding relevant free-preview intent.

Technical SEO: unique title/description, semantic headings, crawlable meaningful content, responsive performance, canonical URLs only after domain configured, sitemap/robots reflecting public pages, noindex private projects/proofs and staging, alt text for real examples, helpful original installation content, internal links. No fabricated reviews, schema ratings, doorway pages or programmatic near-duplicate country pages. Do not claim rich-result eligibility guarantees.

### Analytics / activation / retention

Privacy-minimal events: `landing_view`, `mode_selected`, `template_downloaded`, `capture_added`, `corners_corrected`, `glyph_accepted`, `build_started`, `build_failed(code)`, `proof_viewed`, `checkout_started`, `payment_confirmed`, `export_downloaded`, `install_help_opened`, `use_confirmed`, `refund_requested`. Use a pseudonymous project/session ID, never input images/text samples/card info.

Dashboards: funnel per source/device/mode/country; first-pass success; manual-correction share; time-to-first-glyph and time-to-usable-font; retries/glyph; p50/p95 processing; paid conversion; support minutes/order; contribution after acquisition. Repeat creators over 30/60 days determines whether subscription makes sense; one-off users should not be penalized for low daily retention.

Initial go/no-go hypotheses: at least 20 independent real capture sessions; ≥90% produce an acceptable corrected font without staff editing; ≥80% complete install/use with help; median support ≤2 minutes/order; real measured contribution positive. Statistical uncertainty remains high at this size. Broader advertising waits for larger validation and security signoff.

## Deployment and release gates

Retain the existing Next frontend + containerized Python + Postgres/private storage topology for now. Do not migrate this backend to a static site host just to obtain a URL. Prepare example env/config and a staging runbook. No credentials are checked in or printed.

Release sequence: validate local → dependency/security fixes → private staging account provisioning → apply migrations to staging → signed storage/worker/billing test → end-to-end capture/download/font render → retention and abuse tests → owner identifies production project/domain/budget → production deployment → health + real font canary → small monitored launch. Use immutable versions, migration backups and rollback instructions. Never call a local or demo URL a public production deployment.

## Acceptance and verification

### Private-alpha required checks

- Legacy tests retain documented semantics; fix accidental pytest helper discovery rather than hiding a failing test suite.
- Markerless synthetic flat page under perspective + known manual corners rectifies to canonical dimensions; no-marker PDF generation; rejects invalid/self-crossing/NaN/out-of-bounds/ambiguous quads. Uphold explicit orientation limitations.
- Guided A/i/O/g/-/period fixtures preserve dots, holes, descenders/horizontal strokes; duplicate/unsupported labels and empty/unusable images reject; no empty font sold as success.
- Captures round-trip in persistence; old jobs still build; UI previous/next/redo preserves other accepted glyphs; build payload labels match images.
- Real Potrace + FontForge output inspected for cmap, outlines, space, `.notdef`, advances, embedding bits and rendered text. Mocks alone cannot prove output.
- API rejects oversized/malformed uploads and invalid capture configs; errors are actionable. Private signed artifacts accessible after database reload.
- Fresh Python tests, npm tests, typecheck, lint, production build and Playwright desktop/mobile flow; record warnings/skips honestly.

### Production-only gates

Tenant isolation tests; malicious object references; rate/size/pixel/process limits; queue crash/retry; webhook replay/idempotency; payment-entitlement/download authorization; retention/delete verification; backup/rollback; Windows and macOS Office install/embed/manual usability; measured cost and pricing review. Any unverified item remains an explicit launch blocker.

## Risks / pre-mortem

1. **Capture works, fonts are ugly:** baseline/spacing quality kills conversion. Mitigation: generated-font proof and per-glyph correction, real user corpus, no premature ad spend.
2. **Cheap compute, expensive support/CAC:** narrow ICP, price test, instrumentation and capped trials; stop an acquisition cohort when contribution fails rather than add AI indiscriminately.
3. **Public launch abused/leaks images:** private-first default, scoped auth/ownership, storage isolation, quotas/retention, verified hostile tests before deploy.

## Alternatives and decision record

- Keep ArUco-only: fastest but misses requested low-friction capture; retain only compatibility/diagnostic path.
- Markerless controlled pages + guided labeled masks: chosen; low marginal cost, preserves user intent, needs correction UI and font QA.
- General VLM/style-to-alphabet generation: potentially broader appeal, but not equivalent to faithful extraction, harder correctness/rights testing; separate future product experiment.
- Train custom segmentation now: no adequate real failure dataset or economic evidence; defer until deterministic+manual+pretrained baseline fails defined evaluation targets.

This plan is a direct research-to-delivery plan, not a claim of an OMX consensus-host receipt, production authorization, or completed SaaS launch. The verification report must enumerate what actually shipped and what remains gated.

## Contract freeze after independent review

The independent review found missing template identity, corner acceptance, mask-coordinate and deployment boundaries. Resolve them before parallel work:

1. Template capture: `{mode:'template', templateId:'default-v1', paperSize:'A4', alignment:'markers'|'page', corners?: [[x,y],...]}`. Only this known A4 geometry in alpha; do not advertise Letter support in the new flow. `alignment:'page'` requires **accepted corners at job submission**, normalized 0..1 TL/TR/BR/BL against the EXIF-oriented natural image. Auto-detection is a suggestion via a separate endpoint; confirm/persist its output exactly like manual corners. No capture still means old ArUco v1.
2. Guided capture: `{mode:'guided', format:'mask-v1', glyphs:[{char,inputPhoto,baseline}]}`. `inputPhoto` references the **accepted preview mask**, not the original unprocessed photograph. Browser creates opaque grayscale PNG with black foreground on white background, no printed guides, longest dimension ≤1024; preserves all components/holes. Threshold/invert controls operate locally before acceptance. Preview and uploaded image are the exact same raster. Each mask stays in its full image coordinate system; no hidden crop/rotation after acceptance. Baseline is normalized from the image top, default 0.8, strictly within (0,1). Backend treats <128 as foreground, never performs template guide-removal on masks, rejects blank/all-solid or unsafe dimensions, computes tight bbox without discarding disconnected components. Font coordinates: 1000 UPM, ascent800/descent200, source-image height maps to1000; `top_offset = 800 - baseline*1000 + bbox_top*1000/image_height`; side bearings80; advance `max(280,scaled_ink_width+160)`. This is a deterministic initial spacing policy, not optical kerning. Missing labels remain missing and are shown to user.
3. `inputPhoto` outer envelope mirrors first glyph for existing upload shape; every guided glyph is separately validated, unique printable non-space ASCII, 1..94 glyphs, cumulative upload bound plus per-mask pixel/byte limits. Never use that mirror to skip full-list validation.
4. Pipeline interface: `build_font(..., alignment='markers', corners=None, paper_size='A4')`; corners normalized. New `build_font_from_masks(*, glyphs:list[dict], font_name,family_name,style_name,output_dir)`, where each glyph dict is `{char,image_path:Path,baseline:float}`. Same artifact result keys as `build_font`.
5. Rectification interface: `load_bgr(Path)` returns EXIF-oriented bounded decode; `detect_page_corners(image_bgr)` returns pixel TL/TR/BR/BL suggestions or raises an actionable error; `rectify_template_photo(...,alignment='markers',corners=None,paper_size='A4')` accepts normalized manual corners. CLI may auto-detect; web build requires confirmation.
6. Private alpha means **localhost or access-controlled staging only**. Public static marketing/help may be deployed separately, but **no public upload/build/object endpoints** until auth/ownership, quotas, isolation and hostile tests pass. No checkout/entitlement UI pretending billing works.
7. Alpha output copy: **TTF/OTF only when real generated/validated**. WOFF/WOFF2 is future scope and cannot appear as currently available; research references to competitor formats are landscape evidence only.

## Latest capture/style decisions (supersedes literal thin-line suggestions)

The user delegates template contrast/guide decisions to engineering: earlier
white-paper and invisible-line ideas are direction, not requirements. Optimize
legibility and reliable extraction, then validate on real printers/phones. See
[foreground decision](research/foreground-segmentation.md).

Guided object selection now uses a bounded experimental GrabCut endpoint:
`POST /capture/foreground` with `{inputPhoto,rectangle:[left,top,right,bottom]}`
(normalized oriented source); returns `{maskDataUrl,width,height,method:'grabcut'}`.
The user reviews/accepts this full-frame opaque grayscale PNG through the same
mask-v1 build contract. It is not a trained AI model or arbitrary-scene guarantee.

[24 synthetic style/resize/vector experiments](research/vector-style-experiments.md)
show that silhouette overlap can remain high while thin detail breaks. Preserve
mask resolution conservatively; distinguish monochrome ink/detail from solid
silhouette. Do not promise photographic texture/color from outline fonts.


## Delivery checkpoint — 10 September 2026

The private-alpha milestone is implemented: quiet markerless A4 capture with corner confirmation, guided labeled masks and experimental object cutout, previous/next/redo, baseline and real-font proof, validated TTF/OTF download, install help, persistence/proxy contracts and regression coverage. Final verification: **78 Python, 49 frontend and 13 Chromium tests passed**; production build/typecheck passed; lint has six warnings and no errors; npm audit reports zero vulnerabilities. Full evidence and caveats: [VALIDATION.md](VALIDATION.md).

Research and experiments did not establish arbitrary-photo segmentation quality, real printer/phone acceptance, color/texture font support or Office compatibility. Auth/ownership, durable workers, quotas, billing, retention/deletion and configured production hosting remain the next release stage. No public processing service or paid campaign was launched.
