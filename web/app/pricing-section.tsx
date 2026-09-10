import Link from 'next/link';
import { BILLING_CATALOG } from '@/lib/alpha-plans';

export function PricingSection({ standalone = false }: { standalone?: boolean }) {
  const Heading = standalone ? 'h1' : 'h2';
  return (
    <section id="pricing" className="mx-auto max-w-[980px] py-12 md:py-20" aria-labelledby="pricing-title">
      <div className="mx-auto mb-12 max-w-[560px] text-center">
        <span className="studio-eyebrow">Alpha pricing</span>
        <Heading id="pricing-title" className="mt-5 font-[Georgia,serif] text-[clamp(2.5rem,5vw,4rem)] leading-[1.08] tracking-[-.045em]">Your letters.<br />Yours to keep.</Heading>
        <p className="mt-5 text-sm leading-7 text-text-secondary">Make a font that feels like you. Invited members can use the private alpha for free. No card required.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <article className="flex flex-col rounded-2xl border border-[#b4c4ae] bg-[#eaf0e5] p-7">
          <span className="mb-6 text-[10px] font-semibold uppercase tracking-[.14em] text-teal">Available by invitation</span>
          <h3 className="text-lg font-semibold">{BILLING_CATALOG.alpha.name}</h3>
          <p className="my-5 text-5xl font-medium tracking-tight">$0</p>
          <p className="mb-8 text-sm leading-6 text-text-secondary">Capture, refine, and download your fonts with an invited account. Usage and storage limits apply.</p>
          <Link href="/" className="primary-button primary-anchor mt-auto flex items-center justify-center">Open your studio →</Link>
        </article>
        {BILLING_CATALOG.offers.map((offer) => (
          <article key={offer.id} className="flex flex-col rounded-2xl border border-border bg-surface p-7">
            <span className="mb-6 text-[10px] font-semibold uppercase tracking-[.14em] text-text-tertiary">Planned for launch</span>
            <h3 className="text-lg font-semibold">{offer.name}</h3>
            <p className="my-5 text-5xl font-medium tracking-tight">${(offer.priceCents / 100).toFixed(0)}</p>
            <p className="mb-8 text-sm leading-6 text-text-secondary">{offer.projects} {offer.projects === 1 ? 'font project' : 'font projects'}. One-time purchase, with no subscription needed to keep using downloaded fonts.</p>
            <span className="mt-auto rounded-lg border border-border px-3 py-3 text-center text-xs text-text-secondary">Not available to purchase yet</span>
          </article>
        ))}
      </div>
      <p className="mx-auto mt-8 max-w-xl text-center text-xs leading-6 text-text-secondary">Paid purchases are not available yet. These prices are planned for launch, not a checkout offer. No payment details are collected during alpha.</p>
    </section>
  );
}
