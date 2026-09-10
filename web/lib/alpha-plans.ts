export const ALPHA_LIMITS = {
  dailyUploads: 150,
  dailyUploadBytes: 200 * 1024 * 1024,
  dailyPreviews: 120,
  dailyBuilds: 5,
  activeJobs: 2,
} as const;

export const ALPHA_RETENTION = {
  projectDays: 7,
  downloadHours: 24,
} as const;

export const BILLING_CATALOG = {
  currency: 'USD',
  billingEnabled: false,
  offers: [
    { id: 'single', name: 'Make one font', priceCents: 1200, projects: 1 },
    { id: 'three_pack', name: 'Make three fonts', priceCents: 2900, projects: 3 },
  ],
  alpha: { name: 'Private alpha', priceCents: 0, inviteOnly: true },
  notice: 'Private alpha is free for invited accounts. Paid offers are planned, not available to purchase. No card is collected.',
} as const;

export type BillingOfferId = (typeof BILLING_CATALOG.offers)[number]['id'];

export function isBillingOfferId(value: unknown): value is BillingOfferId {
  return value === 'single' || value === 'three_pack';
}

export function accountPayload(user: { id: string; email?: string | null }) {
  return {
    user: { id: user.id, email: user.email ?? null },
    plan: { id: 'private_alpha', name: 'Private alpha', billingEnabled: false },
    limits: ALPHA_LIMITS,
    retention: ALPHA_RETENTION,
  };
}
