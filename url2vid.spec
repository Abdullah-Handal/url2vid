# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the desktop app.

Run with:  pyinstaller url2vid.spec
"""

import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("web/dist", "web/dist"),
]

# ffmpeg is fetched by scripts/fetch_ffmpeg.py before building. Without it a
# packaged app cannot merge video and audio on a machine that has no ffmpeg.
# ffmpeg only. yt-dlp uses ffprobe for optional metadata work, never for the
# merge -- verified by completing a 240p video+audio merge with no ffprobe
# anywhere on the system. Leaving it out saves 80 MB.
binaries = []
_ffmpeg = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
binaries.append((f"bin/{_ffmpeg}", "bin"))
datas.append(("bin/LICENSE-ffmpeg.txt", "bin"))

# yt-dlp loads its ~1800 extractors lazily, so PyInstaller's static analysis
# finds almost none of them. Without this the packaged app resolves nothing.
yt_datas, yt_binaries, yt_hidden = collect_all("yt_dlp")
datas += yt_datas
binaries += yt_binaries

hiddenimports = yt_hidden + collect_submodules("uvicorn") + [
    "app.cli",
    "app.tui",
]

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Trimmed: large libraries pulled in transitively that this app never uses.
    excludes=[
        "tkinter", "matplotlib", "numpy", "PIL", "pytest", "PySide6", "PyQt5", "PyQt6",
        # Optional uvicorn accelerators; desktop.py asks for asyncio/h11 instead.
        "uvloop", "httptools",
    ],
    noarchive=False,
)

# PyInstaller follows GTK's data files and sweeps up every installed icon and
# desktop theme -- 171 MB of artwork for widgets this app never draws, since
# the entire interface is HTML rendered inside the webview. GTK reads these
# from the system at runtime anyway.
_DROP_PREFIXES = (
    "share/icons",
    "share/themes",
    "share/fontconfig",
    "share/mime",
)


def _wanted(entry):
    dest = entry[0].replace("\\", "/")
    return not dest.startswith(_DROP_PREFIXES)


_before = len(a.datas)
a.datas = [entry for entry in a.datas if _wanted(entry)]
print(f"[url2vid] dropped {_before - len(a.datas)} theme/icon data files")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="url2vid",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="url2vid",
)
