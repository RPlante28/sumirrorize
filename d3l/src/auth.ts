import { signInWithBrowser } from "./browser-login.js";
import { D2L_HOST } from "./config.js";
import { loadCookies } from "./cookies.js";

const BASE_URL = `https://${D2L_HOST}`;
const REFRESH_MARGIN = 5 * 60_000;
// Brightspace ends a session after 180 idle minutes (D2L.PT.Auth.SessionTimeout.Init on
// /d2l/home), so touching it well inside that keeps the session alive indefinitely.
const KEEP_ALIVE_INTERVAL = 30 * 60_000;
const XSRF_TOKEN = /localStorage\.setItem\('XSRF\.Token','([^']+)'\)/;

type Token = { token: string; expiresAt: number };

let cached: Token = { token: "", expiresAt: 0 };
let pending: Promise<string> | null = null;

function cookieHeader(): string {
  const host = `.${D2L_HOST.toLowerCase()}`;
  return loadCookies()
    .filter((c) => host.endsWith(`.${c.domain.replace(/^\./, "")}`))
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
}

/**
 * Gets an API token the way the Brightspace web app does: session cookie plus the XSRF
 * token embedded in /d2l/home. No browser needed. Returns null once the session has ended.
 */
async function mintToken(): Promise<Token | null> {
  const cookie = cookieHeader();
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

async function refresh(): Promise<string> {
  let minted = await mintToken();
  if (!minted) {
    console.error("[auth] Brightspace session has ended, signing in again");
    await signInWithBrowser();
    minted = await mintToken();
    if (!minted) throw new Error("Signed in, but Brightspace would not issue an API token.");
  }
  cached = minted;
  return minted.token;
}

export async function getToken(): Promise<string> {
  if (cached.token && Date.now() < cached.expiresAt - REFRESH_MARGIN) {
    return cached.token;
  }
  // Concurrent requests share one refresh; parallel browser logins would each prompt for MFA.
  pending ??= refresh().finally(() => {
    pending = null;
  });
  return pending;
}

export function clearToken(): void {
  cached = { token: "", expiresAt: 0 };
}

/**
 * Re-mints the token on a timer so the session never idles out. Never opens a browser:
 * if the session has ended, the next real request does the sign-in.
 */
export function startKeepAlive(): void {
  setInterval(async () => {
    const minted = await mintToken().catch(() => null);
    if (minted) cached = minted;
    else console.error("[auth] Keep-alive found the session ended; the next request will sign in");
  }, KEEP_ALIVE_INTERVAL).unref();
}
