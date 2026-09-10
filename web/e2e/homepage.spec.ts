import { test, expect } from '@playwright/test';

test.describe('Homepage', () => {
  test('renders hero section with current proposition', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h1')).toContainText('Turn handwriting and handmade shapes into a font you can type with');
  });

  test('has markerless and legacy template download links', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('a[download][href="/template-markerless.pdf"]')).toContainText('Download markerless A4');
    await expect(page.locator('a[download][href="/template-v1.pdf"]')).toContainText('Legacy V1 PDF');
  });

  test('displays all three capture workflow steps', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Capture real shapes')).toBeVisible();
    await expect(page.getByText('Correct before building')).toBeVisible();
    await expect(page.getByText('Proof and download')).toBeVisible();
  });

  test('shows the markerless template preview image', async ({ page }) => {
    await page.goto('/');
    const img = page.locator('img[alt*="markerless default-v1 A4"]');
    await expect(img).toBeVisible();
  });

  test('displays upload limits and alpha output in facts section', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Max upload')).toBeVisible();
    await expect(page.getByText('15 MB', { exact: true })).toBeVisible();
    await expect(page.getByText('Guided labels')).toBeVisible();
    await expect(page.getByText('Alpha output')).toBeVisible();
    await expect(page.getByText('TTF/OTF', { exact: true })).toBeVisible();
  });
});

test.describe('Upload Workbench', () => {
  test('renders guided capture mode with camera and upload buttons', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('tab', { name: /Guided characters/ })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByText('Take photo')).toBeVisible();
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

    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await expect(page.getByRole('button', { name: 'Undo mask edit' })).toBeEnabled();
    const edited = await pixels();
    expect(edited).not.toEqual(original);

    await page.getByRole('button', { name: 'Undo mask edit' }).click();
    await expect(page.getByText('Undid the last brush stroke.')).toBeVisible();
    expect(await pixels()).toEqual(original);

    await page.mouse.click(box.x + box.width / 3, box.y + box.height / 3);
    await page.mouse.click(box.x + (box.width * 2) / 3, box.y + (box.height * 2) / 3);
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
  test('stacks to usable capture on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/');
    await expect(page.locator('h1')).toBeVisible();
    await expect(page.getByRole('tab', { name: /Guided characters/ })).toBeVisible();
  });

  test('keeps primary capture CTA readable on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    const cta = page.getByRole('link', { name: 'Start capture' });
    await expect(cta).toBeVisible();
    await expect(cta).toHaveCSS('color', 'rgb(255, 255, 255)');
  });
});
