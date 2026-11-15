# d3l

A JSON API over students' Brightspace (D2L) data. Each person signs in to Brightspace once,
and d3l keeps their session alive and fetches their data for the app and the mirror.

It forwards requests to the [Brightspace API](https://docs.valence.desire2learn.com/reference.html)
as that person. Responses come back exactly as Brightspace sends them, with paged results merged
into a single array.

On the server it's at **https://sumirrorize-api.marist.dev/api/**, sharing the address with the
[sign-up app](../../frontends/app/README.md). Traefik removes the `/api`, so the routes below are
written without it: `/due` is `https://sumirrorize-api.marist.dev/api/due`.

## Setup

d3l needs the Sumirrorize database running (see [../../db/README.md](../../db/README.md)).

```bash
cp .env.example .env   # fill in every value
```

Then either run it in Docker (works anywhere, including servers without a desktop):

```bash
cd ../.. && docker compose --profile d3l up -d --build   # http://localhost:3100
```

or directly (needs a machine Chromium can run on, e.g. your laptop):

```bash
npm install            # also downloads Chromium
npm test               # TypeScript build and security checks
npm run dev            # http://localhost:3100
```

## Who's asking

Every request needs an `Authorization: Bearer <key>` header, in one of two forms:

| Caller | Sends | Gets |
|---|---|---|
| A person's own app | their own API key (from the sign-up app's settings page) | that person's data |
| The sign-up app or the mirror's backend | `SERVICE_API_KEY` plus `X-Person-Id: <person_id>` | any person's data |

Errors come back as `{ "error": "...", "code": "..." }`. Codes worth handling:

| Code | Status | Meaning |
|---|---|---|
| `bad_api_key` | 401 | Missing or wrong key |
| `bad_person_id` | 400/404 | Service key used without a valid `X-Person-Id` |
| `signin_required` | 401 | This person isn't signed in to Brightspace (or their session ended) |
| `brightspace_error` | varies | Brightspace said no, e.g. `403` for a course whose access has ended |
| `brightspace_unavailable` | 503 | Brightspace or the school's login site is down or answering oddly. The person's saved login is kept; try again later |
| `busy` | 503 | Too many sign-ins in progress at once |

## Signing in to Brightspace

School logins (SSO and MFA) need a real browser, and our site can't read cookies that
Brightspace puts in the student's own browser. So the browser runs inside d3l, and the student
uses it through a tab that shows its screen and passes their clicks and typing back.

1. The app calls `POST /login` and gets back `{ "path": "/login/<one-time token>", "expiresAt": ... }`.
2. The app opens `<d3l address><path>` in a new tab (`window.open`). The student signs in there
   as usual, on a computer or a phone. The link is the tab's only credential: it works in one
   tab at a time, expires after 10 minutes, and stops working once used.
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

**A saved login is only deleted when Brightspace says the session has ended,** which it does by
sending the browser to its login page. If Brightspace or the school's login site is down, or
answers with an error or maintenance page, requests return `brightspace_unavailable` and the
login stays saved for when it's back.

### On a phone

The tab is a picture of the remote browser, and phones only bring up their keyboard for a real
text field. So a tap on the picture clicks there and puts the cursor in an invisible text field,
and whatever is typed into it is passed on. Dragging a finger scrolls the remote page.

### What the sign-in browser can reach

It's a real browser on our server, steered by whoever is signing in, so it's fenced in two ways:

- **Only the public internet, over HTTPS.** All its traffic goes through a small proxy inside
  d3l (`src/egress.ts`) that refuses private addresses: this machine, the database, the other
  services, anything else on the server's networks.
- **Only the sign-in sites.** The tab can open pages on Brightspace and on the sites listed in
  `SIGN_IN_HOSTS` (the school's login site, and Duo or similar if it's used). Following a link
  anywhere else does nothing. If signing in stops working at some step, d3l's log names the
  site it blocked; add it to `SIGN_IN_HOSTS`.

## Data routes

All are `GET`. `:ou` is a course ID from `/courses` (`OrgUnit.Id`).

| Route | What |
|---|---|
| `/me`, `/profile`, `/profile/image` | Who you are |
| `/courses` | Enrolled courses |
| `/calendar?startDateTime=...&endDateTime=...` | Calendar events across all courses (dates required, ISO 8601) |
| `/items`, `/due`, `/overdue` | Content items, upcoming due, and overdue items across all courses |
| `/awards`, `/locker` | Badges/certificates, personal file locker |
| `/courses/:ou/announcements` | Announcements |
| `/courses/:ou/updates` | Unread counts (feedback, discussions, quizzes) |
| `/courses/:ou/calendar?startDateTime=...&endDateTime=...` | One course's events |
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
| `public/login.*` | The sign-in tab's page, including phone keyboard and touch handling |
| `src/egress.ts` | The proxy that keeps the sign-in browser on the public internet |
| `src/auth.ts` | Turns saved sessions into API tokens and keeps them alive |
| `src/sessions.ts`, `src/vault.ts` | Saving sessions in the database, encrypted |
| `src/browser.ts` | The shared headless Chromium, which sites it may open, and background re-login |
| `src/client.ts` | Calls Brightspace and merges paged results |
