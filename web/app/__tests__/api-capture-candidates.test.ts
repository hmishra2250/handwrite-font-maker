import { beforeEach, describe, expect, it, vi } from 'vitest';

const body = { inputPhoto: { objectKey:'jobs/test/input/a.jpg',contentType:'image/jpeg',sizeBytes:100 }, rectangle:[.1,.1,.9,.9],stage:'ink' };
const pngDataUrl = `data:image/png;base64,${Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0]).toString('base64')}`;
const svgDataUrl = `data:image/svg+xml;base64,${Buffer.from('<?xml version="1.0" standalone="no"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 20010904//EN" "http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd"><svg xmlns="http://www.w3.org/2000/svg"><metadata>Created by potrace</metadata><g transform="translate(0,1) scale(0.01,-0.01)" fill="#000000" stroke="none"><path d="M0 0h100v100z"/></g></svg>').toString('base64')}`;
const rasterSvgDataUrl = `data:image/svg+xml;base64,${Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,AAAA"/></svg>').toString('base64')}`;
const candidate = { id:'clean', label:'Clean letter', maskDataUrl:pngDataUrl, svgDataUrl, width:32,height:32,method:'threshold-clean',warnings:[] };
async function call(value:unknown=body) {
  const { POST } = await import('../api/capture/candidates/route');
  return POST(new Request('http://localhost:3000/api/capture/candidates',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(value)}));
}
describe('automatic candidates API',()=>{
  beforeEach(()=>{ vi.resetModules();vi.unstubAllEnvs();vi.restoreAllMocks(); });
  it('rejects malformed input before upstream work',async()=>{
    const fetch=vi.spyOn(globalThis,'fetch');
    expect((await call({...body,stage:'anything'})).status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });
  it('does not fake options without a worker',async()=>{expect((await call()).status).toBe(503);});
  it('returns true candidate payload and forwards bounded request',async()=>{
    vi.stubEnv('WORKER_API_BASE_URL','http://api:8000');
    const fetch=vi.spyOn(globalThis,'fetch').mockResolvedValue(Response.json({candidates:[candidate],failures:[],stage:'ink'}));
    const response=await call();expect(response.status).toBe(200);expect((await response.json()).candidates[0]).toEqual(candidate);
    expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual(body);
    expect(fetch.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
  });
  it('accepts real backend-style Potrace SVGs with null polarity and normalized mask dimensions',async()=>{
    vi.stubEnv('WORKER_API_BASE_URL','http://api:8000');
    vi.spyOn(globalThis,'fetch').mockResolvedValue(Response.json({candidates:[{...candidate,width:1280,height:1463,polarity:null}],failures:[],stage:'objects'}));
    const response=await call({...body,stage:'objects'});expect(response.status).toBe(200);
    expect((await response.json()).candidates[0]).toEqual({...candidate,width:1280,height:1463});
  });
  it('rejects a raster masquerading as vector',async()=>{
    vi.stubEnv('WORKER_API_BASE_URL','http://api:8000');
    vi.spyOn(globalThis,'fetch').mockResolvedValue(Response.json({candidates:[{...candidate,svgDataUrl:candidate.maskDataUrl}],failures:[],stage:'ink'}));
    expect((await call()).status).toBe(502);
  });
  it('rejects SVGs that embed raster images',async()=>{
    vi.stubEnv('WORKER_API_BASE_URL','http://api:8000');
    vi.spyOn(globalThis,'fetch').mockResolvedValue(Response.json({candidates:[{...candidate,svgDataUrl:rasterSvgDataUrl}],failures:[],stage:'ink'}));
    expect((await call()).status).toBe(502);
  });
  it('reports malformed upstream payloads as invalid extraction data, not timeouts',async()=>{
    vi.stubEnv('WORKER_API_BASE_URL','http://api:8000');
    vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('<html>bad gateway</html>',{status:200,headers:{'content-type':'text/html'}}));
    const response=await call();expect(response.status).toBe(502);expect((await response.json()).error.code).toBe('CAPTURE_CONFIG_INVALID');
  });
  it('reports non-timeout network failures separately from processing timeouts',async()=>{
    vi.stubEnv('WORKER_API_BASE_URL','http://api:8000');
    vi.spyOn(globalThis,'fetch').mockRejectedValue(new TypeError('connection reset'));
    const response=await call();expect(response.status).toBe(502);expect((await response.json()).error.code).toBe('CAPTURE_UPSTREAM_UNAVAILABLE');
  });
  it('gives recoverable timeout instead of unbounded processing',async()=>{
    vi.stubEnv('WORKER_API_BASE_URL','http://api:8000');
    vi.spyOn(globalThis,'fetch').mockRejectedValue(new DOMException('timeout','TimeoutError'));
    const response=await call();expect(response.status).toBe(504);expect((await response.json()).error.code).toBe('CAPTURE_TIMEOUT');
  });
});
