import pg from "pg";
import { DATABASE_URL } from "./config.js";

// Postgres bigints arrive as strings by default. Our IDs are identity columns that will
// never get near 2^53, so plain numbers are safe and much easier to work with.
pg.types.setTypeParser(pg.types.builtins.INT8, Number);

export const pool = new pg.Pool({ connectionString: DATABASE_URL, max: 5 });
