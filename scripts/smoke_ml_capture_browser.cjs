// Actual localhost pretrained cutout -> repair/undo/reset -> accepted mask -> font.
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require('../web/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const boxModel = process.argv.includes('--box-model');
const output = path.join(root, boxModel ? 'output/efficientsam-browser-smoke' : 'output/ml-browser-smoke');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:3011', { waitUntil: 'networkidle' });
  await page.locator('input[type=file]:not([capture])').setInputFiles(path.join(root, 'output/object-api-smoke/source.png'));
  await page.getByRole('radio', { name: /Backend segmentation cutout/ }).check();
  await page.getByRole('radio', { name: boxModel ? /AI box cutout/ : /SlimSAM point cutout/ }).check();
  for (const [side, value] of [['Left', '0.10'], ['Top', '0.05'], ['Right', '0.90'], ['Bottom', '0.90']]) {
    await page.getByRole('spinbutton', { name: `${side} boundary`, exact: true }).fill(value);
  }
  const source = page.getByAltText('Source photo for A');
  async function prompt(x, y) {
    await source.scrollIntoViewIfNeeded();
    const p = await source.evaluate((el, [x, y]) => {
      const r = el.getBoundingClientRect(), scale = Math.min(r.width / el.naturalWidth, r.height / el.naturalHeight);
      return { x: r.left + (r.width - el.naturalWidth * scale) / 2 + x * el.naturalWidth * scale, y: r.top + (r.height - el.naturalHeight * scale) / 2 + y * el.naturalHeight * scale };
    }, [x, y]);
    await page.mouse.click(p.x, p.y);
  }
  if (!boxModel) {
  await prompt(.275, .45);
  await prompt(.18, .14);
  await page.getByRole('radio', { name: 'Exclude background', exact: true }).check();
  await prompt(.5, .5);
  }
  const extraction = page.waitForResponse(r => r.url().endsWith('/api/capture/foreground') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Extract mask', exact: true }).click();
  const response = await extraction;
  const cutout = await response.json();
  if (!response.ok() || cutout.method !== (boxModel ? 'efficientsam' : 'slimsam') || !cutout.modelId) throw new Error(`No real model: ${JSON.stringify(cutout)}`);
  const canvas = page.getByRole('img', { name: 'Editable mask for A', exact: true });
  await canvas.waitFor();
  await page.getByRole('button', { name: 'Reset mask edits', exact: true }).waitFor();
  await page.waitForFunction(() => Array.from(document.querySelectorAll('button')).some(el => el.textContent === 'Reset mask edits' && !el.disabled));
  const original = await canvas.evaluate(el => el.toDataURL());
  const maskPixels = await canvas.evaluate(el => [[195,200], [72,56], [110,180]].map(([x,y]) => el.getContext('2d').getImageData(x,y,1,1).data[0]));
  if (JSON.stringify(maskPixels) !== '[255,0,0]') throw new Error(`Counter/dot/main shape not preserved: ${maskPixels}`);
  async function paint(x, y) {
    await canvas.scrollIntoViewIfNeeded();
    const r = await canvas.boundingBox();
    await page.mouse.click(r.x + x * r.width, r.y + y * r.height);
    await page.waitForTimeout(100);
  }
  await page.getByRole('radio', { name: 'Add black ink', exact: true }).check();
  await paint(.85, .85);
  if (await canvas.evaluate(el => el.toDataURL()) === original) throw new Error('Brush did not change pixels');
  await page.getByRole('button', { name: 'Undo mask edit', exact: true }).click();
  await page.waitForTimeout(100);
  if (await canvas.evaluate(el => el.toDataURL()) !== original) throw new Error('Undo did not restore original pixels');
  await paint(.85, .85);
  await paint(.8, .85);
  await page.getByRole('button', { name: 'Reset mask edits', exact: true }).click();
  await page.waitForTimeout(150);
  if (await canvas.evaluate(el => el.toDataURL()) !== original) throw new Error('Reset did not restore extracted pixels');
  const editorBounds = await canvas.evaluate(el => {
    const r = el.getBoundingClientRect();
    const editor = (el.closest('[data-mask-editor]') || el.parentElement).getBoundingClientRect();
    const editorEl = el.closest('[data-mask-editor]') || el.parentElement;
    const cellEl = editorEl.parentElement;
    const cell = cellEl.getBoundingClientRect();
    const column = cellEl.parentElement.getBoundingClientRect();
    return {canvasRight:r.right,editorRight:editor.right,cellRight:cell.right,columnRight:column.right,canvasWidth:r.width,editorWidth:editor.width,cellWidth:cell.width,documentWidth:document.documentElement.scrollWidth,viewport:window.innerWidth};
  });
  if (editorBounds.editorRight > editorBounds.cellRight + 1 || editorBounds.cellRight > editorBounds.columnRight + 1 || editorBounds.documentWidth > editorBounds.viewport + 1) throw new Error(`Editor overflow: ${JSON.stringify(editorBounds)}`);
  fs.mkdirSync(output, { recursive: true });
  await page.screenshot({ path: path.join(output, 'mask-review.png'), fullPage: true });
  await page.setViewportSize({width:390,height:844});
  const mobileEditorBounds = await page.locator('[data-mask-editor]').evaluate(el => {
    const editor=el.getBoundingClientRect(), frame=el.parentElement.getBoundingClientRect(), column=el.parentElement.parentElement.getBoundingClientRect();
    return {editorRight:editor.right,frameRight:frame.right,columnRight:column.right,documentWidth:document.documentElement.scrollWidth,viewport:window.innerWidth};
  });
  if (mobileEditorBounds.editorRight > mobileEditorBounds.columnRight+1 || mobileEditorBounds.frameRight > mobileEditorBounds.columnRight+1 || mobileEditorBounds.documentWidth > mobileEditorBounds.viewport+1) throw new Error(`Mobile editor overflow: ${JSON.stringify(mobileEditorBounds)}`);
  await page.screenshot({path:path.join(output,'mobile-mask-review.png'),fullPage:true});
  await page.setViewportSize({width:1280,height:1000});
  await page.getByRole('button', { name: 'Accept A', exact: true }).click();
  await page.getByRole('button', { name: /Build guided font/ }).click();
  const link = page.getByRole('link', { name: /TTF/ }).first();
  await link.waitFor({ timeout: 120000 });
  await page.waitForFunction(() => Array.from(document.fonts).some(f => f.family.startsWith('generated-') && f.status === 'loaded'), { timeout: 30000 });
  const font = await page.request.get(await link.evaluate(el => el.href));
  if (!font.ok()) throw new Error('Font download failed');
  fs.mkdirSync(output, { recursive: true });
  await page.screenshot({ path: path.join(output, 'proof.png'), fullPage: true });
  const report = { method: cutout.method, modelId: cutout.modelId, warnings: cutout.warnings, editorBounds, mobileEditorBounds, counterDotMainPreserved: true, brushChangedPixels: true, undoExact: true, resetExact: true, generatedFontLoaded: true, ttfBytes: (await font.body()).length, errors };
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
  if (errors.length) process.exitCode = 1;
})().catch(error => { console.error(error); process.exit(1); });
