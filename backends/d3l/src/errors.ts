/** An error with the HTTP status to send back. `code` lets apps tell failures apart. */
export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

export function signInRequired(): ApiError {
  return new ApiError(401, "This person needs to sign in to Brightspace (POST /login)", "signin_required");
}

/** Brightspace or the school's login site is down or answering oddly. */
export function brightspaceUnavailable(detail: string): ApiError {
  return new ApiError(503, `Brightspace isn't answering properly right now (${detail})`, "brightspace_unavailable");
}
