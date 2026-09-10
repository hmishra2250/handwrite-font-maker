import { expect, it, vi } from 'vitest';
import { readBoundedJson } from '@/lib/read-json';

it('parses bounded valid UTF-8 JSON and rejects malformed or oversized actual bytes', async () => {
  expect(await readBoundedJson(new Request('http://local', { method: 'POST', body: '{"glyph":"é"}' }))).toEqual({ glyph: 'é' });
  expect(await readBoundedJson(new Request('http://local', { method: 'POST', body: '{nope' }))).toBeNull();
  expect(await readBoundedJson(new Request('http://local', { method: 'POST', headers: { 'content-length': '1' }, body: '"' + 'x'.repeat(100) + '"' }), 20)).toBeNull();
});

it('cancels an oversized stream before buffering the rest', async () => {
  const cancel = vi.fn();
  const stream = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(100)); }, cancel });
  const request = new Request('http://local', { method: 'POST', body: stream, duplex: 'half' } as RequestInit);
  expect(await readBoundedJson(request, 10)).toBeNull();
  expect(cancel).toHaveBeenCalled();
});
