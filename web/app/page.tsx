import Image from 'next/image';
import Link from 'next/link';
import { MAX_UPLOAD_BYTES } from '@/lib/contracts';
import { UploadWorkbench } from './upload-workbench';

const modes = [
  {
    title: 'Guided characters',
    detail: 'Pick a label, capture one handwritten character or silhouette, adjust the black-and-white preview, accept it, and move on without losing other characters.',
  },
  {
    title: 'Markerless A4 sheet',
    detail: 'Use the default-v1 A4 page, photograph it upright with the full border visible, then confirm the four page corners before building.',
  },
  {
    title: 'Legacy marker sheet',
    detail: 'Already filled the original marker template? The original template still works in legacy mode.',
  },
] as const;

const steps = [
  { number: '01', title: 'Capture real shapes', detail: 'Use guided character photos or the known A4 sheet. The alpha does not synthesize missing letters.' },
  { number: '02', title: 'Correct before building', detail: 'Confirm page corners or accept the exact black-and-white preview for each guided character.' },
  { number: '03', title: 'Proof and download', detail: 'When a real build returns validated files, preview with the generated TTF and download TTF/OTF for desktop use.' },
] as const;

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-[1200px] px-5 pt-12 pb-24 md:px-10">
      <nav className="mb-6 flex flex-wrap items-center justify-between gap-3 text-sm">
        <Link href="/" className="font-semibold tracking-[-.02em]">Handwrite Font Maker</Link>
        <div className="flex gap-4 text-text-secondary">
          <a href="#capture" className="hover:text-text-primary">Capture</a>
          <a href="/help/install-fonts" className="hover:text-text-primary">Install help</a>
        </div>
      </nav>

      <section className="grid grid-cols-1 items-start gap-10 pt-8 pb-14 md:grid-cols-[1fr_340px] md:gap-14">
        <div className="max-w-[620px]">
          <span className="mb-5 inline-block rounded-[4px] bg-teal-muted px-2.5 py-1 font-mono text-[11px] font-medium uppercase tracking-[.12em] text-teal">
            Private alpha capture
          </span>
          <h1 className="text-[clamp(2.8rem,5.5vw,4.5rem)] font-bold leading-[.95] tracking-[-0.045em] text-text-primary">
            Turn handwriting and handmade shapes into a font you can type with.
          </h1>
          <p className="mt-5 max-w-[56ch] text-base leading-relaxed text-text-secondary">
            Capture labeled characters, review the exact black-and-white previews you accept, and download desktop TTF/OTF font files when the real build finishes. Missing characters stay missing so you always know what will type.
          </p>
          <div className="mt-8 flex gap-2.5 max-sm:flex-col">
            <a href="#capture" className="primary-anchor inline-flex h-11 items-center justify-center rounded-full border border-accent bg-accent px-5 text-sm font-semibold text-white transition-all duration-150 hover:bg-accent-hover active:scale-[0.98] active:translate-y-px max-sm:w-full">
              Start capture
            </a>
            <a href="/template-markerless.pdf" download className="inline-flex h-11 items-center justify-center rounded-full border border-border bg-surface px-5 text-sm font-semibold transition-all duration-150 hover:border-border-strong hover:bg-bg-subtle max-sm:w-full">
              Download markerless A4
            </a>
            <a href="/template-v1.pdf" download className="inline-flex h-11 items-center justify-center rounded-full border border-border bg-surface px-5 text-sm font-semibold transition-all duration-150 hover:border-border-strong hover:bg-bg-subtle max-sm:w-full">
              Legacy V1 PDF
            </a>
          </div>
          <dl className="mt-10 grid grid-cols-3 gap-px overflow-hidden rounded-xl bg-border max-sm:grid-cols-1">
            {[
              { label: 'Max upload', value: `${Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)} MB` },
              { label: 'Guided labels', value: '94 ASCII' },
              { label: 'Alpha output', value: 'TTF/OTF' },
            ].map(({ label, value }) => (
              <div key={label} className="bg-surface px-[18px] py-4">
                <dt className="text-[11px] font-medium uppercase tracking-[.06em] text-text-tertiary">{label}</dt>
                <dd className="mt-1 text-sm font-bold">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="rounded-[28px] border border-border bg-surface p-4 shadow-[0_12px_40px_-12px_rgba(0,0,0,.12)]">
          <Image
            src="/template-markerless.png"
            alt="Preview of the markerless default-v1 A4 handwriting sheet with labeled character cells"
            width={1240}
            height={1754}
            priority
            className="max-h-[480px] w-full rounded-[22px] border border-border object-contain"
          />
          <div className="flex justify-between px-1 pt-3 text-xs text-text-tertiary">
            <span>Markerless A4 sheet</span>
            <span>Confirm page corners before building</span>
          </div>
        </div>
      </section>

      <section className="my-12 grid grid-cols-1 gap-3 md:grid-cols-3" aria-label="Capture modes">
        {modes.map((mode) => (
          <article key={mode.title} className="rounded-[22px] border border-border bg-surface px-6 py-7">
            <h2 className="mb-2 text-[18px] font-semibold tracking-[-0.02em]">{mode.title}</h2>
            <p className="text-[13.5px] leading-relaxed text-text-secondary">{mode.detail}</p>
          </article>
        ))}
      </section>

      <section className="my-16 grid grid-cols-1 gap-3 md:grid-cols-[2fr_1fr_1fr]" aria-label="Workflow steps">
        {steps.map((step, idx) => (
          <article key={step.number} className={`rounded-[22px] border border-border bg-surface px-6 py-7 transition-all duration-200 hover:border-border-strong hover:shadow-[0_1px_2px_rgba(0,0,0,.04)] ${idx === 0 ? 'md:row-span-2 md:flex md:flex-col md:justify-center md:px-8 md:py-9' : ''}`}>
            <span className="font-mono text-xs font-semibold text-teal">{step.number}</span>
            <h2 className={`mt-3 mb-2 font-semibold tracking-[-0.02em] ${idx === 0 ? 'text-[22px]' : 'text-[17px]'}`}>{step.title}</h2>
            <p className="text-[13.5px] leading-relaxed text-text-secondary">{step.detail}</p>
          </article>
        ))}
      </section>

      <div id="capture">
        <UploadWorkbench />
      </div>
    </main>
  );
}
