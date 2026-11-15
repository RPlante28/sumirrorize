import { randomBytes } from "node:crypto";
import type { Server } from "node:http";
import type { BrowserContext, CDPSession, Page } from "playwright";
import { WebSocket, WebSocketServer } from "ws";
import { forgetToken, mintToken } from "./auth.js";
import { isBrightspaceAppUrl, newContext } from "./browser.js";
import { HOME_URL } from "./config.js";
import { ApiError } from "./errors.js";
import { storeSignIn } from "./sessions.js";

/*
 * Browser sign-in in a tab. Brightspace's login cookies land in whichever browser the
 * person signs in with, and our site can't read another site's cookies. So the browser
 * runs here: d3l streams its screen to a tab (the viewer, public/login.html) and plays
 * the person's clicks and typing back into it. Once Brightspace is reached, the cookies
 * are saved for that person and the browser is closed.
 */

const LOGIN_TIMEOUT = 10 * 60_000;
const MAX_LOGINS = 4;
const MIN_VIEWPORT = { width: 360, height: 360 };
const MAX_VIEWPORT = { width: 1920, height: 1200 };
const MAX_PASTE = 1000;
const MOUSE_BUTTONS = ["left", "middle", "right"] as const;

type Viewport = { width: number; height: number };
// Messages from the viewer. Positions are fractions (0-1) of the picture it was shown.
type ViewerMessage =
  | { type: "move" | "down" | "up"; x: number; y: number; button?: string }
  | { type: "wheel"; x: number; y: number; dx: number; dy: number }
  | { type: "key"; key: string; ctrl?: boolean; alt?: boolean; meta?: boolean; shift?: boolean }
  | { type: "text"; text: string }
  | { type: "resize"; width: number; height: number };

const logins = new Map<string, RemoteLogin>();
let starting = 0;

class RemoteLogin {
  readonly token = randomBytes(32).toString("base64url");
  readonly expiresAt = new Date(Date.now() + LOGIN_TIMEOUT);
  private viewer: WebSocket | null = null;
  private shown: Page | null = null;
  private stream: CDPSession | null = null;
  private viewport: Viewport = { width: 1280, height: 800 };
  // Viewer input is applied strictly in order; typed characters must not swap places.
  private inputQueue = Promise.resolve();
  private finishing = false;
  private closed = false;
  private readonly timer: NodeJS.Timeout;

  private constructor(readonly personId: number, private readonly context: BrowserContext) {
    this.timer = setTimeout(() => void this.close("expired"), LOGIN_TIMEOUT);
    context.on("page", (page) => this.watch(page));
  }

  static async start(personId: number): Promise<RemoteLogin> {
    const login = new RemoteLogin(personId, await newContext());
    const page = await login.context.newPage();
    // An SSO chain can abort this navigation; where it ends up is what matters.
    page.goto(HOME_URL).catch(() => {});
    return login;
  }

  private watch(page: Page): void {
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) void this.checkSignedIn(page);
    });
    page.on("close", () => {
      if (this.shown === page) void this.show(this.context.pages().at(-1) ?? null);
    });
    // The newest page (e.g. an SSO pop-up) is the one the person needs to see.
    void this.show(page);
  }

  attach(viewer: WebSocket): void {
    if (this.viewer) {
      viewer.close(4409, "Already open in another tab");
      return;
    }
    this.viewer = viewer;
    viewer.on("message", (data, isBinary) => {
      if (isBinary) return;
      this.inputQueue = this.inputQueue.then(() => this.handleInput(data.toString())).catch(() => {});
    });
    viewer.on("close", () => {
      if (this.viewer !== viewer) return;
      this.viewer = null;
      void this.stopStream();
    });
    void this.show(this.shown);
  }

  /** Points the screen stream at `page`. Streams only while a viewer is connected. */
  private async show(page: Page | null): Promise<void> {
    this.shown = page;
    await this.stopStream();
    if (!page || !this.viewer || this.closed) return;

    const stream = await this.context.newCDPSession(page).catch(() => null);
    if (!stream) return;
    if (this.shown !== page || !this.viewer || this.closed) {
      await stream.detach().catch(() => {});
      return;
    }
    this.stream = stream;
    stream.on("Page.screencastFrame", ({ data, sessionId }) => {
      // Acknowledging only once the frame is sent keeps a slow connection from piling up frames.
      this.viewer?.send(Buffer.from(data, "base64"), () => {
        stream.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
      });
    });
    await page.setViewportSize(this.viewport).catch(() => {});
    await stream.send("Page.startScreencast", { format: "jpeg", quality: 70 }).catch(() => {});
  }

  private async stopStream(): Promise<void> {
    const stream = this.stream;
    this.stream = null;
    await stream?.detach().catch(() => {});
  }

  private async handleInput(raw: string): Promise<void> {
    const page = this.shown;
    if (!page || this.closed) return;
    let message: ViewerMessage;
    try {
      message = JSON.parse(raw);
    } catch {
      return;
    }

    switch (message.type) {
      case "move":
      case "down":
      case "up": {
        await page.mouse.move(...this.toPixels(message));
        const button = MOUSE_BUTTONS.find((b) => b === message.button) ?? "left";
        if (message.type === "down") await page.mouse.down({ button });
        if (message.type === "up") await page.mouse.up({ button });
        break;
      }
      case "wheel":
        await page.mouse.move(...this.toPixels(message));
        await page.mouse.wheel(clamp(message.dx, -2000, 2000), clamp(message.dy, -2000, 2000));
        break;
      case "key": {
        const combo = keyCombo(message);
        if (!combo) break;
        // A lone character is typed: a real key press where the keyboard has that key, plain
        // text where it doesn't (e.g. "é"). Anything else is a named key or a shortcut.
        if (combo === message.key && combo.length === 1) await page.keyboard.type(combo);
        else await page.keyboard.press(combo);
        break;
      }
      case "text":
        if (typeof message.text === "string" && message.text.length <= MAX_PASTE) {
          await page.keyboard.insertText(message.text);
        }
        break;
      case "resize":
        await this.resize(message);
        break;
    }
  }

  private toPixels(message: { x: number; y: number }): [number, number] {
    return [clamp(message.x, 0, 1) * this.viewport.width, clamp(message.y, 0, 1) * this.viewport.height];
  }

  /** Matches the browser to the viewer's size, so the picture is sharp and 1:1. */
  private async resize(size: { width: number; height: number }): Promise<void> {
    this.viewport = {
      width: Math.round(clamp(size.width, MIN_VIEWPORT.width, MAX_VIEWPORT.width)),
      height: Math.round(clamp(size.height, MIN_VIEWPORT.height, MAX_VIEWPORT.height)),
    };
    await Promise.all(this.context.pages().map((p) => p.setViewportSize(this.viewport).catch(() => {})));
  }

  private async checkSignedIn(page: Page): Promise<void> {
    if (this.closed || this.finishing || !isBrightspaceAppUrl(page.url())) return;
    this.finishing = true;
    try {
      await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});
      const cookies = await this.context.cookies();
      // Being on a Brightspace page isn't proof on its own: make sure it will issue a token.
      if (!(await mintToken(cookies))) return;
      await storeSignIn(this.personId, cookies);
      forgetToken(this.personId);
      console.error(`[login] Person ${this.personId} signed in to Brightspace`);
      this.notify({ type: "done" });
      await this.close("signed in");
    } catch (error) {
      console.error(`[login] Couldn't save person ${this.personId}'s sign-in: ${(error as Error).message}`);
    } finally {
      this.finishing = false;
    }
  }

  private notify(message: { type: "done" | "expired" }): void {
    if (this.viewer?.readyState === WebSocket.OPEN) this.viewer.send(JSON.stringify(message));
  }

  async close(reason: "signed in" | "expired" | "replaced" | "cancelled"): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    clearTimeout(this.timer);
    logins.delete(this.token);
    if (reason === "expired") this.notify({ type: "expired" });
    this.viewer?.close(1000, reason);
    await this.stopStream();
    await this.context.close().catch(() => {});
  }
}

function clamp(value: unknown, min: number, max: number): number {
  const n = typeof value === "number" && Number.isFinite(value) ? value : min;
  return Math.min(max, Math.max(min, n));
}

/** Turns a browser keydown into a Playwright key name, e.g. "a", "Shift+Tab", "Control+a". */
function keyCombo(message: Extract<ViewerMessage, { type: "key" }>): string | null {
  const { key } = message;
  if (typeof key !== "string" || key.length === 0 || key.length > 20) return null;
  const name = key === " " ? "Space" : key;
  // A typed character already reflects Shift (and AltGr), so only shortcuts carry modifiers.
  if (key.length === 1 && !message.ctrl && !message.meta) return name;
  const modifiers = [
    message.ctrl && "Control",
    message.alt && "Alt",
    message.meta && "Meta",
    message.shift && key.length > 1 && "Shift",
  ].filter(Boolean);
  return [...modifiers, name].join("+");
}

/** Opens a browser for `personId` to sign in with. Returns the viewer link to open in a new tab. */
export async function startLogin(personId: number): Promise<{ path: string; expiresAt: Date }> {
  if (logins.size + starting >= MAX_LOGINS) {
    throw new ApiError(503, "Too many sign-ins in progress, try again in a minute", "busy");
  }
  starting++;
  let login: RemoteLogin;
  try {
    login = await RemoteLogin.start(personId);
  } finally {
    starting--;
  }
  // One sign-in per person: the newest one wins.
  for (const other of logins.values()) {
    if (other.personId === personId) void other.close("replaced");
  }
  logins.set(login.token, login);
  return { path: `/login/${login.token}`, expiresAt: login.expiresAt };
}

export function isLoginLink(token: string): boolean {
  return logins.has(token);
}

export function isSigningIn(personId: number): boolean {
  return [...logins.values()].some((login) => login.personId === personId);
}

export async function cancelLogins(personId: number): Promise<void> {
  const mine = [...logins.values()].filter((login) => login.personId === personId);
  await Promise.all(mine.map((login) => login.close("cancelled")));
}

/** Accepts the viewer's WebSocket at /login/<token>/stream. The token is its only credential. */
export function acceptViewers(server: Server): void {
  const sockets = new WebSocketServer({ noServer: true, maxPayload: 16 * 1024 });
  server.on("upgrade", (request, socket, head) => {
    const token = request.url?.match(/^\/login\/([\w-]+)\/stream$/)?.[1];
    const login = token ? logins.get(token) : undefined;
    if (!login) {
      socket.end("HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n");
      return;
    }
    sockets.handleUpgrade(request, socket, head, (ws) => login.attach(ws));
  });
}
