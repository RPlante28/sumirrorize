# Frontends

| Folder | What | Status |
|---|---|---|
| [`mirror/`](mirror/README.md) | The mirror display, live at https://sumirrorize.marist.dev | Working |
| [`app/`](app/README.md) | The sign-up app: Google sign-in, face pictures, Brightspace, settings. At https://sumirrorize-api.marist.dev | Working |

The mirror page talks only to its backend in [`../backends/mirror`](../backends/mirror/README.md).
The app is a small Flask server that renders its own pages, so it's its own backend; it also
opens d3l's Brightspace sign-in tab, which shares its address under `/api/`.
