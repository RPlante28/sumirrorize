# mirror (frontend)

The mirror display: plain HTML, CSS and JavaScript, no build step. Served by nginx, which also
passes `/api/` to the [mirror backend](../../backends/mirror/README.md).

Live at **https://sumirrorize.marist.dev**.

## Using it

1. **Open it on the mirror computer** (the demo laptop) and allow the camera when the browser asks.
   To skip the question next time, choose "always allow" for the site.
2. **Walk up.** The page sends a camera frame to the server twice a second. Once it recognizes the
   same person in 3 frames in a row (about 1.5 seconds), it shows their widgets.
3. **Walk away.** About 8 seconds after it last recognized them, the mirror clears back to the
   clock, and their data is removed from the page. If someone else steps up, it switches to them
   the same way. Esc clears it right away.

To be recognized, people need their face saved through sign-up (see
[`backends/faces`](../../backends/faces/README.md)). The camera's live view fills the screen,
flipped like a mirror, with the widgets on top as dark see-through cards. Frames aren't kept
anywhere.

The data refreshes every 5 minutes while someone stays. If the server can't be reached, the last
data stays up with a small notice. If the camera is blocked, the page says so, with a button to
try again.

The 3-frame and 8-second rules come from the face-recog mirror script (`scripts/mirror.py`).
They're `STABLE_MATCHES` and `SESSION_TIMEOUT_MS` at the top of `public/mirror.js`.

## How it's built

- **Black is the mirror.** On a projected mirror black shows as glass, so everything is light on
  black.
- **Widgets go where the person put them.** Each widget is positioned from its saved `x`, `y`,
  `w`, `h` (fractions of the screen).
- **Each widget is a bordered card.** Its text scales with the card (CSS container units), so
  any layout and screen size works. The weather widget adds the next 6 hours when its card isn't
  too wide for its height.
- **Nothing is cut off mid-item.** Lists show only the items that fit whole, plus a "+N more"
  line. The greeting and summary shrink their text if it's too long for the card. Both are
  redone whenever the window is resized.
- **The default layout keeps the middle clear** for the person's reflection (see
  `db/init/004_announcements_and_layout.sql`).
- **No HTML injection.** Brightspace text is always inserted as plain text, never as HTML.
- **Strict page rules.** The page only loads its own files, so outside scripts like Cloudflare
  analytics are blocked, which is fine for a page showing student data. Only this page may use
  the camera, and nothing may use the microphone.

| File | What |
|---|---|
| `public/index.html` | The two screens (waiting, and someone's mirror) and the camera view behind them |
| `public/mirror.js` | Everything else: camera, recognizing who's there, drawing each widget, weather icons |
| `public/mirror.css` | The look |
| `nginx.conf.template` | Serving the files and forwarding `/api/` |

## Adding a widget

1. Add it to the database (`db/init/002_widgets.sql`, plus an insert into running databases).
2. If it needs data, add it to `NEEDS` and `data_for` in `backends/mirror/app/widgets.py`.
3. Add a renderer to `renderers` in `public/mirror.js`, and its styles (`.w-<key>`) in `mirror.css`.
