# Backends

Each folder is one service with its own container and README.

| Folder | What | Language | Port | Status |
|---|---|---|---|---|
| [`d3l/`](d3l/README.md) | Brightspace data for each person, plus the Brightspace sign-in tab | TypeScript | 3100 | Done |
| [`weather/`](weather/README.md) | Weather for the mirror's location | Python | 3200 | Done |
| [`mirror/`](mirror/README.md) | Recognizes who's at the mirror (through faces) and gathers their widgets and data | Python | 3300 | Done |
| [`faces/`](faces/README.md) | Face pictures and fingerprints: saves them at sign-up, recognizes faces at the mirror | Python | 3400 | Done |

The sign-up app is in [`../frontends/app/`](../frontends/app/README.md) (Python, port 3500). It
renders its own pages, so it has no separate backend here.

How they connect:

```
 frontends/app (sign-up) --> faces: save my face --+
       |                                           |
       +-- Brightspace sign-in --> d3l ------------+
                                    ^              +--> Postgres (db/)
 frontends/mirror --> backends/mirror --> faces: who is this?
   (camera frames)          |        --> weather   |
                            +--> widget layouts ---+
```

- **Mirror backend:** sends camera frames to faces. When someone is recognized, it hands the page
  a short-lived pass, then reads d3l (service key plus `X-Person-Id`), weather (the person's units
  setting) and widget layouts for them.
- **Faces:** the only service that touches face pictures and fingerprints.
- **Sign-up app:** creates people on their first Google sign-in, saves their face through faces,
  starts Brightspace sign-ins through d3l (service key plus `X-Person-Id`), and saves their
  settings and API key. People's browsers only open d3l for the sign-in tab.
- **Database:** shared by everything; see [`../db/README.md`](../db/README.md).
