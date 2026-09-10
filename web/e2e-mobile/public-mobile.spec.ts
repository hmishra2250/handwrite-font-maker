import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';

const credentials = JSON.parse(readFileSync('../.alpha/local-test-login.json', 'utf8')) as { email: string; password: string };

test('public HTTPS mobile: private login, camera frame, real worker font and logout', async ({ page, baseURL }, testInfo) => {
  const origin = baseURL!;
  await page.goto('/mobile');
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Take photo', exact: true })).toHaveCount(0);
  expect((await page.request.get('/api/account')).status()).toBe(401);
  // Authenticate without placing the test password in screenshots or DOM snapshots.
  const login = await page.request.post('/api/auth/login', { headers: { origin }, data: credentials });
  expect(login.ok()).toBe(true);
  try {
    await page.reload();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Capture your font');
    expect(await page.evaluate(() => window.isSecureContext)).toBe(true);
    await expect(page.locator('.studio-sidebar')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Take photo', exact: true })).toBeInViewport({ ratio: 1 });
    const cookie = (await page.context().cookies()).find(value => value.name === '__Host-hfm-access');
    expect(cookie?.secure).toBe(true);
    expect(cookie?.httpOnly).toBe(true);
    expect((await page.request.post('/api/auth/logout', { headers: { origin: 'https://untrusted.example.test' } })).status()).toBe(403);
    await page.getByRole('button', { name: 'Take photo', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Capture photo', exact: true })).toBeEnabled();
    await page.screenshot({ path: testInfo.outputPath('public-phone-camera.png') });
    if (process.env.HFM_E2E_PHOTO) {
      await page.getByRole('button', { name: 'Close camera', exact: true }).click();
      await page.locator('input[type="file"]').first().setInputFiles(process.env.HFM_E2E_PHOTO);
      const picker = page.getByTestId('candidate-picker');
      await expect(picker.getByRole('option', { name: /Clean letter/ })).toBeVisible({ timeout: 45_000 });
      await expect(picker.getByText('Choose the cleanest vector option, then accept it.', { exact: true })).toBeVisible({ timeout: 45_000 });
      await expect(picker.getByText('Extraction returned invalid letter options.', { exact: true })).toHaveCount(0);
      const soft = picker.getByRole('option', { name: /Softer edges/ });
      await soft.click();
      await expect(soft).toHaveAttribute('aria-selected', 'true');
      const preview = soft.locator('img');
      await expect.poll(() => preview.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
      const svg = await picker.getByRole('link', { name: 'Download Softer edges SVG', exact: true }).getAttribute('href');
      const xml = Buffer.from(svg!.split(',')[1], 'base64').toString('utf8');
      expect(xml).toContain('<path');
      expect(xml).not.toMatch(/<image|<script/i);
      expect(xml).toMatch(/[cC]/); // Potrace paths contain Bezier curves, not only line segments.
      const downloadEvent = page.waitForEvent('download');
      await picker.getByRole('link', { name: 'Download Softer edges SVG', exact: true }).click();
      const download = await downloadEvent;
      await download.saveAs(testInfo.outputPath('real-letter.svg'));
      expect(readFileSync(testInfo.outputPath('real-letter.svg'), 'utf8')).toBe(xml);
      await picker.scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath('real-letter-options.png'), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    } else {
    await page.getByRole('button', { name: 'Capture photo', exact: true }).click();
    // Chromium's synthetic camera is green-on-green, not dark ink on paper.
    // Use the real refinement controls to isolate its lighter moving shape.
    await page.locator('summary').filter({ hasText: 'Refinement tools' }).click();
    await page.getByRole('slider', { name: 'Global threshold', exact: true }).fill('120');
    await page.getByRole('checkbox', { name: /Invert foreground/ }).check();
    }
    await expect(page.getByRole('button', { name: 'Accept A', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Accept A', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Build guided font (1 accepted)', exact: true })).toBeEnabled();
    const createdResponse = page.waitForResponse(response => response.url().endsWith('/api/jobs') && response.request().method() === 'POST');
    await page.getByRole('button', { name: /Build guided font/ }).click();
    const created = await createdResponse;
    expect(created.ok()).toBe(true);
    const { jobId } = await created.json() as { jobId: string };
    let result: { status: string; artifacts: { kind: string; url: string }[] } | undefined;
    await expect.poll(async () => {
      const response = await page.request.get(`/api/jobs/${jobId}`);
      expect(response.ok()).toBe(true);
      result = await response.json();
      return result?.status;
    }, { timeout: 120_000, intervals: [1500, 2500] }).toBe('succeeded');
    const ttf = result!.artifacts.find(artifact => artifact.kind === 'ttf');
    expect(ttf).toBeDefined();
    const font = await page.request.get(ttf!.url);
    expect(font.ok()).toBe(true);
    expect((await font.body()).subarray(0, 4).toString('hex')).toBe('00010000');
    await (await import('node:fs/promises')).writeFile(testInfo.outputPath('real-letter.ttf'), await font.body());
  } finally {
    const logout = await page.request.post('/api/auth/logout', { headers: { origin } });
    expect(logout.ok()).toBe(true);
  }
  expect((await page.request.get('/api/account')).status()).toBe(401);
});
