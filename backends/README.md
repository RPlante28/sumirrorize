# Backends

Each folder is one service with its own container and README.

| Folder | What | Language | Port | Status |
|---|---|---|---|---|
| [`d3l/`](d3l/README.md) | Brightspace data for each person, plus the Brightspace sign-in tab | TypeScript | 3100 | Done |
| [`weather/`](weather/README.md) | Weather for the mirror's location | Python | 3200 | Done |
| [`mirror/`](mirror/README.md) | Recognizes who's at the mirror (through faces) and gathers their widgets and data | Python | 3300 | Done |
| [`faces/`](faces/README.md) | Face pictures and fingerprints: saves them at sign-up, recognizes faces at the mirror | Python | 3400 | Done |
| `app/` | The phone app's backend: sign-up, widget layouts. Your friend's prototype is in `/webapp` | | | Next |

How they connect:

```
 webapp (sign-up) ──> faces: save my face ─────────┐
       │                                           │
       └── Brightspace sign-in ──> d3l ────────────┤
                                    ^              ├──> Postgres (db/)
 frontends/mirror ──> backends/mirror ──> faces: who is this?
   (camera frames)          │        ──> weather   │
                            └──> widget layouts ───┘
```

- **Mirror backend:** sends camera frames to faces. When someone is recognized, it hands the page
  a short-lived pass, then reads d3l (service key plus `X-Person-Id`), weather (the person's units
  setting) and widget layouts for them.
- **Faces:** the only service that touches face pictures and fingerprints.
- **App backend / webapp:** creates people and their API keys, saves their face through faces, and
  saves widget layouts. The app frontend talks to d3l directly for Brightspace sign-in.
- **Database:** shared by everything; see [`../db/README.md`](../db/README.md).
