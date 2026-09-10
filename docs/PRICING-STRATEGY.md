# Handwrite Font Maker: pricing strategy

**Decision date: 10 September 2026 · Status: recommended experiments, not live offers or validated demand.**

This is the current pricing recommendation. It supersedes the price points and commercial packaging in [PRICING-GTM.md](PRICING-GTM.md), which remains a historical GTM record. The working capture/font systems already exist; the remaining commercial gates below are not a claim that those systems have not shipped.

## 1. Recommendation

**Sell a usable font project, not generations. Start with one-off purchases and a three-project pack. Do not make an occasional customer subscribe.**

| Offer | Proposed price, USD before applicable tax | Customer outcome | Launch decision |
|---|---:|---|---|
| Try it | **Free** | Bounded capture/segmentation preview and a five-character sample proof | Acquisition experience; no card |
| Make one font | **$12 once** | One font project, TTF/OTF/ZIP, editing and correction window | Default paid offer after commercial gates |
| Make three fonts | **$29 once** | Three independent project credits; same quality and rights | Secondary paid offer; $9.67/project |
| Creator | **$24/month, three new project credits** | Regular font creation, not a license to keep using downloaded fonts | Research/pilot only; do not publish as a launch tier |

Do not launch the previous $4.99 promotion, $14.99/three-project subscription or $29.99/eight-project Studio proposal. Their low per-project receipts leave too little room for service/support uncertainty. Do not offer annual subscriptions, lifetime cloud access or unlimited AI before there is evidence they work.

**Why $12 rather than $5 or $49?** It is a low-commitment, testable consumer purchase near direct alternatives, with more room for payment and support costs than $4.99. A $49 price would require stronger demonstrated differentiation for this audience. Neither conclusion proves willingness to pay: test $9.99–$14.99 around the initial $12 offer. The skill improves the decision process; it cannot discover an optimal price without buyers.

## 2. Method: use the skill, not just its title

Applied [Corey Haines’s pricing skill, v2.1.1](https://github.com/coreyhaines31/marketingskills/blob/5b2c0007766c6a1cf1d53fd8fc73e979e0821022/skills/pricing/SKILL.md). [Selection, alternatives, license and adaptations](research/pricing-skill-review.md) are recorded separately.

Its useful structure separates **packaging**, **the charging metric** and **price**. Here those become a usable font with corrections, one project credit, and a separately testable dollar amount. We used existing product context instead of asking the owner to supply unknown economics. Competitors establish alternatives; costs establish viability constraints; customers must establish perceived value. Subscription, surveys and price tests are tools, not mandatory rituals.

Success means profitable, usable fonts and satisfied customers—not maximum generation count, signups, or recurring revenue from people who forgot to cancel. Conversion, support burden, refunds, repeat demand, acquisition cost and deployed unit costs are currently unmeasured.

## 3. What the customer is buying

### Segments and jobs

| Segment | Job and likely cadence — hypotheses to validate | Best initial offer |
|---|---|---|
| Personal handwriting / keepsake / gift | Preserve their own or authorized handwriting; usually episodic | Single |
| Hobby lettering / craft creator | Make a few original styles for projects | Single, then pack |
| Illustrator / repeat content creator | Repeated custom alphabets or ornament sets; values editing efficiency | Pack; invite repeat users to Creator research |
| Educator / workshop / agency | Several participants or clients; may need administration and special privacy handling | Later discovery, not an empty enterprise tier |

Lead with **“Turn your handwriting into a font you can actually type with.”** The object/leaf workflow is differentiated but should be demonstrated with successful, honestly labeled examples. It is not evidence that any river photograph becomes a readable alphabet.

### Working product boundaries

The repository supports markerless A4 sheets, guided per-character capture, deterministic ink extraction, GrabCut and optional EfficientSAM/SlimSAM cutouts, mask review, baseline/scale/spacing correction, saved projects and actual TTF/OTF/ZIP output. Accepted masks are reused for builds. See [README](../README.md), [ML segmentation](ML-SEGMENTATION.md) and the [real-image evidence](research/detection-evidence/README.md).

Current character support is **1–94 unique printable non-space ASCII characters**, with generated space—not 200 characters, all Latin accents or all languages. The initial five-character exercise is onboarding, not the maximum paid alphabet. See `src/handwrite_font_maker/web/contracts.py` and `src/handwrite_font_maker/web/project_store.py`.

Do not sell full-color photo fonts, automatic missing-letter invention, complex-script shaping, professional automatic kerning, guaranteed arbitrary-background extraction, or automatic installation into Word/PowerPoint. Font installation remains a user/OS action. Commercial use depends on the customer having rights to the source material; no exclusive ownership upgrade or legal guarantee about typeface rights.

## 4. Competitive evidence

Official pages checked **10 September 2026**. These are asking prices and capabilities, not evidence of competitors’ conversion, margins or our customers’ willingness to pay.

| Alternative | Official offer | Strategic implication |
|---|---|---|
| [Calligraphr](https://www.calligraphr.com/en/pricing/) | Free: 75 characters, one concurrent font. Pro: **$10 for one month**, or **$36 for six months** ($6/month); 600 characters, 20 concurrent fonts, variants/ligatures and editing features. One-time upgrade or recurring subscription options; generated fonts continue working after Pro expires. | Strong free and paid alternative. Its month of access is not equivalent to one purchased font. We cannot justify a premium merely by having TTF export. |
| [YourFonts](https://www.yourfonts.com/faq/) | Free preview; **$9.95/font**, plus **$5** when both template pages are used. | Closest simple pay-per-font anchor. A customer paying us $12 needs to appreciate easier capture, correction or creative inputs. |
| [Fontself](https://www.fontself.com/store) | Store currently displays **$39 once** for Illustrator and **$59 once** for Illustrator + Photoshop, excluding tax; Adobe software required. Promotional/legacy blocks coexist, so recheck at purchase. | Powerful designer alternative, not a comparable monthly SaaS subscription. Do not position our current ASCII workflow as a replacement for all its professional features. |
| [FontStruct](https://fontstruct.com/faq/88/fs-patrons/all-about-fs-patrons) | Free core builder; patron support **€5/month or €55/year**, with OpenType/advanced benefits. | Some users can solve adjacent font-creation jobs for free. Different construction workflow, but important budget competition. |

**Positioning choice:** ease of getting *your own usable result*, without needing an Adobe workflow. Validate that advantage with real task completion. If users see no advantage over Calligraphr’s free tier, changing the number on the pricing page will not fix the proposition.

## 5. Package and entitlement contract

These are proposed paid rules; they are **not enforced by current beta billing**, which is disabled.

### One project credit

One project is one font family/style assembled from the user’s supplied glyphs. Renaming it, filling missing characters, replacing a bad capture or correcting metrics does not create a new billable project. Keep identity tied to the project record; do not add a speculative classifier to decide whether artwork is “different enough.” Bounded exports control use more predictably.

A checkout purchases credits upfront. A credit is reserved when the first full paid build starts and consumed **only when that build successfully publishes a valid export**. Failed/cancelled work releases the reservation. This is not a claim that payment processing itself happens only after success. Provider webhooks, concurrent builds and retries need transactional idempotency.

### Included in every paid project

- The same extraction options, output quality, TTF/OTF/ZIP, character map and installation help. No higher tier required to repair defects or keep dots/holes.
- Initial export plus **10 successful rebuilds within 30 days of the first successful export**. Local mask/metric edits do not spend rebuilds. Failed processing does not spend the customer allowance, although abuse rate limits still apply.
- **Provisional 200 successful server extraction previews per project** across its creation/correction lifecycle. Local editing does not count. This starting cap must pass the cost and task-completion gates before becoming an offer; 94 glyphs can need more than two attempts each.
- Proposed accepted-mask/project editing and download access for the paid 30-day window. Raw-source retention is separately disclosed; do not imply every original photograph can be re-extracted forever.
- Downloaded fonts keep working indefinitely without an active subscription. This is independent of cloud storage retention.

At a preview/rebuild cap, show the remaining allowance before the next action. Offer manual/local correction, an honest limit message and help for product failures. No automatic overages or silent model charges. If normal users repeatedly hit the cap, fix the workflow/package before scaling—not a surprise rescue paywall.

**Credit redemption:** recommend no expiry for purchased one-off/pack credits, with an outstanding-credit liability tracked internally and terms covering service closure. This does not buy lifetime cloud storage. Subscription credits, if launched, roll into one extra active billing month, capped at six; consume oldest first. Cancellation stops future renewal/grants, not use of already-downloaded files or an existing correction window. Honor earned credits through their disclosed expiry. Terms require provider/consumer-law review before sale.

**Refund policy to validate:** a clear seven-day satisfaction window beginning with the first full export; unused orders refundable within 14 days of purchase, with a disclosed proportional pack policy. Mandatory consumer rights override commercial policy. Support may offer repair but should not become an obstacle course to a promised refund. These terms need review, not an assumption that digital goods are automatically non-refundable.

## 6. Free-to-paid experience

1. Choose handwriting sheet or guided characters; explain the supported alphabet and capture requirements.
2. Make a five-character sample with the user’s own material. Bound anonymous/account server work; proposed starting allowance: ten successful extraction previews and one sample build per account, subject to anti-abuse controls.
3. Show an honest proof, the missing-character list, correction controls and installation explanation. No fake extraction result.
4. Offer “Make one font — $12” as the default and “Make three — $29” as secondary. No card needed for the initial sample; no automatically renewing trial.
5. Before payment, show supported characters, output formats, revision/preview limits, retention, taxes/total and refund terms.
6. After payment, preserve the sample work, complete the project and download/install it. Ask whether installation and typing succeeded; that is a better activation signal than clicking Download.

A five-glyph sample font can be genuinely downloadable. For a full-alphabet proof before purchase, use a server-rendered image rather than sending the complete font to the browser and hiding a download button. A browser-loaded font is already delivered; CSS/JavaScript is not a payment boundary.

No fake “most popular,” inflated crossed-out price, countdown, testimonial or claim that objects automatically form all letters. Pricing and material limits should be ordinary readable HTML; add structured offer data only when those offers actually exist. The current beta should not advertise purchasable plans yet.

## 7. Economics: decision model, not invented measurements

### What is measured

The [local 94-glyph build benchmark](research/local-build-benchmark.json) records about **613 seconds wall time and 60 CPU seconds**, including tracing/build tooling. Local ML probes report roughly **1.39–3.62 GB peak RSS** depending on the model; warm timings are documented in [ML-SEGMENTATION.md](ML-SEGMENTATION.md). These establish capability/resource concerns, **not a cloud cost or production p95**. Rebuilds reuse accepted masks and should not rerun segmentation.

A paid vision API is not inherently required. Current deterministic and optional locally hosted models avoid per-call external API charges, but CPU/RAM, idle capacity, abandoned previews, storage, support and failures still cost money. No custom model training spend is justified by this pricing research alone.

### Payment basis

[Paddle](https://www.paddle.com/pricing) advertises **5% + $0.50** standard checkout pricing and asks businesses with products under $10 to discuss custom pricing. [Lemon Squeezy](https://docs.lemonsqueezy.com/help/getting-started/fees) has a **5% + $0.50** base with possible international (+1.5%), PayPal (+1.5%), subscription (+0.5%) and payout charges. Its percentage fee can apply to the tax-inclusive transaction. Neither is a guarantee of account approval or our exact effective rate.

Use a merchant-of-record fee budget while evaluating provider onboarding. Do not infer merchant domicile or Stripe US eligibility from a US target audience. [Lemon Squeezy’s country documentation](https://docs.lemonsqueezy.com/help/getting-started/supported-countries) includes specific India payout caveats. Provider approval, supported business model and real payout path are launch checks, not assumed facts.

### Illustrative scenarios

[Reproducible calculator](research/pricing_economics.py) → [scenario JSON](research/pricing-economics.json). Run `python3 docs/research/pricing_economics.py`.

Assume tax-exclusive USD prices; payment fee **6.5% + $0.50** for one-offs, **7% + $0.50** for subscriptions; refund reserve **3% of revenue**; support valued at **$30/hour**. These are scenario inputs, not measured refund rates or a binding processor quote.

| Per redeemed project | Low touch | Working case | Stress |
|---|---:|---:|---:|
| Incremental infrastructure + allocated variable free-funnel reserve | $0.25 | $0.65 | $1.50 |
| Support minutes | 1 | 3 | 8 |
| Total service cost, excluding payment/refunds/fixed costs | **$0.75** | **$2.15** | **$5.50** |

The infrastructure reserves are deliberately placeholders. Replace them with session measurements, including failed and abandoned work. They must exclude worker capacity already counted in fixed costs. Every included project is redeemed in this model; **this does not mean every preview/rebuild allowance is exhausted**.

| Offer, all project credits redeemed | Low-touch contribution | Working-case contribution | Stress contribution |
|---|---:|---:|---:|
| $12 single | $9.61 / 80.1% | **$8.21 / 68.4%** | $4.86 / 40.5% |
| $29 three-pack | $23.50 / 81.0% | **$19.30 / 66.5%** | $9.25 / 31.9% |
| $24/month, three projects | $18.85 / 78.5% | **$14.65 / 61.0%** | $4.60 / 19.2% |
| $4.99 single, rejected launch proposal | $3.27 / 65.4% | **$1.87 / 37.4%** | **−$1.48** |

Contribution here is revenue less modeled payment fee, refund reserve and service cost, **before fixed infrastructure and customer acquisition**. FX, PayPal, payout/dispute fees, tax effects on fees, development compensation and income tax are excluded. It is not a net-profit or accounting gross-margin claim. Monetary components are calculated before rounding.

Formula: `contribution = price − (price × payment rate + fixed fee) − price × refund reserve − redeemed projects × service cost`.

Payment sensitivity: on the $12 working case, a hypothetical 20% sales tax adds about **$0.16** to a 6.5% processing fee; an illustrative 1% non-US bank payout charge adds about **$0.11**, reducing $8.21 contribution to roughly **$7.95**. Actual settlement bases/refund treatment can differ. Tax collected is not product revenue, and this is not tax advice.

**Maximum-use warning:** suppose a session actually costs $0.02 per preview, $0.10 per build and $0.20 other infrastructure. At 200 previews and 11 builds, infrastructure alone is **$5.30/project**. Add eight support minutes and service becomes $9.30. Single contribution falls to **$1.06**; the three-pack to **−$2.16**; Creator to **−$6.80**, before fixed costs/CAC. Those unit costs are hypothetical, not measurements. This stress test shows why allowances cannot be sold based only on the optimistic reserve. Benchmark quota-exhaustion sessions; reduce underlying cost, revise clearly disclosed allowances or raise prices before sale if necessary.

### The requested $3–$5 cost per font

That is a target to test, not a budget the system should try to spend. With an illustrative **$150/month fixed infrastructure budget** and the $12 working case:

| Paid single projects/month | Fixed allocation/project | Modeled service + payment + refunds + fixed allocation | Remaining before CAC |
|---:|---:|---:|---:|
| 25 | $6.00 | $9.79 | $2.21 |
| 100 | $1.50 | $5.29 | $6.71 |
| 250 | $0.60 | $4.39 | $7.61 |
| 1,000 | $0.15 | $3.94 | $8.06 |

Exclusions above still apply. These are not a hosting quote, demand forecast or guarantee of $3–$5 all-in costs. Pack receipts and future redemptions must be matched over cohorts; unused credits are a liability, not assumed free margin. Capacity may need another worker as volume/concurrency increases, so fixed costs will not necessarily stay $150 at 1,000 projects.

At these assumptions, about **19 single purchases/month** cover $150 fixed costs without CAC; about **29** cover it with $3 CAC. This excludes development compensation and the other listed costs. Founder support is not “free.”

### Why delay subscriptions

The $24 three-project working case leaves only 61% contribution before fixed costs/CAC. That misses a proposed **65% contribution gate including observed payment/support costs**. With repeat users needing one support minute rather than three, the same $0.65 infrastructure assumption would leave about **73.5%** before additional fees; that is a hypothesis to measure, not an excuse to launch immediately. Raise the price, reduce genuinely unnecessary cost or withhold the tier if it fails. Do not make profitability depend on unused subscriptions.

## 8. Acquisition and price validation

### Start where the economics can work

Use the single font as the entry product; offer the pack when a customer wants another style, not as mandatory spend. Start with organic demonstrations, approved creator/community partnerships and high-intent instructional content. Search topics: “turn handwriting into a font,” “create a font from handwriting,” “handwriting font for Word,” and “make your own font.” Separate experimental object-font content from reliable handwriting claims. These are intent hypotheses, **not researched search-volume or CPC estimates**.

Start English-language learning with US users, then UK/Canada/Australia cohorts; this is an operational hypothesis, not evidence they are the most profitable regions. Do not exclude Indian buyers or invent purchasing-power discounts without local conversion/support evidence. Check currency totals and tax display with the chosen provider. Country-specific offers require transparent rules and review.

Do not start paid acquisition until completed-font quality, refunds and costs are visible. At 100 single projects/month, $8.21 contribution less $1.50 fixed allocation and a $3 retained-profit target permits about **$3.71 CAC before excluded extras**; use **≤$3 CAC** as a cautious initial ceiling, not a claimed market outcome. A $3 CAC ceiling permits $0.03/$0.09/$0.15 CPC at 1%/3%/5% click-to-paid conversion respectively. If actual bids exceed that, fix conversion/AOV or use another channel; do not infer search ads will be profitable. No ad spending is authorized or performed by this document.

### Research before pretending to optimize

1. **Task interviews:** recruit roughly 12–15 adults across personal and repeat-creator segments. Have them make a sample, inspect their own result and explain the alternative they would use. Record task failure separately from price rejection. Small samples are directional, not representative.
2. **Price-sensitivity research:** use the skill’s Van Westendorp-style four questions—prices that seem implausibly cheap, good value, expensive but conceivable, and too expensive—for the same clearly specified one-off project. Analyze segments separately. A 30–50 respondent pilot can reveal misunderstandings; it cannot establish an optimal population price.
3. **Purchase-intent checks:** use Gabor–Granger-style price questions around $9.99, $12 and $14.99 after the own-font proof. Counterbalance order or randomize starting points. Hypothetical intent is weaker evidence than checkout behavior. Optional feature-priority research can compare capture ease, correction, installation, creative inputs and character coverage without promising unbuilt features.
4. **Real paid baseline:** after launch gates, sell the same $12 offer transparently to an initial organic cohort. Track contribution and successful use, not merely whether someone entered a card.
5. **Price experiment:** compare $12 against either $9.99 or $14.99 with identical packaging and stable assignment for new users. Do not split tiny traffic across three simultaneous tests. Predefine the time window and decision rule; account for refunds/support after purchase. If using sequential cohorts, disclose season/channel confounding. Twenty purchases per price is learning evidence, not statistical proof. Size a formal test from observed baseline conversion and the minimum effect worth acting on.

**Primary decision metric:** contribution per qualified visitor, with qualified defined before the price exposure. Also report overall visitor-to-paid conversion so a change in sample completion cannot disappear from the funnel. Guardrails: usable font, successful install, refund rate, support minutes, preview/build cost and complaints. Optimize neither conversion nor ARPU in isolation.

Decision rules: if $12 is rejected after successful proofs specifically because of price, test $9.99; if proofs fail, fix quality first. If $14.99 produces higher contribution per qualified visitor without material deterioration in success/refunds, adopt it for new purchases. Honor prices/allowances already bought; no retroactive reduction of credits.

### Subscription evidence gate

Identify at least 30 genuine repeat creators, for example users completing two distinct projects within 60 days. Invite 10–20 to a clearly disclosed $24 monthly pilot only after paid entitlements work. Observe at least three billing cycles, actual redemptions and cancellation reasons. These counts are recruitment targets, not statistical guarantees. Require the cost gate above and evidence users value continuing creation. Do not extrapolate LTV from one month, hide cancellation or sell annual commitments before retention is understood.

## 9. Commercial launch checklist — separate from the working v1

| Gate | Required evidence before charging |
|---|---|
| Provider onboarding | Approved account, eligible product/domicile, payout route, actual fee schedule and test settlement/refund |
| Paid ledger | Purchase, reservation, consumption and refund reconciliation are idempotent; webhook replay, concurrent builds, failed jobs and cancellation tested |
| Entitlements vs abuse limits | Paid quotas allow a full 94-glyph session plus corrections. Current beta defaults such as 150 uploads/day and 120 previews/day are not the proposed paid contract; source+mask uploads alone can exceed 150 for 94 glyphs. Test realistic bytes, uploads, concurrent work and retries. |
| Retention/downloads | Current beta projects have a seven-day inactivity window and jobs/downloads a separate 24-hour window. Implement promised paid windows, reminders/deletion and recoverable artifacts before advertising 30 days. Re-signing/retrieving identical artifacts must not spend a revision. Raw sources and accepted masks need separate truthful retention descriptions. |
| Actual session cost | Instrument deterministic/ML preview counts, CPU/wall/RAM, successful/failed builds, idle capacity, storage/egress, abandoned free sessions and support. Benchmark normal, p95 and quota-exhaustion sessions on the intended deployment. |
| Unit economics | Measure payment/payout/refund/support costs. Single/pack target ≥65% contribution before fixed/CAC under observed normal use; maximum allowances must not create a systematically loss-making repeatable path. Reprice/repackage before sale if they fail. |
| Customer success | Real captures → corrected glyphs → valid exported fonts → manual installation in advertised apps. Count failures and unsupported images honestly. |
| Terms/support | Publish accurate input rights, retention, allowances, cancellation/refund and support policy. Review jurisdiction/provider requirements. No minors/workshop enterprise promise without appropriate handling. |
| Pricing display | Current offers/limits and final totals match the entitlement implementation; no paid CTA while billing is disabled. |

The app currently explicitly rejects enabled billing; a configuration flag is not a checkout implementation. This pricing task does not enable it or change existing beta behavior.

### Minimum commercial telemetry

Use first-party, privacy-conscious events: sample started/completed, proof shown, price exposure/experiment assignment, checkout started/paid/refunded, credit reserved/consumed/released, export success/failure, install success self-report and repeat project. Attach offer version, workflow, project count, support minutes and aggregated cost counters—not raw photographs or handwriting. Respect the existing consent policy; essential billing records and optional analytics need distinct retention/access rules. Reconcile revenue and credit liabilities with provider reports, not UI click events.

## 10. Rollout and stop conditions

- **Days 1–7, conditional on engineering readiness:** complete payment/entitlement/retention gates and deploy cost probes. Conduct task interviews. Keep existing working v1 available as invite beta.
- **Days 8–14, if gates pass:** small organic paid cohort at $12; offer $29 pack without pressure. Read every failure/refund and measure support time. If gates do not pass, remain free beta rather than charging for an unfulfilled promise.
- **Days 15–30, if traffic permits:** run one price experiment, improve proof/install activation, update the cost model with actual session/provider data. Do not claim a winning price with inadequate data.
- **Days 60–90, only with repeat demand:** consider the Creator pilot. No Studio or annual tier by default.

Pause acquisition if exports are unusable, ordinary users routinely exhaust allowances, refunds indicate misrepresentation, or realized contribution is below the chosen gate. Fix the cause before buying traffic. These are decision checkpoints, not a promise to earn revenue on a particular date.

**Bottom line:** launch the commercial experiment with **free proof → $12 one font / $29 three fonts**. Earn the right to offer a subscription through repeat usage and measured margin. Keep segmentation attempts an internal cost/control metric, not the thing customers are forced to buy.
