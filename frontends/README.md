# Frontends

| Folder | What | Status |
|---|---|---|
| [`mirror/`](mirror/README.md) | The mirror display, live at https://sumirrorize.marist.dev | Working |
| `app/` | Simulates the phone app: sign-up with pictures, widget layout, Brightspace sign-in | Not started |

Each one talks only to its own backend in [`../backends/`](../backends/README.md), except that the
app frontend opens d3l's Brightspace sign-in tab directly (see `../backends/d3l/README.md`).
