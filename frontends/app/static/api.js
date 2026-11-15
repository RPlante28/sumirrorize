// Calls the app's own JSON routes (/me/...). Errors come back as { error, code, ... }.

export class ApiError extends Error {
  constructor(status, body) {
    super(body.error || "Something went wrong, try again");
    this.status = status;
    this.code = body.code;
    this.body = body;
  }
}

export async function api(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, { error: "Can't reach Sumirrorize. Check your connection and try again.", code: "offline" });
  }
  if (response.status === 401) {
    // signed out (e.g. in another tab), start over
    location.href = "/";
    throw new ApiError(401, { error: "Signed out", code: "signed_out" });
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}

export function show(element, text) {
  element.textContent = text;
  element.hidden = false;
}

export function hide(...elements) {
  for (const element of elements) element.hidden = true;
}
