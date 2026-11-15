import pg from "pg";
import { DATABASE_URL } from "./config.js";

// bigints arrive as strings by default. our IDs never get near 2^53, so plain numbers are fine
pg.types.setTypeParser(pg.types.builtins.INT8, Number);

export const pool = new pg.Pool({ connectionString: DATABASE_URL, max: 5 });
