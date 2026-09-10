'use client';

export const STARTER_TARGET_CHARACTERS = 'ABCDE';

export function StarterSamplePanel({ disabled = false, onLoadSample }: { disabled?: boolean; onLoadSample: () => void }) {
  return (
    <section className="contents" aria-label="Starter project onboarding">
      <button type="button" className="secondary-button h-10" onClick={onLoadSample} disabled={disabled}>Load ABCDE sample</button>
    </section>
  );
}
