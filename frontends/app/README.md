# Sign-up app

Where people set up their mirror, at **https://sumirrorize-api.marist.dev**. They:

1. **Sign in with Google.** Their first sign-in creates them in the database. Google also asks
   whether Sumirrorize may see their calendar events, so the mirror can show them.
2. **Take pictures of their face** from five angles (front, left, right, up, down). The faces
   service checks each one, and if one isn't good enough (too dark, too far away, nobody in it,
   someone else in it), the page says which to retake and why.
3. **Connect Brightspace.** This opens d3l's sign-in tab, where they sign in to Marist as usual.
4. **Pick their settings:** weather in Fahrenheit or Celsius, and an API key for their own apps if they want one.

After that, stepping up to the mirror at https://sumirrorize.marist.dev shows their day.

It's a small Flask server that renders its own pages (from your friend's design in `templates/`
and `static/`). It doesn't store anything itself:

```
 browser --> app --> Postgres: people, settings, API keys
               +--> faces: save face pictures (only faces touches face data)
               +--> d3l: start a Brightspace sign-in, check or end it
 browser --> d3l sign-in tab (/api/login/<one-time link>)
```

## Sharing an address with d3l

The app and d3l both live at `sumirrorize-api.marist.dev`. Traefik sends `/api/...` to d3l (with
`/api` removed, so `/api/due` reaches d3l's `/due`) and everything else to the app. So:

- **The app:** `/`, `/faces`, `/login` and `/login/callback` (Google), `/me/...`
- **d3l:** `/api/login/<token>` (the Brightspace sign-in tab) and its data routes for people's
  own API keys, e.g. `curl -H "Authorization: Bearer <key>" https://sumirrorize-api.marist.dev/api/due`

## Running it

On the server it runs in the `sumirrorize` stack (`/opt/containers/sumirrorize`), which needs
`APP_SECRET_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_TOKEN_KEY` in its `.env`.

Locally, from the repo root, with d3l and faces (needs `frontends/app/.env`, see below):

```bash
docker compose --profile d3l --profile mirror --profile app up -d --build   # http://localhost:3500
```

Directly, for development:

```bash
cd frontends/app
cp .env.example .env            # fill in every value
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest      # tests use a fake database, Google, d3l and faces
set -a && . ./.env && set +a && .venv/bin/flask --app 'app.main:create_app()' run --port 3500
```

### Google sign-in

The Google OAuth client (Google Cloud Console -> APIs & Services -> Credentials) must list
`<APP_PUBLIC_URL>/login/callback` as an authorized redirect URI: on the server,
`https://sumirrorize-api.marist.dev/login/callback`, and `http://localhost:3500/login/callback`
for running locally. The app asks Google for the account's ID and name (not their email) and
for read-only access to their calendar events.

### Google Calendar

Signing in also asks for `calendar.events.readonly`. For that to work, the Google Cloud project
needs the **Google Calendar API enabled** (APIs & Services -> Library) and the scope added to the
OAuth consent screen. Until Google has verified the app, people see a "Google hasn't verified
this app" page first and have to click through it.

- If they agree, Google hands over a *refresh token*, which the app encrypts with
  `GOOGLE_TOKEN_KEY` and saves in the `google_calendar` table. The mirror backend has the same
  key and uses the token to read their main calendar.
- Google only hands the token over when it has just asked the person. So someone who said no,
  or disconnected, uses the **Connect Google Calendar** button on the settings page, which
  makes Google ask again.
- **Disconnect** tells Google to take the access away and deletes the saved token.

## Routes

Pages: `/` (sign-in, or settings once signed in), `/faces` (face pictures).

The pages call these, with the login cookie. Errors look like `{"error": "...", "code": "..."}`.

| Route | What |
|---|---|
| `PUT /me/faces` | `{"pictures": [{"angle": "front", "image": "data:image/jpeg;base64,..."}]}`, passed to the faces service. A `422` with `"code": "poor_pictures"` lists each picture's problem |
| `POST /me/brightspace` | Starts a Brightspace sign-in: `{"url": <sign-in tab>, "expiresAt": ...}` |
| `GET /me/brightspace` | `{signedIn, signedInAt, signingIn}`, polled while the sign-in tab is open |
| `DELETE /me/brightspace` | Disconnects Brightspace |
| `PUT /me/units` | `{"units": "imperial"}` or `"metric"`: the mirror's weather units |
| `DELETE /me/calendar` | Disconnects Google Calendar. To connect, send the browser to `/login?calendar=1` |
| `POST /me/api-key` | Makes a new API key (`{"apiKey": ...}`), shown once. The old one stops working |
| `DELETE /me` | Deletes the account: face pictures, Brightspace login, calendar access, settings |
| `POST /logout` | Signs out |

## Security

- **Login cookie:** signed with `APP_SECRET_KEY`, HTTPS-only, hidden from page scripts, and not
  sent by other sites' forms or fetches.
- **Changes only from our own pages:** every `POST`/`PUT`/`DELETE` must carry our address in its
  `Origin` header, which browsers set themselves, so another site can't make changes using
  someone's login.
- **Strict page rules:** pages only run scripts and styles from this app, can't be shown inside
  another site, and may use the camera only on this site.
- **No secrets in the browser:** the d3l and faces keys stay on the server. The browser gets only
  the one-time Brightspace sign-in link and, if asked for, the person's own API key (once).
- **Deleting an account** removes everything about the person: their face pictures and
  fingerprints, saved Brightspace login and settings.

## Files

| File | What |
|---|---|
| `app/main.py` | Routes, Google sign-in, safety checks |
| `app/store.py` | People, settings and API keys in Postgres |
| `app/services.py` | Calls to d3l and faces |
| `app/vault.py` | Encrypting Google Calendar tokens |
| `templates/` | The pages (sign-in, settings, face pictures, errors) |
| `static/settings.js` | Brightspace connect, units, API key and account buttons |
| `static/faces.js` | Taking, checking and sending the face pictures |
| `tests/` | Tests with a fake database, Google, d3l and faces |
