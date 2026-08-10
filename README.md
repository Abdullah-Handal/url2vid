# url2vid

Paste a video URL into a terminal dashboard and watch it download. Built on
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

Paste a URL, press Enter, pick a resolution from the dropdown, and it starts.
Paste another while the first is still running; up to three download at once
and the rest queue.

```
NAME                             RES PROGRESS                  %     LEFT      SPEED      SIZE
Caminandes: Llamigos           1080p ████████████████████ 100.0%     done              85.8 MB
Tears of Steel                  best ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌     --  waiting
Sintel - Official Trailer       720p ████████████████████ 100.0%  merging              45.8 MB
Big Buck Bunny 60fps 4K - Ble… 1080p █████████████░░░░░░░  63.9%   1m 03s   1.3 MB/s  234.3 MB
```

| Key | Action |
|---|---|
| `Enter` | look up the URL in the box |
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
| `app/tui.py` | the dashboard |
| `app/cli.py` | one-shot mode |

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

Covers the progress arithmetic, job state, filename templating, error
cleanup, and the dashboard driven headlessly through Textual's test pilot.
