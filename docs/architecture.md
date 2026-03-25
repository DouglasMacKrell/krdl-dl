# Architecture & Design Choices

This document explains the technical architecture of krdl-dl and the reasoning behind key design decisions.

## Overview

krdl-dl is a Selenium-based web scraper and downloader specifically designed for krdl.moe, a tokusatsu (Japanese special effects) media archive. The tool automates the process of downloading complete series while respecting the site's rate limits and authentication requirements.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     krdl_selenium.py                         │
│                   (Main Entry Point)                         │
└───────────────────────────┬─────────────────────────────────┘
                            │
                ┌───────────┴───────────┐
                │                       │
                ▼                       ▼
┌───────────────────────┐   ┌──────────────────────┐
│   csvdl_core.py       │   │  Selenium WebDriver  │
│   (Utilities)         │   │  (Browser Automation)│
│                       │   │                      │
│ - Job dataclass       │   │ - Chrome browser     │
│ - login_to_krdl()     │   │ - Page navigation    │
│ - scrape_krdl_page()  │   │ - Element finding    │
│ - expand()            │   │ - Download handling  │
└───────────────────────┘   └──────────────────────┘
                │                       │
                └───────────┬───────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │    krdl.moe Website   │
                │  (Target Site)        │
                └───────────────────────┘
```

## Core Components

### 1. KrdlSeleniumDownloader Class

**Location:** `krdl_selenium.py`

**Responsibilities:**
- Browser setup and configuration
- Session management (login/logout)
- Page scraping (link extraction)
- Download queue management
- Progress monitoring

**Key Methods:**

```python
setup_driver()           # Initialize Chrome with custom preferences
login(username, password) # Authenticate with krdl.moe
scrape_download_links()  # Extract download URLs from show page
download_queue()         # Manage concurrent downloads
_is_download_finished()  # Monitor .crdownload files
```

### 2. Utility Functions

**Location:** `csvdl_core.py`

**Responsibilities:**
- Shared utilities used across the application
- Authentication helpers
- Data structures (Job class)

**Key Functions:**

```python
Job                      # Dataclass for tracking downloads
expand(path)            # Path expansion (~, env vars)
login_to_krdl()         # Session-based login (requests)
scrape_krdl_page()      # Fallback scraper (BeautifulSoup)
```

## Design Decisions

### Why Selenium Instead of Requests?

**Initial Approach:** Used `requests` + `BeautifulSoup` + `curl` for downloads.

**Problems:**
- ❌ Session management was fragile (cookies expired quickly)
- ❌ CSRF token handling was unreliable
- ❌ Difficult to debug authentication issues
- ❌ No visibility into download progress
- ❌ Hard to handle rate limiting gracefully

**Selenium Advantages:**
- ✅ Real browser = authentic authentication
- ✅ Visual debugging (can see what's happening)
- ✅ Automatic cookie management
- ✅ Native download handling (Chrome's download manager)
- ✅ Easy to detect redirects (premium/register pages)
- ✅ Handles JavaScript-rendered content

**Trade-off:** Slightly slower, requires Chrome, but much more reliable.

### Why Direct Download to Target Directory?

**Alternative Considered:** Download to temp directory, then move files.

**Chosen Approach:** Configure Chrome to download directly to target directory.

**Reasoning:**
- ✅ Simpler flow (no file moving logic)
- ✅ Fewer potential points of failure
- ✅ No risk of incomplete moves
- ✅ Chrome handles all file naming automatically
- ✅ Atomic operations (file appears when complete)

### Why Monitor .crdownload Files?

**Challenge:** How do we know when a download is complete?

**Solution:** Monitor Chrome's temporary `.crdownload` files.

**Flow:**
1. Chrome creates `Unconfirmed_[HASH].crdownload`
2. File grows as download progresses
3. Chrome renames to final filename when complete
4. We detect the rename and mark download as done

**Why This Works:**
- ✅ Chrome's native behavior (no hacks)
- ✅ Reliable completion detection
- ✅ Works with any filename
- ✅ No polling file sizes or timeouts

### Why Queue Management Instead of Parallel Downloads?

**krdl.moe Limits:**
- Maximum 2 concurrent downloads
- Exceeding limit = temporary account restriction
- ~5 minutes per file (400kbps speed limit)

**Our Approach:**
```python
def download_queue(jobs, max_concurrent=2):
    running = []
    for job in jobs:
        # Wait until we have space
        while len(running) >= max_concurrent:
            check_for_finished_downloads()
            time.sleep(5)

        # Start new download
        running.append(start_download(job))
```

**Benefits:**
- ✅ Never exceeds site limits
- ✅ Automatic refilling as downloads complete
- ✅ Graceful handling of failures
- ✅ User-friendly progress messages

### Why Pagination Handling?

**Problem:** Show pages only display 25 entries by default.

**Solution:** Click "All" in the pagination dropdown before scraping.

**Implementation:**
```python
# Find pagination dropdown
select = driver.find_element(By.CSS_SELECTOR, "select[name*='length']")
select.click()

# Select "All" option
all_option = select.find_element(By.XPATH, ".//option[text()='All']")
all_option.click()

# Wait for table to reload
time.sleep(2)
```

**Why This Matters:**
- ✅ Ensures we get ALL episodes (not just first 25)
- ✅ Works for series with 50+ episodes
- ✅ Handles both "EPISODES & FILMS" and "MISC FILES" tables

### Why Extract Filenames from Table Cells?

**Alternative Considered:** Parse filenames from download URLs.

**Chosen Approach:** Read filename directly from table's first column.

**Reasoning:**
- ✅ Filenames are already in the HTML
- ✅ No URL parsing or reconstruction needed
- ✅ Handles special characters correctly
- ✅ Matches exactly what Chrome will download
- ✅ Simpler code, fewer bugs

**Example:**
```python
# Get filename from first cell
filename = cells[0].text.strip()
# Result: "[GUIS]_Kyouryuu_Sentai_Zyuranger-_01_[018A4A15].mkv"

# Get download URL from last cell
href = cells[-1].find_element(By.CSS_SELECTOR, "a").get_attribute("href")
# Result: "https://krdl.moe/download/[GUIS]_Kyouryuu_Sentai_Zyuranger-_01_[018A4A15]/mkv"
```

### Why Duplicate Checking Before Download?

**Problem:** Re-downloading existing files wastes time and bandwidth.

**Solution:** Scan target directory before starting downloads.

**Implementation:**
```python
existing_files = set()
for file_path in target_dir.glob(f"*.{ext}"):
    existing_files.add(file_path.name.lower())

for url, filename in download_urls:
    if filename.lower() in existing_files:
        skip_download(filename)
```

**Benefits:**
- ✅ Instant skip (no network requests)
- ✅ Resume interrupted sessions
- ✅ Avoid rate limiting from unnecessary downloads
- ✅ User-friendly progress messages

## Error Handling

### Rate Limit Detection

**Symptom:** Browser redirects to `/premium` or `/register` page.

**Response:**
```python
if "premium" in current_url or "register" in current_url:
    print("🚨 RATE LIMIT DETECTED - STOPPING DOWNLOADS")
    print("⏰ Wait 15 minutes before retrying")
    stop_all_downloads()
```

**Why This Works:**
- ✅ Prevents hammering the site
- ✅ Protects user's account
- ✅ Clear user messaging

### Authentication Failures

**Detection:** Check URL after login attempt.

**Response:**
```python
if "login" in response.url:
    print("❌ Login failed - check credentials")
    return False
```

### Download Failures

**Detection:** Monitor process return codes and file sizes.

**Response:**
- Partial downloads: Mark as "PAUSED" (can resume)
- Complete failures: Mark as "FAIL" with error message
- Continue with remaining downloads

## Performance Considerations

### Why Not Headless by Default?

**Trade-off:** Headless mode is faster but harder to debug.

**Default:** Non-headless (visible browser).

**Reasoning:**
- ✅ Users can see authentication happening
- ✅ Easier to diagnose issues
- ✅ Confidence that it's working
- ✅ Can add `--headless` flag for automation

### Why 5-Second Sleep Between Checks?

**Balance:** Responsiveness vs. CPU usage.

**Chosen:** 5 seconds between download status checks.

**Reasoning:**
- Downloads take 5+ minutes each
- Checking every second is wasteful
- 5 seconds is responsive enough
- Reduces CPU usage

## Future Improvements

### Planned Features

1. **TUI (Text User Interface)**
   - Real-time progress bars
   - Interactive file selection
   - Better visual feedback

2. **Resume Capability**
   - Save download state to disk
   - Resume from where you left off
   - Handle interrupted sessions

3. **Batch Processing**
   - Download multiple series at once
   - Queue management across sessions
   - Priority ordering

4. **Smart Retry**
   - Exponential backoff for failures
   - Automatic retry on rate limits
   - Configurable retry strategies

### Potential Optimizations

- **Parallel Scraping:** Scrape multiple show pages simultaneously
- **Predictive Queueing:** Pre-fetch next downloads while current ones run
- **Bandwidth Monitoring:** Adjust concurrent downloads based on speed
- **Smart Scheduling:** Download during off-peak hours

## Security Considerations

### Credential Management

- ✅ Credentials stored in `.env` (gitignored)
- ✅ Never logged or printed
- ✅ Environment variable fallback
- ✅ No hardcoded secrets

### Browser Security

- ✅ Incognito mode for fresh sessions
- ✅ Automatic cookie clearing
- ✅ No persistent browser profile
- ✅ Webdriver detection mitigation

## Testing Strategy

See [Testing Documentation](testing.md) for details on:
- Unit tests for core functions
- Integration tests for download flow
- End-to-end tests with real site
- Regression tests for known bugs

## Contributing

See [Contributing Guide](../CONTRIBUTING.md) for:
- Development setup
- Code style guidelines
- Pull request process
- Testing requirements
