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
binaries = []
for tool in ("ffmpeg", "ffprobe"):
    name = f"{tool}.exe" if sys.platform == "win32" else tool
    binaries.append((f"bin/{name}", "bin"))
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
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest", "PySide6", "PyQt5", "PyQt6"],
    noarchive=False,
)

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
