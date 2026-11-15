# Database

Postgres 18 with [pgvector](https://github.com/pgvector/pgvector) (for matching faces).
The tables are created by the files in `init/`, in name order.

## Running it locally

From the repo root:

```bash
cp .env.example .env          # set POSTGRES_PASSWORD to anything
docker compose up -d
docker compose exec db psql -U sumirrorize   # poke around
```

Apps connect with `postgresql://sumirrorize:<password>@localhost:5432/sumirrorize`.

### Changing the schema

Postgres only runs `init/` when its data is empty, in name order. So **add a new numbered
file** (e.g. `005_something.sql`) rather than editing an old one. A fresh database runs it
along with the rest. An existing one (the server, or your local copy) needs it run by hand:

```bash
docker exec -i sumirrorize-db psql -U sumirrorize < db/init/005_something.sql   # server
docker compose exec -T db psql -U sumirrorize < db/init/005_something.sql       # local
```

Write these files so running them twice is harmless (`ON CONFLICT DO NOTHING`, `IF NOT EXISTS`).
Or, while your local data doesn't matter, wipe it and start fresh:
`docker compose down -v && docker compose up -d`.

| File | What |
|---|---|
| `001_schema.sql` | The tables |
| `002_widgets.sql` | The original widgets |
| `003_brightspace_session.sql` | d3l's saved Brightspace logins |
| `004_announcements_and_layout.sql` | The announcements widget, and a default layout that keeps the middle clear |
| `005_google_accounts.sql` | Links each person to the Google account they sign in to the app with |
| `006_google_calendar.sql` | Saved Google Calendar access |

Once there are many of these, a migration tool that tracks which files have run would be worth it
(Alembic fits Python).

## Tables

```
person --< picture          any number, each labeled with its angle (front, left, ...)
   |
   +----< person_widget >-- widget
   |      (one row per person per widget: on/off, position, settings)
   |
   +----  brightspace_session   (at most one; managed by d3l)
   |
   +----  google_calendar       (at most one; written by the sign-up app)
```

| Table | What it holds |
|---|---|
| `person` | `person_id`, `display_name`, `api_key_hash` (the SHA-256 of their API key; the key itself is never stored), and `google_sub`: the ID of the Google account they sign in to the app with. |
| `picture` | `pic_id`, `person_id`, `angle` (any lowercase label, e.g. `front`), the `image` bytes, `mime_type`, and `face_encoding`: the face's fingerprint, 128 numbers from OpenCV's SFace model. A new upload replaces the person's whole set. Only the [faces service](../backends/faces/README.md) reads or writes this table; save faces through it rather than inserting rows yourself. |
| `widget` | The widgets the mirror offers (`clock`, `greeting`, `summary`, `weather`, `calendar`, `assignments`, `announcements`), each with a description and a default layout. |
| `person_widget` | One row per person per widget: `enabled`, position `x`, `y`, `w`, `h`, and `settings` (JSON, e.g. `{"units": "metric", "variant": "hourly"}`). |
| `brightspace_session` | The person's saved Brightspace login, encrypted by d3l. Only d3l reads or writes it; ask d3l (`GET /session`) whether someone is signed in. |
| `google_calendar` | The person's Google Calendar refresh token, encrypted by the sign-up app. The mirror backend reads it to fetch their events. A row exists only while their calendar is connected. |

Positions are fractions of the screen: `(0, 0)` is the top-left corner and `(1, 1)` the
bottom-right. `x`/`y` is the widget's top-left corner and `w`/`h` its size, so a layout
looks the same on any screen. The database refuses a widget that runs off the screen.

Things the database does for you:
- A new person automatically gets every widget at its default position.
- A newly added widget type is given to everyone who already exists.
- Deleting a person deletes their pictures, widgets, Brightspace login and calendar access.
- `updated_at` is set automatically on every change.

## Face photos are stored

The `picture` table keeps each sign-up photo itself (`image`) next to its fingerprint
(`face_encoding`). **Nothing reads the photos back:** recognition only compares fingerprints.
They're kept so fingerprints could be remade if the face model ever changes.

That means anyone who gets a copy of the database gets everyone's face photos. For the demo
that's accepted. Before real use, stop storing them: have the faces service save only the
fingerprint, and make `image` and `mime_type` optional (or drop them) in a new migration. A
model change would then mean asking people to retake their pictures.

## Common queries

**Sign up** (the [sign-up app](../frontends/app/README.md) does this on someone's first Google
sign-in; their widgets are created automatically):
```sql
INSERT INTO person (display_name, api_key_hash, google_sub) VALUES ($1, $2, $3) RETURNING person_id;
```
Keys are made with `secrets.token_urlsafe(32)` and stored as `hashlib.sha256(key.encode()).digest()`.
The person sees the key once, when they ask the app for one.

**Face pictures:** don't write these yourself. Send them to the faces service
(`PUT /people/{id}/faces`), which checks each photo, makes its fingerprint, and replaces the
person's set in one transaction. Recognition is `POST /identify` on the same service, which
compares fingerprints by cosine similarity (pgvector's `<=>`). See
[backends/faces/README.md](../backends/faces/README.md).

**Who does this API key belong to?**
```sql
SELECT person_id, display_name FROM person WHERE api_key_hash = $1;
```

**Load someone's mirror:**
```sql
SELECT pw.widget_key, w.name, pw.x, pw.y, pw.w, pw.h, pw.settings
FROM person_widget pw JOIN widget w USING (widget_key)
WHERE pw.person_id = $1 AND pw.enabled;
```

**Save a layout** (every widget the user moved, in one statement):
```sql
UPDATE person_widget pw
SET x = v.x, y = v.y, w = v.w, h = v.h, enabled = v.enabled
FROM (VALUES ('clock', 0.5, 0.1, 0.25, 0.12, true),
             ('weather', 0.0, 0.0, 0.25, 0.15, false))
     AS v(widget_key, x, y, w, h, enabled)
WHERE pw.person_id = $1 AND pw.widget_key = v.widget_key;
```

## Adding a widget type

Add an `INSERT INTO widget ... ON CONFLICT (widget_key) DO NOTHING` in a new numbered file in
`init/` (see `004_announcements_and_layout.sql`), and run it on existing databases. Everyone
who already exists gets the widget automatically, at its default position.
