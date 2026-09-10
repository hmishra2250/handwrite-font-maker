// Real local project -> reload -> metric edit -> font package. No API mocks.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('../web/node_modules/playwright');
(async () => {
  const output = path.resolve('output/project-browser-smoke');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ baseURL: process.env.SMOKE_BASE_URL || 'http://127.0.0.1:3011', viewport: { width: 1280, height: 1000 }, acceptDownloads: true });
  const errors = [];
  let uploads = 0;
  const updates = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url().endsWith('/api/uploads') && request.method() === 'POST') uploads++;
    if (request.url().includes('/api/projects/') && request.method() === 'PUT') updates.push(request.postDataJSON());
  });
  try {
    await page.goto(process.env.SMOKE_BASE_URL || 'http://127.0.0.1:3011', { waitUntil: 'networkidle' });
    const createdResponse = page.waitForResponse(r => r.url().endsWith('/api/projects') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'New project', exact: true }).click();
    const created = await createdResponse;
    assert.equal(created.status(), 201, await created.text());
    const project = await created.json();
    await page.getByRole('button', { name: 'Load ABCDE sample', exact: true }).click();
    await page.getByRole('button', { name: 'Build guided font (5 accepted)', exact: true }).waitFor();
    async function waitForProject(predicate) {
      for (let attempt = 0; attempt < 80; attempt++) {
        const response = await page.request.get(`/api/projects/${project.id}`);
        if (response.ok() && predicate(await response.json())) return;
        await page.waitForTimeout(250);
      }
      throw new Error('Project autosave did not reach expected state');
    }
    await waitForProject(p => p.glyphs.length === 5);
    await page.waitForTimeout(2500); // Allow the accepted-mask upload state to settle.
    const initial = await page.request.get(`/api/projects/${project.id}`).then(r => r.json());
    assert.equal(initial.glyphs.length, 5);
    const stableRevision = initial.revision;
    await page.waitForTimeout(2500);
    const settled = await page.request.get(`/api/projects/${project.id}`).then(r => r.json());
    assert.equal(settled.revision, stableRevision, 'Idle project must not autosave indefinitely');
    await page.reload({ waitUntil: 'networkidle' });
    await page.getByRole('combobox', { name: /^Open saved project/ }).selectOption(project.id);
    await page.getByText('5 of 5 ready', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'A accepted review', exact: true }).click();
    await page.getByRole('slider', { name: /^Scale:/ }).fill('1.2');
    await page.getByRole('slider', { name: /^Spacing:/ }).fill('0.1');
    await waitForProject(p => p.glyphs?.some(g => g.char === 'A' && g.scale === 1.2 && g.spacing === 0.1));
    const uploadedBeforeBuild = uploads;
    const jobResponse = page.waitForResponse(r => r.url().endsWith('/api/jobs') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Build guided font (5 accepted)', exact: true }).click();
    const response = await jobResponse;
    assert.ok(response.ok(), await response.text());
    const job = await response.json();
    await page.getByRole('link', { name: /^Download package/ }).waitFor({ timeout: 120_000 });
    assert.equal(uploads, uploadedBeforeBuild, 'Rebuild must reuse persisted masks');
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('link', { name: /^Download package/ }).click();
    const download = await downloadPromise;
    await download.saveAs(path.join(output, 'font-package.zip'));
    const finalJob = await page.request.get(`/api/jobs/${job.jobId}`).then(r => r.json());
    assert.equal(finalJob.status, 'succeeded');
    assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(width <= 390, `Mobile overflow: ${width}`);
    await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true });
    const report = { projectId: project.id, glyphs: 5, initialRevision: stableRevision, uploads, updates: updates.length, jobId: job.jobId, status: finalJob.status, artifacts: finalJob.artifacts.map(a => ({ kind: a.kind, sizeBytes: a.sizeBytes })), mobileWidth: width, errors };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    // Remove only the project created by this canary; preserve other local work.
    await page.request.delete(`/api/projects/${project.id}`, { headers: { origin: new URL(page.url()).origin } });
  } catch (error) {
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
    fs.writeFileSync(path.join(output, 'failure.txt'), await page.locator('body').innerText().catch(() => ''));
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
