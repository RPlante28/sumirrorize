import type { Cookie } from "playwright";
import { signInSilently } from "./browser.js";
import { D2L_HOST } from "./config.js";
import { brightspaceUnavailable, signInRequired } from "./errors.js";
import { forgetSession, loadCookies, peopleWithSessions, updateCookies } from "./sessions.js";

const BASE_URL = `https://${D2L_HOST}`;
const REFRESH_MARGIN = 5 * 60_000;
// Brightspace ends a session after 180 idle minutes (D2L.PT.Auth.SessionTimeout.Init on
// /d2l/home), so touching it well inside that keeps the session alive indefinitely.
const KEEP_ALIVE_INTERVAL = 30 * 60_000;
const XSRF_TOKEN = /localStorage\.setItem\('XSRF\.Token','([^']+)'\)/;
// Where Brightspace sends a browser whose session has ended.
const LOGIN_PATH = "/d2l/login";

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

async function ask(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${BASE_URL}${path}`, init);
  } catch (error) {
    throw brightspaceUnavailable(`couldn't reach it: ${(error as Error).message}`);
  }
}

/**
 * True if Brightspace answered by sending the browser to its login page, which is how it says a
 * session has ended: a small page whose script goes there (status 200), or a plain redirect.
 */
async function sentToLogin(response: Response): Promise<boolean> {
  if (response.headers.get("location")?.includes(LOGIN_PATH)) return true;
  return response.ok && (await response.text()).includes(LOGIN_PATH);
}

/**
 * Gets an API token the way the Brightspace web app does: session cookie plus the XSRF
 * token embedded in /d2l/home. No browser needed.
 *
 * Returns null only when Brightspace says the session has ended. If Brightspace can't be reached
 * or answers with anything else (an error or maintenance page), that says nothing about the
 * session, so this throws and the saved login is kept.
 */
export async function mintToken(cookies: Cookie[]): Promise<Token | null> {
  const cookie = cookieHeader(cookies);
  if (!cookie) return null;

  const home = await ask("/d2l/home", { headers: { cookie }, redirect: "manual" });
  const page = home.ok ? await home.clone().text() : "";
  const xsrf = page.match(XSRF_TOKEN)?.[1];
  if (!xsrf) {
    if (await sentToLogin(home)) return null;
    throw brightspaceUnavailable(`its home page answered ${home.status} without a session`);
  }

  const response = await ask("/d2l/lp/auth/oauth2/token", {
    method: "POST",
    redirect: "manual",
    headers: { cookie, "content-type": "application/x-www-form-urlencoded", "x-csrf-token": xsrf },
    body: "scope=*:*:*",
  });
  if (!response.ok || !response.headers.get("content-type")?.includes("json")) {
    // A rejected request comes back as the same go-to-login page, not an error status.
    if (await sentToLogin(response)) return null;
    throw brightspaceUnavailable(`its token request answered ${response.status}`);
  }

  const { access_token, expires_at } = (await response.json()) as { access_token: string; expires_at: number };
  return { token: access_token, expiresAt: expires_at * 1000 };
}

/**
 * A fresh token for the person. Their saved login is deleted only when Brightspace says the
 * session has ended and renewing it in the background didn't work either. If Brightspace or the
 * school's login site is down, mintToken or signInSilently throws and the login is kept.
 */
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
