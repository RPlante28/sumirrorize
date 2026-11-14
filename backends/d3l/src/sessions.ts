import type { Cookie } from "playwright";
import { pool } from "./db.js";
import { seal, unseal } from "./vault.js";

// Saved Brightspace logins (the brightspace_session table), encrypted per person.

export async function loadCookies(personId: number): Promise<Cookie[]> {
  const { rows } = await pool.query<{ cookies: Buffer }>(
    "SELECT cookies FROM brightspace_session WHERE person_id = $1",
    [personId]
  );
  return rows[0] ? JSON.parse(unseal(rows[0].cookies, String(personId))) : [];
}

/** Saves a sign-in the person just did themselves, replacing any older one. */
export async function storeSignIn(personId: number, cookies: Cookie[]): Promise<void> {
  await pool.query(
    `INSERT INTO brightspace_session (person_id, cookies) VALUES ($1, $2)
     ON CONFLICT (person_id) DO UPDATE SET cookies = EXCLUDED.cookies, signed_in_at = now()`,
    [personId, seal(JSON.stringify(cookies), String(personId))]
  );
}

/**
 * Saves cookies renewed in the background. Only updates: if the person signed out in
 * the meantime, this must not sign them back in.
 */
export async function updateCookies(personId: number, cookies: Cookie[]): Promise<void> {
  await pool.query("UPDATE brightspace_session SET cookies = $2 WHERE person_id = $1", [
    personId,
    seal(JSON.stringify(cookies), String(personId)),
  ]);
}

export async function forgetSession(personId: number): Promise<void> {
  await pool.query("DELETE FROM brightspace_session WHERE person_id = $1", [personId]);
}

export async function signedInAt(personId: number): Promise<Date | null> {
  const { rows } = await pool.query<{ signed_in_at: Date }>(
    "SELECT signed_in_at FROM brightspace_session WHERE person_id = $1",
    [personId]
  );
  return rows[0]?.signed_in_at ?? null;
}

export async function peopleWithSessions(): Promise<number[]> {
  const { rows } = await pool.query<{ person_id: number }>("SELECT person_id FROM brightspace_session");
  return rows.map((row) => row.person_id);
}
