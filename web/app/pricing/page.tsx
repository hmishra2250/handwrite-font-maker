import Link from 'next/link';
import { PricingSection } from '../pricing-section';
import { StudioBrand } from '../studio-chrome';

export const dynamic = 'force-dynamic';

export default function PricingPage() {
  return (
    <main className="mx-auto w-full max-w-[1200px] px-5 pt-8 pb-16 md:px-10">
      <nav className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-6 text-sm">
        <StudioBrand />
        <Link href="/#capture" className="text-text-secondary hover:text-text-primary">← Back to capture</Link>
      </nav>
      <PricingSection standalone />
    </main>
  );
}
