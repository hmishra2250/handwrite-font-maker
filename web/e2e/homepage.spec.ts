import { test, expect } from '@playwright/test';

test.describe('Homepage', () => {
  test('renders hero section with correct heading', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h1')).toContainText('Turn your handwriting into an installable font');
  });

  test('has a working template download link', async ({ page }) => {
    await page.goto('/');
    const downloadLink = page.locator('a[download]').first();
    await expect(downloadLink).toHaveAttribute('href', '/template-v1.pdf');
    await expect(downloadLink).toContainText('Download template');
  });

  test('displays all three workflow steps', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Print the template')).toBeVisible();
    await expect(page.getByText('Fill in every cell')).toBeVisible();
    await expect(page.getByText('Photograph and upload')).toBeVisible();
  });

  test('shows the template preview image', async ({ page }) => {
    await page.goto('/');
    const img = page.locator('img[alt*="ArUco corner markers"]');
    await expect(img).toBeVisible();
  });

  test('displays upload limits in facts section', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Max photo')).toBeVisible();
    await expect(page.getByText('15 MB', { exact: true })).toBeVisible();
    await expect(page.getByText('Retention')).toBeVisible();
    await expect(page.getByText('Characters')).toBeVisible();
  });
});

test.describe('Upload Workbench', () => {
  test('renders capture zone with camera and upload buttons', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Take photo')).toBeVisible();
    await expect(page.getByText('Upload file')).toBeVisible();
  });

  test('build font button is disabled without a file', async ({ page }) => {
    await page.goto('/');
    const btn = page.getByRole('button', { name: 'Build font' });
    await expect(btn).toBeDisabled();
  });

  test('shows image preview after file upload', async ({ page }) => {
    await page.goto('/');
    const inputs = page.locator('input[type="file"]:not([capture])');
    await inputs.setInputFiles({
      name: 'template.jpg',
      mimeType: 'image/jpeg',
      buffer: Buffer.from([0xff, 0xd8, 0xff, 0xe0]),
    });
    await expect(page.getByAltText('Captured template preview')).toBeVisible();
  });

  test('can remove a selected file', async ({ page }) => {
    await page.goto('/');
    const inputs = page.locator('input[type="file"]:not([capture])');
    await inputs.setInputFiles({
      name: 'template.jpg',
      mimeType: 'image/jpeg',
      buffer: Buffer.from([0xff, 0xd8, 0xff, 0xe0]),
    });
    await expect(page.getByAltText('Captured template preview')).toBeVisible();
    await page.getByLabel('Remove photo').click();
    await expect(page.getByAltText('Captured template preview')).not.toBeVisible();
    await expect(page.getByText('Take photo')).toBeVisible();
  });

  test('displays font name field defaults', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('input[value="MyHandwrite-Regular"]')).toBeVisible();
    await expect(page.locator('input[value="My Handwrite"]')).toBeVisible();
    await expect(page.locator('input[value="Regular"]')).toBeVisible();
  });

  test('shows ready status by default', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Ready')).toBeVisible();
    await expect(page.getByText('Upload a photographed template to start a font build.')).toBeVisible();
  });

  test('submits and polls for demo job result', async ({ page }) => {
    await page.goto('/');
    const inputs = page.locator('input[type="file"]:not([capture])');
    await inputs.setInputFiles({
      name: 'template.jpg',
      mimeType: 'image/jpeg',
      buffer: Buffer.from([0xff, 0xd8, 0xff, 0xe0]),
    });
    await page.getByRole('button', { name: 'Build font' }).click();
    await expect(page.getByText('Processing')).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Responsive layout', () => {
  test('stacks to single column on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/');
    await expect(page.locator('h1')).toBeVisible();
    await expect(page.getByText('Take photo')).toBeVisible();
  });
});
