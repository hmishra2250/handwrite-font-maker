import { NextResponse } from 'next/server';
import { applyAuthCookies, currentSession, noStoreResponse } from '@/lib/server-auth';

export async function GET(request: Request) {
  const auth = await currentSession(request);
  if (!auth.ok) {
    return auth.response;
  }
  const response = NextResponse.json({ authenticated: true, mode: auth.auth.mode, user: auth.auth.user });
  return noStoreResponse(applyAuthCookies(response, auth.auth));
}
