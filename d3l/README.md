# d3l

A JSON API over students' Brightspace (D2L) data. Each person signs in to Brightspace once,
and d3l keeps their session alive and fetches their data for the app and the mirror.

It forwards requests to the [Brightspace API](https://docs.valence.desire2learn.com/reference.html)
as that person. Responses come back exactly as Brightspace sends them, with paged results merged
into a single array.

## Setup

d3l needs the Sumirrorize database running (see [../db/README.md](../db/README.md)).

```bash
cp .env.example .env   # fill in every value
```

Then either run it in Docker (works anywhere, including servers without a desktop):

```bash
cd .. && docker compose --profile d3l up -d --build   # http://localhost:3100
```

or directly (needs a machine Chromium can run on, e.g. your laptop):

```bash
npm install            # also downloads Chromium
npm run dev            # http://localhost:3100
```

## Who's asking

Every request needs an `Authorization: Bearer <key>` header, in one of two forms:

| Caller | Sends | Gets |
|---|---|---|
| A person's app | their own API key (made when they signed up; see `db/README.md`) | that person's data |
| The mirror's backend | `SERVICE_API_KEY` plus `X-Person-Id: <person_id>` | any person's data |

Errors come back as `{ "error": "...", "code": "..." }`. Codes worth handling:

| Code | Status | Meaning |
|---|---|---|
| `bad_api_key` | 401 | Missing or wrong key |
| `bad_person_id` | 400/404 | Service key used without a valid `X-Person-Id` |
| `signin_required` | 401 | This person isn't signed in to Brightspace (or their session ended) |
| `brightspace_error` | varies | Brightspace said no, e.g. `403` for a course whose access has ended |
| `busy` | 503 | Too many sign-ins in progress at once |

## Signing in to Brightspace

School logins (SSO and MFA) need a real browser, and our site can't read cookies that
Brightspace puts in the student's own browser. So the browser runs inside d3l, and the student
uses it through a tab that shows its screen and passes their clicks and typing back.

1. The app calls `POST /login` and gets back `{ "path": "/login/<one-time token>", "expiresAt": ... }`.
2. The app opens `<d3l address><path>` in a new tab (`window.open`). The student signs in there
   as usual. The link is the tab's only credential: it works in one tab at a time, expires
   after 10 minutes, and stops working once used.
3. When Brightspace is reached, d3l saves the session (encrypted) for that person, and the tab
   says they're signed in and closes itself.
4. Meanwhile the app polls `GET /session` until `signedIn` is `true`.

| Route | What |
|---|---|
| `POST /login` | Start a sign-in. Starting another one cancels the first |
| `GET /session` | `{ signedIn, signedInAt, signingIn }` |
| `DELETE /session` | Sign out: forget the saved session and cancel any sign-in in progress |

After that, d3l renews everyone's session every 30 minutes, so it never reaches Brightspace's
3-hour idle timeout. If a session ends anyway, d3l first tries to renew it in the background
with the saved school login. If that fails, the person's requests return `signin_required` and
they need to sign in again.

## Data routes

All are `GET`. `:ou` is a course ID from `/courses` (`OrgUnit.Id`).

| Route | What |
|---|---|
| `/me`, `/profile`, `/profile/image` | Who you are |
| `/courses` | Enrolled courses |
| `/calendar?startDateTime=…&endDateTime=…` | Calendar events across all courses (dates required, ISO 8601) |
| `/items`, `/due`, `/overdue` | Content items, upcoming due, and overdue items across all courses |
| `/awards`, `/locker` | Badges/certificates, personal file locker |
| `/courses/:ou/announcements` | Announcements |
| `/courses/:ou/updates` | Unread counts (feedback, discussions, quizzes) |
| `/courses/:ou/calendar?startDateTime=…&endDateTime=…` | One course's events |
| `/courses/:ou/grades` | Your grades |
| `/courses/:ou/grades/final` | Final grade (404 until released) |
| `/courses/:ou/grades/items`, `/grades/categories` | Grade items and categories |
| `/courses/:ou/assignments[/:id]` | Assignments |
| `/courses/:ou/assignments/:id/submissions` | Your submissions and feedback |
| `/courses/:ou/content` | Full content tree |
| `/courses/:ou/content/progress` | Completed / required item counts |
| `/courses/:ou/content/modules[/:id]`, `/content/topics/:id` | Content by module or topic |
| `/courses/:ou/quizzes[/:id]`, `/surveys`, `/checklists` | Quizzes, surveys, checklists |
| `/courses/:ou/discussions` | Forums |
| `/courses/:ou/discussions/:forum/topics[/:topic/posts]` | Topics and posts |
| `/courses/:ou/classlist`, `/groups` | Classmates, groups |

File downloads (streamed with the original filename and type):

| Route |
|---|
| `/courses/:ou/image` |
| `/courses/:ou/content/topics/:id/file` |
| `/courses/:ou/announcements/:id/attachments/:file` |
| `/courses/:ou/assignments/:id/attachments/:file` |
| `/courses/:ou/assignments/:id/submissions/:submission/files/:file` |

Cross-course routes default to all your courses; pass `orgUnitIdsCSV=1,2,3` to narrow them.
Any other query string is passed straight to Brightspace.

### Anything else

`/raw/<path>` forwards a GET to `https://<D2L_HOST>/d2l/api/<path>`, e.g.
`/raw/le/1.100/12345/news/`. Use it to try endpoints before adding them to `src/routes.ts`.

## Adding a route

Add one line to `src/routes.ts`: app path on the left, Brightspace path on the right.
Every `:param` must be a numeric ID.

## Files

| File | What |
|---|---|
| `src/index.ts` | Routes and startup |
| `src/callers.ts` | Works out which person a request is for |
| `src/remote-login.ts` | The sign-in tab: runs the browser and streams it |
| `public/login.*` | The sign-in tab's page |
| `src/auth.ts` | Turns saved sessions into API tokens and keeps them alive |
| `src/sessions.ts`, `src/vault.ts` | Saving sessions in the database, encrypted |
| `src/browser.ts` | The shared headless Chromium and background re-login |
| `src/client.ts` | Calls Brightspace and merges paged results |
