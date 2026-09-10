import { readBoundedJson } from '@/lib/read-json';
import { createClient } from '@supabase/supabase-js';
import { NextResponse } from 'next/server';
import { deploymentMode, enforceMutationOrigin, noStoreResponse, parsePrivateAlphaLogin, protectedDeploymentConfig, setAlphaAccessCookie, setSessionCookies } from '@/lib/server-auth';
import type { User } from '@supabase/supabase-js';

function hasInviteAccess(mode: string, user: User) {
  return mode !== 'invite_beta' || user.app_metadata?.handwrite_beta === true;
}

function authInvalid(status = 401) {
  return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_INVALID', message: 'Invalid email or password.' } }, { status }));
}

async function loginPrivateAlpha(request: Request) {
  const configResult = protectedDeploymentConfig();
  if (!configResult.ok) return configResult.response;
  const config = configResult.config;
  const body = (await readBoundedJson(request, 4096)) as { email?: unknown; password?: unknown } | null;
  const email = typeof body?.email === 'string' ? body.email.trim() : '';
  const password = typeof body?.password === 'string' ? body.password : '';
  if (!email || !password) {
    return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_INVALID', message: 'Email and password are required.' } }, { status: 400 }));
  }
  try {
    const upstream = await fetch(new URL('/auth/login', config.workerApiBaseUrl), {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-internal-api-key': config.internalApiKey },
      body: JSON.stringify({ email, password }),
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    });
    const payload = await upstream.json().catch(() => null);
    if (!upstream.ok) {
      if (upstream.status === 400) return authInvalid(400);
      if (upstream.status === 401 || upstream.status === 403 || upstream.status === 404) return authInvalid(401);
      return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_PROVIDER_UNAVAILABLE', message: 'Authentication is temporarily unavailable. Try again.' } }, { status: 503 }));
    }
    const parsed = parsePrivateAlphaLogin(payload ?? {});
    if (!parsed) {
      return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_PROVIDER_INVALID', message: 'Authentication returned an invalid session.' } }, { status: 502 }));
    }
    const response = NextResponse.json({ authenticated: true, mode: config.mode, user: parsed.user });
    setAlphaAccessCookie(response, parsed.accessToken, parsed.expiresIn, config);
    return noStoreResponse(response);
  } catch {
    return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_PROVIDER_UNAVAILABLE', message: 'Authentication is temporarily unavailable. Try again.' } }, { status: 503 }));
  }
}

export async function POST(request: Request) {
  const originError = enforceMutationOrigin(request);
  if (originError) return originError;

  const mode = deploymentMode();
  if (mode === 'local') {
    return noStoreResponse(NextResponse.json({ authenticated: true, mode: 'local' }));
  }
  if (mode === 'private_alpha') return loginPrivateAlpha(request);

  const configResult = protectedDeploymentConfig();
  if (!configResult.ok) return configResult.response;
  const body = (await readBoundedJson(request, 4096)) as { email?: unknown; password?: unknown } | null;
  const email = typeof body?.email === 'string' ? body.email.trim() : '';
  const password = typeof body?.password === 'string' ? body.password : '';
  if (!email || !password) {
    return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_INVALID', message: 'Email and password are required.' } }, { status: 400 }));
  }

  const supabase = createClient(configResult.config.supabaseUrl!, configResult.config.supabaseAnonKey!, {
    auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
  });
  try {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error || !data.session?.access_token || !data.session.refresh_token) {
      return authInvalid(401);
    }
    const verified = await supabase.auth.getUser(data.session.access_token);
    if (verified.error || !verified.data.user) {
      return authInvalid(401);
    }
    if (!hasInviteAccess(configResult.config.mode, verified.data.user)) {
      return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_INVITE_REQUIRED', message: 'Invite beta access is required.' } }, { status: 403 }));
    }

    const response = NextResponse.json({ authenticated: true, mode: configResult.config.mode, user: { id: verified.data.user.id, email: verified.data.user.email } });
    setSessionCookies(response, data.session);
    return noStoreResponse(response);
  } catch {
    return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_PROVIDER_UNAVAILABLE', message: 'Authentication is temporarily unavailable. Try again.' } }, { status: 503 }));
  }
}
