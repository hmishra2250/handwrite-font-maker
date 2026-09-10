#!/usr/bin/env node
/* eslint-disable no-console */
const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../web/node_modules/typescript');
const { chromium } = require('../web/node_modules/@playwright/test');

const ROOT = path.resolve(__dirname, '..');
const MANIFEST = path.join(ROOT, 'docs/research/handwriting-sources.json');
const OUT_DIR = path.join(ROOT, 'output/detection-panels/ink-mask');
const args = new Map(process.argv.slice(2).map((arg) => {
  const [key, value = 'true'] = arg.replace(/^--/, '').split('=');
  return [key, value];
}));
const MAX_SIDE = Number(args.get('max-side') || 1024);
const LIMIT = args.has('limit') ? Number(args.get('limit')) : null;
if (!Number.isInteger(MAX_SIDE) || MAX_SIDE < 8 || MAX_SIDE > 1024) throw new Error('max-side must be an integer from 8 to 1024.');

function loadInkMask() {
  const source = fs.readFileSync(path.join(ROOT, 'web/lib/ink-mask.ts'), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  const context = vm.createContext({ module, exports: module.exports, Uint8ClampedArray, Float64Array, Error, Number, Math });
  vm.runInContext(compiled, context, { filename: 'ink-mask.js' });
  return module.exports.buildInkMask;
}

function readManifestCandidates() {
  const parsed = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
  if (!Array.isArray(parsed.samples)) throw new Error('A provenance manifest with samples is required.');
  return parsed.samples.map((entry) => {
    if (!entry.local_path || !entry.sha256 || !entry.source_url || !entry.license) throw new Error('Incomplete image provenance.');
    const local = path.resolve(ROOT, entry.local_path);
    const digest = crypto.createHash('sha256').update(fs.readFileSync(local)).digest('hex');
    if (digest !== entry.sha256) throw new Error(`Source hash mismatch: ${entry.sample_id}`);
    return local;
  });
}

function discoverSources() {
  // Never silently include leftover/quarantined/unlicensed files from the cache.
  const sources = Array.from(new Set(readManifestCandidates()));
  return Number.isFinite(LIMIT) && LIMIT > 0 ? sources.slice(0, LIMIT) : sources;
}

function maskImageData(mask, width, height) {
  return { width, height, data: Array.from(mask.data) };
}

function foregroundRatio(mask, width, height) {
  return mask.foreground / (width * height);
}

function diffRatio(a, b, width, height) {
  let differing = 0;
  for (let pixel = 0; pixel < width * height; pixel++) {
    if (a.data[pixel * 4] !== b.data[pixel * 4]) differing++;
  }
  return differing / (width * height);
}

async function decodeImage(page, filePath) {
  const ext = path.extname(filePath).slice(1).toLowerCase().replace('jpg', 'jpeg');
  const dataUrl = `data:image/${ext};base64,${fs.readFileSync(filePath).toString('base64')}`;
  return await page.evaluate(async ({ dataUrl, maxSide }) => {
    const image = new Image();
    image.src = dataUrl;
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new Error('Could not decode source image.'));
    });
    const scale = Math.min(1, maxSide / Math.max(image.naturalWidth, image.naturalHeight));
    const width = Math.max(1, Math.round(image.naturalWidth * scale));
    const height = Math.max(1, Math.round(image.naturalHeight * scale));
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(image, 0, 0, width, height);
    const imageData = ctx.getImageData(0, 0, width, height);
    return { width, height, source: Array.from(imageData.data), sourceDataUrl: canvas.toDataURL('image/png') };
  }, { dataUrl, maxSide: MAX_SIDE });
}

async function renderPanel(page, panel) {
  return await page.evaluate(async ({ sourceDataUrl, globalMask, adaptiveMask, diagnostics }) => {
    const gap = 18;
    const labelHeight = 34;
    const width = globalMask.width;
    const height = globalMask.height;
    const canvas = document.createElement('canvas');
    canvas.width = width * 3 + gap * 2;
    canvas.height = height + labelHeight;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#111827';
    ctx.font = '16px sans-serif';
    const labels = ['source', `global ${diagnostics.globalForegroundRatio.toFixed(3)}`, `adaptive ${diagnostics.adaptiveForegroundRatio.toFixed(3)}`];
    labels.forEach((label, index) => ctx.fillText(label, index * (width + gap), 22));
    const image = new Image();
    image.src = sourceDataUrl;
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new Error('Could not render source panel.'));
    });
    ctx.drawImage(image, 0, labelHeight, width, height);
    const globalData = new ImageData(new Uint8ClampedArray(globalMask.data), width, height);
    const adaptiveData = new ImageData(new Uint8ClampedArray(adaptiveMask.data), width, height);
    ctx.putImageData(globalData, width + gap, labelHeight);
    ctx.putImageData(adaptiveData, (width + gap) * 2, labelHeight);
    return canvas.toDataURL('image/png');
  }, panel);
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const sources = discoverSources();
  if (sources.length === 0) {
    const diagnostics = { noGroundTruth: true, note: 'No docs/research/handwriting-sources.json entries or local output/detection-sources/handwriting images were found.', sources: [] };
    fs.writeFileSync(path.join(OUT_DIR, 'diagnostics.json'), JSON.stringify(diagnostics, null, 2));
    console.log(`No handwriting sources found; wrote ${path.relative(ROOT, path.join(OUT_DIR, 'diagnostics.json'))}.`);
    return;
  }

  const buildInkMask = loadInkMask();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const diagnostics = [];
  try {
    for (const sourcePath of sources) {
      const decoded = await decodeImage(page, sourcePath);
      const source = new Uint8ClampedArray(decoded.source);
      const globalMask = buildInkMask(source, decoded.width, decoded.height, { method: 'global', threshold: 170 });
      const adaptiveMask = buildInkMask(source, decoded.width, decoded.height, { method: 'adaptive' });
      const itemDiagnostics = {
        source: path.relative(ROOT, sourcePath),
        noGroundTruth: true,
        width: decoded.width,
        height: decoded.height,
        globalForegroundRatio: foregroundRatio(globalMask, decoded.width, decoded.height),
        adaptiveForegroundRatio: foregroundRatio(adaptiveMask, decoded.width, decoded.height),
        differingPixelRatio: diffRatio(globalMask, adaptiveMask, decoded.width, decoded.height),
      };
      const basename = path.basename(sourcePath).replace(/\.[^.]+$/, '');
      const panelDataUrl = await renderPanel(page, {
        sourceDataUrl: decoded.sourceDataUrl,
        globalMask: maskImageData(globalMask, decoded.width, decoded.height),
        adaptiveMask: maskImageData(adaptiveMask, decoded.width, decoded.height),
        diagnostics: itemDiagnostics,
      });
      const panelPath = path.join(OUT_DIR, `${basename}-panel.png`);
      fs.writeFileSync(panelPath, Buffer.from(panelDataUrl.split(',')[1], 'base64'));
      diagnostics.push({ ...itemDiagnostics, panel: path.relative(ROOT, panelPath) });
      console.log(`Wrote ${path.relative(ROOT, panelPath)} (no GT; qualitative only).`);
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(OUT_DIR, 'diagnostics.json'), JSON.stringify({ noGroundTruth: true, diagnostics }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
