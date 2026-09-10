import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

describe('studio information hierarchy', () => {
  it('puts the protected workspace first, without a marketing or pricing wall', () => {
    const page = source('app/page.tsx');
    expect(page).toContain('<SessionGate');
    expect(page).toContain('<UploadWorkbench');
    expect(page).not.toContain('<PricingSection');
    expect(page).not.toContain('const steps');
    expect(page).toContain('studio-feedback');
    const navigation = source('app/studio-chrome.tsx');
    expect(navigation).toContain('/template-markerless.pdf');
    expect(navigation).toContain('/template-v1.pdf');
    expect(navigation).toContain('/help/install-fonts');
    expect(navigation).toContain('/pricing');
  });

  it('has a dedicated authenticated mobile capture route without a separate API surface', () => {
    const mobile = source('app/mobile/page.tsx');
    expect(mobile).toContain('surface="mobile"');
    expect(mobile).toContain('presentation="mobile"');
    expect(mobile).toContain('<UploadWorkbench');
    expect(mobile).not.toContain('FeedbackPanel');
    expect(mobile).not.toContain('PricingSection');
  });

  it('keeps proposed pricing honest on its own page', () => {
    const pricing = source('app/pricing-section.tsx') + source('app/pricing/page.tsx');
    expect(pricing).toContain('Alpha pricing');
    expect(pricing).toContain('Back to capture');
    expect(pricing).toContain('Paid purchases are not available yet');
    expect(pricing).toContain('No card required');
    expect(pricing).not.toContain('PAYMENT_NOT_CONFIGURED');
    expect(pricing).not.toMatch(/WOFF2/i);
  });
});
