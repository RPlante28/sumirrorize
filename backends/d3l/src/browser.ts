import { Browser, BrowserContext, chromium, Cookie, Page, Route } from "playwright";
import { D2L_HOST, HOME_URL, SIGN_IN_HOSTS } from "./config.js";
import { startEgressProxy } from "./egress.js";
import { brightspaceUnavailable } from "./errors.js";

// Paths on the Brightspace host that are part of logging in rather than the app.
const AUTH_ROUTE_PREFIXES = ["/d2l/login", "/d2l/lp/auth/"];
const SSO_BUTTON_SELECTORS = ["button.d2l-button-sso-1", 'button:has-text("Student & Staff Login")'];
const SILENT_SIGN_IN_TIMEOUT = 20_000;

let launching: Promise<Browser> | null = null;

/**
 * One headless Chromium shared by everyone. Each sign-in gets its own private context. All of
 * its traffic goes through the proxy in egress.ts, so it can only reach the public internet.
 */
let proxy: Promise<string> | null = null;

async function launch(): Promise<Browser> {
  proxy ??= startEgressProxy();
  return chromium.launch({
    headless: true,
    // "<-loopback>": send even localhost through the proxy (Chromium skips it otherwise).
    proxy: { server: await proxy, bypass: "<-loopback>" },
    // WebRTC can open connections that don't use the proxy; a sign-in page has no need for it.
    args: ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
  });
}

function getBrowser(): Promise<Browser> {
  launching ??= launch().then(
    (browser) => {
      browser.on("disconnected", () => {
        launching = null;
      });
      return browser;
    },
    (error) => {
      launching = null;
      throw error;
    }
  );
  return launching;
}

/** True if a sign-in may open a page on this site: Brightspace, or a site listed in SIGN_IN_HOSTS. */
export function isSignInSite(url: string): boolean {
  try {
    const { protocol, hostname } = new URL(url);
    const host = hostname.toLowerCase();
    return protocol === "https:" && SIGN_IN_HOSTS.some((site) => host === site || host.endsWith(`.${site}`));
  } catch {
    return false;
  }
}

/**
 * Keeps the tab on the sign-in sites: following a link anywhere else does nothing. Only the page
 * in the tab itself is checked; the pictures, scripts and frames those pages load are not.
 */
async function stayOnSignInSites(route: Route): Promise<void> {
  const request = route.request();
  let opensPage = false;
  try {
    opensPage = request.isNavigationRequest() && request.frame().parentFrame() === null;
  } catch {
    // Not a page's own request (e.g. a background worker's), so it can't be opening a page.
  }
  if (opensPage && !isSignInSite(request.url())) {
    console.error(
      `[login] Blocked a page outside the sign-in sites: ${new URL(request.url()).host} ` +
        "(if signing in needs it, add it to SIGN_IN_HOSTS)"
    );
    await route.abort("blockedbyclient");
    return;
  }
  await route.continue();
}

export async function newContext(viewport = { width: 1280, height: 800 }): Promise<BrowserContext> {
  const context = await (await getBrowser()).newContext({ viewport });
  await context.route("**/*", stayOnSignInSites);
  return context;
}

export async function closeBrowser(): Promise<void> {
  if (launching) await (await launching).close();
}

/**
 * True once the browser is back on Brightspace outside its login routes. SSO can bounce
 * through any number of identity-provider hosts, so this is the only reliable signal
 * that the round-trip is done.
 */
export function isBrightspaceAppUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname.toLowerCase();
    return parsed.hostname.toLowerCase() === D2L_HOST && !AUTH_ROUTE_PREFIXES.some((p) => path.startsWith(p));
  } catch {
    return false;
  }
}

async function clickSsoButton(page: Page): Promise<void> {
  for (const selector of SSO_BUTTON_SELECTORS) {
    const button = page.locator(selector).first();
    if (await button.isVisible({ timeout: 1000 }).catch(() => false)) {
      await button.click();
      return;
    }
  }
}

/**
 * Tries to renew an ended Brightspace session without the person: saved cookies often
 * still hold a live school (SSO) login after Brightspace's own session has timed out.
 * Returns the renewed cookies, or null if the person has to sign in again. Throws if a site
 * along the way is down, since that doesn't mean the person's school login has ended.
 */
export async function signInSilently(cookies: Cookie[]): Promise<Cookie[] | null> {
  const context = await newContext();
  try {
    await context.addCookies(cookies);
    const page = await context.newPage();
    // The status of the last page the tab itself loaded (not pictures, scripts and so on).
    let lastStatus = 200;
    page.on("response", (response) => {
      if (response.frame() === page.mainFrame() && response.request().isNavigationRequest()) {
        lastStatus = response.status();
      }
    });
    // An SSO chain can abort this navigation; where we end up is what matters.
    await page.goto(HOME_URL, { waitUntil: "domcontentloaded" }).catch(() => {});
    if (!isBrightspaceAppUrl(page.url())) {
      await clickSsoButton(page);
      await page
        .waitForURL((url) => isBrightspaceAppUrl(url.toString()), { timeout: SILENT_SIGN_IN_TIMEOUT })
        .catch(() => {});
    }
    if (isBrightspaceAppUrl(page.url()) && lastStatus < 500) return await context.cookies();
    // Chromium shows its own error page (chrome-error://) when a site can't be reached at all.
    if (lastStatus >= 500 || page.url().startsWith("chrome-error://")) {
      throw brightspaceUnavailable(`signing in again stopped at ${safeHost(page.url())} (${lastStatus})`);
    }
    return null;
  } finally {
    await context.close();
  }
}

function safeHost(url: string): string {
  try {
    return new URL(url).host || "an error page";
  } catch {
    return "an error page";
  }
}
