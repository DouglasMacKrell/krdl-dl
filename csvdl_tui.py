#!/usr/bin/env python3
"""
Textual TUI for CSV bulk downloads (uses csvdl_core).

Controls:
  - Press ENTER to start (or restart) the queue.
  - Press P to pause (stops after current in-flight finishes).
  - Press Q to quit.

Columns:
  # | File | Status | Progress | Size
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import List, Optional

from csvdl_core import expand, extract_urls_from_text, prepare_jobs, download_job, Job

# Textual / Rich
from rich.progress import Progress
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static, Button

class StatusBar(Static):
    text = reactive("Ready")

    def watch_text(self, text: str) -> None:
        self.update(f"[b]{text}[/b]")

class DownloaderApp(App):
    CSS = """
    Screen { layout: vertical; }
    #toolbar { height: 3; }
    DataTable { height: 1fr; }
    """

    def __init__(self, *, csv_path: str, target: str, ext: str, jobs: int):
        super().__init__()
        self.csv_path = csv_path
        self.target = Path(expand(target))
        self.ext = ext
        self.max_workers = jobs

        self.jobs: List[Job] = []
        self.table: Optional[DataTable] = None
        self.status_bar = StatusBar(id="status")
        self.running = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="toolbar"):
            yield Button("Start (Enter)", id="start", variant="success")
            yield Button("Pause (P)", id="pause", variant="warning")
            yield Button("Quit (Q)", id="quit", variant="error")
        self.table = DataTable(zebra_stripes=True)
        self.table.add_columns("#", "File", "Status", "Progress", "Size")
        yield self.table
        yield self.status_bar
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            self.run_queue()
        elif event.button.id == "pause":
            self.running = False
            self.status_bar.text = "Pausing after current downloads…"
        elif event.button.id == "quit":
            self.exit()

    def on_mount(self) -> None:
        self.refresh_jobs()

    def refresh_jobs(self) -> None:
        self.target.mkdir(parents=True, exist_ok=True)
        urls = extract_urls_from_text(self.csv_path)
        self.jobs = prepare_jobs(urls, self.ext, self.target)

        self.table.clear()
        for idx, j in enumerate(self.jobs, start=1):
            size = f"{j.expected_bytes/1_000_000:.2f} MB" if j.expected_bytes else "-"
            self.table.add_row(str(idx), j.name or "-", j.status, "0%", size)
        self.status_bar.text = f"Loaded {len(self.jobs)} URLs — {self.ext.upper()} only — target: {self.target}"

    async def _run_job(self, j: Job, row_idx: int):
        def _progress_cb(job: Job, frac: float, bytes_done: int):
            percent = int(frac * 100) if frac else 0
            self.call_from_thread(self._update_row, row_idx, job.status, f"{percent}%")

        j = download_job(j, progress_cb=_progress_cb)
        self.call_from_thread(self._finalize_row, row_idx, j)

    def _update_row(self, row_idx: int, status: str, pct: str):
        # Update only the Status and Progress columns
        row = list(self.table.get_row_at(row_idx))
        row[2] = status
        row[3] = pct
        self.table.update_row(row_idx, row)

    def _finalize_row(self, row_idx: int, j: Job):
        row = list(self.table.get_row_at(row_idx))
        row[2] = j.status
        row[3] = "100%" if j.status == "DONE" else row[3]
        self.table.update_row(row_idx, row)

    async def _runner(self):
        # simple bounded concurrency with asyncio.Semaphore + threads
        sem = asyncio.Semaphore(self.max_workers)
        tasks = []

        for i, j in enumerate(self.jobs):
            if j.status == "SKIP":  # already present
                self._finalize_row(i, j)
                continue
            if not self.running:
                break

            await sem.acquire()
            async def run_one(index=i, job=j):
                try:
                    await self.loop.run_in_executor(None, self._run_job, job, index)
                finally:
                    sem.release()

            tasks.append(self.create_task(run_one()))

        if tasks:
            await asyncio.gather(*tasks)

    def run_queue(self):
        if self.running:
            return
        self.running = True
        self.status_bar.text = f"Running — up to {self.max_workers} concurrent"
        self.create_task(self._runner())

    def on_key(self, event) -> None:
        k = event.key.upper()
        if k == "ENTER":
            self.run_queue()
        elif k == "P":
            self.running = False
            self.status_bar.text = "Pausing after current downloads…"
        elif k == "Q":
            self.exit()

def main():
    ap = argparse.ArgumentParser(description="CSV Bulk Downloader — TUI")
    ap.add_argument("--csv", required=True, help="Path to CSV/text file with URLs")
    ap.add_argument("--target", required=True, help="Directory to save downloads")
    ap.add_argument("--ext", choices=["mkv", "mp4"], default="mkv", help="Which extension to download (default: mkv)")
    ap.add_argument("-j", "--jobs", type=int, default=2, help="Max concurrent downloads (default: 2)")
    args = ap.parse_args()

    app = DownloaderApp(csv_path=args.csv, target=args.target, ext=args.ext, jobs=args.jobs)
    app.run()

if __name__ == "__main__":
    main()