#!/usr/bin/env python3
"""
Core logic for CSV bulk downloads with concurrency, skip/resume, and filename inference.

- Extracts http(s) URLs from a CSV/text file.
- Filters URLs to MKV (default) or MP4; supports urls ending in ".mkv"/".mp4" or "/mkv"/"/mp4".
- Infers filenames via Content-Disposition / redirect target / path; normalizes extension.
- Skips existing files.
- Resumes with curl (-C -), follows redirects, retries.
- Provides a progress signal by polling file size on disk vs expected Content-Length.

This module is used by both the CLI (`csvdl.py`) and the TUI (`csvdl_tui.py`).
"""
from __future__ import annotations

import os
import re
import threading
import time
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

URL_RE = re.compile(r"https?://[^\s\",]+", re.IGNORECASE)

@dataclass
class Job:
    url: str
    ext: str = "mkv"
    name: Optional[str] = None
    expected_bytes: Optional[int] = None
    out_path: Optional[Path] = None
    status: str = "QUEUED"   # QUEUED | RUNNING | DONE | SKIP | FAIL | PAUSED
    message: str = ""
    _proc: Optional[subprocess.Popen] = field(default=None, repr=False, compare=False)

def expand(p: str) -> str:
    return os.path.abspath(os.path.expanduser(p))

def extract_urls_from_text(file_path: str) -> List[str]:
    urls: List[str] = []
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            urls.extend(URL_RE.findall(line))
    # de-dup, keep order
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def _curl_headers(url: str) -> str:
    # HEAD request, follow redirects
    try:
        return subprocess.check_output(
            ["curl", "-sIL", "--max-redirs", "10", url],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return ""

def _disposition_filename(headers: str) -> Optional[str]:
    for line in headers.splitlines():
        low = line.lower()
        if low.startswith("content-disposition:") and "filename=" in low:
            part = line.split("filename=", 1)[-1].strip()
            part = part.strip("\"'\r; ")
            return os.path.basename(part)
    return None

def _redirect_basename(headers: str) -> Optional[str]:
    loc = None
    for line in headers.splitlines():
        if line.lower().startswith("location:"):
            loc = line.split(":", 1)[-1].strip()
    if loc:
        loc = loc.split("?", 1)[0].split("#", 1)[0]
        return os.path.basename(loc)
    return None

def _content_length(headers: str) -> Optional[int]:
    # Return last Content-Length seen (after redirects)
    size: Optional[int] = None
    for line in headers.splitlines():
        if line.lower().startswith("content-length:"):
            try:
                size = int(line.split(":", 1)[-1].strip())
            except Exception:
                pass
    return size

def url_matches_extension(url: str, desired_ext: str) -> bool:
    u = url.lower()
    if u.endswith(f".{desired_ext}"):
        return True
    if u.endswith(f"/{desired_ext}") or f"/{desired_ext}?" in u or f"/{desired_ext}#" in u:
        return True
    return False

def infer_filename(url: str, headers: str, desired_ext: str) -> str:
    name = _disposition_filename(headers)
    if not name:
        name = _redirect_basename(headers)
    if not name:
        trimmed = url.split("?", 1)[0].split("#", 1)[0]
        name = os.path.basename(trimmed)

    if name.lower() in {"mkv", "mp4", ""}:
        parts = url.split("/")
        name = f"{(parts[-2] if len(parts) >= 2 else 'download')}.{desired_ext}"

    base, ext = os.path.splitext(name)
    if ext.lower() not in {".mkv", ".mp4"}:
        name = f"{name}.{desired_ext}"
    elif ext.lower().lstrip(".") != desired_ext.lower():
        name = f"{base}.{desired_ext}"
    return os.path.basename(name)

def prepare_jobs(urls: Iterable[str], desired_ext: str, target_dir: Path) -> List[Job]:
    jobs: List[Job] = []
    for u in urls:
        hdr = _curl_headers(u)
        # Quick filter: if neither URL nor inferred name indicate the desired ext, skip.
        if not url_matches_extension(u, desired_ext):
            name_try = infer_filename(u, hdr, desired_ext)
            if not name_try.lower().endswith(f".{desired_ext}"):
                continue
        name = infer_filename(u, hdr, desired_ext)
        size = _content_length(hdr)
        out = target_dir / name
        status = "SKIP" if out.exists() else "QUEUED"
        jobs.append(Job(url=u, ext=desired_ext, name=name, expected_bytes=size, out_path=out, status=status))
    return jobs

# --- download using curl, with on-disk size polling for progress ----------------

def _start_curl(job: Job) -> subprocess.Popen:
    assert job.out_path is not None
    cmd = ["curl", "-fL", "--retry", "3", "-C", "-", "-o", str(job.out_path), job.url]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    job._proc = proc
    return proc

def _current_size(job: Job) -> int:
    try:
        return job.out_path.stat().st_size if job.out_path else 0
    except Exception:
        return 0

def download_job(
    job: Job,
    progress_cb: Optional[Callable[[Job, float, int], None]] = None,
) -> Job:
    """Run a single download; calls progress_cb(job, fraction, bytes_done) periodically."""
    if job.status == "SKIP":
        return job
    job.status = "RUNNING"
    proc = _start_curl(job)

    try:
        while True:
            ret = proc.poll()
            size = _current_size(job)
            frac = 0.0
            if job.expected_bytes:
                frac = max(0.0, min(1.0, size / job.expected_bytes))
            if progress_cb:
                progress_cb(job, frac, size)
            if ret is not None:
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        try:
            proc.terminate()
        except Exception:
            pass
        job.status = "PAUSED"
        job.message = "terminated"
        return job

    if proc.returncode == 0:
        job.status = "DONE"
        job.message = ""
    else:
        # If the file exists and has non-zero size, leave it to resume later.
        if _current_size(job) > 0:
            job.status = "PAUSED"
            job.message = f"curl exit {proc.returncode} (partial saved)"
        else:
            job.status = "FAIL"
            job.message = f"curl exit {proc.returncode}"
    return job