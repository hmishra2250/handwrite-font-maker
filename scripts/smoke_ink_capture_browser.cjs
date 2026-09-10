// Actual optional local adaptive/alpha extraction -> accepted PNG -> exported TTF.
// The controlled image is synthetic; it is NOT counted as an internet sample.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('../web/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'output/ink-browser-smoke');
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.SMOKE_BASE_URL || 'http://127.0.0.1:3011', { waitUntil: 'networkidle' });
    const source = await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 256;
      const ctx = canvas.getContext('2d');
      // Transparent outer border, smooth shaded paper, thin ring and detached dot.
      const shade = ctx.createLinearGradient(20, 0, 236, 0);
      shade.addColorStop(0, '#777777'); shade.addColorStop(1, '#eeeeee');
      ctx.fillStyle = shade; ctx.fillRect(20, 20, 216, 216);
      ctx.strokeStyle = '#101010'; ctx.lineWidth = 6;
      ctx.beginPath(); ctx.ellipse(130, 145, 55, 62, 0, 0, Math.PI * 2); ctx.stroke();
      ctx.fillStyle = '#101010'; ctx.fillRect(126, 47, 8, 8);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    const png = Buffer.from(source, 'base64');
    fs.writeFileSync(path.join(output, 'controlled-source.png'), png);
    await page.locator('input[type=file]:not([capture])').setInputFiles({ name: 'controlled-alpha-shadow.png', mimeType: 'image/png', buffer: png });
    await page.getByRole('radio', { name: /Adaptive local threshold/ }).check();
    const canvas = page.getByRole('img', { name: 'Editable mask for A', exact: true });
    await canvas.waitFor();
    await page.waitForFunction(() => {
      const c = document.querySelector('canvas[aria-label="Editable mask for A"]');
      return c && c.width === 256 && c.getContext('2d').getImageData(40, 128, 1, 1).data[0] === 255;
    });
    const pixels = await canvas.evaluate(el => [[0,0], [40,128], [130,145], [75,145], [130,50]].map(([x,y]) => el.getContext('2d').getImageData(x,y,1,1).data[0]));
    if (JSON.stringify(pixels) !== '[255,255,255,0,0]') throw new Error(`Alpha/shadow/counter/stroke/dot failed: ${pixels}`);
    const raw = await canvas.evaluate(el => el.toDataURL('image/png').split(',')[1]);
    fs.writeFileSync(path.join(output, 'raw-adaptive-mask.png'), Buffer.from(raw, 'base64'));
    // Adaptive threshold sees the sharp paper boundary as ink. Exercise the
    // actual repair UI rather than accepting this known artifact as a good glyph.
    await page.getByRole('radio', { name: 'Remove to white', exact: true }).check();
    await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox();
    for (const [x0,y0,x1,y1] of [[24,20,24,236], [20,24,236,24], [20,231,236,231]]) {
      await page.mouse.move(box.x+x0*box.width/256, box.y+y0*box.height/256);
      await page.mouse.down();
      await page.mouse.move(box.x+x1*box.width/256, box.y+y1*box.height/256, { steps: 60 });
      await page.mouse.up();
    }
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(el => el.textContent === 'Accept A' && !el.disabled));
    const repairedPixels = await canvas.evaluate(el => [[24,128], [128,24], [128,231], [130,145], [75,145], [130,50]].map(([x,y]) => el.getContext('2d').getImageData(x,y,1,1).data[0]));
    if (JSON.stringify(repairedPixels) !== '[255,255,255,255,0,0]') throw new Error(`Mask repair failed: ${repairedPixels}`);
    const accepted = await canvas.evaluate(el => el.toDataURL('image/png').split(',')[1]);
    fs.writeFileSync(path.join(output, 'accepted-mask.png'), Buffer.from(accepted, 'base64'));
    await page.getByRole('button', { name: 'Accept A', exact: true }).click();
    await page.getByRole('button', { name: /Build guided font/ }).click();
    const link = page.getByRole('link', { name: /TTF/ }).first();
    await link.waitFor({ timeout: 120000 });
    await page.waitForFunction(() => Array.from(document.fonts).some(f => f.family.startsWith('generated-') && f.status === 'loaded'));
    const response = await page.request.get(await link.evaluate(el => el.href));
    if (!response.ok()) throw new Error('Generated font download failed.');
    const font = await response.body(); fs.writeFileSync(path.join(output, 'AdaptiveInk.ttf'), font);
    await page.screenshot({ path: path.join(output, 'proof.png'), fullPage: true });
    const report = { scope: 'Synthetic alpha/shadow/thin-ring/dot end-to-end regression, not real-photo accuracy', method: 'adaptive-local', pixels, scriptedEraserStrokes: 3, repairedPixels, generatedFontLoaded: true, ttfBytes: font.length, errors };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2)+'\n');
    console.log(JSON.stringify(report, null, 2));
    if (errors.length) process.exitCode = 1;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
