import type { Cookie } from "playwright";
import { existsSync, readFileSync, writeFileSync } from "fs";
import { COOKIE_FILE } from "./config.js";

export function loadCookies(): Cookie[] {
  return existsSync(COOKIE_FILE) ? JSON.parse(readFileSync(COOKIE_FILE, "utf8")) : [];
}

export function saveCookies(cookies: Cookie[]): void {
  writeFileSync(COOKIE_FILE, JSON.stringify(cookies), { mode: 0o600 });
}
