# mirror (frontend)

The mirror display: plain HTML, CSS and JavaScript, no build step. Served by nginx, which also
passes `/api/` to the [mirror backend](../../backends/mirror/README.md).

Live at **https://sumirrorize.marist.dev**.

## Using it

1. **Connect the screen (once per device).** Open `https://sumirrorize.marist.dev/#key=<MIRROR_KEY>`.
   The page saves the key and removes it from the address bar. Without the key it asks for one.
   The key is in `/opt/containers/sumirrorize/.env`.
2. **Pick who's at the mirror.** This stands in for face recognition. You can also link straight
   to someone with `?person=<id>`. The choice is remembered.
3. **Switch person:** move the mouse and a "Switch person" button appears in the corner, or press Esc.

The data refreshes every 5 minutes. The clock and greeting update every second. If the server
can't be reached, the last data stays up with a small notice.

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
  analytics are blocked, which is fine for a page showing student data.

| File | What |
|---|---|
| `public/index.html` | The three screens: setup, pick a person, the mirror |
| `public/mirror.js` | Everything else: key, API calls, drawing each widget, weather icons |
| `public/mirror.css` | The look |
| `nginx.conf.template` | Serving the files and forwarding `/api/` |

## Adding a widget

1. Add it to the database (`db/init/002_widgets.sql`, plus an insert into running databases).
2. If it needs data, add it to `NEEDS` and `data_for` in `backends/mirror/app/widgets.py`.
3. Add a renderer to `renderers` in `public/mirror.js`, and its styles (`.w-<key>`) in `mirror.css`.
