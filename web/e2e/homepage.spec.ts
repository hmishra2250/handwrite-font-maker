import { test, expect } from '@playwright/test';

test.describe('Studio workspace', () => {
  test('opens directly into the studio instead of a marketing page', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Create your font');
    await expect(page.getByRole('button', { name: 'Upload file', exact: true })).toBeInViewport({ ratio: 1 });
    await expect(page.locator('#pricing')).toHaveCount(0);
  });

  test('opens usable saved-project controls from the resource navigation', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Saved projects', exact: true }).click();
    await expect(page.getByLabel('Project name', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'New project', exact: true })).toBeVisible();
  });

  test('keeps both printable templates in the resource navigation', async ({ page }) => {
    await page.goto('/');
    await page.locator('.studio-sidebar summary').filter({ hasText: 'Templates' }).click();
    await expect(page.locator('.studio-sidebar a[download][href="/template-markerless.pdf"]')).toBeVisible();
    await expect(page.locator('.studio-sidebar a[download][href="/template-v1.pdf"]')).toBeVisible();
  });

  test('keeps all three capture methods available without repeated explainer cards', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('tab', { name: /Guided characters/ })).toBeVisible();
    await expect(page.getByRole('tab', { name: /Markerless A4 sheet/ })).toBeVisible();
    await expect(page.getByRole('tab', { name: /Legacy marker sheet/ })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Workflow steps' })).toHaveCount(0);
  });

  test('desktop exposes upload without a webcam action', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'Take photo', exact: true })).toHaveCount(0);
    await expect(page.locator('input[type="file"]:not([capture])')).toHaveAttribute('accept', 'image/jpeg,image/png,image/webp');
  });

  test('keeps secondary feedback collapsed by default', async ({ page }) => {
    await page.goto('/');
    const feedback = page.locator('.studio-feedback');
    await expect(feedback).not.toHaveAttribute('open');
    await feedback.locator(':scope > summary').click();
    await expect(page.getByRole('heading', { name: 'Help improve the beta' })).toBeVisible();
  });
});

test.describe('Upload Workbench', () => {
  test('renders guided capture mode with desktop upload', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('tab', { name: /Guided characters/ })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('button', { name: 'Take photo', exact: true })).toHaveCount(0);
    await expect(page.getByText('Upload file')).toBeVisible();
  });

  test('guided build button is disabled without an accepted glyph', async ({ page }) => {
    await page.goto('/');
    const btn = page.getByRole('button', { name: /Build guided font/ });
    await expect(btn).toBeDisabled();
  });

  test('guided mask brush edits undo and reset exact canvas pixels', async ({ page }) => {
    await page.goto('/');
    await page.locator('input[type="file"]:not([capture])').setInputFiles({
      name: 'glyph.png',
      mimeType: 'image/png',
      buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAYAAACp8Z5+AAAAF0lEQVR4nGNgYGD4DwJwGoUDpBkIqgAAP0sn2RCw+XYAAAAASUVORK5CYII=', 'base64'),
    });
    await page.locator('summary').filter({ hasText: 'Advanced correction tools' }).click();
    const canvas = page.getByRole('img', { name: 'Editable mask for A' });
    await expect(canvas).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reset mask edits' })).toBeEnabled();
    await canvas.scrollIntoViewIfNeeded();
    await page.getByLabel(/Brush size/i).fill('2');

    const pixels = () => canvas.evaluate((element) => {
      const c = element as HTMLCanvasElement;
      return Array.from(c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data);
    });
    const original = await pixels();
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    if (!box) throw new Error('Canvas box missing');

    await canvas.click({ position: { x: box.width / 2, y: box.height / 2 } });
    await expect(page.getByRole('button', { name: 'Undo mask edit' })).toBeEnabled();
    const edited = await pixels();
    expect(edited).not.toEqual(original);

    await page.getByRole('button', { name: 'Undo mask edit' }).click();
    await expect(page.getByText('Undid the last brush stroke.')).toBeVisible();
    expect(await pixels()).toEqual(original);

    await canvas.click({ position: { x: box.width / 3, y: box.height / 3 } });
    await canvas.click({ position: { x: (box.width * 2) / 3, y: (box.height * 2) / 3 } });
    expect(await pixels()).not.toEqual(original);
    await page.getByRole('button', { name: 'Reset mask edits' }).click();
    await expect(page.getByText('Reset to the latest extracted mask.')).toBeVisible();
    expect(await pixels()).toEqual(original);
  });

  test('can switch to markerless corner confirmation flow', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('tab', { name: /Markerless A4 sheet/ }).click();
    await expect(page.getByText('Markerless page corners')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Build markerless sheet font' })).toBeDisabled();
  });

  test('shows image preview after markerless file upload and requires confirmation', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('tab', { name: /Markerless A4 sheet/ }).click();
    const input = page.locator('input[type="file"]:not([capture])');
    await input.setInputFiles({ name: 'sheet.jpg', mimeType: 'image/jpeg', buffer: Buffer.from([0xff, 0xd8, 0xff, 0xe0]) });
    await expect(page.getByAltText('Captured markerless A4 sheet preview')).toBeVisible();
    await expect(page.getByText('Required before markerless build.')).toBeVisible();
  });

  test('legacy mode is available for original marker sheets', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('tab', { name: /Legacy marker sheet/ }).click();
    await expect(page.getByText(/original marker-template build path/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Build legacy marker font' })).toBeDisabled();
  });

  test('install help route has OS-specific instructions', async ({ page }) => {
    await page.goto('/help/install-fonts');
    await expect(page.getByRole('heading', { name: /Use a generated TTF\/OTF/ })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Windows' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'macOS' })).toBeVisible();
    await expect(page.getByText(/no one-click browser install/i)).toBeVisible();
  });
});

test.describe('Responsive layout', () => {
  test.use({ hasTouch: true, isMobile: true });
  test('stacks to usable capture on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/');
    await expect(page.locator('h1')).toBeVisible();
    await expect(page.getByRole('tab', { name: /Guided characters/ })).toBeVisible();
  });

  test('keeps the camera above the fold and avoids horizontal overflow on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'Take photo', exact: true })).toBeInViewport({ ratio: 1 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expect(page.locator('.studio-mobile-nav')).toBeVisible();
  });
});
