#!/usr/bin/env python3
"""
Selenium-based krdl.moe downloader
Uses browser automation to handle JavaScript and complex authentication
"""

from __future__ import annotations

import argparse
import os
import re
import time
import traceback
import unicodedata
from collections import Counter, deque
from pathlib import Path
from typing import Literal, Optional, Tuple  # noqa: UP035

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from csvdl_core import Job, expand

# Load environment variables from .env file
load_dotenv()

# Finished files at or below this size count as "tiny preview" for a long between-slot cooldown
# (together with canonical ep 00). Mirrors avoiding krdl kicking when a fast preview frees a slot.
_TINY_PREVIEW_MAX_BYTES = 60 * 1024 * 1024


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


def _release_version_counter(filename: str) -> int:
    """
    Numeric suffix from ``..._vN_[crc]`` before the bracket hash (KRDL-style). Base releases
    (no ``_vN_``) return 0 so ``v2`` sorts above unversioned.
    """
    n = _normalize_download_basename(filename)
    m = re.search(r"(?i)_v(\d+)_\[[0-9a-fA-F]{6,12}\]", n)
    if m:
        return int(m.group(1))
    return 0


def _canonical_episode_key(filename: str) -> str:
    """
    Map a table filename to a logical episode / special key so HD vs SD rows dedupe.
    Covers common patterns: ``_-_NN_`` (broadcast), ``_NN_[crc]``, T-N ``_-_NN[`` / ``…NNDC_HD1080[``,
    and ``_NN_HD…[`` Blu-ray MP4 tags (digits + optional DC + ``_HD`` + resolution + ``[``).
    Unknown shapes get a per-filename key (no cross-row dedupe).
    """
    n = _normalize_download_basename(filename)
    if re.search(r"(?i)Grand_Hong_Kong|Teamy_Worky", n):
        return "movie:hong_kong"
    if (
        re.search(r"(?i)(The_)?Movie.*_HD_", n)
        or re.search(r"(?i)_Movie_\s*\[", n)
        or re.search(r"(?i)_The_Movie_", n)
        or re.search(r"(?i)_-_Movie\[", n)
    ):
        return "movie"
    if re.search(r"(?i)Making_Of", n) and re.search(r"(?i)Boukenger", n):
        return "special:gekiranger_vs_boukenger_making_of"
    if re.search(r"(?i)GekiRanger.*Vs.*Boukenger", n) or re.search(
        r"(?i)Gekiranger_VS_Boukenger", n
    ):
        return "special:gekiranger_vs_boukenger"
    m = re.search(r"(?i)_Ep0*(\d+)_", n)
    if m:
        return f"ep:{int(m.group(1)):03d}"
    m = re.search(r"(?i)_-_(\d{2,3})_", n)
    if m:
        return f"ep:{int(m.group(1)):03d}"
    # T-N-style: "..._-_01[CRC].avi" / "..._-_01DVD[CRC].avi" (tag before "["); GS uses "..._01_[CRC].mkv"
    m = re.search(r"(?i)_-_(\d{1,3})[A-Za-z0-9_]*\[", n)
    if m:
        return f"ep:{int(m.group(1)):03d}"
    # T-N / Blu-ray MP4: "..._03_HD1080[CRC]Blu.mp4", "..._05_HD1080Blu[CRC].mp4",
    # "..._01DC_HD1080[CRC]BluV2.mp4", "..._01_HD[CRC]…" (_HD + digits + optional letters, then '[')
    m = re.search(r"(?i)_(\d{1,3})(?:DC|DVD)?_HD\d*[A-Za-z]*\[", n)
    if m:
        return f"ep:{int(m.group(1)):03d}"
    m = re.search(r"(?i)_(\d{1,3})_(?:v\d+_)?\[[0-9a-fA-F]{6,12}\]", n)
    if m:
        return f"ep:{int(m.group(1)):03d}"
    return f"unique:{n}"


_EXT_FALLBACK_ORDER: dict[str, tuple[str, ...]] = {
    "mkv": ("mkv", "mp4", "avi"),
    "mp4": ("mp4", "mkv", "avi"),
    "avi": ("avi", "mkv", "mp4"),
}

ALL_CONTAINER_EXTENSIONS: tuple[str, ...] = ("mkv", "mp4", "avi")

_MEDIA_HREF_CONTAINER = re.compile(r"/(mkv|mp4|avi)(?:\?|#|$)", re.I)


def _container_ext_try_order(prefer: str, *, strict: bool) -> tuple[str, ...]:
    p = prefer.lower().lstrip(".")
    order = _EXT_FALLBACK_ORDER.get(p, ("mkv", "mp4", "avi"))
    return (p,) if strict else order


def _canonical_key_sort_key(k: str) -> tuple[int, str]:
    """Sort movie after numbered episodes; unique:* last."""
    if k == "movie" or k.startswith("movie:"):
        return (1, k)
    if k.startswith("ep:"):
        try:
            n = int(k.split(":", 1)[1])
        except ValueError:
            n = 99999
        return (0, f"{n:05d}")
    return (2, k)


def _krdl_show_base_url(show_url: str) -> str:
    """Strip /mkv|/mp4|/avi so we open the combined episode table (one page load)."""
    base = show_url.strip().rstrip("/")
    for seg in ("/mkv", "/mp4", "/avi"):
        if base.lower().endswith(seg):
            return base[: -len(seg)]
    return base


def _container_from_download_href(href: str) -> str | None:
    m = _MEDIA_HREF_CONTAINER.search(href or "")
    return m.group(1).lower() if m else None


def _krdl_show_url_for_file_extension(show_url: str, extension: str) -> str:
    """Legacy: format-specific tab URL (tests / one-off use)."""
    ext = extension.lower().lstrip(".")
    return f"{_krdl_show_base_url(show_url)}/{ext}"


# Module-level alias: typing.Tuple required for Python 3.9 (tuple[…] and X|Y evaluated at import time).
ScrapeRow = Tuple[str, str, Optional[int]]  # noqa: UP006


def _quality_rows_hd_sort_key(r: tuple[str, str, int | None, bool]) -> tuple[int, int | float, int]:
    url, fn, size_b, is_h = r
    v = _release_version_counter(fn)
    s = size_b if size_b is not None else -1
    return (v, s, 1 if is_h else 0)


def _quality_rows_sd_sort_key(r: tuple[str, str, int | None, bool]) -> tuple[int, float, int]:
    url, fn, size_b, is_h = r
    v = _release_version_counter(fn)
    s = size_b if size_b is not None else float("inf")
    return (-v, s, 1 if is_h else 0)


def filter_by_quality_preference(
    download_items: list[ScrapeRow],
    prefer: Literal["hd", "sd"],
) -> tuple[list[ScrapeRow], dict[str, list[ScrapeRow]]]:
    """
    For each canonical episode key, keep one table row. Prefer the **highest ``_vN_``** release
    (``v2`` over base) when present; then KRDL size (larger for ``hd``, smaller for ``sd``);
    ``_HD_`` in the filename breaks remaining ties. Unknown sizes sort last for ``hd`` and for
    ``sd``.

    Returns primary picks plus ``ranked_by_key``: for each canonical key, all rows for that key
    sorted best-first (same order as the winner). Used to queue alternate releases when the
    preferred file never lands on disk (failed download, bad mirror, etc.).
    """
    if not download_items:
        return [], {}
    key_order: list[str] = []
    groups: dict[str, list[tuple[str, str, int | None, bool]]] = {}
    for url, fn, size_b in download_items:
        key = _canonical_episode_key(fn)
        if key not in groups:
            key_order.append(key)
            groups[key] = []
        groups[key].append((url, fn, size_b, _is_hd_filename(fn)))

    result: list[ScrapeRow] = []
    ranked_by_key: dict[str, list[ScrapeRow]] = {}
    dropped = 0
    for key in key_order:
        g = groups[key]
        if prefer == "hd":
            g_sorted = sorted(g, key=_quality_rows_hd_sort_key, reverse=True)
        else:
            g_sorted = sorted(g, key=_quality_rows_sd_sort_key)
        ranked_by_key[key] = [(t[0], t[1], t[2]) for t in g_sorted]
        chosen = g_sorted[0]
        result.append((chosen[0], chosen[1], chosen[2]))
        dropped += len(g) - 1

    if dropped:
        print(
            f"🎯 Quality preference {prefer!r} (version _vN_, then size, then _HD_ tiebreak): "
            f"dropped {dropped} "
            f"duplicate episode row(s) ({len(download_items)} → {len(result)} files)"
        )
    else:
        print(
            f"🎯 Quality preference {prefer!r}: no duplicate keys in scrape ({len(result)} files)"
        )
    return result, ranked_by_key


def _unified_group_sort_key(
    item: tuple[ScrapeRow, str],
    quality: Literal["hd", "sd"],
    container_order: tuple[str, ...],
) -> tuple:
    (_url, fn, sz), cont = item
    tier = container_order.index(cont) if cont in container_order else 99
    is_h = _is_hd_filename(fn)
    if quality == "hd":
        v = _release_version_counter(fn)
        s = sz if sz is not None else -1
        return (tier, -v, -s, -is_h)
    v = _release_version_counter(fn)
    s = sz if sz is not None else float("inf")
    return (tier, -v, s, is_h)


def pick_episodes_from_unified_scrape(
    rows: list[ScrapeRow],
    quality: Literal["hd", "sd"],
    container_order: tuple[str, ...],
    *,
    strict_container: bool,
) -> tuple[list[ScrapeRow], dict[str, list[ScrapeRow]], dict[str, str]]:
    """
    One queue row per canonical episode key: sort all table rows for that key by container
    preference (mkv→mp4→avi, etc.), then version / size / HD per ``quality``.
    ``ranked_by_key`` lists every row for gap-fill (best first).
    """
    enriched: list[tuple[ScrapeRow, str]] = []
    for url, fn, sz in rows:
        cont = _container_from_download_href(url)
        if cont is None:
            continue
        if strict_container and cont != container_order[0]:
            continue
        enriched.append(((url, fn, sz), cont))

    groups: dict[str, list[tuple[ScrapeRow, str]]] = {}
    key_order: list[str] = []
    for row, cont in enriched:
        key = _canonical_episode_key(row[1])
        if key not in groups:
            key_order.append(key)
            groups[key] = []
        groups[key].append((row, cont))

    ranked_by_key: dict[str, list[ScrapeRow]] = {}
    picks: list[ScrapeRow] = []
    chosen_fmt_by_key: dict[str, str] = {}
    duplicates = 0

    for key in key_order:
        g = groups[key]
        g_sorted = sorted(
            g,
            key=lambda it: _unified_group_sort_key(it, quality, container_order),
        )
        duplicates += len(g_sorted) - 1
        flat = [t[0] for t in g_sorted]
        ranked_by_key[key] = flat
        best_row, best_cont = g_sorted[0]
        picks.append(best_row)
        chosen_fmt_by_key[key] = best_cont

    if duplicates:
        print(
            f"🎯 Unified episode picks ({quality!r}, container priority {container_order}): "
            f"{duplicates} extra table row(s) not queued (same-key alternates / other formats)."
        )
    else:
        print(f"🎯 Unified episode picks ({quality!r}): one row per key from combined table.")

    return picks, ranked_by_key, chosen_fmt_by_key


def discover_canonical_keys_on_disk(target_dir: Path, ext: str) -> set[str]:
    """Set of logical episode/movie keys covered by finished media files in target."""
    keys: set[str] = set()
    for fp in target_dir.glob(f"*.{ext}"):
        keys.add(_canonical_episode_key(fp.name))
    return keys


def _existing_media_basenames(target_dir: Path, ext: str) -> set[str]:
    return {p.name.lower() for p in target_dir.glob(f"*.{ext}")}


def _existing_media_basenames_for_extensions(
    target_dir: Path, extensions: tuple[str, ...]
) -> set[str]:
    names: set[str] = set()
    for e in extensions:
        names |= _existing_media_basenames(target_dir, e)
    return names


def discover_canonical_keys_on_disk_multi(
    target_dir: Path, extensions: tuple[str, ...]
) -> set[str]:
    keys: set[str] = set()
    for e in extensions:
        keys |= discover_canonical_keys_on_disk(target_dir, e)
    return keys


def _filename_blocked_by_existing(filename: str, existing_lower: set[str]) -> bool:
    base_name = filename.lower()
    if base_name in existing_lower:
        return True
    stem = filename.rsplit(".", 1)[0].lower()
    return any(f.startswith(stem) for f in existing_lower)


def filter_scrape_rows_not_on_disk(
    items: list[ScrapeRow],
    target_dir: Path,
    existing_extensions: tuple[str, ...],
    *,
    log_skips: bool = True,
    skip_if_canonical_key_on_disk: bool = True,
) -> list[ScrapeRow]:
    """
    Drop rows whose output basename (or Chrome conflict prefix) already exists on disk, and — when
    ``skip_if_canonical_key_on_disk`` — any row whose logical episode/special key is already
    satisfied by *any* file in ``existing_extensions`` (e.g. skip AVI ep 08 if ep:008 has an MKV).
    """
    existing = _existing_media_basenames_for_extensions(target_dir, existing_extensions)
    # Same episode in .mkv must block a later .avi even when --strict-ext only scrapes one tab.
    keys_on_disk = (
        discover_canonical_keys_on_disk_multi(target_dir, ALL_CONTAINER_EXTENSIONS)
        if skip_if_canonical_key_on_disk
        else set()
    )
    out: list[ScrapeRow] = []
    for url, filename, expected_bytes in items:
        ck = _canonical_episode_key(filename)
        if skip_if_canonical_key_on_disk and not ck.startswith("unique:"):
            if ck in keys_on_disk:
                if log_skips:
                    print(
                        f"⏭️  Skipping {filename} — canonical key {ck!r} already on disk "
                        f"(any of {', '.join(ALL_CONTAINER_EXTENSIONS)})"
                    )
                continue
        base_name = filename.lower()
        if base_name in existing:
            if log_skips:
                print(f"⏭️  Skipping {filename} - already exists")
            continue
        stem = filename.rsplit(".", 1)[0].lower()
        conflicts = [f for f in existing if f.startswith(stem)]
        if conflicts:
            if log_skips:
                print(f"⏭️  Skipping {filename} - similar file exists: {conflicts[0]}")
            continue
        out.append((url, filename, expected_bytes))
    return out


def build_gap_fill_rows(
    ranked_by_key: dict[str, list[ScrapeRow]],
    target_dir: Path,
    existing_extensions: tuple[str, ...],
) -> list[ScrapeRow]:
    """Next-best unified row per missing key (same list order as main pick, skip index 0)."""
    on_disk = discover_canonical_keys_on_disk_multi(target_dir, ALL_CONTAINER_EXTENSIONS)
    fillable = {k for k in ranked_by_key if not k.startswith("unique:")}
    missing = fillable - on_disk
    if not missing:
        return []

    existing_lower = _existing_media_basenames_for_extensions(
        target_dir, ALL_CONTAINER_EXTENSIONS
    )
    out: list[ScrapeRow] = []
    for key in sorted(missing, key=_canonical_key_sort_key):
        alts = ranked_by_key.get(key, [])
        for candidate in alts[1:]:
            _url, filename, _exp = candidate
            if not _filename_blocked_by_existing(filename, existing_lower):
                out.append(candidate)
                existing_lower.add(filename.lower())
                break
    return out


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
        chrome_options.add_argument("--disable-gpu")
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
        """Clear cookies and site storage on krdl.moe (never touch storage on about:blank / data:)."""
        try:
            print("🧹 Clearing all browser data for fresh session...")
            # Must be on a real https origin before localStorage/sessionStorage — Chrome on a
            # blank or data: document throws and some driver builds tear down the session.
            self.driver.get("https://krdl.moe/")
            time.sleep(0.8)
            self.driver.delete_all_cookies()
            self.driver.execute_script(
                "try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}"
            )
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

    def _scrape_show_tab(
        self,
        page_url: str,
        *,
        container_filter: str | None,
    ) -> list[ScrapeRow]:
        """
        Load one show URL, expand the DataTable to ``All``, return rows.
        If ``container_filter`` is set, keep only rows whose download URL ends with that
        container (matches KRDL per-format tabs).
        """
        try:
            print(f"🌐 Navigating to: {page_url!r}")
            self.driver.get(page_url)
            time.sleep(2)

            def _table_or_empty_listing(driver) -> bool:
                if driver.find_elements(By.TAG_NAME, "table"):
                    return True
                src = (driver.page_source or "").lower()
                return "no files" in src or "nothing here" in src

            wait = WebDriverWait(self.driver, 25)
            try:
                wait.until(_table_or_empty_listing)
            except TimeoutException:
                print(
                    "⚠️ Timed out waiting for an episode table (or empty-listing message). "
                    f"URL: {self.driver.current_url!r} title: {self.driver.title!r}"
                )
                return []

            tables = self.driver.find_elements(By.TAG_NAME, "table")
            if not tables:
                print(f"⚠️ No <table> on this page. URL: {self.driver.current_url!r}")
                return []

            print(f"🔍 Current URL: {self.driver.current_url}")

            try:
                error_elements = self.driver.find_elements(
                    By.CSS_SELECTOR, ".alert, .error, .warning, .message"
                )
                if error_elements:
                    for elem in error_elements:
                        print(f"🔍 Error message on show page: {elem.text}")
            except Exception:
                pass

            try:
                show_entries_select = self.driver.find_element(
                    By.CSS_SELECTOR, "select[name*='length'], select[name*='entries']"
                )
                print("🔍 Found pagination dropdown")
                show_entries_select.click()
                time.sleep(0.5)
                all_option = show_entries_select.find_element(By.XPATH, ".//option[text()='All']")
                all_option.click()
                print("✅ Selected 'All' entries - waiting for table to update...")
                time.sleep(2)
            except Exception as e:
                print(f"⚠️  Could not find pagination dropdown (may already show all): {e}")

            download_links: list[ScrapeRow] = []
            for attempt in range(3):
                download_links.clear()
                try:
                    tables = self.driver.find_elements(By.TAG_NAME, "table")
                    print(f"🔍 Found {len(tables)} tables")

                    for i, table in enumerate(tables):
                        rows = table.find_elements(By.TAG_NAME, "tr")
                        print(f"🔍 Table {i}: {len(rows)} rows")

                        for row in rows:
                            cells = row.find_elements(By.TAG_NAME, "td")
                            if len(cells) >= 4:
                                filename = cells[0].text.strip()
                                size_cell = cells[1].text.strip() if len(cells) >= 2 else ""
                                size_b = _parse_krdl_size_bytes(size_cell)
                                link_cell = cells[-1]
                                try:
                                    download_link = link_cell.find_element(By.CSS_SELECTOR, "a")
                                    href = download_link.get_attribute("href") or ""
                                    if "/download/" not in href:
                                        continue
                                    cont = _container_from_download_href(href)
                                    if cont is None:
                                        continue
                                    if container_filter is not None and cont != container_filter:
                                        continue
                                    download_links.append((href, filename, size_b))
                                    sz_dbg = f"{size_b:,} B" if size_b is not None else "size?"
                                    print(f"🔍 Found: {filename} ({sz_dbg})")
                                except Exception:
                                    pass
                    break
                except StaleElementReferenceException:
                    if attempt < 2:
                        print(
                            f"⚠️  Table re-rendered while scraping (attempt {attempt + 1}/3), retrying..."
                        )
                        time.sleep(1.0)
                    else:
                        raise

            by_ct = Counter(
                _container_from_download_href(u) or "?" for u, _fn, _s in download_links
            )
            print(f"✅ Parsed {len(download_links)} row(s) from this tab: {dict(by_ct)}")
            return download_links

        except Exception as e:
            print(f"❌ Scraping error: {type(e).__name__}: {e}")
            return []

    def scrape_format_tab(self, show_url: str, extension: str) -> list[ScrapeRow]:
        """One KRDL format tab (…/mkv, …/mp4, or …/avi)."""
        ext = extension.lower()
        tab_url = _krdl_show_url_for_file_extension(show_url, ext)
        return self._scrape_show_tab(tab_url, container_filter=ext)

    def scrape_all_format_tabs(self, show_url: str) -> list[ScrapeRow]:
        """
        Three navigations (mkv, mp4, avi tabs) so every listing KRDL splits across tabs is
        captured; rows are merged (deduped by URL + filename) for :func:`pick_episodes_from_unified_scrape`.
        """
        print(
            "🌐 Full map: scraping .mkv, .mp4, and .avi tabs (3 page loads) before building the queue."
        )
        combined: list[ScrapeRow] = []
        seen: set[tuple[str, str]] = set()
        for fmt in ALL_CONTAINER_EXTENSIONS:
            tab_url = _krdl_show_url_for_file_extension(show_url, fmt)
            print(f"🔍 Format tab .{fmt}: {tab_url!r}")
            rows = self._scrape_show_tab(tab_url, container_filter=fmt)
            for r in rows:
                key = (r[0], r[1].lower())
                if key in seen:
                    continue
                seen.add(key)
                combined.append(r)
            print(f"   → {len(rows)} row(s); cumulative unique {len(combined)}")
        by_ct = Counter(_container_from_download_href(u) or "?" for u, _fn, _s in combined)
        print(
            f"✅ Combined unique rows after all tabs: {len(combined)} total {dict(by_ct)} "
            "→ unified episode queue next."
        )
        return combined

    def scrape_show_all_download_rows(self, show_url: str) -> list[ScrapeRow]:
        """
        One navigation to the bare show URL: all containers that appear on the combined page.
        Prefer :meth:`scrape_all_format_tabs` when KRDL splits formats across tabs.
        """
        base = _krdl_show_base_url(show_url)
        print("🌐 Single-page scrape (show base URL; any mkv/mp4/avi rows in one table)")
        return self._scrape_show_tab(base, container_filter=None)

    def scrape_download_links(self, show_url: str, extension: str = "mkv") -> list[ScrapeRow]:
        """Compatibility: one format tab only."""
        return self.scrape_format_tab(show_url, extension)

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

    def _is_tiny_preview_complete(self, filename: str) -> bool:
        """Ep 00 / very small finished file: long cooldown before reusing the slot."""
        fn = str(filename or "")
        if not fn:
            return False
        if _canonical_episode_key(fn) == "ep:000":
            return True
        saved = self._saved_file_path(fn)
        if saved is None:
            return False
        try:
            return saved.stat().st_size <= _TINY_PREVIEW_MAX_BYTES
        except OSError:
            return False

    def _had_byte_progress(self, download_info: dict) -> bool:
        """True if we ever saw the partial grow (named or claimed) — Chrome may then drop files."""
        if "last_size" in download_info or "stall_size" in download_info:
            return True
        for k, v in download_info.items():
            if k.startswith("claim_last:"):
                return True
            if k.startswith("claim:") and not k.endswith("_since"):
                if isinstance(v, int) and v > 0:
                    return True
        return False

    def _poll_running_slots(
        self,
        running_downloads: list,
        completed_jobs: list,
        work_q: deque,
        *,
        vanished_partial_grace_sec: float,
        vanished_after_progress_grace_sec: float,
        idle_no_claim_grace_sec: float,
        slot_wait_context: bool,
        slot_wait_loops: int,
        drain_loops: int,
    ) -> tuple[bool, bool, int, int]:
        """
        Finish or abandon active downloads. Appends DONE/FAIL to ``completed_jobs`` or re-queues
        jobs that still have ``krdl_retries_left``. Returns
        ``(slot_freed_by_tiny_preview, had_activity, slot_wait_loops, drain_loops)``.
        """
        finished_downloads: list = []
        abandoned: list = []
        for download in running_downloads:
            if self._should_abandon_stalled_download(
                download,
                vanished_partial_grace_sec=vanished_partial_grace_sec,
                vanished_after_progress_grace_sec=vanished_after_progress_grace_sec,
                idle_no_claim_grace_sec=idle_no_claim_grace_sec,
            ):
                abandoned.append(download)
            elif self._is_download_finished(download):
                finished_downloads.append(download)

        slot_freed_by_tiny_preview = False
        for download in abandoned:
            running_downloads.remove(download)
            job = download["job"]
            if job.krdl_retries_left > 0:
                job.krdl_retries_left -= 1
                job.status = "QUEUED"
                work_q.append(job)
                print(
                    f"🔄 Transient drop for {job.name!r} — re-queued "
                    f"({job.krdl_retries_left} extra attempt(s) left)"
                )
            else:
                if job.status != "FAIL":
                    job.status = "FAIL"
                completed_jobs.append(job)
                print(f"❌ Dropped stalled job: {download['filename']!r}")

        for download in finished_downloads:
            running_downloads.remove(download)
            job = download["job"]
            job.status = "DONE"
            completed_jobs.append(job)
            fn_done = download["filename"]
            print(f"✅ Download finished: {fn_done}")
            if self._is_tiny_preview_complete(fn_done):
                slot_freed_by_tiny_preview = True

        had_activity = bool(finished_downloads or abandoned)
        if not had_activity:
            if slot_wait_context:
                slot_wait_loops += 1
                if slot_wait_loops % 24 == 0:
                    self._log_stuck_poll(running_downloads, slot_wait_loops)
            else:
                drain_loops += 1
                if drain_loops % 24 == 0:
                    self._log_stuck_poll(running_downloads, drain_loops)
        else:
            slot_wait_loops = 0
            drain_loops = 0
        return slot_freed_by_tiny_preview, had_activity, slot_wait_loops, drain_loops

    def download_queue(
        self,
        jobs: list,
        max_concurrent: int = 2,
        stagger_seconds: float = 15.0,
        tiny_preview_cooldown_seconds: float = 600.0,
        *,
        max_transient_retries: int = 3,
        vanished_partial_grace_sec: float = 300.0,
        vanished_after_progress_grace_sec: float = 75.0,
        idle_no_claim_grace_sec: float = 300.0,
    ) -> list:
        """Download files with PROPER QUEUE MANAGEMENT - only start new downloads when others finish"""
        print(f"🚀 Starting download queue with max {max_concurrent} concurrent downloads...")
        print("⚠️  Note: Downloads can take 5+ minutes each. Be patient!")
        print(f"⚠️  CRITICAL: Only {max_concurrent} downloads will run at once!")
        if max_transient_retries > 0:
            print(
                f"🔄 Up to {max_transient_retries} automatic re-queue(s) per job after vanished "
                "partials / stalled handoffs (ethernet↔WiFi, browser hiccups)."
            )
        if tiny_preview_cooldown_seconds > 0:
            print(
                f"⏸️  Tiny preview / ep 00 slot cooldown: {tiny_preview_cooldown_seconds:g}s after "
                "such a file finishes and frees a slot (use --tiny-preview-cooldown-seconds 0 to "
                "disable)."
            )
        if stagger_seconds > 0:
            print(
                f"⏸️  Between-slot stagger: {stagger_seconds:g}s pause before each new download "
                "after the first batch (helps avoid krdl session / rate kicks)."
            )

        completed_jobs: list = []
        work_q: deque = deque()
        for job in jobs:
            if job.status == "SKIP":
                completed_jobs.append(job)
            else:
                work_q.append(job)

        running_downloads: list = []
        slot_wait_loops = 0
        drain_loops = 0
        jobs_started = 0

        while work_q or running_downloads:
            waited_for_slot = False
            slot_freed_by_tiny_preview = False
            while len(running_downloads) >= max_concurrent:
                waited_for_slot = True
                print(
                    f"⏳ {len(running_downloads)} downloads running, waiting for one to finish..."
                )
                time.sleep(5)
                tiny_prev, _, slot_wait_loops, drain_loops = self._poll_running_slots(
                    running_downloads,
                    completed_jobs,
                    work_q,
                    vanished_partial_grace_sec=vanished_partial_grace_sec,
                    vanished_after_progress_grace_sec=vanished_after_progress_grace_sec,
                    idle_no_claim_grace_sec=idle_no_claim_grace_sec,
                    slot_wait_context=True,
                    slot_wait_loops=slot_wait_loops,
                    drain_loops=drain_loops,
                )
                slot_freed_by_tiny_preview = slot_freed_by_tiny_preview or tiny_prev

            if waited_for_slot:
                if tiny_preview_cooldown_seconds > 0 and slot_freed_by_tiny_preview:
                    print(
                        f"⏸️  Tiny preview / ep 00 finished — pausing {tiny_preview_cooldown_seconds:g}s "
                        "before next download..."
                    )
                    time.sleep(tiny_preview_cooldown_seconds)
                elif stagger_seconds > 0:
                    print(
                        f"⏸️  Pausing {stagger_seconds:g}s before starting next download "
                        "(server cooldown)..."
                    )
                    time.sleep(stagger_seconds)

            if len(running_downloads) < max_concurrent and work_q:
                job = work_q.popleft()
                jobs_started += 1
                print(f"📥 Queueing download {jobs_started}: {job.name}")

                print(f"🚀 Starting download: {job.name}")
                print(f"🔍 Download URL: {job.url}")
                print("🔍 Keeping login session active (not clearing data)")
                print("🔍 Navigating to download URL...")
                out_expected = self.target_dir / job.name
                stale_partial = self.target_dir / f"{job.name}.crdownload"
                if stale_partial.is_file() and not out_expected.is_file():
                    try:
                        stale_partial.unlink()
                        print(
                            f"🧹 Removed stale partial so Chrome can retry: {stale_partial.name}"
                        )
                    except OSError as e:
                        print(f"⚠️  Could not remove stale partial {stale_partial.name}: {e}")
                cr_before = frozenset(self._crdownload_basenames())
                self.driver.get(job.url)
                time.sleep(3)

                current_url = self.driver.current_url
                print(f"🔍 Current URL after navigation: {current_url}")
                print(f"🔍 Page title: {self.driver.title}")

                try:
                    error_elements = self.driver.find_elements(
                        By.CSS_SELECTOR, ".alert, .error, .warning, .message"
                    )
                    if error_elements:
                        for elem in error_elements:
                            print(f"🔍 Error message on page: {elem.text}")
                except Exception:
                    pass

                current_url = self.driver.current_url
                if "register" in current_url.lower() or "premium" in current_url.lower():
                    print("🚨 RATE LIMIT REDIRECT DETECTED!")
                    print(f"🚨 Current URL: {current_url}")
                    print("🚨 This means your account has been rate-limited")
                    print("🚨 STOPPING ALL DOWNLOADS TO AVOID FURTHER PUNISHMENT")
                    print("🚨 Please wait 15 minutes before trying again")
                    for d in running_downloads:
                        d["job"].status = "FAIL"
                        completed_jobs.append(d["job"])
                    running_downloads.clear()
                    while work_q:
                        rj = work_q.popleft()
                        rj.status = "FAIL"
                        completed_jobs.append(rj)
                    return completed_jobs

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
                        "(no gen.krdl redirect, no new .crdownload, no file)."
                    )
                    if job.krdl_retries_left > 0:
                        job.krdl_retries_left -= 1
                        job.status = "QUEUED"
                        work_q.append(job)
                        print(
                            f"🔄 Re-queueing ({job.krdl_retries_left} extra attempt(s) left) "
                            "— check network / rate limits."
                        )
                    else:
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
                    print(
                        f"🔖 Tracking Chrome partial(s) for this job: "
                        f"{', '.join(sorted(claimed_new))}"
                    )

                running_downloads.append(download_info)
                print(f"📊 Active downloads: {len(running_downloads)}/{max_concurrent}")
            elif running_downloads:
                print(
                    f"⏳ Waiting for {len(running_downloads)} remaining download(s) to finish..."
                )
                time.sleep(5)
                _, _, slot_wait_loops, drain_loops = self._poll_running_slots(
                    running_downloads,
                    completed_jobs,
                    work_q,
                    vanished_partial_grace_sec=vanished_partial_grace_sec,
                    vanished_after_progress_grace_sec=vanished_after_progress_grace_sec,
                    idle_no_claim_grace_sec=idle_no_claim_grace_sec,
                    slot_wait_context=False,
                    slot_wait_loops=slot_wait_loops,
                    drain_loops=drain_loops,
                )
            else:
                break

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

    def _should_abandon_stalled_download(
        self,
        download_info: dict,
        *,
        vanished_partial_grace_sec: float = 300.0,
        vanished_after_progress_grace_sec: float = 75.0,
        idle_no_claim_grace_sec: float = 300.0,
    ) -> bool:
        """
        Drop jobs that will never satisfy _is_download_finished: frozen named partial,
        or no file / no named partial for so long that Chrome almost certainly never attached.

        ``vanished_partial_grace_sec``: if we never saw byte progress, wait this long after claimed
        partials vanish before abandoning (slow / flaky first bytes).

        ``vanished_after_progress_grace_sec``: if we *did* see progress then Chrome removed all
        ``.crdownload`` files, abandon after this shorter window so slots do not sit stuck for minutes.
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
            eff_vanish = float(vanished_partial_grace_sec)
            if self._had_byte_progress(download_info):
                eff_vanish = min(eff_vanish, float(vanished_after_progress_grace_sec))
            if van is None:
                download_info["claim_vanished_since"] = now
            elif now - van >= eff_vanish:
                print(
                    f"❌ Giving up on {fn!r}: claimed .crdownload(s) vanished with no "
                    f"finished file ({list(claimed)!r}) — Chrome may have cancelled the transfer "
                    f"(grace {eff_vanish:.0f}s)"
                )
                if job is not None:
                    job.status = "FAIL"
                return True
        else:
            download_info.pop("claim_vanished_since", None)

        if not claimed and self._had_byte_progress(download_info):
            o = download_info.get("byte_progress_orphan_since")
            if o is None:
                download_info["byte_progress_orphan_since"] = now
            elif now - o >= float(vanished_after_progress_grace_sec):
                print(
                    f"❌ Giving up on {fn!r}: partial(s) gone after receiving data, "
                    f"no finished file (grace {vanished_after_progress_grace_sec:.0f}s)"
                )
                if job is not None:
                    job.status = "FAIL"
                return True
        else:
            download_info.pop("byte_progress_orphan_since", None)

        if not claimed and elapsed >= float(idle_no_claim_grace_sec):
            print(
                f"❌ Giving up on {fn!r}: no finished file, no named partial, no claimed .crdownload "
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
        if not self.driver:
            return
        try:
            self.driver.quit()
        except Exception as e:
            print(f"⚠️  Browser already closed or quit failed: {e}")
        finally:
            self.driver = None


def main():
    ap = argparse.ArgumentParser(description="krdl-dl — Selenium-based Site Scraper & Downloader")
    ap.add_argument("--url", required=True, help="URL of the krdl.moe page to scrape")
    ap.add_argument("--target", required=True, help="Directory to save downloads (REQUIRED)")
    ap.add_argument(
        "--ext",
        choices=["mkv", "mp4", "avi"],
        default="mkv",
        help=(
            "Preferred container (default: mkv). Default run scans .mkv, .mp4, and .avi tabs "
            "(3 loads), merges rows, then picks one row per episode (preference MKV→MP4→AVI, etc.) "
            "and your --quality rules. See --strict-ext."
        ),
    )
    ap.add_argument(
        "--strict-ext",
        action="store_true",
        help="Only open the --ext tab (1 load); no mkv/mp4/avi merge or cross-format fallback.",
    )
    ap.add_argument(
        "--quality",
        choices=["hd", "sd"],
        default="hd",
        help=(
            "Per episode (canonical numbering), pick one table row: prefer highest _vN_ (e.g. v2 over "
            "base), then for hd = larger KRDL size (tie: _HD_ in name); sd = smaller size (tie: "
            "avoid _HD_)."
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
    ap.add_argument(
        "--tiny-preview-cooldown-seconds",
        type=float,
        default=600.0,
        metavar="SEC",
        help=(
            "After ep 00 or a very small finished file (≤60 MiB) frees a download slot, wait this "
            "long before starting the next job (default: 600). Use 0 to disable. Other slot frees "
            "still use only --stagger-seconds."
        ),
    )
    ap.add_argument(
        "--gap-fill-second-pass",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "After the main queue, find episode/movie keys still missing on disk and queue the "
            "next-best alternate release per key (different encode/group). Disable with "
            "--no-gap-fill-second-pass."
        ),
    )
    ap.add_argument(
        "--max-download-retries",
        type=int,
        default=3,
        metavar="N",
        help=(
            "After a transient failure (vanished .crdownload, never-started handoff), re-queue the "
            "same job up to N times before giving up (default: 3)."
        ),
    )
    ap.add_argument(
        "--vanished-partial-grace-seconds",
        type=float,
        default=300.0,
        metavar="SEC",
        help=(
            "If claimed .crdownload names vanish before any byte progress was seen, wait this long "
            "before abandoning (default: 300). After progress, "
            "--vanished-after-progress-grace-seconds applies instead."
        ),
    )
    ap.add_argument(
        "--vanished-after-progress-grace-seconds",
        type=float,
        default=75.0,
        metavar="SEC",
        help=(
            "If we already saw the partial grow then all .crdownload files disappear, abandon and "
            "re-queue after this many seconds (default: 75). Prevents 2-slot deadlock for minutes."
        ),
    )
    ap.add_argument(
        "--idle-no-claim-grace-seconds",
        type=float,
        default=300.0,
        metavar="SEC",
        help=(
            "With no partial file to track, abandon after this many seconds (default: 300)."
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

        ext_try = _container_ext_try_order(args.ext, strict=args.strict_ext)
        existing_extensions = (ext_try[0],) if args.strict_ext else ALL_CONTAINER_EXTENSIONS

        if args.strict_ext:
            raw_rows = downloader.scrape_format_tab(args.url, ext_try[0])
        else:
            raw_rows = downloader.scrape_all_format_tabs(args.url)
        if not raw_rows:
            print("❌ No usable mkv/mp4/avi download rows after scraping.")
            return

        download_urls, ranked_by_key, chosen_fmt_by_key = pick_episodes_from_unified_scrape(
            raw_rows,
            args.quality,
            ext_try,
            strict_container=args.strict_ext,
        )

        if not download_urls:
            print("❌ No episodes to download after unified episode pick (unexpected).")
            return

        primary = ext_try[0]
        if not args.strict_ext:
            fb = sum(1 for f in chosen_fmt_by_key.values() if f != primary)
            if fb:
                print(
                    f"📦 Per-episode container fallback: {fb} key(s) use a non-preferred format "
                    f"(preference .{primary}). Mix: {dict(Counter(chosen_fmt_by_key.values()))}"
                )

        # CRITICAL: Check for duplicates BEFORE any downloads start
        print("🔍 Checking for existing files to avoid duplicates...")
        n_exist = len(_existing_media_basenames_for_extensions(target_dir, existing_extensions))
        print(
            f"🔍 Found {n_exist} existing on-disk file(s) "
            f"(extensions: {', '.join(existing_extensions)})"
        )

        filtered_items = filter_scrape_rows_not_on_disk(
            download_urls,
            target_dir,
            existing_extensions,
            log_skips=True,
            skip_if_canonical_key_on_disk=True,
        )
        print(f"📊 After duplicate check: {len(filtered_items)} downloads to start")

        def rows_to_jobs(rows: list[ScrapeRow]) -> list[Job]:
            jobs_out: list[Job] = []
            for url, filename, expected_bytes in rows:
                jobs_out.append(
                    Job(
                        url=url,
                        name=filename,
                        out_path=target_dir / filename,
                        status="QUEUED",
                        expected_bytes=expected_bytes,
                        krdl_retries_left=max(0, int(args.max_download_retries)),
                    )
                )
            return jobs_out

        print("📁 Preparing download jobs (mixed .mkv / .mp4 / .avi names are OK)…")
        jobs = rows_to_jobs(filtered_items)

        # Apply limit to the number of downloads (not the filtered list)
        if args.limit and args.limit > 0 and len(jobs) > args.limit:
            jobs = jobs[: args.limit]
            print(f"⚠️  LIMIT APPLIED: Only downloading first {args.limit} NEW files for testing")

        queued_jobs = [j for j in jobs if j.status == "QUEUED"]
        skipped_jobs = [j for j in jobs if j.status == "SKIP"]

        print(f"📊 Jobs: {len(queued_jobs)} to download, {len(skipped_jobs)} already exist")

        if not queued_jobs:
            print("✅ No new downloads needed.")
        else:
            # Download files with PROPER QUEUE - max 2 concurrent
            completed_jobs = downloader.download_queue(
                queued_jobs,
                max_concurrent=2,
                stagger_seconds=args.stagger_seconds,
                tiny_preview_cooldown_seconds=args.tiny_preview_cooldown_seconds,
                max_transient_retries=max(0, int(args.max_download_retries)),
                vanished_partial_grace_sec=float(args.vanished_partial_grace_seconds),
                vanished_after_progress_grace_sec=float(
                    args.vanished_after_progress_grace_seconds
                ),
                idle_no_claim_grace_sec=float(args.idle_no_claim_grace_seconds),
            )

            successful = [j for j in completed_jobs if j.status == "DONE"]
            failed = [j for j in completed_jobs if j.status == "FAIL"]
            skipped = [j for j in completed_jobs if j.status == "SKIP"]

            print("\n📊 Download Summary:")
            print(f"  ✅ Successful: {len(successful)}")
            print(f"  ❌ Failed: {len(failed)}")
            print(f"  ⏭️  Skipped: {len(skipped)}")
            if failed:
                on_disk_keys = discover_canonical_keys_on_disk_multi(
                    target_dir, ALL_CONTAINER_EXTENSIONS
                )
                missing_ep = [
                    j
                    for j in failed
                    if j.name
                    and (not _canonical_episode_key(j.name).startswith("unique:"))
                    and _canonical_episode_key(j.name) not in on_disk_keys
                ]
                if missing_ep:
                    sample = ", ".join(f"{j.name!r}" for j in missing_ep[:8])
                    more = f" (+{len(missing_ep) - 8} more)" if len(missing_ep) > 8 else ""
                    print(
                        f"\n⚠️  {len(missing_ep)} job(s) failed and episode key still missing on disk: "
                        f"{sample}{more}. Re-run after fixing network; tuning: --max-download-retries, "
                        f"--vanished-after-progress-grace-seconds, --vanished-partial-grace-seconds."
                    )

        if args.gap_fill_second_pass:
            gap_candidates = build_gap_fill_rows(
                ranked_by_key,
                target_dir,
                existing_extensions,
            )
            gap_filtered = filter_scrape_rows_not_on_disk(
                gap_candidates,
                target_dir,
                existing_extensions,
                log_skips=True,
                skip_if_canonical_key_on_disk=True,
            )
            if gap_filtered:
                print(
                    f"\n🔁 Gap-fill pass: queueing {len(gap_filtered)} alternate release(s) "
                    "for canonical episode/movie keys still missing on disk."
                )
                gap_jobs = rows_to_jobs(gap_filtered)
                if args.limit and args.limit > 0 and len(gap_jobs) > args.limit:
                    gap_jobs = gap_jobs[: args.limit]
                    print(f"⚠️  LIMIT APPLIED to gap-fill: first {args.limit} job(s) only")
                gap_completed = downloader.download_queue(
                    gap_jobs,
                    max_concurrent=2,
                    stagger_seconds=args.stagger_seconds,
                    tiny_preview_cooldown_seconds=args.tiny_preview_cooldown_seconds,
                    max_transient_retries=max(0, int(args.max_download_retries)),
                    vanished_partial_grace_sec=float(args.vanished_partial_grace_seconds),
                    vanished_after_progress_grace_sec=float(
                        args.vanished_after_progress_grace_seconds
                    ),
                    idle_no_claim_grace_sec=float(args.idle_no_claim_grace_seconds),
                )
                gs = [j for j in gap_completed if j.status == "DONE"]
                gf = [j for j in gap_completed if j.status == "FAIL"]
                gsk = [j for j in gap_completed if j.status == "SKIP"]
                print("\n📊 Gap-fill Summary:")
                print(f"  ✅ Successful: {len(gs)}")
                print(f"  ❌ Failed: {len(gf)}")
                print(f"  ⏭️  Skipped: {len(gsk)}")
            else:
                rem = {
                    k for k in ranked_by_key if not k.startswith("unique:")
                } - discover_canonical_keys_on_disk_multi(target_dir, ALL_CONTAINER_EXTENSIONS)
                if rem:
                    print(
                        "\n⚠️  Gap-fill: some keys still have no file on disk but no alternates "
                        f"remain in the scrape (example keys: {', '.join(sorted(rem)[:5])})."
                    )

    except Exception:
        traceback.print_exc()
        print("❌ Unhandled error — see traceback above.")
    finally:
        downloader.close()


if __name__ == "__main__":
    main()
