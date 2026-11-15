# The `db` branch

This branch adds two things:

1. **A Postgres database** for people, their face pictures, and their mirror widget layouts.
2. **Multi-person d3l.** d3l used to serve one Brightspace account. Now every person signs in
   with their own account through a tab in the app, and d3l keeps everyone's session alive.

Details live next to the code: [db/README.md](db/README.md) for the tables and queries,
[backends/d3l/README.md](backends/d3l/README.md) for the API. This page covers how it fits together, how to run
and deploy it, what the frontends need to do, and the drawbacks.

## How it fits together

```
 phone-app frontend ──(person's API key)──┐
                                          ├──> d3l ──> brightspace.marist.edu
 mirror backend ──(service key + id)──────┘     │
        │                                       │
        └──────────────> Postgres <─────────────┘
                 people, pictures, widgets,
                 saved Brightspace logins (encrypted)
```

- **Postgres** holds everything. A new person automatically gets every widget at its default
  position.
- **d3l** reads Brightspace for a person. It's the only thing that touches saved Brightspace
  logins.
- **Phone-app frontend/backend** (not built yet) creates people, uploads pictures, saves widget
  layouts, and starts Brightspace sign-ins.
- **Mirror backend** (not built yet) recognizes a face, then loads that person's widgets and data.

## Running it locally

Each teammate runs their own copy. From the repo root:

```bash
cp .env.example .env            # set POSTGRES_PASSWORD to anything
docker compose up -d            # the database and the weather service
```

To run d3l too:

```bash
cp backends/d3l/.env.example backends/d3l/.env    # D2L_HOST=brightspace.marist.edu, and generate the two keys
docker compose --profile d3l up -d --build      # d3l on http://localhost:3100
```

The d3l image is about 2 GB because it includes a browser. On a laptop you can skip Docker for
d3l: `cd backends/d3l && npm install && npm run dev`.

**Changing the schema:** edit `db/init/`, then reset your local database with
`docker compose down -v && docker compose up -d`. This deletes your local data.

## Server deployment

Runs from `/opt/containers/sumirrorize/` (not in this repo). That stack builds d3l from this
checkout at `/home/nathan1/projects/sumirrorize`.

| Container | What | Reachable at |
|---|---|---|
| `sumirrorize-db` | Postgres + pgvector | `sumirrorize-db:5432` on the `sumirrorize` Docker network only |
| `sumirrorize-d3l` | d3l | `https://sumirrorize-api.marist.dev/api` (Cloudflare tunnel → Traefik), and `http://sumirrorize-d3l:3100` on the `sumirrorize` network |

- **Public hostname:** `sumirrorize-api.marist.dev` needs a Public Hostname in the Cloudflare
  tunnel pointing at `http://traefik:80`, like every other site. Traefik picks the route up from
  d3l's container labels. WebSockets (used by the sign-in tab) pass through both without any
  extra setup.
- **Secrets** are in `/opt/containers/sumirrorize/.env`:
  - `POSTGRES_PASSWORD`
  - `SERVICE_API_KEY`: give this to the mirror backend.
  - `SESSION_ENCRYPTION_KEY`: losing or changing it signs everyone out of Brightspace.
- **After pulling new d3l code:**
  `docker compose -f /opt/containers/sumirrorize/docker-compose.yml up -d --build sumirrorize-d3l`
- **Other containers** (the frontends and backends) should join the `sumirrorize` network to
  reach the database and d3l.
- **Database admin:** `docker exec -it sumirrorize-db psql -U sumirrorize`
- **Schema changes on the server:** `db/init/` only runs on an empty database. Until there's
  data worth keeping, apply a new file by hand
  (`docker exec -i sumirrorize-db psql -U sumirrorize < db/init/00X_new.sql`), or wipe and
  recreate the volume. Once real people sign up, we need proper migrations.

## For the phone-app frontend/backend

> **Since this branch:** this is built now. The sign-up app ([frontends/app](frontends/app/README.md))
> creates people on their first Google sign-in and has the Connect Brightspace button. It took
> over `sumirrorize-api.marist.dev`, and d3l moved under `/api/` there (the addresses below are
> updated to match).

### Creating a person

Nothing does this yet. The backend should do it when someone submits their name and pictures,
in one transaction:

```python
api_key = secrets.token_urlsafe(32)                 # give this to the person's app, once
key_hash = hashlib.sha256(api_key.encode()).digest()
# INSERT INTO person (display_name, api_key_hash) VALUES (%s, %s) RETURNING person_id
# then insert their pictures: see db/README.md
```

The database stores only the hash, so a lost key can't be recovered. To make a new one, update
`person.api_key_hash` with the new key's hash.

### The "Connect Brightspace" button

```js
const D3L = "https://sumirrorize-api.marist.dev/api";   // http://localhost:3100 locally

async function connectBrightspace(apiKey) {
  // Open the tab right away, inside the click handler. Opening it after an `await` gets it
  // blocked as a pop-up.
  const tab = window.open("about:blank", "_blank");
  const headers = { Authorization: `Bearer ${apiKey}` };

  const { path } = await (await fetch(`${D3L}/login`, { method: "POST", headers })).json();
  tab.location = D3L + path;

  // The tab closes itself once the student is signed in. Poll until then.
  while (true) {
    await new Promise((r) => setTimeout(r, 2000));
    const session = await (await fetch(`${D3L}/session`, { headers })).json();
    if (session.signedIn) return true;      // connected
    if (!session.signingIn) return false;   // timed out, or the student gave up
  }
}
```

In the tab, the student sees Brightspace's Marist page. They click **Marist SSO**, then log in
on Marist's page as usual, MFA included. The link works for 10 minutes, in one tab only.

- **Status:** `GET /session` returns `{ signedIn, signedInAt, signingIn }`. Show "Connect" or
  "Connected" based on it.
- **Sign out:** `DELETE /session`.
- **Errors:** any data request can return `{"code": "signin_required"}`. Show the Connect button
  again when it does.

## For the mirror backend

Send `Authorization: Bearer <SERVICE_API_KEY>` plus `X-Person-Id: <person_id>` to any d3l route,
e.g. `GET http://sumirrorize-d3l:3100/due`. Read the database directly for face matching and the
layout. [db/README.md](db/README.md) has the ready-made queries.

## Testing a real Marist sign-in

Done once on the server (see below). To repeat it:

```bash
# Make a test person (pick any long random key)
docker exec sumirrorize-db psql -U sumirrorize -c \
  "INSERT INTO person (display_name, api_key_hash) VALUES ('Test', sha256('my-long-test-key')) RETURNING person_id"

curl -X POST -H "Authorization: Bearer my-long-test-key" https://sumirrorize-api.marist.dev/api/login
# open https://sumirrorize-api.marist.dev/api<path from the reply> in a browser and sign in

curl -H "Authorization: Bearer my-long-test-key" https://sumirrorize-api.marist.dev/api/session
curl -H "Authorization: Bearer my-long-test-key" https://sumirrorize-api.marist.dev/api/due

# Clean up
docker exec sumirrorize-db psql -U sumirrorize -c "DELETE FROM person WHERE display_name = 'Test'"
```

## What's been tested

- **Database:** every rule, checked against a throwaway database. That covers automatic widget
  rows, replacing picture sets, face matching, saving layouts, rejecting bad data, and deleting
  a person.
- **d3l, end to end, against a fake Brightspace:** wrong keys, one-time links, typing and pasting
  into the login form, saving the login encrypted, reading data with both kinds of key, and an
  ended session being cleaned up. A second browser also clicked and typed into the real sign-in
  tab.
- **On the server, through Traefik:** the tab streams Marist's real login page from the
  locked-down container.
- **A real Marist sign-in, end to end** (Nov 14), through `sumirrorize-api.marist.dev`:
  Marist SSO, Duo, then reading real data. `/me`, `/courses`, `/due`, `/overdue` and
  `/calendar` all returned data in under 2 seconds, and the saved login was confirmed
  encrypted in the database.
- **Not tested yet:** a session surviving past Brightspace's 3-hour idle timeout on the
  keep-alive alone. It works against the fake Brightspace, but hasn't been tried against
  Marist over that long.

## Drawbacks and things to know

**Security**
- **Typing passes through the server.** Passwords go through d3l on their way to Marist's login
  page. They aren't saved or logged, but students are trusting the server with them.
- **The sign-in browser can go elsewhere.** It's a real browser, so a student could click away
  from the login page and browse other sites for up to 10 minutes. It needs a valid API key, and
  at most 4 sign-ins run at once.
- **Saved logins work like passwords.** Anyone holding one is signed in to that student's
  Brightspace. They're encrypted with `SESSION_ENCRYPTION_KEY`, which lives outside the
  database, so a database leak alone doesn't expose them.
- **The database holds students' face photos.** It isn't reachable from the internet. Deleting a
  person deletes their pictures, widgets and login.
- **Open CORS.** Any website can call d3l, but only with a valid key.

**Brightspace**
- **Unofficial login method.** d3l gets API access the same way the Brightspace website does,
  not as an app registered with Marist. If D2L changes how their website logs in, d3l breaks
  until it's updated.
- **Sessions can still end.** d3l renews everyone's session every 30 minutes. If one ends anyway
  (password change, Marist ending the session), d3l tries a silent background re-login first.
  If that fails, the student has to click Connect again.
- **School logins may change.** Some identity providers block automated browsers. Marist's login
  page currently loads fine in it.

**The sign-in tab**
- **Duo options.** Duo Push and typed passcodes work. Touch ID, Windows Hello and security
  keys don't, because they need hardware on the computer running the browser, which is the
  server. Students offered one of those should pick "Other options" and choose Push or Passcode.
- **Desktop only.** A phone's on-screen keyboard won't open in the tab, so the phone-app
  simulator should run on a computer for the demo.
- **Some page elements don't show.** Dropdown menus (`<select>`) don't appear in the stream.
  Marist's login page doesn't use them.

**Running it**
- **Restarts cancel sign-ins.** In-progress sign-ins live in d3l's memory, so a restart cancels
  them. Saved logins survive.
- **One copy of d3l only.** Because of that in-memory state, d3l can't run as several copies.
  That's fine for the demo.
- **No migrations yet.** Schema changes currently mean resetting the database (see above).
- **Face fingerprint size is fixed.** `picture.face_encoding` holds 128 numbers, which is what
  the `face_recognition` library produces. If the team settles on a model with a different size,
  change `vector(128)` to match.
- **Big image.** The d3l Docker image is about 2 GB, because Playwright's base image includes
  several browsers.

## Troubleshooting

| Problem | Likely cause |
|---|---|
| `bad_api_key` | Wrong or missing `Authorization` header, or the person was deleted |
| `signin_required` | That person hasn't connected Brightspace, or their session ended |
| Sign-in tab says "already open in another tab" | The link is already open somewhere; start a new sign-in |
| Sign-in tab says "lost connection" | d3l restarted, or the 10 minutes ran out; start again |
| d3l won't start | A setting in `.env` is missing; the log names it (`docker logs sumirrorize-d3l`) |
| Public URL gives a Cloudflare error | The tunnel's Public Hostname isn't set up, or d3l is down |
