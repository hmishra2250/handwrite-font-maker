import { expect, test } from '@playwright/test';

test.use({
    viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true,
    userAgent: 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    permissions: ['camera'],
    launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
});

test.describe('Mobile live capture', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      const evidence = { calls: [] as MediaStreamConstraints[], streams: [] as MediaStream[] };
      Object.assign(window, { cameraEvidence: evidence });
      navigator.mediaDevices.getUserMedia = async (constraints) => {
        evidence.calls.push(constraints ?? {});
        const stream = await original(constraints);
        evidence.streams.push(stream);
        return stream;
      };
    });
  });

  test('requests rear camera only on tap, captures a real video frame, then releases tracks', async ({ page }, testInfo) => {
    await page.goto('/');
    const evidence = () => page.evaluate(() => {
      const data = (window as unknown as { cameraEvidence: { calls: MediaStreamConstraints[]; streams: MediaStream[] } }).cameraEvidence;
      return { calls: data.calls, states: data.streams.flatMap(stream => stream.getTracks().map(track => track.readyState)) };
    });
    await expect(page.getByRole('button', { name: 'Take photo', exact: true })).toBeVisible();
    expect((await evidence()).calls).toHaveLength(0);
    await page.getByRole('button', { name: 'Take photo', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'Phone camera' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Capture photo', exact: true })).toBeEnabled();
    expect((await evidence()).calls[0]).toMatchObject({ audio: false, video: { facingMode: { ideal: 'environment' } } });
    await page.screenshot({ path: testInfo.outputPath('phone-live-camera.png'), fullPage: false });
    await page.getByRole('button', { name: 'Capture photo', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByRole('img', { name: 'Source photo for A', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Accept A', exact: true })).toBeEnabled();
    expect((await evidence()).states.every(state => state === 'ended')).toBe(true);
    await page.getByRole('button', { name: 'Retake', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Capture photo', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Close camera' }).click();
    expect((await evidence()).states.every(state => state === 'ended')).toBe(true);
    await expect(page.getByRole('img', { name: 'Source photo for A', exact: true })).toBeVisible();
  });

  test('denied camera remains recoverable through picker or gallery upload', async ({ page }) => {
    await page.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied for test', 'NotAllowedError'); };
    });
    await page.goto('/');
    await page.getByRole('button', { name: 'Take photo', exact: true }).click();
    await expect(page.getByRole('dialog').getByRole('alert')).toContainText('permission');
    await expect(page.getByRole('button', { name: 'Use phone picker' })).toBeVisible();
    await expect(page.locator('input[capture="environment"]')).toHaveAttribute('accept', 'image/jpeg,image/png,image/webp');
    await page.getByRole('button', { name: 'Close camera' }).click();
    await page.locator('input[type="file"]:not([capture])').setInputFiles({
      name: 'A.png', mimeType: 'image/png',
      buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAYAAACp8Z5+AAAAF0lEQVR4nGNgYGD4DwJwGoUDpBkIqgAAP0sn2RCw+XYAAAAASUVORK5CYII=', 'base64'),
    });
    await expect(page.getByRole('button', { name: 'Accept A', exact: true })).toBeEnabled();
  });
});
