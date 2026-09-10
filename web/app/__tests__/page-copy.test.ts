import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('home page copy', () => {
  it('describes the real alpha capture modes without checkout or WOFF2 promises', () => {
    const source = readFileSync(join(process.cwd(), 'app/page.tsx'), 'utf8');
    expect(source).toContain('Turn handwriting and handmade shapes into a font you can type with.');
    expect(source).toContain('Guided characters');
    expect(source).toContain('Markerless A4 sheet');
    expect(source).toContain('Legacy marker sheet');
    expect(source).toContain('/template-markerless.pdf');
    expect(source).toContain('TTF/OTF');
    expect(source).not.toMatch(/checkout|pricing|WOFF2/i);
  });
});
