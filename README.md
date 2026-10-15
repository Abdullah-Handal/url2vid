# url2vid

Paste a video URL, pick a quality, get the file. A small desktop app for
Windows and Linux built on [yt-dlp](https://github.com/yt-dlp/yt-dlp), so it
handles roughly 1800 sites — YouTube, X/Twitter, TikTok, Instagram, Reddit,
Vimeo, Facebook, Twitch, news sites — plus direct `.mp4`/HLS/DASH links.

DRM-protected services (Netflix, Disney+, Prime Video) are **not** supported
and never will be.

## Download

Nothing to install first: Python, ffmpeg and everything else are inside the
file.

| System | File | Size | |
|---|---|---|---|
| **Windows 10/11** (64-bit) | [**url2vid-windows-setup.exe**](https://github.com/Abdullah-Handal/url2vid/releases/latest/download/url2vid-windows-setup.exe) | 68 MB | Recommended — installer |
| Windows 10/11 (64-bit) | [url2vid-windows-portable.exe](https://github.com/Abdullah-Handal/url2vid/releases/latest/download/url2vid-windows-portable.exe) | 86 MB | One file, no install |
| **Linux** (x86-64) | [**url2vid-linux-x86_64.tar.gz**](https://github.com/Abdullah-Handal/url2vid/releases/latest/download/url2vid-linux-x86_64.tar.gz) | 77 MB | |

Every version, with notes: **[Releases](https://github.com/Abdullah-Handal/url2vid/releases)**.

### Windows

Run the **setup** file. It installs for your user only (under
`%LOCALAPPDATA%\Programs\url2vid`), adds a Desktop shortcut and a Start-menu
entry, and asks for no administrator rights — so it works on a locked-down
machine without a UAC prompt. Uninstalling leaves your downloaded videos alone.

Windows will show a blue **"Windows protected your PC"** box on first run,
because the file is not signed by a paid certificate. Click **More info →
Run anyway**. Code-signing costs a few hundred dollars a year, which this
project does not have.

The **portable** file needs no install at all — but it unpacks itself into a
temporary folder every single time you open it, which costs several seconds
per launch and makes your antivirus rescan it each time. Use the installer
unless you specifically need to run it from a USB stick.

### Linux

```bash
tar -xzf url2vid-linux-x86_64.tar.gz
./url2vid/url2vid
```

To get it into your apps menu, copy `url2vid.desktop` from the repo to
`~/.local/share/applications/` and point its `Exec=` line at wherever you
unpacked it.

## Using it

The app opens its own window. Paste a link, press **Fetch**, and a panel
appears with the thumbnail, the title, and everything on offer:

- **Quality buttons** — every resolution the site has, each showing roughly how
  large the file will be, so you can tell 480p from 4K before committing.
- **Audio** on or off — off gives you a silent video file.
- **Audio only** — swaps the buttons for MP3 bitrates (320 / 256 / 192 / 128 /
  96 kbps) with their sizes. The result is a real `.mp3`, converted with
  ffmpeg, not the site's raw `.webm` stream.

Press **Download** and the panel gives way to the queue. Paste another link
while the first is still going; three download at once and the rest wait. Each
row shows a live percentage, speed, size and time remaining.

**Cancel deletes the file.** A cancelled download takes its partial pieces with
it rather than leaving half a video on your disk.

**Some links skip the panel.** A URL that already points at a media file, or a
site that only serves one pre-muxed stream, has no quality to choose — those
fetch their title and start immediately.

### Where files go

Your system's **Downloads** folder, unless you say otherwise. **Choose
folder…** opens a native folder picker and the choice is remembered from then
on.

### When it breaks

Failures are explained rather than echoed. yt-dlp's own wording answers *what*
broke but rarely *whose problem it is* — `Unsupported URL` in particular reads
like a bug in this app when it is not:

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

### Keeping it working

Video sites change constantly, and a downloader that cannot keep up stops
working within weeks. The app carries a copy of yt-dlp but checks for a newer
one on request: press **Update** and it fetches the current release into your
own data folder, which takes over from the bundled copy on the next launch.
You do not have to reinstall the app to keep it working.

## Running from source

The desktop app is the packaged form of the same code. To run it directly you
need **[Git](https://git-scm.com/downloads)**, **Python 3.11+**, **Node** (for
the UI), and **ffmpeg** on your PATH.

**Windows** — in Command Prompt (`cmd`):

```bat
git clone https://github.com/Abdullah-Handal/url2vid.git
cd url2vid
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
```

Then pick a front end:

```bat
.venv\Scripts\python desktop.py     :: native window
.venv\Scripts\python run_web.py     :: browser UI on http://127.0.0.1:8000
.venv\Scripts\python url2vid.py     :: terminal dashboard
```

Or skip all of it: **`start-web.bat`** does the clone's worth of setup for you
— virtualenv, packages, build, server, browser — and double-clicks straight
from Explorer. Pass a port if 8000 is taken: `start-web.bat 9000`.

**Linux / macOS**:

```bash
git clone https://github.com/Abdullah-Handal/url2vid.git
cd url2vid
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
```

Then pick a front end:

```bash
.venv/bin/python desktop.py            # native window
.venv/bin/python run_web.py            # browser UI on http://127.0.0.1:8000
.venv/bin/python url2vid.py            # terminal dashboard
```

`./start-web.sh` is the same one-tap shortcut as the `.bat`, and reads a port
from the environment: `PORT=9000 ./start-web.sh`.

### The terminal dashboard

```
  https://www.youtube.com/watch?v=aqz-KE-bpKQ            [ Fetch ]

█ Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film
█ Youtube · 10:35 · 8 resolutions

  [ Best available     ▾ ]   [ Download ]
```

| Key | Action |
|---|---|
| `Enter` | look up the URL in the box |
| `Esc` / `F2` | move focus to the list / back to the URL box |
| `F3` | cancel the selected download |
| `F4` | clear finished rows |
| `F5` | show the downloads folder |
| `Ctrl+Q` | quit |

It also downloads in one shot, without the dashboard:

```bash
.venv/bin/python url2vid.py "https://…"
.venv/bin/python url2vid.py "https://…" -r 1080     # cap the resolution
.venv/bin/python url2vid.py "https://…" --list      # show resolutions, don't download
```

### Frontend work

Run the two halves separately so the UI hot-reloads:

```bash
.venv/bin/python run_web.py            # API on :8000
cd web && npm run dev                  # UI on :5173, proxies /api to :8000
```

The server binds to `127.0.0.1` only. That is not a preference — it is what
makes accepting a filesystem path over HTTP safe. Do not change it.

### Building the installers

Push a version tag and GitHub Actions builds both platforms:

```bash
git tag v0.1.4 && git push origin v0.1.4
```

`.github/workflows/release.yml` builds the UI, fetches a static ffmpeg, freezes
everything with PyInstaller, runs the tests and a smoke test against the frozen
bundle, wraps Windows with Inno Setup, and attaches all three files to the
release.

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
than guessed.

## Layout

| Path | Purpose |
|---|---|
| `desktop.py` | desktop entry point: free port, server thread, native window |
| `app/paths.py` | every path, for both frozen and source runs — the only place that knows about PyInstaller |
| `app/progress.py` | percentage, ETA, size and format arithmetic — no I/O, fully unit-tested |
| `app/jobs.py` | thread-safe job registry shared by workers and the UI |
| `app/downloader.py` | all yt-dlp contact; owns the worker pool |
| `app/updater.py` | fetches a newer yt-dlp into the user's data folder |
| `app/tui.py` | the terminal dashboard |
| `app/cli.py` | one-shot mode |
| `server/main.py` | FastAPI routes and the SSE job stream |
| `web/src/App.tsx` | UI state and orchestration |
| `web/src/components/FoundPanel.tsx` | the quality / audio / download panel |
| `url2vid.spec` | PyInstaller build |
| `packaging/url2vid.iss` | Inno Setup installer |
| `scripts/fetch_ffmpeg.py` | pulls a static ffmpeg at build time |

Every front end adds routes on top of `app/downloader.py`, `app/jobs.py` and
`app/progress.py` rather than duplicating them, so a fix to the progress
arithmetic or the error explanations lands in all of them at once.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
cd web && npm run typecheck
```

Covers the progress arithmetic, job state, filename templating, error
explanation, the terminal dashboard driven headlessly through Textual's test
pilot, the HTTP API with the network mocked out, and the windowed-build startup
path that has no console attached.

## Credits and licences

Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense), which does all
the actual site handling.

The Windows and Linux downloads include a static build of
[ffmpeg](https://ffmpeg.org/), licensed under the GPL. The full licence text
ships next to the binary as `LICENSE-ffmpeg.txt`; the builds come from
[johnvansickle.com](https://johnvansickle.com/ffmpeg/) and
[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds), where the
corresponding source is available.

url2vid downloads what you already have access to. It does not break DRM, does
not sign in, and does not use cookies. What you do with it is on you.
