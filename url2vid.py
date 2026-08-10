#!/usr/bin/env python3
"""url2vid — download a video from (almost) any URL.

    url2vid                       launch the full-screen dashboard
    url2vid <URL>                 download at best quality
    url2vid <URL> -r 1080         download at a chosen resolution
    url2vid <URL> --list          list available resolutions and exit
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="url2vid",
        description="Download a video from a URL. Run with no arguments for the interactive dashboard.",
    )
    parser.add_argument("url", nargs="?", help="video URL (omit to launch the dashboard)")
    parser.add_argument(
        "-r", "--resolution", type=int, metavar="HEIGHT",
        help="max height, e.g. 1080. Defaults to the best available.",
    )
    parser.add_argument("-l", "--list", action="store_true", help="list available resolutions and exit")
    args = parser.parse_args()

    if args.url is None:
        from app.tui import run
        run()
        return 0

    from app.cli import download_once
    return download_once(args.url, args.resolution, list_only=args.list)


if __name__ == "__main__":
    sys.exit(main())
