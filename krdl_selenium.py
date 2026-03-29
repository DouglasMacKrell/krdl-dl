#!/usr/bin/env python3
"""
Selenium-based krdl.moe downloader
Uses browser automation to handle JavaScript and complex authentication
"""

import argparse
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from csvdl_core import Job, expand

# Load environment variables from .env file
load_dotenv()


def _normalize_download_basename(name: str) -> str:
    """
    Match scraped / expected filenames to on-disk names. Table text can use NBSP or NFC/NFD
    mismatches vs what Chrome writes; without this we never see the finished .mkv and loop forever.
    """
    if not name:
        return ""
    t = unicodedata.normalize("NFC", name.strip())
    for ch in ("\u00a0", "\u2007", "\u202f", "\ufeff"):
        t = t.replace(ch, " ")
    return t


def _parse_krdl_size_bytes(size_cell: str) -> int | None:
    """
    Parse KRDL table size text (e.g. '244.85 MiB', '1.19 GiB') to bytes. Unknown shapes → None.
    """
    t = _normalize_download_basename(size_cell).strip()
    if not t:
        return None
    m = re.match(r"^([\d.]+)\s*(KiB|MiB|GiB|TiB|KB|MB|GB)\s*$", t, re.I)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2).lower()
    mult = {
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
    }.get(unit)
    if mult is None:
        return None
    return int(val * mult)


def _is_hd_filename(filename: str) -> bool:
    return bool(re.search(r"(?i)_HD_", _normalize_download_basename(filename)))


def _canonical_episode_key(filename: str) -> str:
    """
    Map a table filename to a logical episode / special key so HD vs SD rows dedupe.
    Unknown shapes get a per-filename key (no cross-row dedupe).
    """
    n = _normalize_download_basename(filename)
    if (
        re.search(r"(?i)(The_)?Movie.*_HD_", n)
        or re.search(r"(?i)_Movie_\s*\[", n)
        or re.search(r"(?i)_The_Movie_", n)
    ):
        return "movie"
    m = re.search(r"(?i)_Ep0*(\d+)_", n)
    if m:
        return f"ep:{int(m.group(1)):03d}"
    m = re.search(r"(?i)_-_(\d{2,3})_", n)
    if m:
        return f"ep:{int(m.group(1)):03d}"
    m = re.search(r"(?i)_(\d{1,3})_\[[0-9a-fA-F]{6,12}\]", n)
    if m:
        return f"ep:{int(m.group(1)):03d}"
    return f"unique:{n}"


ScrapeRow = tuple[str, str, int | None]


def filter_by_quality_preference(
    download_items: list[ScrapeRow],
    prefer: Literal["hd", "sd"],
) -> list[ScrapeRow]:
    """
    For each canonical episode key, keep one table row. Uses KRDL file size as the main signal
    (larger = better for prefer='hd', smaller for prefer='sd'); ``_HD_`` in the filename breaks ties.
    Unknown sizes sort last for 'hd' (lose to known sizes) and last for 'sd' (lose to known small).
    """
    key_order: list[str] = []
    groups: dict[str, list[tuple[str, str, int | None, bool]]] = {}
    for url, fn, size_b in download_items:
        key = _canonical_episode_key(fn)
        if key not in groups:
            key_order.append(key)
            groups[key] = []
        groups[key].append((url, fn, size_b, _is_hd_filename(fn)))

    result: list[ScrapeRow] = []
    dropped = 0
    for key in key_order:
        g = groups[key]
        if prefer == "hd":
            chosen = max(
                g,
                key=lambda r: (
                    r[2] if r[2] is not None else -1,
                    1 if r[3] else 0,
                ),
            )
        else:
            chosen = min(
                g,
                key=lambda r: (
                    r[2] if r[2] is not None else float("inf"),
                    1 if r[3] else 0,
                ),
            )
        result.append((chosen[0], chosen[1], chosen[2]))
        dropped += len(g) - 1

    if dropped:
        print(
            f"🎯 Quality preference {prefer!r} (size-primary, _HD_ tiebreak): dropped {dropped} "
            f"duplicate episode row(s) ({len(download_items)} → {len(result)} files)"
        )
    else:
        print(
            f"🎯 Quality preference {prefer!r}: no duplicate keys in scrape ({len(result)} files)"
        )
    return result


class KrdlSeleniumDownloader:
    def __init__(self, target_dir: Path, headless: bool = False):
        self.target_dir = target_dir
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self.driver = None
        self.headless = headless

    def setup_driver(self):
        """Setup Chrome driver with proper options"""
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless")

        # Browser options to mimic real user
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--disable-features=VizDisplayCompositor")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        # FRESH SESSION - Clear all data to avoid rate limiting
        # NOTE: Removed --incognito because it prevents Chrome from respecting download preferences
        # We still get a fresh session by clearing all browser data in clear_all_data()
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        chrome_options.add_argument("--disable-renderer-backgrounding")
        chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # DISABLE SAVE DIALOGS - Force automatic downloads
        chrome_options.add_argument("--disable-popup-blocking")
        chrome_options.add_argument("--disable-prompt-on-repost")
        chrome_options.add_argument("--disable-hang-monitor")
        chrome_options.add_argument("--disable-client-side-phishing-detection")
        chrome_options.add_argument("--disable-sync")
        chrome_options.add_argument("--disable-translate")
        chrome_options.add_argument("--disable-ipc-flooding-protection")
        chrome_options.add_argument("--disable-popup-blocking")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--disable-images")
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--disable-default-apps")
        chrome_options.add_argument("--disable-infobars")

        # Set download directory to target directory - Chrome downloads directly there!
        # No moving needed, simpler flow
        prefs = {
            "download.default_directory": str(self.target_dir.absolute()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing_for_trusted_sources_enabled": False,
            "profile.default_content_setting_values.automatic_downloads": 1,  # Allow automatic downloads
        }
        chrome_options.add_experimental_option("prefs", prefs)

        # Setup driver
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)

        # Verify download directory is set correctly
        print(f"🔍 Chrome will download directly to target: {self.target_dir.absolute()}")

        # Execute script to remove webdriver property
        self.driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Clear all cookies and storage immediately
        self.clear_all_data()

    def clear_all_data(self):
        """Clear all browser data to start fresh"""
        try:
            print("🧹 Clearing all browser data for fresh session...")
            # Clear cookies
            self.driver.delete_all_cookies()

            # Clear local storage
            self.driver.execute_script("window.localStorage.clear();")
            self.driver.execute_script("window.sessionStorage.clear();")

            # Clear IndexedDB
            self.driver.execute_script("""
                if (window.indexedDB) {
                    indexedDB.databases().then(databases => {
                        databases.forEach(db => {
                            indexedDB.deleteDatabase(db.name);
                        });
                    });
                }
            """)

            print("✅ Browser data cleared successfully")
        except Exception as e:
            print(f"⚠️  Warning: Could not clear all browser data: {e}")

    def clear_session_data(self):
        """Clear session data between downloads to avoid rate limiting"""
        try:
            # Clear cookies for krdl.moe domain
            self.driver.delete_all_cookies()

            # Clear any session storage
            self.driver.execute_script("window.sessionStorage.clear();")

            print("🧹 Cleared session data between downloads")
        except Exception as e:
            print(f"⚠️  Warning: Could not clear session data: {e}")

    def login(self, username: str, password: str) -> bool:
        """Login to krdl.moe"""
        try:
            print(f"🔐 Logging in to krdl.moe with username: {username[:3]}***")

            # Go to login page
            self.driver.get("https://krdl.moe/login")
            time.sleep(5)  # Wait longer for page to load

            # Debug: Print page source to see what we're working with
            print("🔍 Page title:", self.driver.title)

            # Check if we're on a register page instead of login
            if "register" in self.driver.current_url.lower():
                print("🚨 Redirected to register page - account may be rate limited")
                return False

            # Try different selectors for email field
            email_field = None
            for selector in [
                "input[name='email']",
                "input[type='email']",
                "#email",
                "input[placeholder*='email']",
            ]:
                try:
                    email_field = self.driver.find_element(By.CSS_SELECTOR, selector)
                    print(f"✅ Found email field with selector: {selector}")
                    break
                except Exception:
                    continue

            if not email_field:
                print("❌ Could not find email field")
                return False

            # Try different selectors for password field
            password_field = None
            for selector in [
                "input[name='password']",
                "input[type='password']",
                "#password",
                "input[placeholder*='password']",
            ]:
                try:
                    password_field = self.driver.find_element(By.CSS_SELECTOR, selector)
                    print(f"✅ Found password field with selector: {selector}")
                    break
                except Exception:
                    continue

            if not password_field:
                print("❌ Could not find password field")
                return False

            # Fill in credentials
            email_field.clear()
            email_field.send_keys(username)
            password_field.clear()
            password_field.send_keys(password)

            # Try different selectors for submit button
            submit_button = None
            for selector in [
                "button[type='submit']",
                "input[type='submit']",
                "button",
                ".btn",
                "#login-button",
            ]:
                try:
                    submit_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    print(f"✅ Found submit button with selector: {selector}")
                    break
                except Exception:
                    continue

            if not submit_button:
                print("❌ Could not find submit button")
                return False

            # Submit form
            submit_button.click()
            time.sleep(3)  # Wait for redirect

            # Check if login was successful
            current_url = self.driver.current_url
            print(f"🔍 Current URL after login: {current_url}")
            print(f"🔍 Page title after login: {self.driver.title}")

            # Check for any error messages on the page
            try:
                error_elements = self.driver.find_elements(
                    By.CSS_SELECTOR, ".alert, .error, .warning, .message"
                )
                if error_elements:
                    for elem in error_elements:
                        print(f"🔍 Error message after login: {elem.text}")
            except Exception:
                pass

            if "login" not in current_url:
                print("✅ Successfully logged in to krdl.moe")
                return True
            else:
                print("❌ Login failed - still on login page")
                return False

        except Exception as e:
            print(f"❌ Login failed: {e}")
            return False

    def scrape_download_links(self, show_url: str, extension: str = "mkv") -> list[ScrapeRow]:
        """Scrape download links from show page; each row is (url, filename, size_bytes | None)."""
        try:
            print(f"🌐 Scraping krdl.moe page: {show_url}")

            # Navigate to show page
            print(f"🔍 Navigating to show page: {show_url}")
            self.driver.get(show_url)

            # Wait for page to load
            wait = WebDriverWait(self.driver, 10)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))

            # Log current state after navigation
            current_url = self.driver.current_url
            print(f"🔍 Current URL after show page navigation: {current_url}")
            print(f"🔍 Page title: {self.driver.title}")

            # Check for any error messages on the page
            try:
                error_elements = self.driver.find_elements(
                    By.CSS_SELECTOR, ".alert, .error, .warning, .message"
                )
                if error_elements:
                    for elem in error_elements:
                        print(f"🔍 Error message on show page: {elem.text}")
            except Exception:
                pass

            # CRITICAL: Click "All" in pagination to show all entries
            try:
                # Look for the "Show X entries" dropdown
                show_entries_select = self.driver.find_element(
                    By.CSS_SELECTOR, "select[name*='length'], select[name*='entries']"
                )
                print("🔍 Found pagination dropdown")

                # Click on it to open options
                show_entries_select.click()
                time.sleep(0.5)

                # Find and click "All" option
                all_option = show_entries_select.find_element(By.XPATH, ".//option[text()='All']")
                all_option.click()
                print("✅ Selected 'All' entries - waiting for table to update...")
                time.sleep(2)  # Wait for table to reload with all entries
            except Exception as e:
                print(f"⚠️  Could not find pagination dropdown (may already show all): {e}")

            # Find all download links with their filenames from tables
            download_links = []

            tables = self.driver.find_elements(By.TAG_NAME, "table")
            print(f"🔍 Found {len(tables)} tables")

            for i, table in enumerate(tables):
                rows = table.find_elements(By.TAG_NAME, "tr")
                print(f"🔍 Table {i}: {len(rows)} rows")

                for row in rows:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 4:  # Should have: filename, size, ext, download link
                        # Get the filename from first cell
                        filename_cell = cells[0]
                        filename = filename_cell.text.strip()
                        size_cell = cells[1].text.strip() if len(cells) >= 2 else ""
                        size_b = _parse_krdl_size_bytes(size_cell)

                        # Get the download link from last cell
                        link_cell = cells[-1]
                        try:
                            download_link = link_cell.find_element(By.CSS_SELECTOR, "a")
                            href = download_link.get_attribute("href")

                            if href and "/download/" in href and f"/{extension}" in href:
                                download_links.append((href, filename, size_b))
                                sz_dbg = f"{size_b:,} B" if size_b is not None else "size?"
                                print(f"🔍 Found: {filename} ({sz_dbg})")
                        except Exception:
                            pass

            print(f"✅ Found {len(download_links)} download links for extension: {extension}")
            return download_links

        except Exception as e:
            print(f"❌ Scraping error: {e}")
            return []

    def download_file(self, url: str, filename: str) -> bool:
        """Download a single file using browser automation"""
        try:
            print(f"📥 Downloading: {filename}")

            # Navigate to download URL
            self.driver.get(url)
            time.sleep(2)

            # Check for register/premium redirect - GRACEFUL STOP
            current_url = self.driver.current_url
            if "register" in current_url.lower() or "premium" in current_url.lower():
                print("🚨 RATE LIMIT REDIRECT DETECTED!")
                print(f"🚨 Current URL: {current_url}")
                print("🚨 This means your account has been rate-limited")
                print("🚨 STOPPING DOWNLOADS TO AVOID FURTHER PUNISHMENT")
                return "RATE_LIMIT_REDIRECT"  # Special return value

            # Check if we got redirected to gen.krdl.moe (good sign)
            if "gen.krdl.moe" in current_url:
                print(f"✅ Redirected to download server: {current_url}")
            else:
                print(f"🔍 Current URL: {current_url}")

            # Let Chrome handle downloads automatically

            # Check if download started by looking for file in download directory
            expected_file = self.target_dir / filename
            temp_file = self.target_dir / f"{filename}.crdownload"
            max_wait = 30  # Wait up to 30 seconds for download to start

            for _ in range(max_wait):
                if expected_file.exists() or temp_file.exists():
                    print(f"✅ Download started: {filename}")
                    return True
                time.sleep(1)

            print(f"❌ Download failed to start: {filename}")
            return False

        except Exception as e:
            print(f"❌ Download error for {filename}: {e}")
            return False

    def _handle_save_dialog(self, filename: str):
        """Handle browser save dialog automatically"""
        try:
            # Wait a moment for dialog to appear
            time.sleep(2)

            # Try multiple approaches to handle save dialog
            try:
                # Approach 1: Look for save dialog elements
                save_dialogs = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "input[type='text'], input[name='filename'], input[placeholder*='filename']",
                )
                if save_dialogs:
                    print(f"🔍 Found save dialog, setting filename: {filename}")
                    save_dialogs[0].clear()
                    save_dialogs[0].send_keys(filename)

                    # Look for save button
                    save_buttons = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "button:contains('Save'), input[value='Save'], button[type='submit']",
                    )
                    if save_buttons:
                        save_buttons[0].click()
                        print(f"✅ Save dialog handled for: {filename}")
                        return

                # Approach 2: Use keyboard shortcuts
                from selenium.webdriver.common.action_chains import ActionChains
                from selenium.webdriver.common.keys import Keys

                print(f"🔍 Trying keyboard shortcuts for: {filename}")
                actions = ActionChains(self.driver)

                # Try Enter to accept default save
                actions.send_keys(Keys.ENTER).perform()
                time.sleep(1)

                # Try Tab + Enter to navigate and save
                actions.send_keys(Keys.TAB, Keys.ENTER).perform()
                time.sleep(1)

                print(f"✅ Save dialog handled with keyboard shortcuts for: {filename}")
                return

            except Exception as e:
                print(f"⚠️  Could not handle save dialog automatically: {e}")
                print(f"⚠️  Manual intervention may be required for: {filename}")

        except Exception as e:
            print(f"⚠️  Save dialog handling failed: {e}")

    def download_queue(
        self, jobs: list, max_concurrent: int = 2, stagger_seconds: float = 15.0
    ) -> list:
        """Download files with PROPER QUEUE MANAGEMENT - only start new downloads when others finish"""
        print(f"🚀 Starting download queue with max {max_concurrent} concurrent downloads...")
        print("⚠️  Note: Downloads can take 5+ minutes each. Be patient!")
        print(f"⚠️  CRITICAL: Only {max_concurrent} downloads will run at once!")
        if stagger_seconds > 0:
            print(
                f"⏸️  Between-slot stagger: {stagger_seconds:g}s pause before each new download "
                "after the first batch (helps avoid krdl session / rate kicks)."
            )

        completed_jobs = []
        running_downloads = []  # Track active downloads
        slot_wait_loops = 0

        for i, job in enumerate(jobs):
            if job.status == "SKIP":
                completed_jobs.append(job)
                continue

            print(f"📥 Queueing download {i + 1}/{len(jobs)}: {job.name}")

            waited_for_slot = False
            # WAIT until we have space for a new download
            while len(running_downloads) >= max_concurrent:
                waited_for_slot = True
                print(
                    f"⏳ {len(running_downloads)} downloads running, waiting for one to finish..."
                )
                time.sleep(5)  # Check every 5 seconds

                # Check if any downloads have finished (or stalled with no real progress)
                finished_downloads = []
                abandoned = []
                for download in running_downloads:
                    if self._should_abandon_stalled_download(download):
                        abandoned.append(download)
                    elif self._is_download_finished(download):
                        finished_downloads.append(download)

                for download in abandoned:
                    running_downloads.remove(download)
                    completed_jobs.append(download["job"])
                    print(f"❌ Dropped stalled job (slot freed): {download['filename']!r}")

                # Remove finished downloads
                for download in finished_downloads:
                    running_downloads.remove(download)
                    print(f"✅ Download finished: {download['filename']}")

                if not finished_downloads and not abandoned:
                    slot_wait_loops += 1
                    if slot_wait_loops % 24 == 0:
                        self._log_stuck_poll(running_downloads, slot_wait_loops)
                else:
                    slot_wait_loops = 0

            slot_wait_loops = 0

            if waited_for_slot and stagger_seconds > 0:
                print(
                    f"⏸️  Pausing {stagger_seconds:g}s before starting next download "
                    "(server cooldown)..."
                )
                time.sleep(stagger_seconds)

            # Start new download
            print(f"🚀 Starting download: {job.name}")
            print(f"🔍 Download URL: {job.url}")

            # DON'T clear session data - keep the login session active
            print("🔍 Keeping login session active (not clearing data)")

            # Navigate to download URL to start download
            print("🔍 Navigating to download URL...")
            out_expected = self.target_dir / job.name
            stale_partial = self.target_dir / f"{job.name}.crdownload"
            if stale_partial.is_file() and not out_expected.is_file():
                try:
                    stale_partial.unlink()
                    print(f"🧹 Removed stale partial so Chrome can retry: {stale_partial.name}")
                except OSError as e:
                    print(f"⚠️  Could not remove stale partial {stale_partial.name}: {e}")
            cr_before = frozenset(self._crdownload_basenames())
            self.driver.get(job.url)
            time.sleep(3)  # Let redirect / download handoff settle (was 2s; krdl is sensitive)

            # Log current state after navigation
            current_url = self.driver.current_url
            print(f"🔍 Current URL after navigation: {current_url}")
            print(f"🔍 Page title: {self.driver.title}")

            # Check for any error messages on the page
            try:
                error_elements = self.driver.find_elements(
                    By.CSS_SELECTOR, ".alert, .error, .warning, .message"
                )
                if error_elements:
                    for elem in error_elements:
                        print(f"🔍 Error message on page: {elem.text}")
            except Exception:
                pass

            # Check for register/premium redirect - GRACEFUL STOP
            current_url = self.driver.current_url
            if "register" in current_url.lower() or "premium" in current_url.lower():
                print("🚨 RATE LIMIT REDIRECT DETECTED!")
                print(f"🚨 Current URL: {current_url}")
                print("🚨 This means your account has been rate-limited")
                print("🚨 STOPPING ALL DOWNLOADS TO AVOID FURTHER PUNISHMENT")
                print("🚨 Please wait 15 minutes before trying again")
                return completed_jobs  # Stop immediately

            # Check if we got redirected to gen.krdl.moe (good sign)
            if "gen.krdl.moe" in current_url:
                print(f"✅ Redirected to download server: {current_url}")
            else:
                print(f"🔍 Current URL: {current_url}")

            began, claimed_new = self._wait_for_download_begin_signal(
                job.name, cr_before, timeout_sec=90
            )
            if not began:
                print(
                    f"❌ No download began for {job.name!r} within 90s "
                    "(no gen.krdl redirect, no new .crdownload, no file). "
                    "Not reserving a slot — fix rate limits / network and re-run."
                )
                job.status = "FAIL"
                completed_jobs.append(job)
                continue

            download_info = {
                "job": job,
                "filename": job.name,
                "start_time": time.time(),
                "url": job.url,
                "claimed_crdownloads": set(claimed_new),
            }
            if claimed_new:
                print(f"🔖 Tracking Chrome partial(s) for this job: {', '.join(sorted(claimed_new))}")

            running_downloads.append(download_info)
            print(f"📊 Active downloads: {len(running_downloads)}/{max_concurrent}")

        # Wait for remaining downloads to finish
        print(f"⏳ Waiting for {len(running_downloads)} remaining downloads to finish...")
        drain_loops = 0
        while running_downloads:
            time.sleep(5)
            finished_downloads = []
            abandoned = []
            for download in running_downloads:
                if self._should_abandon_stalled_download(download):
                    abandoned.append(download)
                elif self._is_download_finished(download):
                    finished_downloads.append(download)
                    print(f"✅ Download completed: {download['filename']}")

            for download in abandoned:
                running_downloads.remove(download)
                completed_jobs.append(download["job"])
                print(f"❌ Dropped stalled job: {download['filename']!r}")

            # Remove finished downloads
            for download in finished_downloads:
                running_downloads.remove(download)

            if not finished_downloads and not abandoned:
                drain_loops += 1
                if drain_loops % 24 == 0:
                    self._log_stuck_poll(running_downloads, drain_loops)
            else:
                drain_loops = 0

        print("🎉 All downloads completed!")
        return completed_jobs

    def _saved_file_path(self, filename: str):
        """Path to the finished video if it exists (exact path or normalized basename match)."""
        if not filename:
            return None
        want = _normalize_download_basename(filename).lower()
        p = self.target_dir / filename
        try:
            if p.is_file():
                return p
        except OSError:
            pass
        try:
            for f in self.target_dir.iterdir():
                if not f.is_file():
                    continue
                if _normalize_download_basename(f.name).lower() == want:
                    return f
        except OSError:
            pass
        return None

    def _named_partial_path(self, filename: str):
        """Chrome partial ``<name>.crdownload`` if present (normalized basename match)."""
        if not filename:
            return None
        want = _normalize_download_basename(filename).lower()
        t = self.target_dir / f"{filename}.crdownload"
        try:
            if t.is_file():
                return t
        except OSError:
            pass
        try:
            for f in self.target_dir.iterdir():
                if not f.is_file():
                    continue
                n = f.name
                low = n.lower()
                if not low.endswith(".crdownload"):
                    continue
                stem = n[: -len(".crdownload")]
                if _normalize_download_basename(stem).lower() == want:
                    return f
        except OSError:
            pass
        return None

    def _log_stuck_poll(self, running_downloads: list, polls: int) -> None:
        """Explain why we are not seeing completion (helps debug false-negative stalls)."""
        elapsed_s = polls * 5
        print(
            f"⚠️  Still waiting (~{elapsed_s // 60}m {elapsed_s % 60}s, {polls} polls @ 5s) — "
            "filesystem check:"
        )
        for d in running_downloads:
            fn = d.get("filename")
            if not fn:
                print("   • (job has no filename)")
                continue
            saved = self._saved_file_path(fn)
            partial = self._named_partial_path(fn)
            claimed = d.get("claimed_crdownloads") or set()
            claim_status = ", ".join(c for c in sorted(claimed) if c) or "none"
            print(
                f"   • {fn!r} → "
                f"final={'OK ' + saved.name if saved else 'missing'}, "
                f"partial={partial.name if partial else 'none'}, "
                f"claimed={claim_status}"
            )

    def _crdownload_basenames(self) -> set[str]:
        try:
            return {p.name for p in self.target_dir.glob("*.crdownload")}
        except OSError:
            return set()

    def _wait_for_download_begin_signal(
        self, filename: str | None, cr_before: frozenset[str], *, timeout_sec: int = 90
    ) -> tuple[bool, frozenset[str]]:
        """
        Do not treat a navigation as a live download until the browser or filesystem shows
        something real. Returns which *new* .crdownload names appeared when we succeed so each
        job tracks *its* Chrome partial (avoids phantom slots when a partial vanishes).
        """
        deadline = time.time() + timeout_sec
        fn = str(filename or "")
        while time.time() < deadline:
            try:
                cur = self.driver.current_url or ""
            except Exception:
                cur = ""
            after = frozenset(self._crdownload_basenames())
            new_crs = frozenset(after - cr_before)

            if "gen.krdl.moe" in cur:
                return True, new_crs
            if fn and (self._saved_file_path(fn) or self._named_partial_path(fn)):
                return True, new_crs
            if new_crs:
                return True, new_crs
            time.sleep(2)
        return False, frozenset()

    def _should_abandon_stalled_download(self, download_info: dict) -> bool:
        """
        Drop jobs that will never satisfy _is_download_finished: frozen named partial,
        or no file / no named partial for so long that Chrome almost certainly never attached.
        """
        job = download_info.get("job")
        fn = str(download_info.get("filename") or "")
        if not fn:
            if job is not None:
                job.status = "FAIL"
            return True
        if self._saved_file_path(fn):
            return False

        now = time.time()
        start = float(download_info.get("start_time", now))
        elapsed = now - start
        partial = self._named_partial_path(fn)

        if partial is not None:
            sz = partial.stat().st_size
            if "stall_size" not in download_info:
                download_info["stall_size"] = sz
                download_info["stall_since"] = now
                return False
            if sz != download_info["stall_size"]:
                download_info["stall_size"] = sz
                download_info["stall_since"] = now
                return False
            stall = now - float(download_info.get("stall_since", start))
            if stall >= 480:
                print(
                    f"❌ Giving up on {fn!r}: named .crdownload stuck at {sz:,} B for {stall:.0f}s"
                )
                if job is not None:
                    job.status = "FAIL"
                return True
            return False

        claimed = download_info.get("claimed_crdownloads") or set()
        any_claim_file = False
        for cname in claimed:
            cp = self.target_dir / cname
            try:
                if cp.is_file() and cname.lower().endswith(".crdownload"):
                    any_claim_file = True
                    sz = cp.stat().st_size
                    key = f"claim:{cname}"
                    if f"{key}_since" not in download_info:
                        download_info[key] = sz
                        download_info[f"{key}_since"] = now
                    elif sz != download_info[key]:
                        download_info[key] = sz
                        download_info[f"{key}_since"] = now
                    else:
                        cstall = now - float(download_info.get(f"{key}_since", start))
                        if cstall >= 480:
                            print(
                                f"❌ Giving up on {fn!r}: claimed partial {cname!r} "
                                f"stuck at {sz:,} B for {cstall:.0f}s"
                            )
                            if job is not None:
                                job.status = "FAIL"
                            return True
            except OSError:
                pass

        if claimed and not any_claim_file:
            van = download_info.get("claim_vanished_since")
            if van is None:
                download_info["claim_vanished_since"] = now
            elif now - van >= 90:
                print(
                    f"❌ Giving up on {fn!r}: claimed .crdownload(s) vanished with no "
                    f".mkv ({list(claimed)!r}) — Chrome may have cancelled the transfer"
                )
                if job is not None:
                    job.status = "FAIL"
                return True
        else:
            download_info.pop("claim_vanished_since", None)

        if not claimed and elapsed >= 180:
            print(
                f"❌ Giving up on {fn!r}: no .mkv, no named partial, no claimed .crdownload "
                f"after {elapsed:.0f}s (nothing to track — likely never really started)"
            )
            if job is not None:
                job.status = "FAIL"
            return True
        return False

    def _notify_saved_complete(self, download_info: dict, saved: Path, fn: str) -> bool:
        file_size = saved.stat().st_size
        if "completed" not in download_info:
            download_info["completed"] = True
            if saved.name != fn:
                print(f"✅ Download complete: {fn} ({file_size:,} bytes) [on disk: {saved.name}]")
            else:
                print(f"✅ Download complete: {fn} ({file_size:,} bytes)")
        return True

    def _is_download_finished(self, download_info: dict) -> bool:
        """
        Complete when the expected file exists in the target directory (case-insensitive name).
        While `filename.crdownload` exists, treat as still downloading (data may be streaming).
        If there is no such partial, look at the folder again — we do not wait on Chrome alone.
        """
        try:
            fn = download_info.get("filename")
            if not fn:
                return False
            fn = str(fn)
            saved = self._saved_file_path(fn)
            if saved is not None:
                return self._notify_saved_complete(download_info, saved, fn)

            partial = self._named_partial_path(fn)
            if partial is not None:
                current_size = partial.stat().st_size
                if "last_size" not in download_info:
                    download_info["last_size"] = current_size
                    print(f"🔍 Download started: {fn} (partial: {partial.name})")
                elif current_size != download_info["last_size"]:
                    download_info["last_size"] = current_size
                    print(f"🔍 Downloading: {fn} ({current_size:,} bytes)")
                return False

            for cname in sorted(download_info.get("claimed_crdownloads") or ()):
                cp = self.target_dir / cname
                try:
                    if cp.is_file() and cname.lower().endswith(".crdownload"):
                        current_size = cp.stat().st_size
                        key = f"claim_last:{cname}"
                        if key not in download_info:
                            download_info[key] = current_size
                            print(f"🔍 Download started: {fn} (partial: {cname})")
                        elif current_size != download_info[key]:
                            download_info[key] = current_size
                            print(f"🔍 Downloading: {fn} ({cname}, {current_size:,} bytes)")
                        return False
                except OSError:
                    pass

            saved = self._saved_file_path(fn)
            if saved is not None:
                return self._notify_saved_complete(download_info, saved, fn)

            if "waiting" not in download_info:
                download_info["waiting"] = True
                print(f"⏳ Waiting for download to start: {fn}")

            return False

        except Exception as e:
            print(f"⚠️  Error checking download status: {e}")
            return False

    def close(self):
        """Close the browser"""
        if self.driver:
            self.driver.quit()


def main():
    ap = argparse.ArgumentParser(description="krdl-dl — Selenium-based Site Scraper & Downloader")
    ap.add_argument("--url", required=True, help="URL of the krdl.moe page to scrape")
    ap.add_argument("--target", required=True, help="Directory to save downloads (REQUIRED)")
    ap.add_argument(
        "--ext",
        choices=["mkv", "mp4"],
        default="mkv",
        help="Which video extension to download (default: mkv)",
    )
    ap.add_argument(
        "--quality",
        choices=["hd", "sd"],
        default="hd",
        help=(
            "Per episode (canonical numbering), pick one table row: hd = largest file size from "
            "KRDL, tie-breaking with _HD_ in the filename (fills gaps with whatever size exists); "
            "sd = smallest size, tie-breaking toward non-HD names, falling back when only large/HD "
            "files exist."
        ),
    )
    ap.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    ap.add_argument("--username", help="krdl.moe username for authentication")
    ap.add_argument("--password", help="krdl.moe password for authentication")
    ap.add_argument("--limit", type=int, help="Limit the number of files to download (for testing)")
    ap.add_argument(
        "--stagger-seconds",
        type=float,
        default=15.0,
        metavar="SEC",
        help=(
            "Seconds to pause before starting each new download after waiting for a slot to free "
            "(default: 15). Use 0 to disable. Helps avoid krdl premium/rate redirects when chaining "
            "many files."
        ),
    )
    args = ap.parse_args()

    # Validate target directory
    if not args.target:
        print("❌ ERROR: --target directory is REQUIRED!")
        print("Usage: python krdl_selenium.py --url <show_url> --target <download_directory>")
        return

    target_dir = Path(expand(args.target))

    # Check if target directory exists or can be created
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 Target directory: {target_dir.absolute()}")
    except Exception as e:
        print(f"❌ ERROR: Cannot create target directory '{target_dir}': {e}")
        return

    # Handle authentication
    username = args.username or os.getenv("KRDL_USERNAME")
    password = args.password or os.getenv("KRDL_PASSWORD")

    if not username or not password:
        print(
            "❌ No credentials provided. Use --username/--password or set KRDL_USERNAME/KRDL_PASSWORD in .env"
        )
        return

    # Initialize downloader
    downloader = KrdlSeleniumDownloader(target_dir, headless=args.headless)

    try:
        # Setup browser
        downloader.setup_driver()

        # Login
        if not downloader.login(username, password):
            print("❌ Login failed. Exiting...")
            return

        # Scrape download links
        download_urls = downloader.scrape_download_links(args.url, args.ext)
        download_urls = filter_by_quality_preference(download_urls, args.quality)

        if not download_urls:
            print("❌ No download links found on the page")
            return

        # CRITICAL: Check for duplicates BEFORE any downloads start
        print("🔍 Checking for existing files to avoid duplicates...")
        existing_files = set()

        # Only treat finished rips as duplicates. Do NOT skip because of *.crdownload: after a
        # failed or interrupted run Chrome often deletes the partial, but if a stale .crdownload
        # remains, treating it as "already have this episode" skips the job forever with no .mkv.
        for file_path in target_dir.glob(f"*.{args.ext}"):
            existing_files.add(file_path.name.lower())

        print(f"🔍 Found {len(existing_files)} existing {args.ext!r} files in target directory")

        # Filter out URLs that would create duplicates BEFORE starting downloads
        # download_urls is (url, filename, expected_bytes | None)
        filtered_items = []
        for url, filename, expected_bytes in download_urls:
            # Filename already has extension from table
            base_name = filename.lower()

            # Check for exact match
            if base_name in existing_files:
                print(f"⏭️  Skipping {filename} - already exists")
                continue

            # Check for potential conflicts (Chrome auto-renaming)
            # Remove extension for prefix matching
            filename_without_ext = filename.rsplit(".", 1)[0].lower()
            potential_conflicts = [f for f in existing_files if f.startswith(filename_without_ext)]
            if potential_conflicts:
                print(f"⏭️  Skipping {filename} - similar file exists: {potential_conflicts[0]}")
                continue

            filtered_items.append((url, filename, expected_bytes))

        print(f"📊 After duplicate check: {len(filtered_items)} downloads to start")

        # Prepare jobs with filtered URLs and filenames
        print(f"📁 Preparing jobs for {args.ext} files...")
        jobs = []
        for url, filename, expected_bytes in filtered_items:
            job = Job(
                url=url,
                name=filename,
                out_path=target_dir / filename,
                status="QUEUED",
                expected_bytes=expected_bytes,
            )
            jobs.append(job)

        # Apply limit to the number of downloads (not the filtered list)
        if args.limit and args.limit > 0 and len(jobs) > args.limit:
            jobs = jobs[: args.limit]
            print(f"⚠️  LIMIT APPLIED: Only downloading first {args.limit} NEW files for testing")

        queued_jobs = [j for j in jobs if j.status == "QUEUED"]
        skipped_jobs = [j for j in jobs if j.status == "SKIP"]

        print(f"📊 Jobs: {len(queued_jobs)} to download, {len(skipped_jobs)} already exist")

        if not queued_jobs:
            print("✅ No new downloads needed.")
            return

        # Download files with PROPER QUEUE - max 2 concurrent
        completed_jobs = downloader.download_queue(
            queued_jobs,
            max_concurrent=2,
            stagger_seconds=args.stagger_seconds,
        )

        # Summary
        successful = [j for j in completed_jobs if j.status == "DONE"]
        failed = [j for j in completed_jobs if j.status == "FAIL"]
        skipped = [j for j in completed_jobs if j.status == "SKIP"]

        print("\n📊 Download Summary:")
        print(f"  ✅ Successful: {len(successful)}")
        print(f"  ❌ Failed: {len(failed)}")
        print(f"  ⏭️  Skipped: {len(skipped)}")

    finally:
        downloader.close()


if __name__ == "__main__":
    main()
