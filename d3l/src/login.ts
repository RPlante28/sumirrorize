#!/usr/bin/env node
import { getToken } from "./auth.js";

try {
  await getToken();
  console.log("Signed in. The session is saved and the server will reuse it.");
} catch (error) {
  console.error((error as Error).message);
  process.exit(1);
}
