// Actual local UI -> upload -> API detection, with synthetic positive/reject controls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('../web/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'output/page-corner-browser');
fs.mkdirSync(out, { recursive: true });
execFileSync(path.join(root, '.venv/bin/python'), ['-c', `
import importlib.util
from pathlib import Path
from PIL import Image, ImageDraw
spec=importlib.util.spec_from_file_location('quality', 'tests/test_page_detection_quality.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
image, _=m._page_on_desk(); image.save('output/page-corner-browser/page.png')
ellipse=Image.new('RGB',(1000,1300),(70,75,80));ImageDraw.Draw(ellipse).ellipse((210,120,790,1180),fill=(245,245,240));ellipse.save('output/page-corner-browser/ellipse.png')
`], { cwd: root });
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ baseURL: 'http://127.0.0.1:3011' });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto('/', { waitUntil: 'networkidle' });
    await page.getByRole('tab', { name: /Markerless A4 sheet/ }).click();
    const upload = page.locator('input[type=file]:not([capture])');
    const build = page.getByRole('button', { name: 'Build markerless sheet font', exact: true });
    await upload.setInputFiles(path.join(out, 'page.png'));
    let response = page.waitForResponse(r => r.url().endsWith('/api/capture/page'));
    await page.getByRole('button', { name: 'Find corners', exact: true }).click();
    const positive = await response;
    assert.equal(positive.status(), 200);
    const corners = (await positive.json()).corners;
    assert.equal(corners.length, 4);
    await page.getByText('Corner suggestions loaded. Confirm them or adjust TL/TR/BR/BL before building.', { exact: true }).waitFor();
    assert.equal(await build.isEnabled(), false, 'Detection must not auto-confirm');
    await page.getByRole('button', { name: 'Confirm page corners', exact: true }).click();
    assert.equal(await build.isEnabled(), true);
    await page.getByRole('button', { name: 'Remove photo', exact: true }).click();
    await upload.setInputFiles(path.join(out, 'ellipse.png'));
    response = page.waitForResponse(r => r.url().endsWith('/api/capture/page'));
    await page.getByRole('button', { name: 'Find corners', exact: true }).click();
    const rejected = await response;
    assert.ok(!rejected.ok(), 'Ellipse must not be accepted as paper');
    await page.getByText('Automatic detection is unavailable. Use click, keyboard, or numeric corner edits, then confirm.', { exact: true }).waitFor();
    assert.equal(await build.isEnabled(), false);
    assert.equal(await page.getByRole('button', { name: 'Confirm page corners', exact: true }).isEnabled(), true);
    assert.deepEqual(errors, []);
    const report = { scope: 'Synthetic controls, real local API; no font build or real-phone accuracy claim.', positiveStatus: positive.status(), rejectedStatus: rejected.status(), corners, manualConfirmationRequired: true, manualFallbackAvailable: true, errors };
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2)+'\n');
    await page.screenshot({ path: path.join(out, 'rejection.png'), fullPage: true });
    console.log(JSON.stringify(report, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
