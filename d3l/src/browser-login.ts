import { chromium, Locator, Page } from "playwright";
import { readdirSync } from "fs";
import { D2L_HOST } from "./config.js";
import { loadCookies, saveCookies } from "./cookies.js";

const D2L_USERNAME = process.env.D2L_USERNAME;
const D2L_PASSWORD = process.env.D2L_PASSWORD;
const HOME_URL = `https://${D2L_HOST}/d2l/home`;
const D2L_HOSTNAME = new URL(HOME_URL).hostname.toLowerCase();

// Paths on the Brightspace host that are part of logging in rather than the app.
const AUTH_ROUTE_PREFIXES = ["/d2l/login", "/d2l/lp/auth/"];

const SILENT_SSO_TIMEOUT = 15000;
// Long enough for the form plus SSO redirects, short enough that an MFA prompt
// we cannot answer gives up and falls through to a visible window.
const CREDENTIAL_SSO_TIMEOUT = Number(process.env.D2L_LOGIN_TIMEOUT_MS) || 45000;
const INTERACTIVE_SSO_TIMEOUT = 300000;
const SETTLE_TIMEOUT = 15000;

const USERNAME_SELECTORS = [
  'input[placeholder*="username" i]',
  'input[placeholder*="user" i]',
  'input[name="userName"]',
  'input[name="username"]',
  'input[name="user"]',
  'input[type="text"][id*="user" i]',
];
const PASSWORD_SELECTORS = ['input[name="password"]', 'input[name="passWord"]', 'input[type="password"]'];
const SUBMIT_SELECTORS = [
  'button[type="submit"]',
  'input[type="submit"]',
  'button:has-text("Log in")',
  'button:has-text("Login")',
  'button:has-text("Sign in")',
  "form button",
];
const SSO_BUTTON_SELECTORS = ["button.d2l-button-sso-1", 'button:has-text("Student & Staff Login")'];

type LoginAttempt = { label: string; headless: boolean; timeout: number };

/**
 * True once the browser is back on Brightspace outside its login routes. SSO
 * can bounce through any number of identity-provider hosts, so this is the only
 * reliable signal that the round-trip is done.
 */
function isBrightspaceAppUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname.toLowerCase();
    return (
      parsed.hostname.toLowerCase() === D2L_HOSTNAME &&
      !AUTH_ROUTE_PREFIXES.some((prefix) => path.startsWith(prefix))
    );
  } catch {
    return false;
  }
}

async function findVisible(page: Page, selectors: string[]): Promise<Locator | null> {
  for (const selector of selectors) {
    const field = page.locator(selector).first();
    if (await field.isVisible({ timeout: 1000 }).catch(() => false)) {
      return field;
    }
  }
  return null;
}

async function submitCredentials(page: Page): Promise<boolean> {
  if (!D2L_USERNAME || !D2L_PASSWORD) return false;

  const username = await findVisible(page, USERNAME_SELECTORS);
  const password = await findVisible(page, PASSWORD_SELECTORS);
  if (!username || !password) return false;

  await username.fill(D2L_USERNAME);
  await password.fill(D2L_PASSWORD);
  const submit = await findVisible(page, SUBMIT_SELECTORS);
  await (submit ? submit.click() : password.press("Enter"));
  return true;
}

async function clickSsoButton(page: Page): Promise<void> {
  const button = await findVisible(page, SSO_BUTTON_SELECTORS);
  await button?.click();
}

/**
 * A service started before anyone logged in has no DISPLAY, so probe for a live
 * X socket before deciding a login window cannot be shown.
 */
function ensureDisplay(): boolean {
  if (process.env.DISPLAY || process.env.WAYLAND_DISPLAY) return true;

  let sockets: string[] = [];
  try {
    sockets = readdirSync("/tmp/.X11-unix");
  } catch {
    return false;
  }
  const screen = sockets.find((name) => /^X\d+$/.test(name));
  if (!screen) return false;

  process.env.DISPLAY = `:${screen.slice(1)}`;
  return true;
}

/**
 * Ways to get in, cheapest first. Saved cookies can still hold a live identity-provider
 * session after Brightspace's has ended; only a visible window can clear MFA.
 */
function loginAttempts(): LoginAttempt[] {
  const attempts: LoginAttempt[] = [];
  if (loadCookies().length > 0) {
    attempts.push({ label: "saved cookies", headless: true, timeout: SILENT_SSO_TIMEOUT });
  }
  if (D2L_USERNAME && D2L_PASSWORD) {
    attempts.push({ label: "stored credentials", headless: true, timeout: CREDENTIAL_SSO_TIMEOUT });
  }
  if (ensureDisplay()) {
    attempts.push({ label: "browser window", headless: false, timeout: INTERACTIVE_SSO_TIMEOUT });
  }
  return attempts;
}

/** Drives whatever login page we land on until the browser is back on Brightspace. */
async function reachBrightspaceApp(page: Page, attempt: LoginAttempt): Promise<boolean> {
  const deadline = Date.now() + attempt.timeout;
  let loginDriven = false;

  while (Date.now() < deadline) {
    // A dashboard with long-polling never goes idle; the URL is what we act on.
    await page.waitForLoadState("networkidle", { timeout: SETTLE_TIMEOUT }).catch(() => {});
    if (isBrightspaceAppUrl(page.url())) return true;

    if (!loginDriven) {
      loginDriven = true;
      if (!(await submitCredentials(page))) await clickSsoButton(page);
      if (!attempt.headless) console.error("[auth] Finish signing in in the browser window...");
    }

    await page
      .waitForURL((url) => isBrightspaceAppUrl(url.toString()), {
        timeout: Math.max(1000, deadline - Date.now()),
        waitUntil: "domcontentloaded",
      })
      .catch(() => {});
  }
  return isBrightspaceAppUrl(page.url());
}

async function tryAttempt(attempt: LoginAttempt): Promise<boolean> {
  console.error(`[auth] Signing in via ${attempt.label}`);
  const browser = await chromium.launch({ headless: attempt.headless });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
    await context.addCookies(loadCookies()).catch(() => {});
    const page = await context.newPage();
    // An SSO chain can abort this navigation; where we end up is what matters.
    await page.goto(HOME_URL, { waitUntil: "domcontentloaded" }).catch(() => {});
    if (!(await reachBrightspaceApp(page, attempt))) return false;

    saveCookies(await context.cookies());
    return true;
  } finally {
    await browser.close();
  }
}

/** Signs in to Brightspace with a real browser and saves the resulting session cookies. */
export async function signInWithBrowser(): Promise<void> {
  const attempts = loginAttempts();
  for (const attempt of attempts) {
    if (await tryAttempt(attempt)) return;
  }

  const tried = attempts.map((a) => a.label).join(" -> ") || "nothing";
  throw new Error(
    `Failed to sign in to Brightspace (tried: ${tried}). ` +
      "Run `npm run login` from a desktop session to sign in with MFA."
  );
}
