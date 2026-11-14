# Backends

Each folder is one service with its own container and README.

| Folder | What | Language | Port | Status |
|---|---|---|---|---|
| [`d3l/`](d3l/README.md) | Brightspace data for each person, plus the Brightspace sign-in tab | TypeScript | 3100 | Done |
| [`weather/`](weather/README.md) | Weather for the mirror's location | Python | 3200 | Done |
| [`mirror/`](mirror/README.md) | Gathers a person's widgets and their data for the mirror. Face recognition goes here next | Python | 3300 | Working (person picked from a list) |
| `app/` | The phone app's backend: sign-up, pictures, widget layouts | | | Not started |

How they connect:

```
 frontends/app ──> backends/app ──────────────┐
       │                                      ├──> Postgres (db/)
       └── Brightspace sign-in ──> d3l ───────┘
                                    ^
 frontends/mirror ──> backends/mirror ──> weather
                            │
                            └──> Postgres (faces, widget layouts)
```

- **Mirror backend:** reads d3l with the service key plus `X-Person-Id`, reads weather with the
  person's units setting, and reads face fingerprints and widget layouts straight from the database.
- **App backend:** creates people and their API keys, and saves pictures and layouts in the
  database. The app frontend talks to d3l directly for Brightspace sign-in.
- **Database:** shared by everything; see [`../db/README.md`](../db/README.md).
