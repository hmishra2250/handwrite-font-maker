# Pricing, packaging and go-to-market decisions

**10 September 2026 — recommended experiment, not validated revenue.** The owner delegated packaging/GTM decisions. This supersedes the earlier plan's simple 'one font / two rebuilds' sketch. See [market evidence](research/market.md), [technical evidence](research/technology.md), and [delivery plan](PRODUCT-PLAN.md).

## Sell projects, not failures

A **font project** is one named font/style assembled from the customer's supplied characters. It contains the original captures, accepted masks and metric corrections. **Generation** is an internal processing attempt; **revision** is a new successful export of that same project. A new style/family is a new project; adding/replacing missing characters within its correction window is a revision. A project is not ownership of a typeface sold back to its author.

- Free: bounded capture/mask preview and sample proof; no claim of unlimited server-side generation. Rate/size limits apply.
- Spend one project credit at the first successful full export, not at initial upload and not on failed processing.
- Include **10 successful rebuilds over 30 days** for corrections to the same project. Local mask/corner edits do not spend rebuilds. Server failures do not consume allowances. Explain limits before purchase; don't make users pay for a bug.
- Downloaded TTF/OTF keep working after the plan ends. No subscription check embedded in font files.
- Storage retention is a separate policy from license/use rights. Keep projects for the advertised window only after durable storage/deletion is implemented; give expiry reminders and export options. Do not promise perpetual cloud storage.
- Project and rebuild allowances are transactionally enforced server-side. Idempotency protects double-clicks and webhook retries. A failed checkout or build must not lose a credit.

## Recommended offers

| Offer | Recommended price | Included projects | Intended user |
|---|---:|---:|---|
| Single project | **$9.99 one-off** | 1 | Personal handwriting, gifts, one-off creator |
| Launch offer | **$4.99 one-off** | 1, same usable output | First bounded organic beta cohort / pricing experiment |
| Project pack | **$24.99 one-off** | 3 prepaid project credits | Occasional repeat creator without subscription |
| Creator | **$14.99/month** | 3 new project credits each billing month | Regular lettering/content creator |
| Studio | **$29.99/month** | 8 new project credits each billing month | Educator/studio making repeated styles |

These are proposed packages to validate, not products that can be bought in the current repository. Launch the **single project + pack** first. Put subscriptions behind a repeat-creator beta only after durable project storage and entitlement metering work. This is a deliberate two-segment business, not an assumption every personal handwriting customer wants recurring billing. The price-per-project falls to $5.00/$3.75 on subscriptions; evaluate full utilization, not hoped-for unused credits.

Proposed subscription rules: allow unused monthly credits to roll for one extra active billing month, cap balances at 2× the monthly allocation; consume oldest first; no automatic overages. Pause new credit grants at cancellation; honor already-paid credits through their disclosed expiry and let existing 30-day correction windows finish. Non-renewing one-off/pack credits should have generous explicitly disclosed redemption terms; choose exact expiry only after applicable consumer-law review. No annual plan until retention/churn is measured.

No “exclusive ownership”, “all languages”, “any photograph works”, or “unlimited AI generation” tier. All paid tiers get accurate output, clear rights, corrections and install help. Differences are volume and workflow convenience, not withheld quality fixes.

## Full-utilization economics

Use measured processing costs before launch. Illustrative *conservative reserve*, not actual spend: $0.10 per successful build, 11 total exports (initial + 10 revisions) = **$1.10 compute/project** at full use. This intentionally differs from the cheaper active-CPU estimates: it provides space for overhead/failures, but must be replaced by instrumentation. Add support, storage, free previews, taxes and payment fees.

Example full-use Creator month: 3 × $1.10 = $3.30 build reserve; 3 × $0.50 = $1.50 support (one minute at $30/hr per project); $0.60 storage/free-preview reserve; US Stripe benchmark fee ≈ $0.735; 3% refund reserve ≈ $0.45. Total ≈ $6.59; pre-CAC contribution ≈ **$8.40 (56%)**. At 5 support minutes/project instead of 1, contribution falls by $6 to **$2.40**. This is not an acceptable paid-acquisition product until support is low or pricing is adjusted.

Example full-use Studio month: 8 × ($1.10 + $0.50 + $0.20) = $14.40; fee ≈ $1.17; refund reserve ≈ $0.90. Total ≈ $16.47; contribution ≈ **$13.52 (45%)** before CAC/fixed costs/tax. This is a **beta hypothesis**, not a launch promise of 80% gross margin. If actual cost/support resembles these reserves, reduce included volume or raise price before scaling; don't rely on customers failing to use paid allowances.

The one-off at $9.99 tolerates more support and is the strongest launch default. Typical corrections may be fewer than ten, but forecast both typical usage and full utilization. Optional paid ML may need a separate clearly-priced rescue allowance; never silently turn on 94 per-glyph model calls in a fixed low-price plan.

Payment fee examples use published [Stripe US standard pricing](https://stripe.com/pricing) as a benchmark only. Merchant domicile, onboarding, taxes, currency conversion, cross-border fees and disputes must be verified for the actual account. Do not assume a US audience implies US merchant fees or account eligibility.

## ML economics update: measured local capability, not a cloud bill

Both optional learned paths now run on CPU without a paid external inference API. Four-run isolated probes on the shared Mac measured warm medians ~0.71s for EfficientSAM, ~1.88s for SlimSAM fp32 and ~1.98s for SlimSAM int8; RSS peaks were ~1.39/2.71/3.62GB. Do not turn these into cloud prices or assume quantization is cheaper without deployment measurements. Benchmarks and limitations: [ML runbook](ML-SEGMENTATION.md).

Keep **$9.99 per project** as the first launch hypothesis; do not charge $3–$5 *in compute* per font by design. An accepted mask is reused by subsequent builds, so rebuilding a font must not call a segmentation model again. Model attempts and exports are different meters. Before public launch, measure the cost of an entire session including abandoned previews, retries, worker idle time and support; set a visible preview/capture allowance from that distribution. Local brush edits cost no server inference. Do not sell unlimited model attempts or advertise a fixed AI allowance before server-side limits exist.

Use `session COGS = model attempt count × measured per-attempt infrastructure cost + build cost + storage/egress + payment fees + support + refunds`. Price and package changes should follow measured contribution at full utilization, not download size or synthetic accuracy. Billing remains unimplemented; this is a commercial decision record, not a live offer.

## Acquisition sequence

1. **Quality before reach:** 10–15 adult testers, then ≥20 independent real sessions; measure capture, proof, installation, support and willingness to pay. Include different phones, skin/hands in frame, dark/white surfaces, printing scales, missing characters and uneven light. Small samples identify failures, not market size.
2. **Organic high intent:** helpful original guides for handwriting-to-font and Word/PowerPoint installation; real examples and a concise demonstration. Community participation with permission, creator collaborations and transparent incentives. No mass unsolicited outreach.
3. **Paid search experiment:** after billing/security/quality pass, owner-authorized $100–$200 total cap. Start one country (US) and one intent (“turn handwriting into a font”), exact/phrase match, real keyword forecasts, narrow negative list. UK/Canada/Australia and a separate India creator cohort are later comparisons, not simultaneous scattershot spend.
4. **Short-form demonstrations:** pen page → corner correction → typed message; leaves arranged into glyphs → typed title; character redo → improved word. These creatives show actual results and constraints, not generated product claims. Test hooks and completion-to-proof, not impressions alone.
5. **Retention-led subscription:** invite creators who export ≥2 projects in 30 days; measure uptake, credit utilization, support and next-month renewal. Do not show a recurring plan as the default to one-off buyers.

## Funnel, SEO and measurement

Canonical homepage message: **“Turn your handwriting and handmade characters into a font.”** Subheading: **“Scan a sheet or capture one character at a time. Fix it, preview it, then download a font for desktop apps.”**

- Intent pages: `/handwriting-to-font`, `/image-to-font` (explicit supplied-character extraction), install help; future fair Calligraphr comparison with dated evidence. No AI style-completion page until that capability exists.
- Core seeds: handwriting to font, turn handwriting into a font, create font from drawings, scan alphabet to font, convert character images to TTF, use my handwriting in Word. Validate with Keyword Planner/Search Console; volumes and CPC are unknown.
- Initial exclusions to inspect: font identifier, font finder, keyboard fonts, free font download. Don't indiscriminately exclude “free” if the landing page offers a real free preview.
- SEO engineering: unique metadata, semantic copy, public sitemap, correct canonical after domain chosen, noindex projects/proofs/staging, real alt text, fast mobile capture, links from installation content to the actual workflow. No fake testimonials, review schema or copied comparison pages.
- Events: visit → mode → first accepted glyph → successful proof → checkout → paid export → install help/use confirmation. Segment by device/mode/country/channel without storing source handwriting in analytics.
- North-star: **paid projects successfully used**, not total generations. Secondary: time-to-usable-font, corrected-build success, support minutes, refunds, free-to-paid conversion, per-project contribution and repeat creators.

## Pricing test and stop rules

Compare $9.99 standard against a bounded $4.99 launch offer with otherwise identical scope. Use sequential cohorts if traffic is too small for a powered A/B test; label results directional. Don't declare a winner from two sales. Collect why users did not buy (quality, capture effort, installation, price, missing charset).

`allowable CPC = target CAC × click-to-paid conversion`. Example: target CAC $4 and 3% conversion permits $0.12 CPC. If observed bids/conversion cannot fit, improve conversion/organic acquisition or price—not wishful ROAS.

Pause a campaign when its capped experiment ends or actual contribution cannot support acquisition. Don't scale until cost, support and refund distributions are measured. Never promise the owner quick revenue merely because the conversion pipeline works.


## Invite-beta economics boundary (2026-09-10)

The deployable beta adds resource quotas, not purchased credits. A guided character
can consume a source upload, a preview, and a separate accepted-mask upload; price
and limit the **whole project**, not one HTTP request. Local inference avoids a
per-call model-provider bill, but paid hosting, idle capacity, storage/egress,
support, refunds, and payment fees remain real costs. Allocate fixed monthly cost
across actual paying projects before claiming a margin. No new cloud cost or paid
conversion was measured in this deployment pass.

Checkout/subscriptions remain unavailable until stable project/revision identity,
webhook signature/idempotency, credit reservation, refunds, and provider test-mode
acceptance are implemented and verified. The nature-photo probes support reviewed
leaf/fern ornament glyphs; river/delta extraction failed the current quality bar.
Do not advertise automatic river alphabets or photographic color fonts from these
results. Keep acquisition as an invited quality cohort before paid campaigns.
