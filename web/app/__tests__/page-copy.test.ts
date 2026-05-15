import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('home page copy', () => {
  it('documents the V1 template workflow', () => {
    const source = readFileSync(join(process.cwd(), 'app/page.tsx'), 'utf8');
    expect(source).toContain('Turn your handwriting into an installable font.');
    expect(source).toContain('ArUco corner markers');
    expect(source).toContain('/template-v1.pdf');
    expect(source).toContain('94 glyph cells');
  });
});
