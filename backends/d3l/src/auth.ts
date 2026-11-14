import type { Cookie } from "playwright";
import { signInSilently } from "./browser.js";
import { D2L_HOST } from "./config.js";
import { signInRequired } from "./errors.js";
import { forgetSession, loadCookies, peopleWithSessions, updateCookies } from "./sessions.js";

const BASE_URL = `https://${D2L_HOST}`;
const REFRESH_MARGIN = 5 * 60_000;
// Brightspace ends a session after 180 idle minutes (D2L.PT.Auth.SessionTimeout.Init on
// /d2l/home), so touching it well inside that keeps the session alive indefinitely.
const KEEP_ALIVE_INTERVAL = 30 * 60_000;
const XSRF_TOKEN = /localStorage\.setItem\('XSRF\.Token','([^']+)'\)/;

type Token = { token: string; expiresAt: number };

// Per person: their current API token, and the renewal in flight (if any).
const tokens = new Map<number, Token>();
const renewals = new Map<number, Promise<string>>();

function cookieHeader(cookies: Cookie[]): string {
  const host = `.${D2L_HOST}`;
  return cookies
    .filter((c) => host.endsWith(`.${c.domain.replace(/^\./, "")}`))
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
}

/**
 * Gets an API token the way the Brightspace web app does: session cookie plus the XSRF
 * token embedded in /d2l/home. No browser needed. Returns null if the session has ended;
 * throws if Brightspace couldn't be reached (which says nothing about the session).
 */
export async function mintToken(cookies: Cookie[]): Promise<Token | null> {
  const cookie = cookieHeader(cookies);
  if (!cookie) return null;

  // An ended session redirects to the login page instead of returning 200.
  const home = await fetch(`${BASE_URL}/d2l/home`, { headers: { cookie }, redirect: "manual" });
  const xsrf = home.ok ? (await home.text()).match(XSRF_TOKEN)?.[1] : undefined;
  if (!xsrf) return null;

  const response = await fetch(`${BASE_URL}/d2l/lp/auth/oauth2/token`, {
    method: "POST",
    redirect: "manual",
    headers: { cookie, "content-type": "application/x-www-form-urlencoded", "x-csrf-token": xsrf },
    body: "scope=*:*:*",
  });
  // A rejected request comes back as a 200 HTML redirect page, not an error status.
  if (!response.ok || !response.headers.get("content-type")?.includes("json")) return null;

  const { access_token, expires_at } = (await response.json()) as { access_token: string; expires_at: number };
  return { token: access_token, expiresAt: expires_at * 1000 };
}

async function renewNow(personId: number): Promise<string> {
  const cookies = await loadCookies(personId);
  if (cookies.length === 0) throw signInRequired();

  let minted = await mintToken(cookies);
  if (!minted) {
    const renewed = await signInSilently(cookies);
    if (renewed) {
      await updateCookies(personId, renewed);
      minted = await mintToken(renewed);
    }
  }
  if (!minted) {
    console.error(`[auth] Person ${personId}'s Brightspace session has ended; they need to sign in again`);
    await forgetSession(personId);
    forgetToken(personId);
    throw signInRequired();
  }
  tokens.set(personId, minted);
  return minted.token;
}

/** Mints a fresh token. Concurrent callers for the same person share one renewal. */
function renew(personId: number): Promise<string> {
  let renewal = renewals.get(personId);
  if (!renewal) {
    renewal = renewNow(personId).finally(() => renewals.delete(personId));
    renewals.set(personId, renewal);
  }
  return renewal;
}

export async function getToken(personId: number): Promise<string> {
  const cached = tokens.get(personId);
  if (cached && Date.now() < cached.expiresAt - REFRESH_MARGIN) return cached.token;
  return renew(personId);
}

/** Drops a person's cached token, e.g. after Brightspace rejected it or they signed in again. */
export function forgetToken(personId: number): void {
  tokens.delete(personId);
}

/** Re-mints everyone's token on a timer so no session idles out. */
export function startKeepAlive(): void {
  setInterval(async () => {
    const people = await peopleWithSessions().catch((error) => {
      console.error(`[auth] Keep-alive couldn't list sessions: ${error.message}`);
      return [];
    });
    for (const personId of people) {
      // A signin_required failure was already logged; anything else is likely temporary.
      await renew(personId).catch((error) => {
        if (error.code !== "signin_required") {
          console.error(`[auth] Keep-alive for person ${personId} failed: ${error.message}`);
        }
      });
    }
  }, KEEP_ALIVE_INTERVAL).unref();
}
