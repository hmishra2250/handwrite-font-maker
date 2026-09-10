import { BILLING_CATALOG } from '@/lib/alpha-plans';
import { deploymentMode, noStoreResponse, protectedDeploymentConfig } from '@/lib/server-auth';
import { NextResponse } from 'next/server';

export async function GET() {
  if (deploymentMode() === 'private_alpha') {
    const configResult = protectedDeploymentConfig();
    if (!configResult.ok) return configResult.response;
    try {
      const upstream = await fetch(new URL('/billing/catalog', configResult.config.workerApiBaseUrl), {
        method: 'GET',
        headers: { 'x-internal-api-key': configResult.config.internalApiKey },
        cache: 'no-store',
        signal: AbortSignal.timeout(10_000),
      });
      const payload = await upstream.json().catch(() => null);
      if (!upstream.ok || !payload) {
        return noStoreResponse(NextResponse.json({ error: { code: 'BILLING_UNAVAILABLE', message: 'Pricing is temporarily unavailable.' } }, { status: 503 }));
      }
      return noStoreResponse(NextResponse.json(payload, { status: upstream.status }));
    } catch {
      return noStoreResponse(NextResponse.json({ error: { code: 'BILLING_UNAVAILABLE', message: 'Pricing is temporarily unavailable.' } }, { status: 503 }));
    }
  }
  return noStoreResponse(NextResponse.json(BILLING_CATALOG));
}
