import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

function files(root: string): string[] {
  return readdirSync(root).flatMap((entry) => {
    const path = join(root, entry);
    return statSync(path).isDirectory() ? files(path) : [path];
  }).filter((path) => path.endsWith('.ts'));
}

describe('Vercel route boundary', () => {
  it('does not proxy files or run native build tooling', () => {
    const forbidden = ['child_process', 'spawn(', 'exec(', 'fontforge', 'potrace', 'build_font', 'handwrite_font_maker', 'arrayBuffer', 'ReadableStream'];
    for (const path of files(join(process.cwd(), 'app/api'))) {
      const source = readFileSync(path, 'utf8');
      for (const token of forbidden) {
        expect(source, `${path} contains ${token}`).not.toContain(token);
      }
    }
  });
});
