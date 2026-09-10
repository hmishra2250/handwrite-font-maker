// Real local persistence of unbuilt markerless/legacy sheets, including reload.
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('../web/node_modules/playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ baseURL: 'http://127.0.0.1:3011' });
  const projects = [];
  try {
    for (const mode of ['markerless', 'legacy']) {
      await page.goto('/', { waitUntil: 'networkidle' });
      const createdResponse = page.waitForResponse(r => r.url().endsWith('/api/projects') && r.request().method() === 'POST');
      await page.getByRole('button', { name: 'New project', exact: true }).click();
      const project = await (await createdResponse).json(); projects.push(project.id);
      await page.waitForFunction(id => Array.from(document.querySelectorAll('select')).some(el => el.value === id), project.id);
      await page.getByRole('tab', { name: mode === 'markerless' ? /Markerless A4 sheet/ : /Legacy marker sheet/ }).click();
      await page.locator('input[type=file]:not([capture])').setInputFiles(path.resolve(`web/public/${mode === 'markerless' ? 'template-markerless.png' : 'template-v1-preview.png'}`));
      if (mode === 'markerless') await page.getByRole('button', { name: 'Confirm page corners', exact: true }).click();
      let saved;
      for (let i = 0; i < 80; i++) {
        saved = await page.request.get(`/api/projects/${project.id}`).then(r => r.json());
        if (saved.mode === mode && saved.sheet?.inputPhoto && (mode !== 'markerless' || saved.sheet.cornersConfirmed)) break;
        await page.waitForTimeout(250);
      }
      assert.equal(saved.mode, mode); assert.ok(saved.sheet?.inputPhoto); assert.equal(saved.glyphs.length, 0);
      await page.reload({ waitUntil: 'networkidle' });
      await page.getByRole('combobox', { name: /^Open saved project/ }).selectOption(project.id);
      const preview = page.getByAltText(mode === 'markerless' ? 'Captured markerless A4 sheet preview' : 'Captured template preview', { exact: true });
      await preview.waitFor();
      await preview.evaluate(img => img.decode());
      assert.ok(await preview.evaluate(img => img.complete && img.naturalWidth > 0), 'Restored sheet must decode');
      const build = page.getByRole('button', { name: mode === 'markerless' ? 'Build markerless sheet font' : 'Build legacy marker font', exact: true });
      assert.ok(await build.isEnabled(), 'Restored sheet must be ready to build without reupload');
      console.log(JSON.stringify({ mode, savedWithoutBuild: true, restoredPreview: true, buildEnabled: true }));
    }
  } finally {
    for (const id of projects) await page.request.delete(`/api/projects/${id}`, { headers: { origin: 'http://127.0.0.1:3011' } }).catch(() => {});
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
