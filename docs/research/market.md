# Handwriting / Labeled-Glyph-to-Font Market Research

Access date: 2026-09-10. Sources were gathered from official/live primary pages using Firecrawl unless noted. This is market/pricing research only; no spending, publishing, or implementation scope is included.

## Scope correction for MVP

The MVP evaluated here is **extraction-only**: the user supplies the actual glyphs to be included (for example, a labeled handwriting sheet, template, or individual glyph images), and the product extracts/vectorizes/builds a usable font from those supplied glyphs. It **does not synthesize missing letters from a logo, artwork, or style reference**.

AI style/prompt-to-font competitors are included as **landscape and future R&D context only**. Their claims about generating complete alphabets from prompts/images should not be used as MVP positioning, landing-page copy, or paid-search promises until the product actually supports that capability.

## Strongest conclusions

1. **The clearest near-term wedge is “upload supplied/labeled glyphs → preview → export a usable font file.”** This puts the MVP closest to template handwriting-to-font tools (Calligraphr, YourFonts, Scanahand) and glyph-sheet extraction tools (GLIPH), not broad “logo/style-to-font” synthesis.
2. **Recommended default price: $9.99 per exported font.** This matches the YourFonts $9.95 one-off anchor and gives more room for payment fees, retries, support, and refunds than a $4.99 default.
3. **Recommended bounded launch test: $4.99 per exported font.** Use $4.99 only as a limited acquisition/price-elasticity test or launch promo with strict retry/support limits. It is defensible because Lipi’s “Buy for Use” and Birdfont commercial start at roughly this level, but it leaves little COGS headroom.
4. **Do not sell “ownership” or exclusivity for ordinary extraction of the user’s own handwriting/glyphs.** Recommend transparent terms instead: the user retains rights to their uploaded inputs; the product grants export/download and ordinary usage rights for the generated font file; no exclusivity or copyright-transfer promise unless separately reviewed and operationalized.
5. **Initial ICP:** non-professional creators who already have handwriting/lettering/glyph artwork and want a fast, usable font export without learning a full font editor. Secondary ICP: personal handwriting users.
6. **Initial GTM:** Search intent should focus on extraction/conversion, not synthesis: “turn handwriting into font,” “handwriting font generator,” “convert PNG letters to TTF,” “glyph sheet to font,” “Calligraphr alternative.” Do not assume volume/CAC; use Google Keyword Planner before spend.

## Market map: evidence vs interpretation

### Evidence from current tools

| Segment | Representative tools | Current pricing / packaging | Key capabilities | Evidence |
|---|---:|---:|---|---|
| Template handwriting-to-font | Calligraphr | Free registration; Pro is **$10 for one month** or **$6/month for 6 months** | Handwriting/calligraphy to standard TTF/OTF; free tier capped at 75 chars, 1 concurrent font, no ligatures; Pro supports 600 chars, 20 concurrent fonts, variants, ligatures, spacing, backup, priority processing | [Calligraphr pricing](https://www.calligraphr.com/en/pricing/) |
| Template handwriting-to-font | YourFonts | **$9.95**; +**$5.00** if uploading both template pages; free preview | Online OpenType handwriting font generator; >200 chars; output for Windows/Mac/Linux and Word/PowerPoint; positioned around personal fonts, scrapbooking, invitations, family handwriting | [YourFonts homepage](https://www.yourfonts.com/) |
| Desktop template/scanning font generator | Scanahand 9 | Standard **$59**, Premium **$99**; free trial | Windows app; template print/draw/scan/digitize/generate workflow; compatible with Windows, macOS, mobile, web, Word/PowerPoint/Adobe/Figma; premium has template editor; spacing/kerning tools | [Scanahand product](https://www.high-logic.com/font-generator/scanahand), [High-Logic shop](https://www.high-logic.com/buy-now/new-licenses) |
| Creator font-making apps/plugins | Fontself | Desktop Maker **$39** discounted from $98; Illustrator+Photoshop bundle **$59** discounted from $78; iPad app listed at **$19.99 + IAP** on Apple App Store | Illustrator/Photoshop extension: vector/color fonts, auto spacing/kerning, alternates, ligatures, free updates; iPad app: draw handmade fonts, export OTF, Procreate/Canva/Photoshop/Illustrator workflows | [Fontself store](https://www.fontself.com/store), [Fontself homepage](https://www.fontself.com/), [Apple App Store listing](https://apps.apple.com/us/app/fontself-make-your-own-fonts/id1512959192) |
| Free/browser font editor | Glyphr Studio | **$0 forever**, donation-supported | 100% in-browser, no sign-up, imports SVG/OTF/TTF/WOFF, vector editing, combine glyphs, export font files, custom ligatures; built for hobbyists/beginners | [Glyphr Studio](https://www.glyphrstudio.com/) |
| Free/low-cost font editor | Birdfont | Open source/freeware free; commercial **$4.99+**; Plus **$9.99+** | Runs Linux/Windows/Mac; TTF/SVG/kerning/ligatures/alternates/SVG import; commercial use in paid/open-source versions; Plus adds color fonts, OTF CFF, COLR/CPAL, single-stroke, variable fonts | [Birdfont download/pricing](https://birdfont.org/download.php) |
| Open-source font editor | FontForge | Free/open source/donation-supported | Windows/Mac/Linux font editor; community documentation and downloads; useful as “power-user fallback” after generation | [FontForge](https://fontforge.org/en-US/), [downloads](https://fontforge.org/en-US/downloads/) |
| AI prompt-to-font (landscape only) | Lipi.ai | Buy for Use **$4.99**; Full Ownership **$9.99** | Text prompt to complete font in about 60 seconds; TTF/OTF/WOFF/WOFF2; commercial license, Font ID/certificate; use cases include startup/product branding, games, web/SaaS, editorial | [Lipi AI Font Generator](https://www.lipi.ai/deep-generate) |
| AI image/style-to-font (future R&D landscape only) | Lipi.ai | Same license model implied via purchase step; public image page points to license choice | Upload logos, handwriting, vintage signs, artwork; AI creates matching font; generates A-Z, numbers, symbols; exports TTF/OTF/WOFF/WOFF2; 36-language Latin set, with 81-language multilingual option | [Lipi Image to Font](https://www.lipi.ai/image-generate) |
| AI bitmap/glyph-sheet-to-font | GLIPH | Beta **$5/month**; 500 credits/month; 100 sheet uploads at 5 credits each; 10 free credits | Upload hand-drawn or AI-generated glyph sheets; AI extraction, vectorization, manual/auto labeling, missing glyph upload, vector editor beta; exports TTF; targets designers, developers, artists, marketers | [GLIPH](https://gliph.us/) |
| Pro font editor anchor | Glyphs / FontLab | Glyphs 4 **€319**, Glyphs Mini **€49**; FontLab lifetime **US$499**, 3-month **US$97** | Professional editor price anchors; useful contrast for “not for type-design pros” positioning | [Glyphs buy](https://glyphsapp.com/buy), [FontLab 8](https://www.fontlab.com/font-editor/fontlab/) |

### Interpretation / hypothesis

- **The market is fragmented by user sophistication.** Free editors solve control but not speed. Template tools solve handwriting but require structured forms. AI/image-to-font tools solve broader style synthesis, but that is not the MVP promise.
- **The MVP should compete on extraction quality, labeling, preview accuracy, and export convenience.** Differentiation is not “generate a missing alphabet from a logo”; it is “quickly turn the glyphs you actually drew/uploaded into a working font.”
- **The best positioning is not “professional type design.”** It should be “make a usable personal/display font from your own supplied handwriting or glyph sheet in minutes.”

## Pricing recommendation and COGS target

This section records the initial research hypotheses. Final packaging, revision allowances and subscription decisions are in [PRICING-GTM.md](../PRICING-GTM.md), which supersedes the tentative bundles below.

### Recommended public pricing ladder

| Offer | Price to test | Rationale |
|---|---:|---|
| Free preview | $0 | Competitors condition users with free registration/free preview/free trials: Calligraphr has a free tier; YourFonts offers free preview; Scanahand has trial; GLIPH offers free credits. Subjective creative output needs preview before payment. |
| Standard exported font | **$9.99 default** | Best default for MVP: matches YourFonts’ $9.95 one-off anchor and gives materially more room for support/retries/CAC than $4.99. Include TTF/OTF only for alpha (WOFF/WOFF2 are future roadmap), transparent input-retention terms, and a bounded retry/rebuild allowance. |
| Bounded launch test / promo | **$4.99** | Use as a limited price-elasticity or launch test with strict scope: one supplied glyph set, one export, limited retry/rebuild. Do not use as permanent default unless measured COGS/support/retry rates stay low. |
| Multi-font / creator bundle | Later, only after repeat evidence | Do not launch subscription or bundles until usage data shows repeat generation. Candidate future tests: 3 fonts for $19, 5 fonts for $29, or $9/month creator plan. |

### Licensing recommendation for extraction-only MVP

Use plain, non-overreaching language:

- User retains ownership/rights in uploaded handwriting, artwork, and glyph inputs.
- The product processes supplied inputs into downloadable font files.
- Purchase grants the user the ability to download and use the generated font file for personal/commercial projects, subject to terms.
- The service does **not** guarantee legal exclusivity, copyright transfer, trademark clearance, or ownership of third-party source material.
- Do not create a “Full Ownership / Exclusive” upsell for ordinary extraction. That would be confusing for user-owned handwriting and risky for uploaded third-party logos/art.

### COGS target, not measured COGS

Hard COGS cannot be known from competitor pages. It must be measured from the actual extraction/build pipeline: image processing/vectorization, font-building CPU time, storage/bandwidth, retries, refunds, and support minutes. The following are **pricing-derived target budgets**.

Using Stripe’s published US standard online card pricing of **2.9% + $0.30** per successful card transaction ([Stripe pricing](https://stripe.com/pricing)), the approximate processor fee and remaining non-payment COGS budget are:

| Price | Stripe fee estimate | Non-payment COGS budget for ~80% gross margin before CAC | Non-payment COGS budget for ~70% gross margin before CAC | Pre-CAC contribution if non-payment variable COGS = $0.50 | Pre-CAC contribution if non-payment variable COGS = $1.00 |
|---:|---:|---:|---:|---:|---:|
| $4.99 | $0.44 | $0.55 | $1.05 | $4.05 | $3.55 |
| $7.99 | $0.53 | $1.07 | $1.87 | $6.96 | $6.46 |
| $9.99 | $0.59 | $1.41 | $2.41 | $8.90 | $8.40 |
| $14.99 | $0.73 | $2.26 | $3.76 | $13.76 | $13.26 |

**Recommended COGS guardrails:**

- For the **$9.99 default**, target **all-in non-payment variable COGS <= $1.25-$1.50 per paid font** after average retries to preserve room for refunds/support and some paid acquisition testing.
- For a **$4.99 launch test**, target **<= $0.50 per paid font** after average retries. If the pipeline cannot hit that, keep $4.99 as a narrow promo or abandon it.
- Track COGS as: `payment fee + extraction/vectorization/font-build compute * (1 + retry_rate) + storage/bandwidth + support_minutes/60 * support_hourly_cost + refund/chargeback allocation`.
- Track CAC separately. Do not commit paid media until measured contribution margin is positive under realistic retry/support rates.
- If future R&D uses OpenAI vision/image generation, OpenAI prices image inputs/outputs by tokens and says image costs are calculated from image tokens; the public price page gives token rates but not your per-font token count. Instrument actual token usage before declaring per-font COGS ([OpenAI API pricing](https://openai.com/api/pricing/)).

## Product positioning

### Evidence-backed positioning ingredients

- **Personal handwriting:** Calligraphr and YourFonts both lead with handwriting/calligraphy-to-font; YourFonts emphasizes personal use cases such as scrapbook pages, invitations, family handwriting history, Word/PowerPoint.
- **Creator workflows:** Fontself emphasizes Procreate, Photoshop, Canva, Illustrator, OpenType export, vector brushes, auto spacing/kerning.
- **Glyph-sheet extraction:** GLIPH supports hand-drawn alphabets, AI-generated letterforms, bitmap glyph sheets, AI extraction/vectorization, manual/auto labeling, missing glyph upload, and TTF export.
- **AI style/prompt synthesis as future landscape:** Lipi supports prompt/image style-to-font generation with complete-character claims, but that is outside the extraction-only MVP.

### Recommended positioning statement

> Turn your supplied handwriting or labeled glyph sheet into a font you can type with. Inspect your captures and export TTF/OTF with transparent usage terms while retaining rights to your uploaded inputs.

WOFF/WOFF2 are future roadmap formats, not current export options.

### Differentiation to test

1. **Less friction than traditional template tools:** support photos/scans of labeled glyph sheets and individual glyph images, while still being clear that only supplied glyphs are extracted.
2. **Less complexity than font editors:** no need to learn Glyphr/Birdfont/FontForge/Glyphs/FontLab for a simple personal/display font.
3. **Better preview and labeling than manual workflows:** show extracted glyphs before payment/export, allow users to fix labels or re-upload missing glyphs.
4. **Clear, conservative licensing:** user retains inputs; purchase covers export/use of generated font files; no exclusivity/copyright-transfer promise.
5. **Bounded retry/edit promise:** include a limited number of rebuilds or glyph fixes to reduce perceived risk without creating unlimited support COGS.

## Initial ICP

### Primary ICP: creator with supplied glyph artwork

**Evidence:** Fontself targets handmade/vector calligraphy and Procreate/Canva/Adobe workflows; GLIPH names designers, artists, marketers, developers and centers hand-drawn or generated glyph sheets; Calligraphr/YourFonts prove handwriting-to-font demand.

**Hypothesis:** Best first ICP is creators who already have glyphs/letters drawn and want export speed without professional font-editor complexity:

- lettering artists and calligraphers
- Procreate/Canva/Adobe/Figma users who draw alphabets or display lettering
- Etsy/Creative Market-style digital product sellers creating handwritten/display fonts
- comic/zine/poster/merch creators who need a custom display alphabet
- indie game/UI creators with supplied title/display glyph sets

### Secondary ICP: personal handwriting users

**Evidence:** Calligraphr and YourFonts prove demand for “my handwriting as a font”; YourFonts emphasizes invitations, scrapbooks, family handwriting, Word/PowerPoint.

**Hypothesis:** This segment converts on emotional/personal use but may have lower repeat purchase frequency. It is a strong SEO segment and a weaker subscription segment.

### De-prioritize initially

- **Logo/style-reference users expecting a full generated alphabet.** This is a future R&D segment, not an MVP promise.
- Professional type designers: already served by Glyphs, FontLab, FontForge, Birdfont, Glyphr; expectations for kerning, interpolation, OpenType features, hinting, and glyph coverage will raise support burden.
- Enterprise brand typography: may pay more, but legal/exclusivity/review cycles complicate a quick low-cost paid test.

## GTM / SEO / paid search test

### Evidence-backed channel notes

- Google Ads Keyword Planner is the official tool to discover keyword ideas, forecasts, and bid estimates; use it before any spend rather than inventing volume/CAC ([Google Keyword Planner](https://ads.google.com/intl/en_in/home/tools/keyword-planner/)).
- Google Ads match types control which searches trigger ads; if no match type is specified, keywords are broad match. For a small test, exact and phrase match are safer than broad until negative keywords are known ([Google Ads match types](https://support.google.com/google-ads/answer/6324?hl=en)).

### Countries / regions to test

**Evidence:** Current competitor pages and prices are primarily English and USD/EUR; Lipi’s image-to-font page calls out Latin-script language coverage and an 81-language multilingual option.

**Hypotheses for staged testing:**

1. **Phase 1 English paid-search test:** US, Canada, UK, Ireland, Australia, New Zealand. Rationale: English landing page and English search intent; higher willingness to pay likely, but CPC may be higher. No volume/CAC assumed.
2. **Phase 1b low-price English creator test:** India, Philippines, Singapore, South Africa. Rationale: English creator/design markets may respond to a bounded $4.99 promo; run separately so CPC/conversion data is not blended with Tier-1 geos.
3. **Phase 2 localized SEO/search:** Germany, Netherlands, Nordics, France, Spain, Brazil/Mexico only after diacritics/language support and localized landing pages are real. Do not advertise unsupported glyph coverage.

### Keyword groups for SEO and exact/phrase paid search

Use these as seed groups for Keyword Planner; do not assume volume. Prioritize extraction/conversion terms; avoid style-synthesis terms until product capability exists.

**Handwriting extraction intent**

- turn handwriting into font
- handwriting to font
- make handwriting font
- create font from handwriting
- make your own handwriting font
- handwriting font generator
- convert handwriting to font
- calligraphy to font

**Glyph sheet / supplied-letter conversion intent**

- glyph sheet to font
- alphabet sheet to font
- turn alphabet into font
- convert drawn letters to font
- convert scanned letters to font
- convert PNG letters to TTF
- convert SVG letters to font
- create font from drawing alphabet
- make font from hand drawn letters
- TTF from handwriting sheet

**Workflow/tool modifiers**

- font for Procreate
- font for Canva
- font for Photoshop
- font for Illustrator
- custom OTF font maker
- custom TTF font maker
- custom WOFF font generator
- font maker for lettering artists

**Competitor / alternative intent**

- Calligraphr alternative
- Calligraphr pricing
- YourFonts alternative
- Fontself alternative
- Scanahand alternative
- Glyphr Studio alternative
- Birdfont commercial font

**Landscape/future R&D keywords — do not buy for MVP unless clearly qualified**

- logo to font generator
- image to font generator
- AI image to font
- AI font generator
- generate alphabet from logo
- style to font generator

**Negative keyword candidates**

- free fonts download
- handwriting fonts free
- font identifier
- font pairing
- keyboard fonts
- tattoo font download
- Microsoft Word fonts download
- DaFont
- Google Fonts
- logo design
- AI art generator

### Landing-page tests

1. **Handwriting page:** “Turn your handwriting into a font.” Show before/after; emphasize supplied handwriting sheet, free preview, and Word/Canva/Procreate usage.
2. **Glyph-sheet page:** “Turn your drawn alphabet or labeled glyph sheet into a font.” Emphasize extraction, label review, missing-glyph upload, and real font export.
3. **Creator workflow page:** “Make a custom display font from letters you already drew.” Target Procreate/Canva/Adobe/Figma users; avoid implying missing glyph synthesis.
4. **Competitor alternative pages:** “Calligraphr alternative,” “Fontself alternative,” etc. Must be fair, factual, and avoid trademark confusion.

## Risks and unknowns

- **Output quality drives refunds/support.** Creative-output products fail if previews differ from downloaded fonts, glyphs are mislabeled, spacing is poor, or users expect a polished type family.
- **Capability clarity is critical.** The MVP extracts supplied glyphs; it should not imply it can infer a full alphabet from a logo/style image.
- **License wording is a product feature.** Avoid “full ownership,” “exclusive,” or “copyright transfer” upsells for ordinary user-supplied handwriting/glyph extraction. State that users retain their inputs and receive downloadable/useable font files under clear terms.
- **Language/glyph coverage matters.** Competitors advertise limits (Calligraphr 75 vs 600 chars; Lipi 36/81 Latin-language options; GLIPH 60-100+ chars/sheet). Avoid paid ads for unsupported glyph sets.
- **$5/month subscription may be unsustainable.** GLIPH presents $5/month as beta/limited-time. Treat it as a competitive signal, not proof of long-term unit economics.
- **CAC is unknown.** Google can estimate bids in Keyword Planner, but actual CAC requires campaign data. Keep budgets small and isolate keyword/geography tests.

## Source register

All accessed 2026-09-10.

- Calligraphr pricing — https://www.calligraphr.com/en/pricing/
- Calligraphr homepage — https://www.calligraphr.com/en/
- YourFonts homepage — https://www.yourfonts.com/
- Scanahand product — https://www.high-logic.com/font-generator/scanahand
- High-Logic shop/new licenses — https://www.high-logic.com/buy-now/new-licenses
- Fontself store — https://www.fontself.com/store
- Fontself homepage — https://www.fontself.com/
- Fontself Apple App Store listing — https://apps.apple.com/us/app/fontself-make-your-own-fonts/id1512959192
- Glyphr Studio — https://www.glyphrstudio.com/
- Birdfont download/pricing — https://birdfont.org/download.php
- FontForge homepage — https://fontforge.org/en-US/
- FontForge downloads — https://fontforge.org/en-US/downloads/
- Lipi AI Font Generator — https://www.lipi.ai/deep-generate
- Lipi Image to Font — https://www.lipi.ai/image-generate
- GLIPH — https://gliph.us/
- Glyphs buy — https://glyphsapp.com/buy
- FontLab 8 — https://www.fontlab.com/font-editor/fontlab/
- Stripe pricing — https://stripe.com/pricing
- Google Keyword Planner — https://ads.google.com/intl/en_in/home/tools/keyword-planner/
- Google Ads match types — https://support.google.com/google-ads/answer/6324?hl=en
- OpenAI API pricing — https://openai.com/api/pricing/
