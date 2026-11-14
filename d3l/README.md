# d3l

A small JSON API over one student's Brightspace (D2L) data, for a phone app to read from.

It forwards requests to the [Brightspace API](https://docs.valence.desire2learn.com/reference.html)
as you. Responses come back exactly as Brightspace sends them, with paged results merged into a
single array.

## Setup

```bash
npm install
cp .env.example .env   # set D2L_HOST and API_KEY
npm run build
npm run login          # opens a browser: sign in once, including MFA
npm start              # http://localhost:3100
```

The app must send `Authorization: Bearer <API_KEY>` with every request.

## How sign-in works

1. `npm run login` signs in with a real browser once (so SSO and MFA work) and saves the
   session cookies to `~/.d3l-cookies.json`. Anyone with that file is signed in as you.
2. The server gets 60-minute API tokens with plain HTTP requests using those cookies, the same
   way the Brightspace website does. No browser.
3. Every 30 minutes it renews the token, so the session never reaches Brightspace's 180-minute
   idle timeout. Restarts reuse the cookies.
4. If the session ends anyway, it signs in again, cheapest way first:
   - Saved cookies in a headless browser. This works without a password while your school's
     login (SSO) session is still alive.
   - `D2L_USERNAME`/`D2L_PASSWORD` if set. MFA prompts can't be answered this way.
   - A visible browser window, if the machine has a display.

   If none of these works, run `npm run login` again.

## Routes

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

Courses whose access has ended return `403`. That is Brightspace refusing, not a bug.

## Adding a route

Add one line to `src/routes.ts`: app path on the left, Brightspace path on the right.
Every `:param` must be a numeric ID.
