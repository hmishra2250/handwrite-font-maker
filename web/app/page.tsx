import Image from 'next/image';
import { JOB_RETENTION_HOURS, MAX_UPLOAD_BYTES } from '@/lib/contracts';
import { UploadWorkbench } from './upload-workbench';

const steps = [
  { number: '01', title: 'Print the template', detail: 'Download the V1 PDF and print at 100% scale. The four ArUco corner markers must stay visible and uncropped.' },
  { number: '02', title: 'Fill in every cell', detail: 'Write one character per cell using a dark pen. Bright, even lighting and a flat surface produce the best results.' },
  { number: '03', title: 'Photograph and upload', detail: 'Snap a photo with your phone or upload an image. The pipeline detects markers, corrects perspective, extracts glyphs, and builds your font.' },
] as const;

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-[1200px] px-5 pt-12 pb-24 md:px-10">

      {/* Hero */}
      <section className="grid grid-cols-1 items-start gap-10 pt-8 pb-14 md:grid-cols-[1fr_340px] md:gap-14">
        <div className="max-w-[560px]">
          <span className="inline-block rounded-[4px] bg-teal-muted px-2.5 py-1 font-mono text-[11px] font-medium uppercase tracking-[.12em] text-teal mb-5">
            Template V1
          </span>
          <h1 className="text-[clamp(2.8rem,5.5vw,4.5rem)] leading-[.95] font-bold tracking-[-0.045em] text-text-primary">
            Turn your handwriting into an installable font.
          </h1>
          <p className="mt-5 max-w-[48ch] text-base leading-relaxed text-text-secondary">
            Print a template, fill it in by hand, photograph it, and get back OTF and TTF files.
            The computer-vision pipeline handles marker detection, perspective correction, and glyph extraction.
          </p>
          <div className="mt-8 flex gap-2.5 max-sm:flex-col">
            <a
              href="/template-v1.pdf"
              download
              className="inline-flex h-11 items-center justify-center rounded-full border border-accent bg-accent px-5 text-sm font-semibold text-white transition-all duration-150 hover:bg-accent-hover active:scale-[0.98] active:translate-y-px max-sm:w-full"
            >
              Download template
            </a>
            <a
              href="/template-v1-preview.png"
              className="inline-flex h-11 items-center justify-center rounded-full border border-border bg-surface px-5 text-sm font-semibold transition-all duration-150 hover:border-border-strong hover:bg-bg-subtle max-sm:w-full"
            >
              Preview
            </a>
          </div>
          <dl className="mt-10 grid grid-cols-3 gap-px overflow-hidden rounded-xl bg-border max-sm:grid-cols-1">
            {[
              { label: 'Max photo', value: `${Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)} MB` },
              { label: 'Retention', value: `${JOB_RETENTION_HOURS} hours` },
              { label: 'Characters', value: '94' },
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
            src="/template-v1-preview.png"
            alt="Preview of the handwriting template with ArUco corner markers and 94 character cells"
            width={1240}
            height={1754}
            priority
            className="w-full max-h-[480px] rounded-[22px] border border-border object-contain"
          />
          <div className="flex justify-between px-1 pt-3 text-xs text-text-tertiary">
            <span>Four ArUco corner markers</span>
            <span>94 glyph cells</span>
          </div>
        </div>
      </section>

      {/* Workflow */}
      <section className="my-16 grid grid-cols-1 gap-3 md:grid-cols-[2fr_1fr_1fr]" aria-label="Workflow steps">
        {steps.map((step, idx) => (
          <article
            key={step.number}
            className={`rounded-[22px] border border-border bg-surface px-6 py-7 transition-all duration-200 hover:border-border-strong hover:shadow-[0_1px_2px_rgba(0,0,0,.04)] ${
              idx === 0 ? 'md:row-span-2 md:flex md:flex-col md:justify-center md:px-8 md:py-9' : ''
            }`}
          >
            <span className="font-mono text-xs font-semibold text-teal">{step.number}</span>
            <h2 className={`mt-3 mb-2 font-semibold tracking-[-0.02em] ${idx === 0 ? 'text-[22px]' : 'text-[17px]'}`}>
              {step.title}
            </h2>
            <p className="text-[13.5px] leading-relaxed text-text-secondary">{step.detail}</p>
          </article>
        ))}
      </section>

      {/* Upload Workbench */}
      <UploadWorkbench />
    </main>
  );
}
