import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { SESSION_ENCRYPTION_KEY } from "./config.js";

const IV_BYTES = 12;
const TAG_BYTES = 16;

/**
 * AES-256-GCM. The same `label` (e.g. the person ID) is needed to unseal, so one person's sealed
 * data can't be copied into another's row. Layout: IV | auth tag | ciphertext.
 */
export function seal(plaintext: string, label: string): Buffer {
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv("aes-256-gcm", SESSION_ENCRYPTION_KEY, iv);
  cipher.setAAD(Buffer.from(label));
  const body = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]);
}

/** Throws if the data was tampered with, or the key or label is wrong. */
export function unseal(sealed: Buffer, label: string): string {
  const decipher = createDecipheriv("aes-256-gcm", SESSION_ENCRYPTION_KEY, sealed.subarray(0, IV_BYTES));
  decipher.setAAD(Buffer.from(label));
  decipher.setAuthTag(sealed.subarray(IV_BYTES, IV_BYTES + TAG_BYTES));
  const body = sealed.subarray(IV_BYTES + TAG_BYTES);
  return Buffer.concat([decipher.update(body), decipher.final()]).toString("utf8");
}
