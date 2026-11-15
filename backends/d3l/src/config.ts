import "dotenv/config";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} must be set (see .env.example)`);
  return value;
}

export const D2L_HOST = required("D2L_HOST").toLowerCase();
export const HOME_URL = `https://${D2L_HOST}/d2l/home`;
export const PORT = Number(process.env.PORT) || 3100;
export const DATABASE_URL = required("DATABASE_URL");

// lets a trusted backend read any person's data by also sending X-Person-Id
export const SERVICE_API_KEY = required("SERVICE_API_KEY");
if (SERVICE_API_KEY.length < 32) throw new Error("SERVICE_API_KEY must be at least 32 characters");

// encrypts saved Brightspace logins
export const SESSION_ENCRYPTION_KEY = Buffer.from(required("SESSION_ENCRYPTION_KEY"), "base64");
if (SESSION_ENCRYPTION_KEY.length !== 32) {
  throw new Error("SESSION_ENCRYPTION_KEY must be 32 bytes, base64 encoded (openssl rand -base64 32)");
}

// sites a sign-in may open pages on besides Brightspace (school login, Duo). subdomains count too
export const SIGN_IN_HOSTS = [
  D2L_HOST,
  ...required("SIGN_IN_HOSTS").toLowerCase().split(",").map((host) => host.trim()).filter(Boolean),
];

// latest versions this host supports: GET https://<host>/d2l/api/versions/
export const LP = "lp/1.64";
export const LE = "le/1.100";
export const BAS = "bas/1.6";
