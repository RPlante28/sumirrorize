# mirror (frontend)

The mirror display: plain HTML, CSS and JavaScript, no build step. Served by nginx, which also
passes `/api/` to the [mirror backend](../../backends/mirror/README.md).

Live at **https://sumirrorize.marist.dev**.

## Using it

1. **Open it on the mirror computer** (the demo laptop, or a phone) and allow the camera when the
   browser asks. To skip the question next time, choose "always allow" for the site.
2. **Walk up.** The page sends a camera frame to the server twice a second. When it recognizes
   someone, it says "Hi, Alex. Blink to open your mirror".
3. **Blink.** While it waits, frames go up to 10 times a second so the blink isn't missed. Once
   the server has seen it, the page shows their widgets. A photo of someone can't blink, so it
   never gets past the greeting. If no blink is seen in 6 seconds, the page suggests closing
   your eyes for a second, which is easier to catch than a quick blink.
4. **Walk away.** About 8 seconds after it last recognized them, the mirror clears back to the
   clock, and their data is removed from the page. If someone else steps up and is recognized,
   the mirror clears straight away and asks them to blink. Esc clears it right away.

To be recognized, people need their face saved through sign-up (see
[`backends/faces`](../../backends/faces/README.md)). The camera's live view fills the screen,
flipped like a mirror, with the widgets on top as dark see-through cards. Frames aren't kept
anywhere.

The data refreshes every 5 minutes while someone stays. If the server can't be reached, the last
data stays up with a small notice. If the camera is blocked, the page says so, with a button to
try again.

The timings are at the top of `public/mirror.js`: `STABLE_MATCHES` (frames in a row before
greeting someone), `SESSION_TIMEOUT_MS`, and the `BLINK_...` frame rates. The blink itself is
judged by the server; see [the backend](../../backends/mirror/README.md).

## How it's built

- **The camera view is the mirror.** It fills the screen, flipped, with light text on dark
  see-through cards over it.
- **Widgets go where the person put them.** Each widget is positioned from its saved `x`, `y`,
  `w`, `h` (fractions of the screen).
- **Except on tall screens.** On a phone held upright (narrower than 4:5), saved positions would
  squeeze every widget into a thin strip, so the page arranges them itself: clock and weather
  side by side at the top, then the greeting and summary, your reflection in the middle, and
  everything else as a row of cards along the bottom to swipe through. Turning the phone
  switches between the two.
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
