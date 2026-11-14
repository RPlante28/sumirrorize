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

Postgres only runs `init/` when its data is empty. After editing a file there, wipe
your local copy and start fresh:

```bash
docker compose down -v && docker compose up -d
```

That deletes everything in your local database. Once the server holds real people's
data, this stops being an option and we'll need proper migrations (Alembic fits,
since the backend already uses SQLAlchemy).

## Tables

```
person ──< picture          any number, each labeled with its angle (front, left, ...)
   │
   └────< person_widget >── widget
          (one row per person per widget: on/off, position, settings)
```

| Table | What it holds |
|---|---|
| `person` | `person_id`, `display_name`, and `api_key_hash`: the SHA-256 of their API key. The key itself is never stored. |
| `picture` | `pic_id`, `person_id`, `angle` (any lowercase label, e.g. `front`), the `image` bytes, `mime_type`, and `face_encoding`: the 128 numbers `face_recognition` produces. `face_encoding` is empty if no face was found, which is common for side shots. A new upload replaces the person's whole set. |
| `widget` | The widgets the mirror offers (`clock`, `weather`, `summary`, `greeting`, `calendar`, `assignments`), each with a description and a default layout. |
| `person_widget` | One row per person per widget: `enabled`, position `x`, `y`, `w`, `h`, and `settings` (JSON, e.g. `{"city": "Poughkeepsie"}`). |

Positions are fractions of the screen: `(0, 0)` is the top-left corner and `(1, 1)` the
bottom-right. `x`/`y` is the widget's top-left corner and `w`/`h` its size, so a layout
looks the same on any screen. The database refuses a widget that runs off the screen.

Things the database does for you:
- A new person automatically gets every widget at its default position.
- A newly added widget type is given to everyone who already exists.
- Deleting a person deletes their pictures and widgets.
- `updated_at` is set automatically on every change.

## Common queries

**Sign up** (one transaction; the person's widgets are created automatically):
```sql
INSERT INTO person (display_name, api_key_hash) VALUES ($1, $2) RETURNING person_id;
```
Make the key with `secrets.token_urlsafe(32)`, store `hashlib.sha256(key.encode()).digest()`,
and give the key to the person once.

**Upload or replace a picture set** (one transaction, so the mirror never sees half a set;
for a brand-new person, do the sign-up insert in the same transaction):
```sql
BEGIN;
DELETE FROM picture WHERE person_id = $1;
INSERT INTO picture (person_id, angle, image, mime_type, face_encoding)
VALUES ($1, 'front', $2, $3, $4),
       ($1, 'left',  $5, $6, $7),
       ($1, 'right', $8, $9, $10);   -- as many as were sent
COMMIT;
```

**Who is at the mirror?** (closest stored face; `face_recognition` treats a distance under
about 0.6 as the same person):
```sql
SELECT person_id, face_encoding <-> $1 AS distance
FROM picture
WHERE face_encoding IS NOT NULL
ORDER BY distance
LIMIT 1;
```
In Python, the `pgvector` package lets you pass a numpy array as `$1`.

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

Add a row to `init/002_widgets.sql` (so fresh databases get it) and insert the same row
into any database that's already running. Everyone gets it automatically.
