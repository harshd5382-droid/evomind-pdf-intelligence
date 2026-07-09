# Demo capture kit

Generates the README hero GIF by driving the **real** EvoMind UI — no mockups.
The sequence: empty dashboard → drop a PDF → questions stream into the Feed →
the knowledge graph fills → the agent's Mind → the intelligence score ticks up.

Until you run it, the README shows [`demo-poster.svg`](demo-poster.svg) as a
clean placeholder. One command replaces it with the live capture.

## One command

```bash
make demo-gif
```

That runs [`make-gif.sh`](make-gif.sh), which:

1. generates the deterministic sample PDF ([`sample-paper.pdf`](sample-paper.pdf)),
2. installs Playwright + Chromium locally under `docs/demo/` (first run only),
3. drives the live UI and records a video ([`capture.mjs`](capture.mjs)),
4. transcodes it to an optimized, looping `docs/demo/demo.gif`,
5. points the README hero at that GIF ([`_wire-readme.py`](_wire-readme.py)).

## Prerequisites

**The app must already be running** before you capture:

```bash
docker compose up --build          # web on :3000, API on :8000
# or run apps/web (npm run dev) and apps/api (uvicorn) yourself
```

On your PATH: `node`, `python3`, and **`ffmpeg`** (`brew install ffmpeg` /
`apt-get install ffmpeg`). [`gifski`](https://gif.ski) is optional — if present
it's used automatically for better quality at smaller size.

For the richest capture, ingest a few papers first so the graph and score have
something to show. A single-PDF run still works out of the box.

## Configuration

All optional, via environment variables:

| Var | Default | Purpose |
|-----|---------|---------|
| `WEB_URL` | `http://localhost:3000` | web app base URL |
| `API_URL` | `http://localhost:8000` | FastAPI base URL |
| `API_KEY` | _(none)_ | sent as `X-API-Key` when the backend has auth on |
| `PDF` | `docs/demo/sample-paper.pdf` | document to ingest |
| `FPS` / `WIDTH` | `12` / `1000` | GIF frame rate / width (lower them to shrink) |
| `HEADLESS` | `1` | set `0` to watch the browser drive itself |

```bash
# smaller file
FPS=10 WIDTH=880 make demo-gif

# against a remote deployment with auth
WEB_URL=https://demo.example.com API_URL=https://api.example.com API_KEY=… make demo-gif
```

> **Auth note:** the browser upload step uses the app's own uploader, which does
> not yet forward an API key (see the roadmap). Run the demo with auth disabled
> (the default), or the loop is still kicked via the API using `API_KEY`.

## Files

| File | Role |
|------|------|
| `make-gif.sh` | orchestrator (`make demo-gif` calls this) |
| `capture.mjs` | Playwright script that drives the UI and records the video |
| `make-sample-pdf.py` | zero-dependency generator for `sample-paper.pdf` |
| `sample-paper.pdf` | committed deterministic sample document |
| `demo-poster.svg` | placeholder shown until the GIF is generated |
| `_wire-readme.py` | swaps the README hero between poster and GIF (`--reset` to revert) |
| `demo.gif` | the generated capture (produced by `make demo-gif`) |

To revert the README to the placeholder: `python3 docs/demo/_wire-readme.py --reset`.
