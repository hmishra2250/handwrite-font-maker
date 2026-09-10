import { createClient, type Session, type User } from '@supabase/supabase-js';
import { NextResponse } from 'next/server';

export type DeploymentMode = 'local' | 'invite_beta' | 'production';
export type RuntimeDeploymentMode = DeploymentMode | 'invalid';

export const ACCESS_COOKIE = '__Host-hfm-access';
export const REFRESH_COOKIE = '__Host-hfm-refresh';

export interface ProtectedDeploymentConfig {
  mode: Exclude<DeploymentMode, 'local'>;
  supabaseUrl: string;
  supabaseAnonKey: string;
  internalApiKey: string;
  workerApiBaseUrl: string;
  siteOrigin: string;
}

export interface AuthenticatedRequest {
  mode: DeploymentMode;
  protected: boolean;
  user: Pick<User, 'id' | 'email'> | null;
  accessToken: string | null;
  config: ProtectedDeploymentConfig | null;
  refreshedSession?: Session;
  clearSession?: boolean;
}

export type AuthResult = { ok: true; auth: AuthenticatedRequest } | { ok: false; response: NextResponse };

const REFRESH_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;


function configuredDeploymentMode(): DeploymentMode | 'invalid' {
  const value = process.env.DEPLOYMENT_MODE;
  if (!value) {
    const protectedEnvPresent = Boolean(process.env.SUPABASE_URL || process.env.SUPABASE_ANON_KEY || process.env.INTERNAL_API_KEY || process.env.SITE_URL);
    return protectedEnvPresent ? 'invalid' : 'local';
  }
  if (value === 'local' || value === 'invite_beta' || value === 'production') return value;
  return 'invalid';
}

export function deploymentMode(): RuntimeDeploymentMode {
  return configuredDeploymentMode();
}

export function isProtectedDeployment() {
  return configuredDeploymentMode() !== 'local';
}

export function noStoreResponse<T extends NextResponse>(response: T): T {
  response.headers.set('cache-control', 'no-store');
  return response;
}

function publicError(status: number, code: string, message: string) {
  return noStoreResponse(NextResponse.json({ error: { code, message } }, { status }));
}

function isLocalhost(hostname: string) {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';
}

export function protectedDeploymentConfig(): { ok: true; config: ProtectedDeploymentConfig } | { ok: false; response: NextResponse } {
  const mode = configuredDeploymentMode();
  if (mode === 'invalid') {
    return { ok: false, response: publicError(500, 'INTERNAL_ERROR', 'Invite beta authentication is not configured.') };
  }
  if (mode === 'local') {
    return { ok: false, response: publicError(500, 'INTERNAL_ERROR', 'Protected deployment configuration was requested in local mode.') };
  }
  const supabaseUrl = process.env.SUPABASE_URL;
  const supabaseAnonKey = process.env.SUPABASE_ANON_KEY;
  const internalApiKey = process.env.INTERNAL_API_KEY;
  const workerApiBaseUrl = process.env.WORKER_API_BASE_URL;
  const siteUrl = process.env.SITE_URL;
  let siteOrigin = '';
  try {
    if (siteUrl) {
      const parsed = new URL(siteUrl);
      if (parsed.username || parsed.password) throw new Error('SITE_URL must not include credentials.');
      if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && isLocalhost(parsed.hostname))) throw new Error('SITE_URL must be https.');
      siteOrigin = parsed.origin;
    }
    if (workerApiBaseUrl) {
      const parsed = new URL(workerApiBaseUrl);
      if (parsed.username || parsed.password) throw new Error('WORKER_API_BASE_URL must not include credentials.');
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') throw new Error('WORKER_API_BASE_URL must be http(s).');
    }
    if (supabaseUrl) {
      const parsed = new URL(supabaseUrl);
      if (parsed.username || parsed.password) throw new Error('SUPABASE_URL must not include credentials.');
      if (parsed.protocol !== 'https:') throw new Error('SUPABASE_URL must be https.');
    }
  } catch {
    return { ok: false, response: publicError(500, 'INTERNAL_ERROR', 'Invite beta authentication is not configured.') };
  }
  if (!supabaseUrl || !supabaseAnonKey || !workerApiBaseUrl || !siteOrigin || !internalApiKey || internalApiKey.length < 32) {
    return { ok: false, response: publicError(500, 'INTERNAL_ERROR', 'Invite beta authentication is not configured.') };
  }
  return { ok: true, config: { mode, supabaseUrl, supabaseAnonKey, internalApiKey, workerApiBaseUrl, siteOrigin } };
}

export function readSessionCookie(request: Request, name: string) {
  const header = request.headers.get('cookie') ?? '';
  for (const part of header.split(';')) {
    const [rawName, ...rawValue] = part.trim().split('=');
    if (rawName !== name) continue;
    try {
      return decodeURIComponent(rawValue.join('='));
    } catch {
      return '';
    }
  }
  return '';
}


function hasInviteAccess(config: ProtectedDeploymentConfig, user: User) {
  if (config.mode !== 'invite_beta') return true;
  return user.app_metadata?.handwrite_beta === true;
}

function inviteRequiredError() {
  return publicError(403, 'AUTH_INVITE_REQUIRED', 'Invite beta access is required.');
}

function supabaseFor(config: ProtectedDeploymentConfig) {
  return createClient(config.supabaseUrl, config.supabaseAnonKey, {
    auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
  });
}

export function enforceMutationOrigin(request: Request): NextResponse | null {
  if (!isProtectedDeployment()) return null;
  const configResult = protectedDeploymentConfig();
  if (!configResult.ok) return configResult.response;
  const origin = request.headers.get('origin');
  if (origin !== configResult.config.siteOrigin) {
    return publicError(403, 'AUTH_ORIGIN_INVALID', 'Request origin is not allowed.');
  }
  return null;
}

function cookieOptions(maxAge: number) {
  return { httpOnly: true, secure: true, sameSite: 'lax' as const, path: '/', maxAge };
}

export function setSessionCookies(response: NextResponse, session: Pick<Session, 'access_token' | 'refresh_token' | 'expires_in'>) {
  response.cookies.set(ACCESS_COOKIE, session.access_token, cookieOptions(Math.max(60, Math.min(session.expires_in ?? 3600, 3600))));
  response.cookies.set(REFRESH_COOKIE, session.refresh_token, cookieOptions(REFRESH_MAX_AGE_SECONDS));
}

export function clearSessionCookies(response: NextResponse) {
  response.cookies.set(ACCESS_COOKIE, '', cookieOptions(0));
  response.cookies.set(REFRESH_COOKIE, '', cookieOptions(0));
}

export function applyAuthCookies(response: NextResponse, auth: AuthenticatedRequest) {
  if (auth.refreshedSession) setSessionCookies(response, auth.refreshedSession);
  if (auth.clearSession) clearSessionCookies(response);
  return noStoreResponse(response);
}

export async function requireAuthenticatedRequest(request: Request): Promise<AuthResult> {
  const mode = deploymentMode();
  if (mode === 'local') {
    return { ok: true, auth: { mode, protected: false, user: null, accessToken: null, config: null } };
  }
  const configResult = protectedDeploymentConfig();
  if (!configResult.ok) return configResult;
  const { config } = configResult;
  const accessToken = readSessionCookie(request, ACCESS_COOKIE);
  const refreshToken = readSessionCookie(request, REFRESH_COOKIE);
  const supabase = supabaseFor(config);

  try {
    if (accessToken) {
      const { data, error } = await supabase.auth.getUser(accessToken);
      if (!error && data.user) {
        if (!hasInviteAccess(config, data.user)) return { ok: false, response: inviteRequiredError() };
        return { ok: true, auth: { mode: config.mode, protected: true, user: { id: data.user.id, email: data.user.email }, accessToken, config } };
      }
    }

    if (refreshToken) {
      const { data } = await supabase.auth.refreshSession({ refresh_token: refreshToken });
      const session = data.session;
      if (session?.access_token && session.refresh_token) {
        const verified = await supabase.auth.getUser(session.access_token);
        if (!verified.error && verified.data.user) {
          if (!hasInviteAccess(config, verified.data.user)) return { ok: false, response: inviteRequiredError() };
          return {
            ok: true,
            auth: {
              mode: config.mode,
              protected: true,
              user: { id: verified.data.user.id, email: verified.data.user.email },
              accessToken: session.access_token,
              config,
              refreshedSession: session,
            },
          };
        }
      }
    }
  } catch {
    return { ok: false, response: publicError(503, 'AUTH_PROVIDER_UNAVAILABLE', 'Authentication is temporarily unavailable. Try again.') };
  }

  const response = publicError(401, 'AUTH_REQUIRED', 'Sign in to continue.');
  clearSessionCookies(response);
  return { ok: false, response };
}

export async function currentSession(request: Request): Promise<AuthResult> {
  const mode = deploymentMode();
  if (mode === 'local') {
    return { ok: true, auth: { mode, protected: false, user: null, accessToken: null, config: null } };
  }
  return requireAuthenticatedRequest(request);
}

export function authenticatedWorkerHeaders(auth: AuthenticatedRequest, headers: HeadersInit = {}): HeadersInit {
  if (!auth.protected || !auth.config || !auth.accessToken) return headers;
  return {
    ...headers,
    authorization: `Bearer ${auth.accessToken}`,
    'x-internal-api-key': auth.config.internalApiKey,
  };
}

export function protectedWorkerBaseUrl(auth: AuthenticatedRequest) {
  return auth.protected ? auth.config?.workerApiBaseUrl ?? '' : process.env.WORKER_API_BASE_URL ?? '';
}

export function sanitizeProtectedWorkerError(auth: AuthenticatedRequest, payload: unknown, fallbackMessage: string) {
  if (!auth.protected) return payload;
  const code = typeof (payload as { error?: { code?: unknown } })?.error?.code === 'string'
    ? (payload as { error: { code: string } }).error.code
    : 'INTERNAL_ERROR';
  return { error: { code, message: fallbackMessage } };
}
