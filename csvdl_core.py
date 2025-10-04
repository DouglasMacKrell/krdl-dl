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
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
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

def login_to_krdl(username: str, password: str) -> Optional[str]:
    """
    Login to krdl.moe and return session cookies for authenticated downloads.
    Returns the cookie string to use with curl, or None if login fails.
    """
    try:
        # Start a session to maintain cookies
        session = requests.Session()
        
        # Get the login page first to get any CSRF tokens
        login_page = session.get('https://krdl.moe/login')
        login_page.raise_for_status()
        
        # Look for CSRF token using BeautifulSoup
        soup = BeautifulSoup(login_page.text, 'html.parser')
        csrf_token = None
        
        # Look for CSRF token in meta tags
        csrf_meta = soup.find('meta', {'name': 'csrf-token'})
        if csrf_meta:
            csrf_token = csrf_meta.get('content')
        
        # If not found in meta, look in form
        if not csrf_token:
            csrf_input = soup.find('input', {'name': '_token'})
            if csrf_input:
                csrf_token = csrf_input.get('value')
        
        # Prepare login data
        login_data = {
            'email': username,
            'password': password,
        }
        
        if csrf_token:
            login_data['_token'] = csrf_token
        
        # Add headers to mimic browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'Referer': 'https://krdl.moe/login',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        # Attempt login with redirects
        login_response = session.post('https://krdl.moe/login', data=login_data, headers=headers, allow_redirects=True)
        
        # Check if login was successful by looking for redirect or success indicators
        if (login_response.status_code == 200 and 
            ('dashboard' in login_response.url or 
             'home' in login_response.url or 
             'logout' in login_response.text.lower() or
             'welcome' in login_response.text.lower())):
            # Extract cookies from session
            cookies = []
            for cookie in session.cookies:
                cookies.append(f"{cookie.name}={cookie.value}")
            
            cookie_string = "; ".join(cookies)
            print(f"✅ Successfully logged in to krdl.moe")
            return cookie_string
        else:
            print(f"❌ Login failed - check credentials")
            return None
            
    except Exception as e:
        print(f"❌ Login error: {e}")
        return None

def scrape_krdl_page(url: str, auth_cookies: Optional[str] = None) -> List[str]:
    """
    Scrape download links from a krdl.moe page.
    Returns list of download URLs.
    """
    try:
        # Set up session with authentication if provided
        session = requests.Session()
        if auth_cookies:
            # Parse cookies from string
            for cookie_pair in auth_cookies.split(';'):
                if '=' in cookie_pair:
                    name, value = cookie_pair.strip().split('=', 1)
                    session.cookies.set(name, value, domain='krdl.moe')
        
        # Headers to mimic browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        # Fetch the page
        response = session.get(url, headers=headers)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all download links
        download_links = []
        
        # Debug: Print page structure
        print(f"🔍 Debug: Looking for download links...")
        
        # Process ALL tables to get both EPISODES & FILMS (50) + MISC FILES (3) = 53 total
        tables = soup.find_all('table')
        print(f"🔍 Found {len(tables)} tables")
        
        for i, table in enumerate(tables):
            # Check table headers
            headers = table.find_all('th')
            header_text = ' '.join([th.get_text().strip() for th in headers]).lower()
            print(f"🔍 Table {i} headers: {header_text}")
            
            # Process this table
            rows = table.find_all('tr')
            print(f"🔍 Processing {len(rows)} rows from table {i}")
            
            for j, row in enumerate(rows):
                cells = row.find_all('td')
                if len(cells) >= 4:  # File name, size, ext, link
                    # Look for download link in the last cell
                    link_cell = cells[-1]
                    download_link = link_cell.find('a', class_='download')
                    if download_link:
                        href = download_link.get('href')
                        print(f"🔍 Found download link: {href}")
                        # Convert relative URL to absolute with proper encoding
                        if href.startswith('/'):
                            # URL encode the path to handle special characters like []
                            # Use quote with safe='/' to preserve path separators
                            encoded_path = quote(href, safe='/')
                            full_url = f"https://krdl.moe{encoded_path}"
                        else:
                            full_url = href
                        print(f"🔍 Encoded URL: {full_url}")
                        download_links.append(full_url)
                    else:
                        # Debug: show what's in the cell
                        print(f"🔍 No download link in cell: {link_cell.get_text()[:50]}...")
        
        print(f"✅ Found {len(download_links)} download links from {url}")
        return download_links
        
    except Exception as e:
        print(f"❌ Scraping error: {e}")
        return []

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

def _curl_headers(url: str, auth_cookies: Optional[str] = None) -> str:
    # HEAD request, follow redirects
    try:
        cmd = ["curl", "-sIL", "--max-redirs", "10", url]
        if auth_cookies:
            cmd.extend(["-H", f"Cookie: {auth_cookies}"])
        
        result = subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return result
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

def prepare_jobs(urls: Iterable[str], desired_ext: str, target_dir: Path, auth_cookies: Optional[str] = None) -> List[Job]:
    jobs: List[Job] = []
    for u in urls:
        # Don't use auth cookies for header checking to avoid session invalidation
        hdr = _curl_headers(u, None)
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

def _start_curl(job: Job, auth_cookies: Optional[str] = None) -> subprocess.Popen:
    assert job.out_path is not None
    
    # Use provided auth cookies (required for authenticated downloads)
    if not auth_cookies:
        raise ValueError("Authentication cookies are required for downloads. Please login first.")
    
    krdl_cookies = auth_cookies
    
    cmd = [
        "curl", "-fL", "--retry", "3", "-C", "-", "--max-redirs", "10",
        "-H", f"Cookie: {krdl_cookies}",
        "-H", "Referer: https://krdl.moe/show/kyouryuu-sentai-zyuranger",  # Specific referer
        "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "-H", "Accept-Language: en-US,en;q=0.9",
        "-H", "Sec-Fetch-Dest: document",
        "-H", "Sec-Fetch-Mode: navigate", 
        "-H", "Sec-Fetch-Site: same-origin",
        "-H", "Sec-Fetch-User: ?1",
        "-H", "Upgrade-Insecure-Requests: 1",
        "-o", str(job.out_path), 
        job.url
    ]
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
    auth_cookies: Optional[str] = None,
) -> Job:
    """Run a single download; calls progress_cb(job, fraction, bytes_done) periodically."""
    if job.status == "SKIP":
        return job
    job.status = "RUNNING"
    
    # Use the SAME authentication cookies - don't re-authenticate
    proc = _start_curl(job, auth_cookies)

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

def download_queue(
    jobs: List[Job],
    auth_cookies: Optional[str] = None,
    max_concurrent: int = 2,
    progress_cb: Optional[Callable[[Job, float, int], None]] = None,
) -> List[Job]:
    """
    Download jobs with proper queue management.
    - Maximum 2 concurrent downloads
    - Only start new downloads when others finish
    - No re-authentication
    """
    print(f"🚀 Starting download queue with max {max_concurrent} concurrent downloads...")
    print(f"⚠️  Note: Downloads can take 5+ minutes each. Be patient!")
    
    # Track running downloads
    running_downloads = []
    completed_jobs = []
    
    for i, job in enumerate(jobs):
        if job.status == "SKIP":
            completed_jobs.append(job)
            continue
            
        print(f"📥 Queueing download {i+1}/{len(jobs)}: {job.name}")
        
        # Wait until we have space for a new download
        while len(running_downloads) >= max_concurrent:
            # Check if any downloads have finished
            finished_downloads = []
            for download in running_downloads:
                if download['process'].poll() is not None:
                    # Download finished
                    result = download['job']
                    if download['process'].returncode == 0:
                        result.status = "DONE"
                        result.message = ""
                        print(f"  ✅ Completed: {result.name}")
                    else:
                        if _current_size(result) > 0:
                            result.status = "PAUSED"
                            result.message = f"curl exit {download['process'].returncode} (partial saved)"
                        else:
                            result.status = "FAIL"
                            result.message = f"curl exit {download['process'].returncode}"
                        print(f"  ❌ Failed: {result.name} - {result.message}")
                    completed_jobs.append(result)
                    finished_downloads.append(download)
            
            # Remove finished downloads
            for download in finished_downloads:
                running_downloads.remove(download)
            
            # Wait a bit before checking again
            time.sleep(1)
        
        # Start new download
        print(f"  🚀 Starting download: {job.name}")
        proc = _start_curl(job, auth_cookies)
        running_downloads.append({
            'job': job,
            'process': proc,
            'start_time': time.time()
        })
    
    # Wait for remaining downloads to finish
    print(f"⏳ Waiting for {len(running_downloads)} remaining downloads to finish...")
    while running_downloads:
        finished_downloads = []
        for download in running_downloads:
            if download['process'].poll() is not None:
                # Download finished
                result = download['job']
                if download['process'].returncode == 0:
                    result.status = "DONE"
                    result.message = ""
                    print(f"  ✅ Completed: {result.name}")
                else:
                    if _current_size(result) > 0:
                        result.status = "PAUSED"
                        result.message = f"curl exit {download['process'].returncode} (partial saved)"
                    else:
                        result.status = "FAIL"
                        result.message = f"curl exit {download['process'].returncode}"
                    print(f"  ❌ Failed: {result.name} - {result.message}")
                completed_jobs.append(result)
                finished_downloads.append(download)
        
        # Remove finished downloads
        for download in finished_downloads:
            running_downloads.remove(download)
        
        # Wait a bit before checking again
        time.sleep(1)
    
    print(f"🎉 All downloads completed!")
    return completed_jobs