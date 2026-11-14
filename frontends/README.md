# Frontends

| Folder | What | Status |
|---|---|---|
| `mirror/` | The mirror display (projected onto the mirror for the demo) | Not started |
| `app/` | Simulates the phone app: sign-up with pictures, widget layout, Brightspace sign-in | Not started |

Each one talks only to its own backend in [`../backends/`](../backends/README.md), except that the
app frontend opens d3l's Brightspace sign-in tab directly (see `../backends/d3l/README.md`).
