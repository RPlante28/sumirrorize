import { clearToken, getToken } from "./auth.js";
import { D2L_HOST } from "./config.js";

const MAX_PAGES = 50;

export class D2LError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type PagedResultSet = { PagingInfo: { Bookmark: string; HasMoreItems: boolean }; Items: unknown[] };
type ObjectListPage = { Next: string | null; Objects: unknown[] };

async function send(url: URL, token: string): Promise<Response> {
  return fetch(url, { headers: { Authorization: `Bearer ${token}` } });
}

/** GETs a Brightspace API path (e.g. "le/1.100/123/news/"), re-signing in once if the token was rejected. */
export async function d2lFetch(path: string | URL, query: Record<string, string> = {}): Promise<Response> {
  const url = new URL(path, `https://${D2L_HOST}/d2l/api/`);
  for (const [key, value] of Object.entries(query)) url.searchParams.set(key, value);
  if (url.host !== D2L_HOST.toLowerCase()) throw new D2LError(400, `Refusing to send credentials to ${url.host}`);

  let response = await send(url, await getToken());
  if (response.status === 401) {
    clearToken();
    response = await send(url, await getToken());
  }
  if (!response.ok) {
    throw new D2LError(response.status, `${url.pathname}: ${await response.text()}`);
  }
  return response;
}

/** Like d2lFetch, but parses JSON and flattens Brightspace's two paging formats into one array. */
export async function getJson(path: string, query: Record<string, string> = {}): Promise<unknown> {
  const first = await (await d2lFetch(path, query)).json();

  if (isPagedResultSet(first)) {
    const items = [...first.Items];
    let page = first;
    for (let i = 1; page.PagingInfo.HasMoreItems && i < MAX_PAGES; i++) {
      page = (await (await d2lFetch(path, { ...query, bookmark: page.PagingInfo.Bookmark })).json()) as PagedResultSet;
      items.push(...page.Items);
    }
    return items;
  }

  if (isObjectListPage(first)) {
    const objects = [...first.Objects];
    let page = first;
    for (let i = 1; page.Next && i < MAX_PAGES; i++) {
      page = (await (await d2lFetch(new URL(page.Next))).json()) as ObjectListPage;
      objects.push(...page.Objects);
    }
    return objects;
  }

  return first;
}

function isPagedResultSet(body: unknown): body is PagedResultSet {
  return typeof body === "object" && body !== null && "PagingInfo" in body && "Items" in body;
}

function isObjectListPage(body: unknown): body is ObjectListPage {
  return typeof body === "object" && body !== null && "Next" in body && "Objects" in body;
}
