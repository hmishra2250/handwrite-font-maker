import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('home page copy', () => {
  it('documents the V1 flow and deployment boundary', () => {
    const source = readFileSync(join(process.cwd(), 'app/page.tsx'), 'utf8');
    expect(source).toContain('Turn a photographed handwriting sheet into a test font.');
    expect(source).toContain('Supabase stores job data and files');
    expect(source).toContain('Render runs the native FontForge/potrace worker');
    expect(source).toContain('/template-v1.pdf');
  });
});
