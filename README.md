# url2vid

Paste a video URL into a terminal dashboard — or a local web page — and
watch it download. Built on
[yt-dlp](https://github.com/yt-dlp/yt-dlp), so it handles roughly 1800 sites —
YouTube, X/Twitter, TikTok, Instagram, Reddit, Vimeo, Facebook, Twitch, news
sites — plus direct `.mp4`/HLS/DASH links on arbitrary pages.

DRM-protected services (Netflix, Disney+, Prime Video) are not supported.

## Requirements

- Python 3.11+
- `ffmpeg` on your PATH (needed to merge video and audio into one file)

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Use

**Dashboard** — run with no arguments:

```bash
.venv/bin/python url2vid.py
```

Paste a URL and press **Enter** (or click **Fetch**). The video's title and
source appear as soon as they are known:

```
  https://www.youtube.com/watch?v=aqz-KE-bpKQ            [ Fetch ]

█ Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film
█ Youtube · 10:35 · 8 resolutions

  [ Best available     ▾ ]   [ Download ]

✓ Found "Big Buck Bunny 60fps 4K…" — pick a resolution and press Download.
```

Pick a resolution, press **Download**, and the row appears in the table below.
Paste another while the first is still running; up to three download at once
and the rest queue.

**Direct links download themselves.** A URL that already points at a media file
— `.mp4`, `.mkv`, `.webm`, `.m3u8` and friends, with or without a signed query
string — has no resolution to choose, so it is fetched for its title and then
starts immediately without a second click. The same applies to any site that
only serves one pre-muxed stream.

```
NAME                           RES PROGRESS                  %     LEFT      SPEED      SIZE
Caminandes: Llamigos         1080p ████████████████████ 100.0%     done              85.8 MB
Tears of Steel                best ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌     --  waiting
Sintel - Official Trailer     720p ████████████████████ 100.0%  merging              45.8 MB
Big Buck Bunny 60fps 4K…     1080p █████████████░░░░░░░  63.9%   1m 03s   1.3 MB/s  234.3 MB
```

### Feedback

Every action reports back on the message line under the input, so nothing fails
quietly:

| Situation | What you see |
|---|---|
| Fetch with an empty box | `! Nothing to fetch — paste a video URL in the box first.` |
| URL without a scheme | `✗ That is not a full URL. It has to start with http:// or https://` |
| Lookup in flight | `◐ Searching that link for a video…` and the button reads *Searching…* |
| Download finished | `✓ Saved <filename> to <folder>` |
| Download failed | `✗ <title> failed — <the reason>` |

A failed row is also drawn in red in the table, but its message is trimmed to
fit the column — the message line always carries the full text.

Failures are explained rather than echoed. yt-dlp's own wording answers *what*
broke but rarely *whose problem it is* — `Unsupported URL` in particular reads
like a bug in this app when it is not — so `explain_error` classifies the
common cases:

| yt-dlp says | url2vid says |
|---|---|
| `Unsupported URL: https://…` | yt-dlp has no extractor for `<site>`, and no video could be found in the page itself. Sites that build their player in JavaScript keep the stream out of the page source. |
| `…Name or service not known` | Could not reach `<site>` — that domain does not resolve. |
| `HTTP Error 404: Not Found` | `<site>` returned 404 Not Found — the link is wrong, or the video was deleted. |
| `HTTP Error 403: Forbidden` | `<site>` refused the request. The link may have expired, or the site may be blocking non-browser requests. |
| `Private video. Sign in…` | That video needs an account — url2vid does not sign in or use cookies. |
| `…not available in your country` | `<site>` blocks that video in your region. |

Anything unrecognised is passed through unchanged, with yt-dlp's `[extractor]
id:` prefix and `(caused by …)` tail stripped. Flattening an unknown failure
into a generic apology would throw away the only clue available.

| Key | Action |
|---|---|
| `Enter` | look up the URL in the box (same as the **Fetch** button) |
| `Esc` | move focus to the download list |
| `F2` | jump back to the URL box |
| `F3` | cancel the selected download |
| `F4` | clear finished rows |
| `F5` | show the downloads folder |
| `Ctrl+Q` | quit |

The single-letter shortcuts (`d`, `c`, `x`, `o`, `q`) also work once focus is on
the list — while the URL box has focus it receives those keystrokes as text.

**One-shot** — pass a URL to download and exit:

```bash
.venv/bin/python url2vid.py "https://www.youtube.com/watch?v=..."
.venv/bin/python url2vid.py "https://..." -r 1080     # cap the resolution
.venv/bin/python url2vid.py "https://..." --list      # show resolutions, don't download
```

Files land in `downloads/`.

**Web UI** — a React + TypeScript page over the same download engine:

```bash
cd web && npm install && npm run build && cd ..
.venv/bin/python run_web.py            # then open http://127.0.0.1:8000
```

For frontend work, run the two halves separately so the UI hot-reloads:

```bash
.venv/bin/python run_web.py            # API on :8000
cd web && npm run dev                  # UI on :5173, proxies /api to :8000
```

### Choosing where videos are saved

Click **Choose folder…** once. The browser's own folder picker opens, and from
then on every finished video is written straight into that folder — the choice
is remembered across restarts, so it becomes your default. **Use default** puts
things back to the server's `downloads/` folder.

This uses the File System Access API, which is a Chromium-only feature today
(Chrome, Edge, Brave, Opera). Firefox and Safari get told so plainly, and every
finished download carries a **Save…** button that opens the ordinary browser
save dialog — so the feature degrades to per-video instead of disappearing.
That button is present in every browser, which is also how you put a second
copy somewhere else.

A note on how it works, because it constrains the design: the API hands out a
*handle*, never a path — a web page is not allowed to learn where things are on
your disk. The handle is kept in IndexedDB (`localStorage` only stores strings
and would flatten it), and browsers may downgrade its permission to "prompt"
after a restart, which can only be cleared by a click. That is what the
**Reconnect** button is for.

## How progress is measured

yt-dlp is used as a library rather than a subprocess, so progress arrives as
exact byte counts instead of scraped text.

The awkward part is that a merged download fetches video and audio as two
separate files. A naive per-file percentage drops back to zero halfway through,
so each finished stream's bytes are banked into a running total and the bar
spans both as one continuous measure. Stream size estimates also tend to
overshoot, which would leave the bar stalling in the high eighties before
snapping to 100%; each stream's estimate is replaced with its real size as it
completes, so the total converges on the truth.

Time remaining is derived from a smoothed speed over the remaining bytes rather
than from yt-dlp's own `eta`, which describes only the stream currently in
flight. When a site reports no size at all, the percentage is withheld rather
than guessed and the row falls back to yt-dlp's own estimate.

## Layout

| Path | Purpose |
|---|---|
| `url2vid.py` | entry point; argument parsing |
| `app/progress.py` | percentage, ETA, and format arithmetic — no I/O, fully unit-tested |
| `app/jobs.py` | thread-safe job registry shared by workers and the UI |
| `app/downloader.py` | all yt-dlp contact; owns the worker pool |
| `app/tui.py` | the terminal dashboard |
| `app/cli.py` | one-shot mode |
| `run_web.py` | entry point for the web UI |
| `server/main.py` | FastAPI routes and the SSE job stream |
| `web/src/folder.ts` | folder picking, persistence, and writing files to disk |
| `web/src/App.tsx` | web UI state and orchestration |

The web UI adds routes on top of `app/downloader.py`, `app/jobs.py` and
`app/progress.py` rather than duplicating them, so a fix to the progress
arithmetic or the error explanations lands in both front ends at once.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

Covers the progress arithmetic, job state, filename templating, error
explanation, the terminal dashboard driven headlessly through Textual's test
pilot, and the HTTP API with the network mocked out.

```bash
cd web && npm run typecheck    # frontend types
```
