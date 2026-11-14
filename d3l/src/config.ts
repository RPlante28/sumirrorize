import "dotenv/config";
import { homedir } from "os";
import { join } from "path";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} must be set (see .env.example)`);
  return value;
}

export const D2L_HOST = required("D2L_HOST");
export const PORT = Number(process.env.PORT) || 3100;
export const API_KEY = process.env.API_KEY;

// Latest versions this host supports: GET https://<host>/d2l/api/versions/
export const LP = "lp/1.64";
export const LE = "le/1.100";
export const BAS = "bas/1.6";

// Brightspace login cookies. Holding this file is as good as being signed in, so it is written owner-only.
export const COOKIE_FILE = process.env.D2L_COOKIE_FILE || join(homedir(), ".d3l-cookies.json");
