#!/usr/bin/env python3
"""Start the web UI: `python run_web.py`, then open http://127.0.0.1:8000."""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="run_web", description="Serve the url2vid web UI.")
    parser.add_argument("--port", type=int, default=8000)
    # Loopback by default: this app downloads whatever it is told to and has no
    # authentication, so it must not listen on the network unless asked.
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--reload", action="store_true", help="restart on code changes")
    args = parser.parse_args()

    print(f"url2vid → http://{args.host}:{args.port}")
    uvicorn.run("server.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
