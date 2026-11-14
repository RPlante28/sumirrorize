#!/usr/bin/env node
import express, { NextFunction, Request, Response } from "express";
import cors from "cors";
import { Readable } from "node:stream";
import { API_KEY, LP, PORT } from "./config.js";
import { startKeepAlive } from "./auth.js";
import { D2LError, d2lFetch, getJson } from "./client.js";
import { fileRoutes, jsonRoutes } from "./routes.js";

type Query = Record<string, string>;

const app = express();
app.use(cors());

app.use((req, res, next) => {
  if (!API_KEY || req.get("authorization") === `Bearer ${API_KEY}`) return next();
  res.status(401).json({ error: "Missing or wrong API key" });
});

// Values the server looks up itself so the app doesn't have to pass them.
const lookups: Record<string, () => Promise<string>> = {
  "{me}": async () => {
    const me = (await getJson(`${LP}/users/whoami`)) as { Identifier: string };
    return me.Identifier;
  },
  "{courses}": async () => {
    const enrollments = (await getJson(jsonRoutes["/courses"])) as { OrgUnit: { Id: number } }[];
    return enrollments.map((e) => e.OrgUnit.Id).join(",");
  },
};

/** Fills a route template's ":params" from the request and its "{lookups}" from Brightspace. */
async function brightspacePath(template: string, params: Record<string, string>): Promise<string> {
  let path = template.replace(/:(\w+)/g, (_, name: string) => {
    const value = params[name];
    // Every route param is a numeric ID; anything else could rewrite the path.
    if (!/^\d+$/.test(value)) throw new D2LError(400, `${name} must be a number`);
    return value;
  });
  for (const [token, lookup] of Object.entries(lookups)) {
    if (path.includes(token)) path = path.replace(token, await lookup());
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
  app.get(route, async (req, res, next) => {
    try {
      res.json(await getJson(await brightspacePath(template, req.params), req.query as Query));
    } catch (error) {
      next(error);
    }
  });
}

for (const [route, template] of Object.entries(fileRoutes)) {
  app.get(route, async (req, res, next) => {
    try {
      pipeFile(await d2lFetch(await brightspacePath(template, req.params), req.query as Query), res);
    } catch (error) {
      next(error);
    }
  });
}

// Any other Brightspace API GET, e.g. /raw/le/1.100/123/quizzes/
app.get("/raw/*", async (req, res, next) => {
  try {
    const path = (req.params as Record<string, string>)[0];
    const upstream = await d2lFetch(path, req.query as Query);
    if (upstream.headers.get("content-type")?.includes("json")) {
      res.json(await upstream.json());
    } else {
      pipeFile(upstream, res);
    }
  } catch (error) {
    next(error);
  }
});

app.use((error: Error, _req: Request, res: Response, _next: NextFunction) => {
  const status = error instanceof D2LError ? error.status : 500;
  console.error(`[d3l] ${status}: ${error.message}`);
  res.status(status).json({ error: error.message });
});

app.listen(PORT, () => {
  console.error(`d3l listening on http://localhost:${PORT}`);
  startKeepAlive();
  if (!API_KEY) console.error("[d3l] API_KEY is not set: anyone who can reach this port can read your Brightspace data");
});
