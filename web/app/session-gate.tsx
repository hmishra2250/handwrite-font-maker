"use client";

import { FormEvent, KeyboardEvent, ReactNode, useEffect, useState } from "react";
import type { RuntimeDeploymentMode } from "@/lib/server-auth";
import { AccountPanel } from "./account-panel";
import { StudioBrand, StudioIcon, StudioNavigation } from "./studio-chrome";

type SessionState =
  | { status: "loading" }
  | { status: "authenticated"; email?: string | null; error?: string | null }
  | { status: "anonymous"; error?: string | null; notice?: string | null };

type SessionGateSurface = "studio" | "mobile";

export function SessionGate({
  deploymentMode,
  children,
  surface = "studio",
}: {
  deploymentMode: RuntimeDeploymentMode;
  children: ReactNode;
  surface?: SessionGateSurface;
}) {
  const [session, setSession] = useState<SessionState>(
    deploymentMode === "local"
      ? { status: "authenticated" }
      : { status: "loading" },
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (deploymentMode === "local") return;
    let cancelled = false;
    fetch("/api/auth/session", {
      cache: "no-store",
      credentials: "same-origin",
    })
      .then((res) => res.json())
      .then(
        (data: {
          authenticated?: boolean;
          user?: { email?: string | null };
        }) => {
          if (cancelled) return;
          setSession(
            data.authenticated
              ? { status: "authenticated", email: data.user?.email }
              : { status: "anonymous" },
          );
        },
      )
      .catch(() => {
        if (!cancelled)
          setSession({
            status: "anonymous",
            error: "Could not check your alpha session.",
          });
      });
    return () => {
      cancelled = true;
    };
  }, [deploymentMode]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setSession({ status: "anonymous" });
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ email, password }),
      });
      const data = (await res.json()) as {
        authenticated?: boolean;
        user?: { email?: string | null };
        error?: { message?: string };
      };
      if (!res.ok || !data.authenticated)
        throw new Error(data.error?.message ?? "Sign in failed.");
      setPassword("");
      setSession({ status: "authenticated", email: data.user?.email ?? email });
    } catch (err) {
      setSession({
        status: "anonymous",
        error: err instanceof Error ? err.message : "Sign in failed.",
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function logout() {
    setSubmitting(true);
    setSession((current) =>
      current.status === "authenticated"
        ? { ...current, error: null }
        : current,
    );
    try {
      const res = await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "same-origin",
      });
      if (!res.ok) throw new Error("Logout failed. Try again.");
      setPassword("");
      setSession({ status: "anonymous" });
    } catch {
      setSession((current) =>
        current.status === "authenticated"
          ? { ...current, error: "Logout failed. Try again." }
          : current,
      );
    } finally {
      setSubmitting(false);
    }
  }

  const isMobileSurface = surface === "mobile";

  function accountMenu() {
    if (deploymentMode === "local") return null;
    return (
      <details className="studio-account-menu">
        <summary aria-label="Account and settings">
          <span className="studio-avatar">
            {session.status === "authenticated"
              ? (session.email?.[0] ?? "Y").toUpperCase()
              : "Y"}
          </span>
          <span className="studio-account-label">Account</span>
          <span aria-hidden="true">⌄</span>
        </summary>
        <div className="studio-account-popover">
          <p className="mb-4 break-words text-sm text-text-secondary">
            Signed in
            {session.status === "authenticated" && session.email
              ? ` as ${session.email}`
              : ""}
          </p>
          {deploymentMode === "private_alpha" &&
            session.status === "authenticated" && (
              <AccountPanel
                onSignedOut={(notice) =>
                  setSession({ status: "anonymous", notice })
                }
              />
            )}
          <button
            type="button"
            className="secondary-button mt-4 w-full"
            onClick={logout}
            disabled={submitting}
          >
            {submitting ? "Logging out…" : "Logout"}
          </button>
          {session.status === "authenticated" && session.error && (
            <p className="mt-3 text-[13px] text-red" role="alert">
              {session.error}
            </p>
          )}
        </div>
      </details>
    );
  }

  function closeDisclosureOnEscape(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== "Escape") return;
    const disclosure = (event.target as HTMLElement).closest("details");
    disclosure?.removeAttribute("open");
    disclosure?.querySelector("summary")?.focus();
  }

  if (deploymentMode !== "local" && session.status === "loading") {
    return (
      <main className={isMobileSurface ? "studio-loading mobile-capture-loading" : "studio-loading"}>
        <StudioBrand />
        <p role="status">Opening your {isMobileSurface ? "phone capture" : "studio"}…</p>
      </main>
    );
  }

  if (deploymentMode !== "local" && session.status !== "authenticated") {
    return (
      <main className={isMobileSurface ? "studio-login mobile-capture-login" : "studio-login"}>
        <section
          className="studio-login-form"
          aria-labelledby="alpha-login-title"
        >
          <StudioBrand />
          <div className="studio-login-content">
            <span className="studio-eyebrow">
              {isMobileSurface ? "PHONE CAPTURE ALPHA" : "YOUR LETTERS. YOUR FONT."}
            </span>
            <h1 id="alpha-login-title">
              {isMobileSurface ? "Capture your font" : "A little more"}
              <br />
              {isMobileSurface ? "from your phone." : "you in every word."}
            </h1>
            <p className="studio-login-intro">
              {isMobileSurface
                ? "Sign in on your phone to use the back camera or upload from your gallery."
                : "Turn your handwriting, drawings, or found shapes into a font you can type with."}
            </p>
            <h2 className="sr-only">Sign in to capture your font</h2>
            <form className="grid gap-5" onSubmit={login}>
              <label className="grid gap-2 text-sm font-semibold">
                Email
                <input
                  className="field"
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                />
              </label>
              <label className="grid gap-2 text-sm font-semibold">
                Password
                <input
                  className="field"
                  type="password"
                  autoComplete="current-password"
                  placeholder="Your invite password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </label>
              {session.status === "anonymous" && session.notice && (
                <p
                  className="rounded-lg bg-green-muted px-3.5 py-2.5 text-[13px] text-green"
                  role="status"
                >
                  {session.notice}
                </p>
              )}
              {session.status === "anonymous" && session.error && (
                <p
                  className="rounded-lg bg-red-muted px-3.5 py-2.5 text-[13px] text-red"
                  role="alert"
                >
                  {session.error}
                </p>
              )}
              <button
                type="submit"
                className="primary-button flex items-center justify-center gap-3"
                disabled={submitting}
              >
                {submitting ? "Signing in…" : "Sign in"}
                <StudioIcon name="arrow" />
              </button>
            </form>
            <p className="studio-invite-note">
              Invite-only alpha · Free to try
              <br />
              Use the credentials shared with your invite. Need access or a
              password reset? Contact the person who invited you.
            </p>
          </div>
          <div className="studio-login-footer">
            {!isMobileSurface && <a href="/pricing">Pricing</a>}
            <a href="/help/install-fonts">How to use your font</a>
          </div>
        </section>
        {!isMobileSurface && (
          <aside
            className="studio-specimen"
            aria-label="Illustrative type specimen, not a generated font"
          >
            <div className="studio-specimen-top">
              <span>THE BEAUTY IS IN THE IMPERFECTIONS</span>
              <span>01 — Aa</span>
            </div>
            <div className="studio-specimen-paper">
              <span className="studio-specimen-label">
                A NOTE TO MAKE YOUR OWN
              </span>
              <p>
                sincerely,
                <br />
                <em>you.</em>
              </p>
              <span className="studio-specimen-rule" />
              <span className="studio-specimen-foot">
                Something only you could write.
              </span>
            </div>
            <div className="studio-specimen-bottom">
              <p>
                From a mark on paper
                <br />
                to something you can type.
              </p>
              <span>CAPTURE → REFINE → CREATE</span>
            </div>
          </aside>
        )}
      </main>
    );
  }

  if (isMobileSurface) {
    return (
      <div className="mobile-capture-layout">
        <a className="studio-skip" href="#capture">
          Skip to phone capture
        </a>
        <header className="mobile-capture-header" onKeyDown={closeDisclosureOnEscape}>
          <StudioBrand />
          <div className="flex min-w-0 items-center gap-2">
            <span className="studio-alpha-pill">Private alpha</span>
            {accountMenu()}
          </div>
        </header>
        <main id="capture" className="mobile-capture-content">
          {children}
        </main>
      </div>
    );
  }

  return (
    <div className="studio-layout">
      <a className="studio-skip" href="#capture">
        Skip to font studio
      </a>
      <aside className="studio-sidebar">
        <StudioBrand />
        <StudioNavigation />
      </aside>
      <div className="studio-main">
        <header
          className="studio-topbar"
          onKeyDown={closeDisclosureOnEscape}
        >
          <details className="studio-mobile-nav">
            <summary aria-label="Open navigation">
              <StudioIcon name="menu" />
              <span>handwrite</span>
            </summary>
            <div
              onClick={(event) => {
                if ((event.target as HTMLElement).closest("a"))
                  event.currentTarget
                    .closest("details")
                    ?.removeAttribute("open");
              }}
            >
              <StudioNavigation />
            </div>
          </details>
          <div className="studio-breadcrumb">
            <span>Workspace</span>
            <span aria-hidden="true">/</span>
            <strong>Font studio</strong>
          </div>
          <div className="flex min-w-0 items-center gap-3">
            <span className="studio-alpha-pill">Private alpha</span>
            {accountMenu()}
          </div>
        </header>
        <main id="capture" className="studio-content">
          {children}
        </main>
      </div>
    </div>
  );
}
