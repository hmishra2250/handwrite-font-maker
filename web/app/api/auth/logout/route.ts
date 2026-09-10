import { createClient, type Session } from '@supabase/supabase-js';
import { NextResponse } from 'next/server';
import { ACCESS_COOKIE, clearSessionCookies, deploymentMode, enforceMutationOrigin, isLocalHttpAlpha, LOCAL_ALPHA_ACCESS_COOKIE, noStoreResponse, protectedDeploymentConfig, readSessionCookie, REFRESH_COOKIE, setSessionCookies, type ProtectedDeploymentConfig } from '@/lib/server-auth';

type StatusError = { status?: unknown } | null | undefined;
type LogoutSession = Pick<Session, 'access_token' | 'refresh_token' | 'expires_in'>;

function statusOf(error: StatusError) {
  return typeof error?.status === 'number' ? error.status : undefined;
}

function isInvalidSessionStatus(status: number | undefined) {
  return status === 400 || status === 401 || status === 403 || status === 404;
}

function unavailableResponse(session?: LogoutSession) {
  const response = NextResponse.json({ error: { code: 'AUTH_PROVIDER_UNAVAILABLE', message: 'Authentication is temporarily unavailable. Try again.' } }, { status: 503 });
  if (session) setSessionCookies(response, session);
  return noStoreResponse(response);
}

function readAlphaAccess(request: Request, config: ProtectedDeploymentConfig) {
  return readSessionCookie(request, ACCESS_COOKIE) || (isLocalHttpAlpha(config) ? readSessionCookie(request, LOCAL_ALPHA_ACCESS_COOKIE) : '');
}

async function logoutPrivateAlpha(request: Request) {
  const configResult = protectedDeploymentConfig();
  if (!configResult.ok) return configResult.response;
  const accessToken = readAlphaAccess(request, configResult.config);
  if (accessToken) {
    try {
      const upstream = await fetch(new URL('/auth/logout', configResult.config.workerApiBaseUrl), {
        method: 'POST',
        headers: { authorization: `Bearer ${accessToken}`, 'x-internal-api-key': configResult.config.internalApiKey },
        cache: 'no-store',
        signal: AbortSignal.timeout(10_000),
      });
      if (!upstream.ok && !isInvalidSessionStatus(upstream.status)) return unavailableResponse();
    } catch {
      return unavailableResponse();
    }
  }
  const response = NextResponse.json({ ok: true });
  clearSessionCookies(response);
  return noStoreResponse(response);
}

export async function POST(request: Request) {
  const originError = enforceMutationOrigin(request);
  if (originError) return originError;

  const mode = deploymentMode();
  if (mode === 'private_alpha') return logoutPrivateAlpha(request);

  if (mode !== 'local') {
    const configResult = protectedDeploymentConfig();
    if (!configResult.ok) return configResult.response;
    const accessToken = readSessionCookie(request, ACCESS_COOKIE);
    const refreshToken = readSessionCookie(request, REFRESH_COOKIE);
    const supabase = createClient(configResult.config.supabaseUrl!, configResult.config.supabaseAnonKey!, {
      auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
    });

    let refreshedSession: LogoutSession | undefined;

    try {
      let needsRefreshRevocation = !accessToken && Boolean(refreshToken);
      if (accessToken) {
        const { error } = await supabase.auth.admin.signOut(accessToken, 'local');
        const status = statusOf(error);
        if (error && !isInvalidSessionStatus(status)) return unavailableResponse();
        needsRefreshRevocation = Boolean(error && refreshToken);
      }

      if (needsRefreshRevocation && refreshToken) {
        const { data, error } = await supabase.auth.refreshSession({ refresh_token: refreshToken });
        const status = statusOf(error);
        if (error && !isInvalidSessionStatus(status)) return unavailableResponse();
        const session = data?.session;
        if (!session?.access_token || !session.refresh_token) {
          if (!error) return unavailableResponse();
        } else {
          refreshedSession = session;
          const { error: signOutError } = await supabase.auth.admin.signOut(session.access_token, 'local');
          const signOutStatus = statusOf(signOutError);
          if (signOutError && !isInvalidSessionStatus(signOutStatus)) return unavailableResponse(refreshedSession);
        }
      }
    } catch {
      return unavailableResponse(refreshedSession);
    }
  }

  const response = NextResponse.json({ ok: true });
  clearSessionCookies(response);
  return noStoreResponse(response);
}
