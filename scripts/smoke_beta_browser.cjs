#!/usr/bin/env node
// Production-build browser checks. Provider sessions are mocked only for the UI portion.
const { chromium } = require('../web/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const base = process.env.BETA_PREVIEW_URL || 'http://localhost:3012';
  const output = path.resolve('output/beta-browser');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    await page.getByRole('heading', { name: 'Sign in to capture your font' }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Build font' }).count(), 0);
    assert.equal(await page.locator('meta[name="robots"]').getAttribute('content'), 'noindex, nofollow');
    await page.screenshot({ path: path.join(output, 'login-mobile.png'), fullPage: true });
    const auth = await page.request.get(`${base}/api/auth/session`);
    assert.equal(auth.status(), 401);
    assert.match(auth.headers()['cache-control'], /no-store/);
    const denied = await page.request.post(`${base}/api/uploads`, { headers: { origin: base }, data: { filename: 'x.png', contentType: 'image/png', sizeBytes: 42 } });
    assert.equal(denied.status(), 401);
    const csrf = await page.request.post(`${base}/api/jobs`, { headers: { origin: 'https://attacker.test' }, data: {} });
    assert.equal(csrf.status(), 403);
    const object = await page.request.get(`${base}/api/objects/jobs/private/file.ttf`);
    assert.equal(object.status(), 401);

    // UI contract only. This does not emulate/claim hosted Supabase verification.
    await page.route('**/api/auth/login', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ authenticated: true, user: { email: 'invited@example.test' } }) }));
    await page.getByLabel('Email', { exact: true }).fill('invited@example.test');
    await page.getByLabel('Password', { exact: true }).fill('fixture-password');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.getByRole('button', { name: 'Logout', exact: true }).waitFor();
    assert.ok(await page.getByText('Signed in as invited@example.test.', { exact: false }).count());
    await page.route('**/api/auth/logout', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
    await page.getByRole('button', { name: 'Logout', exact: true }).click();
    await page.getByText('Logout failed. Try again.', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Logout', exact: true }).count(), 1);
    const bounds = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth }));
    assert.ok(bounds.width <= bounds.viewport, JSON.stringify(bounds));
    await page.screenshot({ path: path.join(output, 'authenticated-ui-mobile.png'), fullPage: true });
    await page.unroute('**/api/auth/logout');
    await page.route('**/api/auth/logout', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }));
    await page.getByRole('button', { name: 'Logout', exact: true }).click();
    await page.getByRole('heading', { name: 'Sign in to capture your font' }).waitFor();
    assert.deepEqual(errors, []);
    const report = { realServerChecks: ['runtime beta login gate', 'unauthenticated session/upload/object denied', 'cross-origin mutation denied', 'no-store', 'noindex'], mockedUiChecks: ['login unlocks workbench', 'failed logout retains UI session and shows retry', 'successful logout locks workbench'], bounds, pageErrors: errors, caveat: 'No real hosted Supabase identity/refresh or cloud deployment tested.' };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
