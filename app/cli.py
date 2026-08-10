"""One-shot mode: `url2vid <URL>` downloads and exits."""

from __future__ import annotations

import time

from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from . import downloader, jobs
from .jobs import registry

console = Console()


def download_once(url: str, height: int | None, list_only: bool = False) -> int:
    """Download one URL with a live bar. Returns a process exit code."""
    console.print("[bright_yellow]Fetching info…[/]")
    try:
        info = downloader.probe(url)
    except Exception as exc:  # noqa: BLE001 - report the site's own reason
        console.print(f"[bright_red]✗ {escape(downloader.clean_error(str(exc)))}[/]")
        return 1

    console.print(f"[bold]{escape(info['title'])}[/] [dim]({escape(str(info.get('extractor') or 'unknown source'))})[/]")
    if info.get("note"):
        console.print(f"[bright_yellow]{escape(info['note'])}[/]")

    available = [f["height"] for f in info["formats"]]
    if list_only:
        if not available:
            console.print("[dim]No separate video resolutions reported.[/]")
        for fmt in info["formats"]:
            size = f"  {fmt['size_label']}" if fmt["size_label"] else ""
            console.print(f"  [bright_cyan]{fmt['label']:>6}[/][dim]{size}[/]")
        return 0

    if height and available and height not in available:
        nearest = min(available, key=lambda h: abs(h - height))
        console.print(f"[bright_yellow]No {height}p available — using {nearest}p instead.[/]")
        height = nearest

    job = downloader.start(url, height, info["title"])

    columns = (
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=30, complete_style="bright_cyan", finished_style="bright_green"),
        TextColumn("[bright_cyan]{task.percentage:>5.1f}%"),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(compact=True),
    )

    with Progress(*columns, console=console) as bar:
        task = bar.add_task(escape(_short(info["title"])), total=None)
        while True:
            state = registry.get(job.id)
            if state is None:
                break
            snapshot = state.as_dict()
            total = state.total_bytes
            done = state.completed_bytes + state.downloaded_bytes
            if total:
                bar.update(task, total=total, completed=done)
            if snapshot["status"] == jobs.MERGING:
                bar.update(task, description=escape(_short(state.title)) + " [yellow](merging)[/]")
            if snapshot["status"] in jobs.TERMINAL:
                if total:
                    bar.update(task, completed=total)
                break
            time.sleep(0.2)

    final = registry.get(job.id)
    if final is None:
        return 1
    if final.status == jobs.DONE:
        console.print(f"[bright_green]✓ Saved[/] {final.filename or ''}", soft_wrap=True)
        console.print(f"[dim]  in {downloader.DOWNLOAD_DIR}[/]", soft_wrap=True)
        return 0
    if final.status == jobs.CANCELLED:
        console.print("[grey50]Cancelled.[/]")
        return 130
    console.print(f"[bright_red]✗ {escape(final.error or 'Download failed.')}[/]")
    return 1


def _short(title: str, width: int = 32) -> str:
    return title if len(title) <= width else title[: width - 1] + "…"
