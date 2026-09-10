'use client';

export const STARTER_TARGET_CHARACTERS = 'ABCDE';

export function StarterSamplePanel({ disabled = false, onLoadSample }: { disabled?: boolean; onLoadSample: () => void }) {
  return (
    <section className="rounded-xl border border-teal-muted bg-teal-muted/40 p-4" aria-label="Starter project onboarding">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-[58ch]">
          <strong className="text-sm text-text-primary">Start with five characters</strong>
          <p className="mt-1 text-xs text-text-secondary">The MVP starter uses A B C D E so you can save, reload, tune spacing, and build quickly. Use your own handwriting photos for real output, or load the synthetic masks to test the workflow without any model.</p>
        </div>
        <button type="button" className="secondary-button" onClick={onLoadSample} disabled={disabled}>Load ABCDE sample</button>
      </div>
    </section>
  );
}
