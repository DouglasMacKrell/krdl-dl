#!/usr/bin/env python3
"""
Selenium-based krdl.moe downloader
Uses browser automation to handle JavaScript and complex authentication
"""
import os
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from csvdl_core import expand, scrape_krdl_page, prepare_jobs, Job

# Load environment variables from .env file
load_dotenv()

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
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # FRESH SESSION - Clear all data to avoid rate limiting
        # NOTE: Removed --incognito because it prevents Chrome from respecting download preferences
        # We still get a fresh session by clearing all browser data in clear_all_data()
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        chrome_options.add_argument("--disable-renderer-backgrounding")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
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
            "profile.default_content_setting_values.automatic_downloads": 1  # Allow automatic downloads
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        # Setup driver
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Verify download directory is set correctly
        print(f"🔍 Chrome will download directly to target: {self.target_dir.absolute()}")
        
        # Execute script to remove webdriver property
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
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
            for selector in ["input[name='email']", "input[type='email']", "#email", "input[placeholder*='email']"]:
                try:
                    email_field = self.driver.find_element(By.CSS_SELECTOR, selector)
                    print(f"✅ Found email field with selector: {selector}")
                    break
                except:
                    continue
            
            if not email_field:
                print("❌ Could not find email field")
                return False
            
            # Try different selectors for password field
            password_field = None
            for selector in ["input[name='password']", "input[type='password']", "#password", "input[placeholder*='password']"]:
                try:
                    password_field = self.driver.find_element(By.CSS_SELECTOR, selector)
                    print(f"✅ Found password field with selector: {selector}")
                    break
                except:
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
            for selector in ["button[type='submit']", "input[type='submit']", "button", ".btn", "#login-button"]:
                try:
                    submit_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    print(f"✅ Found submit button with selector: {selector}")
                    break
                except:
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
                error_elements = self.driver.find_elements(By.CSS_SELECTOR, ".alert, .error, .warning, .message")
                if error_elements:
                    for elem in error_elements:
                        print(f"🔍 Error message after login: {elem.text}")
            except:
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
    
    def scrape_download_links(self, show_url: str, extension: str = "mkv") -> list:
        """Scrape download links from show page"""
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
                error_elements = self.driver.find_elements(By.CSS_SELECTOR, ".alert, .error, .warning, .message")
                if error_elements:
                    for elem in error_elements:
                        print(f"🔍 Error message on show page: {elem.text}")
            except:
                pass
            
            # CRITICAL: Click "All" in pagination to show all entries
            try:
                # Look for the "Show X entries" dropdown
                show_entries_select = self.driver.find_element(By.CSS_SELECTOR, "select[name*='length'], select[name*='entries']")
                print(f"🔍 Found pagination dropdown")
                
                # Click on it to open options
                show_entries_select.click()
                time.sleep(0.5)
                
                # Find and click "All" option
                all_option = show_entries_select.find_element(By.XPATH, ".//option[text()='All']")
                all_option.click()
                print(f"✅ Selected 'All' entries - waiting for table to update...")
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
                        
                        # Get the download link from last cell
                        link_cell = cells[-1]
                        try:
                            download_link = link_cell.find_element(By.CSS_SELECTOR, "a")
                            href = download_link.get_attribute("href")
                            
                            if href and "/download/" in href and f"/{extension}" in href:
                                # Store as tuple: (url, filename)
                                download_links.append((href, filename))
                                print(f"🔍 Found: {filename}")
                        except:
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
                print(f"🚨 RATE LIMIT REDIRECT DETECTED!")
                print(f"🚨 Current URL: {current_url}")
                print(f"🚨 This means your account has been rate-limited")
                print(f"🚨 STOPPING DOWNLOADS TO AVOID FURTHER PUNISHMENT")
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
                save_dialogs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[name='filename'], input[placeholder*='filename']")
                if save_dialogs:
                    print(f"🔍 Found save dialog, setting filename: {filename}")
                    save_dialogs[0].clear()
                    save_dialogs[0].send_keys(filename)
                    
                    # Look for save button
                    save_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button:contains('Save'), input[value='Save'], button[type='submit']")
                    if save_buttons:
                        save_buttons[0].click()
                        print(f"✅ Save dialog handled for: {filename}")
                        return
                
                # Approach 2: Use keyboard shortcuts
                from selenium.webdriver.common.keys import Keys
                from selenium.webdriver.common.action_chains import ActionChains
                
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
    
    def download_queue(self, jobs: list, max_concurrent: int = 2) -> list:
        """Download files with PROPER QUEUE MANAGEMENT - only start new downloads when others finish"""
        print(f"🚀 Starting download queue with max {max_concurrent} concurrent downloads...")
        print(f"⚠️  Note: Downloads can take 5+ minutes each. Be patient!")
        print(f"⚠️  CRITICAL: Only {max_concurrent} downloads will run at once!")
        
        completed_jobs = []
        running_downloads = []  # Track active downloads
        
        for i, job in enumerate(jobs):
            if job.status == "SKIP":
                completed_jobs.append(job)
                continue
            
            print(f"📥 Queueing download {i+1}/{len(jobs)}: {job.name}")
            
            # WAIT until we have space for a new download
            while len(running_downloads) >= max_concurrent:
                print(f"⏳ {len(running_downloads)} downloads running, waiting for one to finish...")
                time.sleep(5)  # Check every 5 seconds
                
                # Check if any downloads have finished
                finished_downloads = []
                for download in running_downloads:
                    if self._is_download_finished(download):
                        finished_downloads.append(download)
                
                # Remove finished downloads
                for download in finished_downloads:
                    running_downloads.remove(download)
                    print(f"✅ Download finished: {download['filename']}")
            
            # Start new download
            print(f"🚀 Starting download: {job.name}")
            print(f"🔍 Download URL: {job.url}")
            
            # DON'T clear session data - keep the login session active
            print(f"🔍 Keeping login session active (not clearing data)")
            
            # Navigate to download URL to start download
            print(f"🔍 Navigating to download URL...")
            self.driver.get(job.url)
            time.sleep(2)  # Wait for redirect
            
            # Log current state after navigation
            current_url = self.driver.current_url
            print(f"🔍 Current URL after navigation: {current_url}")
            print(f"🔍 Page title: {self.driver.title}")
            
            # Check for any error messages on the page
            try:
                error_elements = self.driver.find_elements(By.CSS_SELECTOR, ".alert, .error, .warning, .message")
                if error_elements:
                    for elem in error_elements:
                        print(f"🔍 Error message on page: {elem.text}")
            except:
                pass
            
            # Check for register/premium redirect - GRACEFUL STOP
            current_url = self.driver.current_url
            if "register" in current_url.lower() or "premium" in current_url.lower():
                print(f"🚨 RATE LIMIT REDIRECT DETECTED!")
                print(f"🚨 Current URL: {current_url}")
                print(f"🚨 This means your account has been rate-limited")
                print(f"🚨 STOPPING ALL DOWNLOADS TO AVOID FURTHER PUNISHMENT")
                print(f"🚨 Please wait 15 minutes before trying again")
                return completed_jobs  # Stop immediately
            
            # Check if we got redirected to gen.krdl.moe (good sign)
            if "gen.krdl.moe" in current_url:
                print(f"✅ Redirected to download server: {current_url}")
            else:
                print(f"🔍 Current URL: {current_url}")
            
            download_info = {
                'job': job,
                'filename': job.name,
                'start_time': time.time(),
                'url': job.url
            }
            
            running_downloads.append(download_info)
            print(f"📊 Active downloads: {len(running_downloads)}/{max_concurrent}")
        
        # Wait for remaining downloads to finish
        print(f"⏳ Waiting for {len(running_downloads)} remaining downloads to finish...")
        while running_downloads:
            time.sleep(5)
            finished_downloads = []
            for download in running_downloads:
                if self._is_download_finished(download):
                    finished_downloads.append(download)
                    print(f"✅ Download completed: {download['filename']}")
            
            # Remove finished downloads
            for download in finished_downloads:
                running_downloads.remove(download)
        
        print(f"🎉 All downloads completed!")
        return completed_jobs
    
    def _is_download_finished(self, download_info: dict) -> bool:
        """Check if a download has finished by monitoring for .crdownload files in target directory"""
        try:
            # Chrome downloads directly to target directory
            expected_file = self.target_dir / download_info['filename']
            temp_file = self.target_dir / f"{download_info['filename']}.crdownload"
            
            # Check if final file exists (download complete)
            if expected_file.exists():
                file_size = expected_file.stat().st_size
                if 'completed' not in download_info:
                    download_info['completed'] = True
                    print(f"✅ Download complete: {download_info['filename']} ({file_size:,} bytes)")
                return True
            
            # Check if .crdownload file exists (download in progress)
            if temp_file.exists():
                current_size = temp_file.stat().st_size
                
                # Track progress
                if 'last_size' not in download_info:
                    download_info['last_size'] = current_size
                    print(f"🔍 Download started: {download_info['filename']}")
                elif current_size != download_info['last_size']:
                    download_info['last_size'] = current_size
                    print(f"🔍 Downloading: {download_info['filename']} ({current_size:,} bytes)")
                
                # Still downloading
                return False
            
            # No .crdownload and no final file yet - waiting for download to start
            if 'waiting' not in download_info:
                download_info['waiting'] = True
                print(f"⏳ Waiting for download to start: {download_info['filename']}")
            
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
    ap.add_argument("--ext", choices=["mkv", "mp4"], default="mkv", help="Which video extension to download (default: mkv)")
    ap.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    ap.add_argument("--username", help="krdl.moe username for authentication")
    ap.add_argument("--password", help="krdl.moe password for authentication")
    ap.add_argument("--limit", type=int, help="Limit the number of files to download (for testing)")
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
    username = args.username or os.getenv('KRDL_USERNAME')
    password = args.password or os.getenv('KRDL_PASSWORD')
    
    if not username or not password:
        print("❌ No credentials provided. Use --username/--password or set KRDL_USERNAME/KRDL_PASSWORD in .env")
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
        
        if not download_urls:
            print("❌ No download links found on the page")
            return
        
        # CRITICAL: Check for duplicates BEFORE any downloads start
        print(f"🔍 Checking for existing files to avoid duplicates...")
        existing_files = set()
        
        # Get all existing .mkv files
        for file_path in target_dir.glob(f"*.{args.ext}"):
            existing_files.add(file_path.name.lower())
        
        # Get all existing .crdownload files (in-progress downloads)
        for file_path in target_dir.glob("*.crdownload"):
            base_name = file_path.name.replace(".crdownload", "")
            existing_files.add(base_name.lower())
        
        print(f"🔍 Found {len(existing_files)} existing files in target directory")
        
        # Filter out URLs that would create duplicates BEFORE starting downloads
        # download_urls is now a list of tuples: (url, filename)
        # NOTE: filename from table already includes extension like .mkv
        filtered_items = []
        for url, filename in download_urls:
            # Filename already has extension from table
            base_name = filename.lower()
            
            # Check for exact match
            if base_name in existing_files:
                print(f"⏭️  Skipping {filename} - already exists")
                continue
                
            # Check for potential conflicts (Chrome auto-renaming)
            # Remove extension for prefix matching
            filename_without_ext = filename.rsplit('.', 1)[0].lower()
            potential_conflicts = [f for f in existing_files if f.startswith(filename_without_ext)]
            if potential_conflicts:
                print(f"⏭️  Skipping {filename} - similar file exists: {potential_conflicts[0]}")
                continue
                
            filtered_items.append((url, filename))
        
        print(f"📊 After duplicate check: {len(filtered_items)} downloads to start")
        
        # Prepare jobs with filtered URLs and filenames
        print(f"📁 Preparing jobs for {args.ext} files...")
        jobs = []
        for url, filename in filtered_items:
            job = Job(url=url, name=filename, out_path=target_dir / filename, status="QUEUED")
            jobs.append(job)
        
        # Apply limit to the number of downloads (not the filtered list)
        if args.limit and args.limit > 0 and len(jobs) > args.limit:
            jobs = jobs[:args.limit]
            print(f"⚠️  LIMIT APPLIED: Only downloading first {args.limit} NEW files for testing")
        
        queued_jobs = [j for j in jobs if j.status == "QUEUED"]
        skipped_jobs = [j for j in jobs if j.status == "SKIP"]
        
        print(f"📊 Jobs: {len(queued_jobs)} to download, {len(skipped_jobs)} already exist")
        
        if not queued_jobs:
            print("✅ No new downloads needed.")
            return
        
        # Download files with PROPER QUEUE - max 2 concurrent
        completed_jobs = downloader.download_queue(queued_jobs, max_concurrent=2)
        
        # Summary
        successful = [j for j in completed_jobs if j.status == "DONE"]
        failed = [j for j in completed_jobs if j.status == "FAIL"]
        skipped = [j for j in completed_jobs if j.status == "SKIP"]
        
        print(f"\n📊 Download Summary:")
        print(f"  ✅ Successful: {len(successful)}")
        print(f"  ❌ Failed: {len(failed)}")
        print(f"  ⏭️  Skipped: {len(skipped)}")
        
    finally:
        downloader.close()

if __name__ == "__main__":
    main()
