#!/usr/bin/env python3
"""
Core utilities for krdl-dl: Selenium-based downloader for krdl.moe

Provides:
- Job dataclass for tracking downloads
- URL extraction from CSV/text files
- Authentication (login) to krdl.moe
- Web scraping for download links
- Utility functions (path expansion, etc.)
"""
from __future__ import annotations

import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

URL_RE = re.compile(r"https?://[^\s\",]+", re.IGNORECASE)

@dataclass
class Job:
    """Represents a single download job"""
    url: str
    ext: str = "mkv"
    name: Optional[str] = None
    expected_bytes: Optional[int] = None
    out_path: Optional[Path] = None
    status: str = "QUEUED"   # QUEUED | RUNNING | DONE | SKIP | FAIL | PAUSED
    message: str = ""

def expand(p: str) -> str:
    """Expand ~ and environment variables in path"""
    return os.path.abspath(os.path.expanduser(p))

def login_to_krdl(username: str, password: str) -> Optional[str]:
    """
    Login to krdl.moe and return session cookies for authenticated downloads.
    Returns the cookie string to use with requests, or None if login fails.
    """
    try:
        # Start a session to maintain cookies
        session = requests.Session()
        
        # Get the login page to retrieve CSRF token
        login_page_url = "https://krdl.moe/login"
        response = session.get(login_page_url)
        response.raise_for_status()
        
        # Parse the login page to find CSRF token
        soup = BeautifulSoup(response.text, 'html.parser')
        csrf_token = None
        
        # Try to find CSRF token in meta tag
        csrf_meta = soup.find('meta', {'name': 'csrf-token'})
        if csrf_meta:
            csrf_token = csrf_meta.get('content')
        
        # If not in meta, try hidden input
        if not csrf_token:
            csrf_input = soup.find('input', {'name': '_token'})
            if csrf_input:
                csrf_token = csrf_input.get('value')
        
        if not csrf_token:
            print("⚠️  Could not find CSRF token on login page")
            return None
        
        # Prepare login data
        login_data = {
            '_token': csrf_token,
            'email': username,
            'password': password,
        }
        
        # Submit login form
        login_url = "https://krdl.moe/login"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'Referer': login_page_url,
        }
        
        response = session.post(login_url, data=login_data, headers=headers, allow_redirects=True)
        
        # Check if login was successful (redirected away from login page)
        if 'login' not in response.url and response.status_code == 200:
            # Extract cookies as a string
            cookie_string = "; ".join([f"{cookie.name}={cookie.value}" for cookie in session.cookies])
            return cookie_string
        else:
            print(f"❌ Login failed. Response URL: {response.url}")
            return None
            
    except Exception as e:
        print(f"❌ Login error: {e}")
        return None

def scrape_krdl_page(url: str, auth_cookies: Optional[str] = None) -> List[str]:
    """
    Scrape download links from a krdl.moe page.
    Returns list of download URLs.
    
    Note: This is a fallback scraper using requests/BeautifulSoup.
    The main krdl_selenium.py uses Selenium for more reliable scraping.
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
        
        # Process all tables to get both EPISODES & FILMS and MISC FILES
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 4:  # File name, size, ext, link
                    # Look for download link in the last cell
                    link_cell = cells[-1]
                    download_link = link_cell.find('a', class_='download')
                    if download_link:
                        href = download_link.get('href')
                        # Convert relative URL to absolute with proper encoding
                        if href.startswith('/'):
                            # URL encode the path to handle special characters like []
                            # Use quote with safe='/' to preserve path separators
                            encoded_path = quote(href, safe='/')
                            full_url = f"https://krdl.moe{encoded_path}"
                        else:
                            full_url = href
                        download_links.append(full_url)
        
        return download_links
        
    except Exception as e:
        print(f"❌ Scraping error: {e}")
        return []

def extract_urls_from_text(file_path: str) -> List[str]:
    """Extract all http(s) URLs from a text/CSV file"""
    urls: List[str] = []
    try:
        with open(expand(file_path), "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        urls = URL_RE.findall(text)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    return urls

def prepare_jobs(
    urls: List[str],
    ext: str,
    target_dir: Path,
    auth_cookies: Optional[str] = None
) -> List[Job]:
    """
    Prepare Job objects from URLs, filtering by extension.
    Checks for existing files and marks them as SKIP.
    
    Note: This is a simplified version for Selenium-based downloads.
    Filename inference is handled by the browser.
    """
    jobs: List[Job] = []
    
    for url in urls:
        # Filter by extension in URL
        if not (url.endswith(f".{ext}") or url.endswith(f"/{ext}")):
            continue
        
        # Create job with minimal info (Selenium will handle the rest)
        job = Job(
            url=url,
            ext=ext,
            status="QUEUED"
        )
        jobs.append(job)
    
    return jobs