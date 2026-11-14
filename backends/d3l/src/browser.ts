import { Browser, BrowserContext, chromium, Cookie, Page } from "playwright";
import { D2L_HOST, HOME_URL } from "./config.js";

// Paths on the Brightspace host that are part of logging in rather than the app.
const AUTH_ROUTE_PREFIXES = ["/d2l/login", "/d2l/lp/auth/"];
const SSO_BUTTON_SELECTORS = ["button.d2l-button-sso-1", 'button:has-text("Student & Staff Login")'];
const SILENT_SIGN_IN_TIMEOUT = 20_000;

let launching: Promise<Browser> | null = null;

/** One headless Chromium shared by everyone. Each sign-in gets its own private context. */
function getBrowser(): Promise<Browser> {
  launching ??= chromium.launch({ headless: true }).then(
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

export async function newContext(viewport = { width: 1280, height: 800 }): Promise<BrowserContext> {
  return (await getBrowser()).newContext({ viewport });
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
 * Returns the renewed cookies, or null if the person has to sign in again.
 */
export async function signInSilently(cookies: Cookie[]): Promise<Cookie[] | null> {
  const context = await newContext();
  try {
    await context.addCookies(cookies);
    const page = await context.newPage();
    // An SSO chain can abort this navigation; where we end up is what matters.
    await page.goto(HOME_URL, { waitUntil: "domcontentloaded" }).catch(() => {});
    if (!isBrightspaceAppUrl(page.url())) {
      await clickSsoButton(page);
      await page
        .waitForURL((url) => isBrightspaceAppUrl(url.toString()), { timeout: SILENT_SIGN_IN_TIMEOUT })
        .catch(() => {});
    }
    return isBrightspaceAppUrl(page.url()) ? await context.cookies() : null;
  } finally {
    await context.close();
  }
}
