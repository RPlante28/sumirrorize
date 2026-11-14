#!/usr/bin/env node
import express, { NextFunction, Request, RequestHandler, Response } from "express";
import cors from "cors";
import { dirname, join } from "node:path";
import { Readable } from "node:stream";
import { fileURLToPath } from "node:url";
import { forgetToken, startKeepAlive } from "./auth.js";
import { closeBrowser } from "./browser.js";
import { identifyPerson } from "./callers.js";
import { d2lFetch, getJson } from "./client.js";
import { LP, PORT } from "./config.js";
import { pool } from "./db.js";
import { ApiError } from "./errors.js";
import { acceptViewers, cancelLogins, isLoginLink, isSigningIn, startLogin } from "./remote-login.js";
import { fileRoutes, jsonRoutes } from "./routes.js";
import { forgetSession, signedInAt } from "./sessions.js";

type Query = Record<string, string>;

const PUBLIC_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "public");

const app = express();
app.disable("x-powered-by");
app.use(cors());

/** Express 4 doesn't catch rejected promises from handlers; this passes them to the error handler. */
function handle(fn: (req: Request, res: Response) => Promise<unknown>): RequestHandler {
  return (req, res, next) => fn(req, res).catch(next);
}

function personId(res: Response): number {
  return res.locals.personId as number;
}

// --- Sign-in viewer. Opened in a new tab, so the one-time link is its only credential. ---

app.get("/login/:token", (req, res) => {
  if (!isLoginLink(req.params.token)) {
    res.status(404).type("text").send("This sign-in link has expired. Start again from the app.");
    return;
  }
  res.set({
    "Cache-Control": "no-store",
    // Keeps the link out of Referer headers and stops other sites framing the page.
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy":
      "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
  });
  res.sendFile(join(PUBLIC_DIR, "login.html"));
});
app.use("/static", express.static(PUBLIC_DIR, { index: false }));

// --- Everything below needs an API key. ---

app.use((req, res, next) => {
  identifyPerson(req.get("authorization"), req.get("x-person-id")).then((id) => {
    res.locals.personId = id;
    next();
  }, next);
});

/** Starts a Brightspace sign-in. Open `path` (on this server) in a new tab. */
app.post(
  "/login",
  handle(async (_req, res) => {
    res.status(201).json(await startLogin(personId(res)));
  })
);

/** Whether this person's Brightspace is connected. Poll it while the sign-in tab is open. */
app.get(
  "/session",
  handle(async (_req, res) => {
    const since = await signedInAt(personId(res));
    res.json({ signedIn: since !== null, signedInAt: since, signingIn: isSigningIn(personId(res)) });
  })
);

/** Signs out: forgets the saved Brightspace login and stops any sign-in in progress. */
app.delete(
  "/session",
  handle(async (_req, res) => {
    await cancelLogins(personId(res));
    await forgetSession(personId(res));
    forgetToken(personId(res));
    res.status(204).end();
  })
);

// --- Brightspace data ---

// Values the server looks up itself so the app doesn't have to pass them.
const lookups: Record<string, (personId: number) => Promise<string>> = {
  "{me}": async (personId) => {
    const me = (await getJson(personId, `${LP}/users/whoami`)) as { Identifier: string };
    return me.Identifier;
  },
  "{courses}": async (personId) => {
    const enrollments = (await getJson(personId, jsonRoutes["/courses"])) as { OrgUnit: { Id: number } }[];
    return enrollments.map((e) => e.OrgUnit.Id).join(",");
  },
};

/** Fills a route template's ":params" from the request and its "{lookups}" from Brightspace. */
async function brightspacePath(personId: number, template: string, params: Record<string, string>): Promise<string> {
  let path = template.replace(/:(\w+)/g, (_, name: string) => {
    const value = params[name];
    // Every route param is a numeric ID; anything else could rewrite the path.
    if (!/^\d+$/.test(value)) throw new ApiError(400, `${name} must be a number`);
    return value;
  });
  for (const [token, lookup] of Object.entries(lookups)) {
    if (path.includes(token)) path = path.replace(token, await lookup(personId));
  }
  return path;
}

function pipeFile(upstream: globalThis.Response, res: Response): void {
  for (const header of ["content-type", "content-length", "content-disposition"]) {
    const value = upstream.headers.get(header);
    if (value) res.setHeader(header, value);
  }
  Readable.fromWeb(upstream.body as never).pipe(res);
}

for (const [route, template] of Object.entries(jsonRoutes)) {
  app.get(
    route,
    handle(async (req, res) => {
      const path = await brightspacePath(personId(res), template, req.params);
      res.json(await getJson(personId(res), path, req.query as Query));
    })
  );
}

for (const [route, template] of Object.entries(fileRoutes)) {
  app.get(
    route,
    handle(async (req, res) => {
      const path = await brightspacePath(personId(res), template, req.params);
      pipeFile(await d2lFetch(personId(res), path, req.query as Query), res);
    })
  );
}

// Any other Brightspace API GET, e.g. /raw/le/1.100/123/quizzes/
app.get(
  "/raw/*",
  handle(async (req, res) => {
    const path = (req.params as Record<string, string>)[0];
    const upstream = await d2lFetch(personId(res), path, req.query as Query);
    if (upstream.headers.get("content-type")?.includes("json")) {
      res.json(await upstream.json());
    } else {
      pipeFile(upstream, res);
    }
  })
);

app.use((error: Error, _req: Request, res: Response, _next: NextFunction) => {
  const status = error instanceof ApiError ? error.status : 500;
  const code = error instanceof ApiError ? error.code : undefined;
  if (status >= 500 || code === "brightspace_error") console.error(`[d3l] ${status}: ${error.message}`);
  res.status(status).json({ error: error.message, code });
});

const server = app.listen(PORT, () => {
  console.error(`d3l listening on http://localhost:${PORT}`);
  startKeepAlive();
});
acceptViewers(server);

async function shutDown(): Promise<void> {
  server.close();
  await closeBrowser().catch(() => {});
  await pool.end().catch(() => {});
  process.exit(0);
}
process.on("SIGTERM", shutDown);
process.on("SIGINT", shutDown);
