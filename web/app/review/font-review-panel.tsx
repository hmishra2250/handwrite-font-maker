'use client';

export interface ReviewGlyph {
  char: string;
  accepted: boolean;
  baseline?: number;
  scale?: number;
  spacing?: number;
  foregroundRatio?: number;
  url?: string;
}

function glyphWarnings(glyph: ReviewGlyph) {
  const warnings: string[] = [];
  if (!glyph.accepted) warnings.push('Missing capture.');
  if (glyph.accepted && (glyph.foregroundRatio ?? 0) < 0.01) warnings.push('Very light mask; try a darker capture or lower threshold.');
  if (glyph.accepted && (glyph.foregroundRatio ?? 0) > 0.85) warnings.push('Mask is very full; erase background pixels before rebuild.');
  if (glyph.accepted && (glyph.baseline ?? 0.8) < 0.2) warnings.push('Baseline is high; lower it if the glyph floats.');
  if (glyph.accepted && (glyph.baseline ?? 0.8) > 0.92) warnings.push('Baseline is low; raise it if descenders clip.');
  return warnings;
}

export function FontReviewPanel({ glyphs, selectedChar, onSelect, onMetricsChange }: {
  glyphs: ReviewGlyph[];
  selectedChar: string;
  onSelect: (char: string) => void;
  onMetricsChange: (char: string, metrics: { baseline?: number; scale?: number; spacing?: number }) => void;
}) {
  const selected = glyphs.find((glyph) => glyph.char === selectedChar) ?? glyphs[0];
  const warnings = selected ? glyphWarnings(selected) : [];
  const accepted = glyphs.filter((glyph) => glyph.accepted).length;
  return (
    <section className="grid min-w-0 gap-4 rounded-xl border border-border bg-bg p-4" aria-label="Whole font review">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <strong className="text-sm">Whole font review</strong>
          <p className="mt-1 text-xs text-text-tertiary">Review every target glyph before rebuilding. Baseline, scale, and spacing edits are applied by the backend on the next build.</p>
        </div>
        <span className="text-xs text-text-tertiary">{accepted} of {glyphs.length} ready</span>
      </div>
      <div className="grid grid-cols-5 gap-1 sm:grid-cols-10" aria-label="Review target glyphs">
        {glyphs.map((glyph) => {
          const selectedGlyph = glyph.char === selectedChar;
          return (
            <button
              key={glyph.char}
              type="button"
              onClick={() => onSelect(glyph.char)}
              className={`grid min-h-11 place-items-center rounded-md border text-sm font-semibold ${selectedGlyph ? 'border-accent bg-accent text-white' : glyph.accepted ? 'border-green bg-green-muted text-green' : 'border-border bg-surface text-text-secondary'}`}
              aria-label={`${glyph.char} ${glyph.accepted ? 'accepted' : 'missing'} review`}
            >
              {glyph.url ? <img src={glyph.url} alt="" className="max-h-8 max-w-8 object-contain" /> : glyph.char}
            </button>
          );
        })}
      </div>
      {selected && (
        <div className="grid min-w-0 gap-3 rounded-lg border border-border bg-surface p-3">
          <div className="flex items-center justify-between gap-2">
            <strong className="text-sm">Selected glyph {selected.char}</strong>
            <span className="text-xs text-text-tertiary">{selected.accepted ? 'Accepted mask' : 'Missing capture'}</span>
          </div>
          <label className="grid min-w-0 gap-1 text-xs font-semibold text-text-secondary">
            Baseline from top: {(selected.baseline ?? 0.8).toFixed(2)}
            <input type="range" min="0.05" max="0.95" step="0.01" value={selected.baseline ?? 0.8} onChange={(event) => onMetricsChange(selected.char, { baseline: Number(event.target.value) })} />
          </label>
          <label className="grid min-w-0 gap-1 text-xs font-semibold text-text-secondary">
            Scale: {(selected.scale ?? 1).toFixed(2)}
            <input type="range" min="0.5" max="1.5" step="0.01" value={selected.scale ?? 1} onChange={(event) => onMetricsChange(selected.char, { scale: Number(event.target.value) })} />
          </label>
          <label className="grid min-w-0 gap-1 text-xs font-semibold text-text-secondary">
            Spacing: {(selected.spacing ?? 0).toFixed(2)} em
            <input type="range" min="-0.05" max="0.25" step="0.01" value={selected.spacing ?? 0} onChange={(event) => onMetricsChange(selected.char, { spacing: Number(event.target.value) })} />
          </label>
          {warnings.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-muted px-3 py-2 text-xs text-[#92400e]" role="status">
              <strong>Actionable quality warning{warnings.length > 1 ? 's' : ''}:</strong>
              <ul className="mt-1 list-disc pl-4">{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
            </div>
          )}
          <p className="text-xs text-text-tertiary">Metric edits mark the project for rebuild; they do not change existing downloads until you build again.</p>
        </div>
      )}
    </section>
  );
}
