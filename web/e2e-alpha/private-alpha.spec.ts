import { test, expect } from '@playwright/test';

const origin = `http://localhost:${process.env.ALPHA_E2E_WEB_PORT ?? 3007}`;
const password = 'e2e-test-password-only-1234';
const mask = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAAAAADmVT4XAAACNUlEQVR4nO1b2ZLCMAyLNPz/L3sfl2Vz+IozTOMHKK0ly0oH0tJA2tng4frtCuAdgnZPwsPBK6DdITgcvALaHYJA4OPdE6+IgIYmsfKtITAnfKssjzwJMdguE5ATdCP/No3nOYDF5+0CsoJO3P+G8SwHoNy3TcBvRC/v6UL1m8UJByRqAT2gUauod0DCZwEdmHGjqHZA3l6dQTtk1iZqHZCPd0/QjJg3iUoHpLPVtgtA8HhYQOu2XTctR0JGSMCoabcFtKVr2kONA7L4vEcAErNcAmYNOy2gJVnbGvY7IMp9uQKwIbP5HOg367KA+lTLyGKvA2LcnyMAJl7sdEAcR+ICYCTGPgfEeSwmAGZm7HJAAkf9AmDlVWNopV21aLWAqizfzQ/scEASMuwCYOM04Wij1LRns4CKHP+tcGQ7IIlZegGw8JmxtNBpW7NYwGVG8D+p1H/N0PKDu4vi2++WI1wB3+0AEkrgmx1ASg1kfA9Icl2dA7BXNfNQR+G56tNhWPLNi6gD4iqrQrHmpwcxB8RZVoNj0W8vIg6Iu6wCyarJB/wOSKDsGsuy2Re8Dkio7BLNuuknfA5IsOwKzzIDBqxcgOLrHxYMrDOgz8s5JGMByJyDhQZ0mTkF5KyAmbKw0oAeN2fpWUuAZjwsNaDDzkly3hqoCRNrDeg8hyjDlNRFYEPS1/9c2eeCqB9sRrIBY8ZXP32DC5L/aHdKMIfmCvAH2+HgFdDuEBwOXgHtDsHh4OMF/ADH01IY+WOn/AAAAABJRU5ErkJggg==', 'base64');

test('private alpha: real login, capture, persisted project, worker font, isolation and logout', async ({ page, browser }, testInfo) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1, name: /A little more/ })).toBeVisible();
  await expect(page.getByRole('tab', { name: /Guided characters/ })).toHaveCount(0);
  expect((await page.request.get('/api/projects')).status()).toBe(401);
  expect((await page.request.post('/api/auth/login', { data: { email: 'alpha@example.test', password }, headers: { origin: 'https://evil.example' } })).status()).toBe(403);
  await page.getByLabel('Email', { exact: true }).fill('alpha@example.test');
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('tab', { name: /Guided characters/ })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('alpha-workspace.png'), fullPage: true });
  const cookies = await page.context().cookies();
  const session = cookies.find(cookie => cookie.name.includes('alpha'));
  expect(session).toBeDefined();
  expect(session?.httpOnly).toBe(true);
  expect(await page.evaluate(() => document.cookie)).not.toContain(session!.value);
  expect(JSON.stringify(await (await page.request.get('/api/auth/session')).json())).not.toContain(session!.value);
  const account = await (await page.request.get('/api/account')).json();
  expect(account.plan.billingEnabled).toBe(false);
  const deniedCheckout = await page.request.post('/api/billing/checkout', { data: { offerId: 'single' }, headers: { origin } });
  expect(deniedCheckout.status()).toBe(503);
  expect((await deniedCheckout.json()).error.code).toBe('PAYMENT_NOT_CONFIGURED');

  // Exercise the current automatic SVG candidate UX and protected upload/build path.
  await page.locator('input[type="file"]:not([capture])').setInputFiles({ name: 'A.png', mimeType: 'image/png', buffer: mask });
  const picker = page.getByTestId('candidate-picker');
  await expect(picker).toBeVisible({ timeout: 60_000 });
  await expect(picker.getByRole('listbox', { name: 'Extracted vector candidates' })).toBeVisible();
  const firstCandidate = picker.getByRole('option').first();
  await expect(firstCandidate).toBeVisible();
  await expect(firstCandidate.getByRole('img', { name: /vector preview for A/i })).toBeVisible();
  await firstCandidate.click();
  await expect(firstCandidate).toHaveAttribute('aria-selected', 'true');
  await expect(picker.getByRole('link', { name: /Download .* SVG/i }).first()).toHaveAttribute('href', /^data:image\/svg\+xml;base64,/);
  await page.getByRole('button', { name: 'Accept A', exact: true }).click();
  const creation = page.waitForResponse(response => response.url().endsWith('/api/jobs') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Build guided font (1 accepted)', exact: true }).click();
  const createdResponse = await creation;
  expect(createdResponse.ok()).toBe(true);
  const created = await createdResponse.json();
  let job: { status: string; error?: unknown; artifacts: { kind: string; url: string; objectKey: string }[] };
  await expect.poll(async () => {
    const response = await page.request.get(`/api/jobs/${created.jobId}`);
    expect(response.ok()).toBe(true);
    job = await response.json();
    if (job!.status === 'failed') throw new Error(JSON.stringify(job!.error));
    return job!.status;
  }, { timeout: 120_000, intervals: [1000, 2000] }).toBe('succeeded');
  const ttf = job!.artifacts.find(artifact => artifact.kind === 'ttf');
  expect(ttf).toBeDefined();
  const font = await page.request.get(ttf!.url);
  expect(font.ok()).toBe(true);
  expect((await font.body()).subarray(0, 4).toString('hex')).toBe('00010000');

  // Save accepted input through the public contract and prove persistence/ownership.
  const createBody = createdResponse.request().postDataJSON();
  if (process.env.ALPHA_E2E_ML === '1') {
    await test.step('real local EfficientSAM through the authenticated alpha API', async () => {
      const cutout = await page.request.post('/api/capture/foreground', { headers: { origin }, timeout: 120_000, data: {
        inputPhoto: createBody.inputPhoto, rectangle: [0.05, 0.05, 0.95, 0.95], method: 'box-model', style: 'silhouette',
      } });
      expect(cutout.ok(), await cutout.text()).toBe(true);
      const result = await cutout.json();
      expect(result.method).toBe('efficientsam');
      expect(result.modelId).toBeTruthy();
      expect(result.maskDataUrl).toMatch(/^data:image\/png;base64,/);
    });
  }
  const projectResponse = await page.request.post('/api/projects', { headers: { origin }, data: {
    name: 'Alpha real font', font: createBody.font, mode: 'guided', targetCharacters: 'A',
    glyphs: createBody.capture.glyphs.map((glyph: Record<string, unknown>) => ({ ...glyph, width: 128, height: 128, foregroundRatio: 0.2, filename: 'A.png' })), lastJobId: created.jobId,
  } });
  expect(projectResponse.ok()).toBe(true);
  const projectBody = await projectResponse.json();
  const project = projectBody.project ?? projectBody;
  const projectId = project.projectId ?? project.id;
  expect(projectId).toBeTruthy();
  expect((await page.request.get(`/api/projects/${projectId}`)).ok()).toBe(true);
  await page.reload();
  await expect(page.getByRole('tab', { name: /Guided characters/ })).toBeVisible();

  const other = await browser.newContext({ baseURL: origin });
  const login = await other.request.post('/api/auth/login', { headers: { origin }, data: { email: 'other@example.test', password } });
  expect(login.ok()).toBe(true);
  expect((await other.request.get(`/api/projects/${projectId}`)).status()).toBe(404);
  expect((await other.request.get(`/api/jobs/${created.jobId}`)).status()).toBe(404);
  expect((await other.request.get(ttf!.url)).ok()).toBe(false);
  await other.close();

  await page.getByLabel('Account and settings').click();
  await page.getByRole('button', { name: 'Logout', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: /A little more/ })).toBeVisible();
  expect((await page.request.get(ttf!.url)).status()).toBe(401);
  const replay = await page.request.get('/api/account', { headers: { cookie: `${session!.name}=${session!.value}` } });
  expect(replay.status()).toBe(401);
});

test('pricing is public, alpha is free, paid checkout is not misrepresented', async ({ page }, testInfo) => {
  await page.goto('/pricing');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByText('$12', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('$29', { exact: false }).first()).toBeVisible();
  await expect(page.getByText(/not available|not enabled|not open|planned/i).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('alpha-pricing.png'), fullPage: true });
  expect((await page.request.post('/api/billing/checkout', { headers: { origin }, data: { offerId: 'single' } })).status()).toBe(401);
});


test('studio layout: focused login, desktop capture, and phone capture without overflow', async ({ page, browser }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath('studio-login-desktop.png'), fullPage: true });
  await page.getByLabel('Email', { exact: true }).fill('alpha@example.test');
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Create your font');
  await expect(page.getByRole('button', { name: 'Upload file', exact: true })).toBeInViewport({ ratio: 1 });
  await expect(page.locator('.studio-account-menu')).not.toHaveAttribute('open');
  await page.screenshot({ path: testInfo.outputPath('studio-desktop.png'), fullPage: true });
  const phone = await browser.newContext({ baseURL: origin, viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, storageState: await page.context().storageState() });
  const mobilePage = await phone.newPage();
  await mobilePage.goto('/');
  await expect(mobilePage.getByRole('button', { name: 'Take photo', exact: true })).toBeInViewport({ ratio: 1 });
  expect(await mobilePage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await mobilePage.screenshot({ path: testInfo.outputPath('studio-mobile.png'), fullPage: true });
  await mobilePage.getByLabel('Open navigation').click();
  await mobilePage.locator('.studio-mobile-nav').getByRole('link', { name: 'Font studio', exact: true }).click();
  await expect(mobilePage.locator('.studio-mobile-nav')).not.toHaveAttribute('open');
  await mobilePage.getByLabel('Account and settings').click();
  await mobilePage.getByRole('button', { name: 'Logout', exact: true }).click();
  await expect(mobilePage.getByRole('button', { name: 'Sign in', exact: true })).toBeInViewport();
  await mobilePage.screenshot({ path: testInfo.outputPath('studio-login-mobile.png'), fullPage: true });
  await phone.close();
});
