import { createHash, timingSafeEqual } from "node:crypto";
import { SERVICE_API_KEY } from "./config.js";
import { pool } from "./db.js";
import { ApiError } from "./errors.js";

function sha256(value: string): Buffer {
  return createHash("sha256").update(value).digest();
}

// hash first so both sides are the same length, which timingSafeEqual needs
const SERVICE_KEY_HASH = sha256(SERVICE_API_KEY);

/**
 * Whose data is this request for? Either a person's own API key (stored as a SHA-256 hash), or
 * a trusted backend sending SERVICE_API_KEY plus X-Person-Id.
 */
export async function identifyPerson(authorization?: string, personHeader?: string): Promise<number> {
  const key = authorization?.match(/^Bearer (.+)$/)?.[1];
  if (!key) throw new ApiError(401, "Missing API key", "bad_api_key");
  const keyHash = sha256(key);

  if (timingSafeEqual(keyHash, SERVICE_KEY_HASH)) {
    if (!personHeader || !/^\d{1,15}$/.test(personHeader)) {
      throw new ApiError(400, "Send the person's ID in the X-Person-Id header", "bad_person_id");
    }
    const personId = Number(personHeader);
    const { rowCount } = await pool.query("SELECT 1 FROM person WHERE person_id = $1", [personId]);
    if (!rowCount) throw new ApiError(404, `No person with ID ${personId}`, "bad_person_id");
    return personId;
  }

  const { rows } = await pool.query<{ person_id: number }>(
    "SELECT person_id FROM person WHERE api_key_hash = $1",
    [keyHash]
  );
  if (!rows[0]) throw new ApiError(401, "Wrong API key", "bad_api_key");
  return rows[0].person_id;
}
