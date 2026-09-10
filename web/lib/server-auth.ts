import { createClient, type Session, type User } from '@supabase/supabase-js';
import { NextResponse } from 'next/server';

export type DeploymentMode = 'local' | 'invite_beta' | 'production' | 'private_alpha';
export type RuntimeDeploymentMode = DeploymentMode | 'invalid';

export const ACCESS_COOKIE = '__Host-hfm-access';
export const REFRESH_COOKIE = '__Host-hfm-refresh';
export const LOCAL_ALPHA_ACCESS_COOKIE = 'hfm-alpha-access';

export interface AuthenticatedUser {
  id: string;
  email?: string | null;
}

export interface ProtectedDeploymentConfig {
  mode: Exclude<DeploymentMode, 'local'>;
  supabaseUrl?: string;
  supabaseAnonKey?: string;
  internalApiKey: string;
  workerApiBaseUrl: string;
  siteOrigin: string;
}

export interface AuthenticatedRequest {
  mode: DeploymentMode;
  protected: boolean;
  user: AuthenticatedUser | null;
  accessToken: string | null;
  config: ProtectedDeploymentConfig | null;
  refreshedSession?: Session;
  clearSession?: boolean;
}

export type AuthResult = { ok: true; auth: AuthenticatedRequest } | { ok: false; response: NextResponse };

const REFRESH_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;
const DEFAULT_ALPHA_MAX_AGE_SECONDS = 60 * 60 * 24;

type PrivateAlphaSessionPayload = {
  user?: { id?: unknown; email?: unknown };
};

type PrivateAlphaLoginPayload = PrivateAlphaSessionPayload & {
  accessToken?: unknown;
  expiresIn?: unknown;
};

function configuredDeploymentMode(): DeploymentMode | 'invalid' {
  const value = process.env.DEPLOYMENT_MODE;
  if (!value) {
    const protectedEnvPresent = Boolean(process.env.SUPABASE_URL || process.env.SUPABASE_ANON_KEY || process.env.INTERNAL_API_KEY || process.env.SITE_URL);
    return protectedEnvPresent ? 'invalid' : 'local';
  }
  if (value === 'local' || value === 'invite_beta' || value === 'production' || value === 'private_alpha') return value;
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

function parseTrustedSiteOrigin(siteUrl: string | undefined): string | null {
  if (!siteUrl) return null;
  try {
    const parsed = new URL(siteUrl);
    if (parsed.username || parsed.password) return null;
    if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && isLocalhost(parsed.hostname))) return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

export function isLocalHttpAlpha(config?: ProtectedDeploymentConfig | null) {
  if (config?.mode !== 'private_alpha') return false;
  try {
    const parsed = new URL(config.siteOrigin);
    return parsed.protocol === 'http:' && isLocalhost(parsed.hostname);
  } catch {
    return false;
  }
}

function safeWorkerApiBaseUrl(workerApiBaseUrl: string | undefined) {
  if (!workerApiBaseUrl) return null;
  try {
    const parsed = new URL(workerApiBaseUrl);
    if (parsed.username || parsed.password) return null;
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
    return workerApiBaseUrl;
  } catch {
    return null;
  }
}

function safeSupabaseUrl(supabaseUrl: string | undefined) {
  if (!supabaseUrl) return null;
  try {
    const parsed = new URL(supabaseUrl);
    if (parsed.username || parsed.password) return null;
    if (parsed.protocol !== 'https:') return null;
    return supabaseUrl;
  } catch {
    return null;
  }
}

export function protectedDeploymentConfig(): { ok: true; config: ProtectedDeploymentConfig } | { ok: false; response: NextResponse } {
  const mode = configuredDeploymentMode();
  if (mode === 'invalid') {
    return { ok: false, response: publicError(500, 'INTERNAL_ERROR', 'Protected alpha authentication is not configured.') };
  }
  if (mode === 'local') {
    return { ok: false, response: publicError(500, 'INTERNAL_ERROR', 'Protected deployment configuration was requested in local mode.') };
  }

  const internalApiKey = process.env.INTERNAL_API_KEY;
  const workerApiBaseUrl = safeWorkerApiBaseUrl(process.env.WORKER_API_BASE_URL);
  const siteOrigin = parseTrustedSiteOrigin(process.env.SITE_URL);
  if (!workerApiBaseUrl || !siteOrigin || !internalApiKey || internalApiKey.length < 32) {
    return { ok: false, response: publicError(500, 'INTERNAL_ERROR', 'Protected alpha authentication is not configured.') };
  }

  if (mode === 'private_alpha') {
    return { ok: true, config: { mode, internalApiKey, workerApiBaseUrl, siteOrigin } };
  }

  const supabaseUrl = safeSupabaseUrl(process.env.SUPABASE_URL);
  const supabaseAnonKey = process.env.SUPABASE_ANON_KEY;
  if (!supabaseUrl || !supabaseAnonKey) {
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

function readAccessCookie(request: Request, config: ProtectedDeploymentConfig) {
  return readSessionCookie(request, ACCESS_COOKIE) || (isLocalHttpAlpha(config) ? readSessionCookie(request, LOCAL_ALPHA_ACCESS_COOKIE) : '');
}

function hasInviteAccess(config: ProtectedDeploymentConfig, user: User) {
  if (config.mode !== 'invite_beta') return true;
  return user.app_metadata?.handwrite_beta === true;
}

function inviteRequiredError() {
  return publicError(403, 'AUTH_INVITE_REQUIRED', 'Invite beta access is required.');
}

function supabaseFor(config: ProtectedDeploymentConfig) {
  if (!config.supabaseUrl || !config.supabaseAnonKey) throw new Error('Supabase config missing.');
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

function secureCookieOptions(maxAge: number) {
  return { httpOnly: true, secure: true, sameSite: 'lax' as const, path: '/', maxAge };
}

function localAlphaCookieOptions(maxAge: number) {
  return { httpOnly: true, secure: false, sameSite: 'lax' as const, path: '/', maxAge };
}

export function setSessionCookies(response: NextResponse, session: Pick<Session, 'access_token' | 'refresh_token' | 'expires_in'>) {
  response.cookies.set(ACCESS_COOKIE, session.access_token, secureCookieOptions(Math.max(60, Math.min(session.expires_in ?? 3600, 3600))));
  response.cookies.set(REFRESH_COOKIE, session.refresh_token, secureCookieOptions(REFRESH_MAX_AGE_SECONDS));
}

export function setAlphaAccessCookie(response: NextResponse, token: string, expiresIn: number | undefined, config: ProtectedDeploymentConfig) {
  const maxAge = Math.max(60, Math.min(expiresIn ?? DEFAULT_ALPHA_MAX_AGE_SECONDS, DEFAULT_ALPHA_MAX_AGE_SECONDS));
  if (isLocalHttpAlpha(config)) {
    response.cookies.set(LOCAL_ALPHA_ACCESS_COOKIE, token, localAlphaCookieOptions(maxAge));
    response.cookies.set(ACCESS_COOKIE, '', secureCookieOptions(0));
  } else {
    response.cookies.set(ACCESS_COOKIE, token, secureCookieOptions(maxAge));
    response.cookies.set(LOCAL_ALPHA_ACCESS_COOKIE, '', localAlphaCookieOptions(0));
  }
  response.cookies.set(REFRESH_COOKIE, '', secureCookieOptions(0));
}

export function clearSessionCookies(response: NextResponse) {
  response.cookies.set(ACCESS_COOKIE, '', secureCookieOptions(0));
  response.cookies.set(REFRESH_COOKIE, '', secureCookieOptions(0));
  response.cookies.set(LOCAL_ALPHA_ACCESS_COOKIE, '', localAlphaCookieOptions(0));
}

export function applyAuthCookies(response: NextResponse, auth: AuthenticatedRequest) {
  if (auth.refreshedSession) setSessionCookies(response, auth.refreshedSession);
  if (auth.clearSession) clearSessionCookies(response);
  return noStoreResponse(response);
}

function parseAuthenticatedUser(payload: PrivateAlphaSessionPayload): AuthenticatedUser | null {
  const id = payload.user?.id;
  const email = payload.user?.email;
  if (typeof id !== 'string' || id.length < 1) return null;
  if (email !== undefined && email !== null && typeof email !== 'string') return null;
  return { id, email: email ?? null };
}

export function parsePrivateAlphaLogin(payload: PrivateAlphaLoginPayload): { accessToken: string; expiresIn: number; user: AuthenticatedUser } | null {
  const user = parseAuthenticatedUser(payload);
  if (!user || typeof payload.accessToken !== 'string' || payload.accessToken.length < 16) return null;
  const expiresIn = typeof payload.expiresIn === 'number' && Number.isFinite(payload.expiresIn) ? Math.floor(payload.expiresIn) : DEFAULT_ALPHA_MAX_AGE_SECONDS;
  if (expiresIn < 60) return null;
  return { accessToken: payload.accessToken, expiresIn, user };
}

async function verifyPrivateAlphaSession(request: Request, config: ProtectedDeploymentConfig): Promise<AuthResult> {
  const accessToken = readAccessCookie(request, config);
  if (!accessToken) {
    const response = publicError(401, 'AUTH_REQUIRED', 'Sign in to continue.');
    clearSessionCookies(response);
    return { ok: false, response };
  }
  try {
    const upstream = await fetch(new URL('/auth/session', config.workerApiBaseUrl), {
      method: 'GET',
      headers: {
        authorization: `Bearer ${accessToken}`,
        'x-internal-api-key': config.internalApiKey,
      },
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    });
    const payload = (await upstream.json().catch(() => null)) as PrivateAlphaSessionPayload | null;
    if (upstream.ok && payload) {
      const user = parseAuthenticatedUser(payload);
      if (user) return { ok: true, auth: { mode: config.mode, protected: true, user, accessToken, config } };
      return { ok: false, response: publicError(502, 'AUTH_PROVIDER_INVALID', 'Authentication returned an invalid session.') };
    }
    if (upstream.status === 401 || upstream.status === 403 || upstream.status === 404) {
      const response = publicError(401, 'AUTH_REQUIRED', 'Sign in to continue.');
      clearSessionCookies(response);
      return { ok: false, response };
    }
    return { ok: false, response: publicError(503, 'AUTH_PROVIDER_UNAVAILABLE', 'Authentication is temporarily unavailable. Try again.') };
  } catch {
    return { ok: false, response: publicError(503, 'AUTH_PROVIDER_UNAVAILABLE', 'Authentication is temporarily unavailable. Try again.') };
  }
}

export async function requireAuthenticatedRequest(request: Request): Promise<AuthResult> {
  const mode = deploymentMode();
  if (mode === 'local') {
    return { ok: true, auth: { mode, protected: false, user: null, accessToken: null, config: null } };
  }
  const configResult = protectedDeploymentConfig();
  if (!configResult.ok) return configResult;
  const { config } = configResult;

  if (config.mode === 'private_alpha') return verifyPrivateAlphaSession(request, config);

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
