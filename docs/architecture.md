# Architecture & design

How krdl-dl is structured, why it uses Selenium, and how scraping, unified episode picking, disk dedupe, and the download queue fit together.

## High-level diagram

```
                    krdl_selenium.py (CLI + orchestration)
 login ─► scrape (per-format tabs, sizes) ─► unified pick ─► disk dedupe ─► download_queue ─► [gap-fill]
                                              │                    │
         csvdl_core.py (Job, expand, …) ◄──────┴────────────────────┘
                                              │
                                   Chrome / chromedriver ─► krdl.moe + gen.krdl
```

## Main components

### `krdl_selenium.py`

- **`KrdlSeleniumDownloader`**: Chrome profile (download directory prefs), `setup_driver`, `clear_all_data` after launch, `login`, **`scrape_format_tab`** / **`scrape_all_format_tabs`**, **`download_queue`**, completion / stall / retry helpers.
- **Pure helpers** (unit-tested without a browser):
  - `_parse_krdl_size_bytes` — table strings like `244.85 MiB`, `1.19 GiB` → integer bytes.
  - `_canonical_episode_key` — maps a table filename to a stable key (`ep:001`, `movie`, `movie:hong_kong`, `special:…`, or `unique:…`). Includes T-N / Blu-ray styles such as `_03_HD1080[CRC]` and `_01DC_HD1080[CRC]` so they merge with `_-_03_` / `…_03_[…]` rips from other groups.
  - **`pick_episodes_from_unified_scrape`** — one primary **`ScrapeRow`** per key from merged mkv/mp4/avi rows, plus **`ranked_by_key`** for gap-fill.
  - **`filter_scrape_rows_not_on_disk`** — basename + **canonical-key** skip across `.mkv`/`.mp4`/`.avi`.
  - **`build_gap_fill_rows`** — next-best row per key still missing on disk (non-`unique:` keys).
  - `filter_by_quality_preference` — still used in tests / related paths; unified scrape is the primary queue builder.

### `csvdl_core.py`

Shared utilities: **`Job`** (`url`, `name`, `out_path`, `expected_bytes`, **`krdl_retries_left`**, `status`, …), **`expand`**, requests/BeautifulSoup helpers used by tests or alternate flows—not the primary Selenium path.

## End-to-end pipeline

1. **Driver setup**
   Chrome is configured with `download.default_directory` = `--target`, prompts disabled, automation flags toned down. **Incognito is intentionally not used** so download prefs apply; a **fresh session** is approximated by clearing storage/cookies in `clear_all_data()` on the real site origin after startup.

2. **Login**
   Form fill on `/login`, then check URL/title for success.

3. **Scrape**
   - **Default**: **`scrape_all_format_tabs(show_url)`** — for each of **`mkv`**, **`mp4`**, **`avi`**, open `{show}/{ext}`, set DataTables **All**, parse rows into **`(url, filename, size_bytes | None)`**, merge and dedupe by **(url, filename)**.
   - **`--strict-ext`**: a single **`scrape_format_tab`** for `--ext` only.
   - Row filter: href must expose a container segment (`/mkv`, `/mp4`, `/avi`) for **`_container_from_download_href`**.

4. **Unified episode pick**
   - **`pick_episodes_from_unified_scrape(rows, quality, container_order, strict_container)`** groups by **`_canonical_episode_key`**, sorts each group by **container preference** (from `--ext` order) then **`_unified_group_sort_key`** (`_vN_`, size for hd/sd, `_HD_` tie).
   - **`strict_container=True`**: only rows matching the first container in the order are considered (used with **`--strict-ext`**).
   - Output: primary **`download_urls`**, **`ranked_by_key`** (all rows per key, best-first), **`chosen_fmt_by_key`** (diagnostics).

5. **Disk dedupe**
   - **`filter_scrape_rows_not_on_disk`**: skip if basename exists or stem-prefix collision against **existing_extensions** from the CLI mode; if **`skip_if_canonical_key_on_disk`**, skip when the row’s **canonical key** is already present on disk scanning **all** of **`mkv`/`mp4`/`avi`** (so MKV satisfied blocks redundant AVI even under `--strict-ext`).
   - **Do not** treat `*.crdownload` as complete—prevents false skips after crashes.

6. **Jobs**
   **`Job.expected_bytes`** from the table when parsing succeeded; **`krdl_retries_left`** initialized from **`--max-download-retries`**.

7. **Download queue**
   - Work list is a **`deque`** of jobs; at most **`max_concurrent=2`** entries in **`running_downloads`**.
   - **Transient abandon** (`vanished` partials, failed begin, etc.): if **`krdl_retries_left > 0`**, decrement and **re-append** the job; else **`FAIL`** and record.
   - Per job: optionally **delete** `filename.crdownload` if the final `filename` is missing (retry hygiene).
   - Snapshot `*.crdownload` basenames **before** `driver.get(job.url)`; **`_wait_for_download_begin_signal`** gates slot reservation.
   - **Claimed partials**: new `.crdownload` names at begin time are stored; **`_had_byte_progress`** plus **`--vanished-after-progress-grace-seconds`** shorten abandon when Chrome removes partials **after** data was moving (avoids long 2-slot deadlocks).
   - **`--stagger-seconds`**, **`--tiny-preview-cooldown-seconds`** pace slot reuse.
   - **Rate limit**: register/premium URL → **stop**, **`FAIL`** running and **drain** pending jobs onto **`completed_jobs`**.

8. **Completion**
   Final file with Unicode-normalized basename match; jobs set **`DONE`** when finished. **`_should_abandon_stalled_download`** encapsulates frozen partial, vanished partial, and idle-without-track cases (tunable timeouts).

9. **Gap-fill** (optional, default on)
   **`build_gap_fill_rows`** uses **`ALL_CONTAINER_EXTENSIONS`** on disk for “missing key” detection; queues at most one alternate per missing key (skips basename conflicts).

## Design choices

### Why Selenium?

krdl is a logged-in, JS-heavy site with cookie/session behavior; driving a real browser matches what users do manually and makes redirects observable. **`requests`-only** helpers remain in `csvdl_core` for tests or experimentation, not the main downloader path.

### Why table sizes for “quality”?

Filenames are not always honest (“HD” in the name does not guarantee the larger file). The **site-published size** is used as the primary signal among rows that share a canonical key; **`_vN_`** prefers newer re-releases; **`_HD_`** is a tiebreaker when sizes tie or are missing.

### Why one browser tab?

Each `driver.get(download_url)` serializes navigation. Concurrency is **filesystem + server**: up to two transfers in flight in Chrome, not ten parallel tabs.

### Pagination “All”

Default table length hides rows; selecting **All** prevents partial series lists.

### Multi-tab merge vs `--strict-ext`

Many shows split encodes across **mkv** vs **avi** tabs. Merging gives **one** logical episode queue with explicit container preference. **`--strict-ext`** restores older “single extension table only” behavior and smaller page-load budgets.

## Limitations & gotchas

- **Unknown filenames** fall into **`unique:…`** keys—no cross-row dedupe for those unrelated shapes.
- **Very slow free tier** (e.g. ~400 kbps/file): wall time dominates; stall timeouts assume eventually consistent disk state.
- **Two processes** hitting the same account can exceed “2 downloads” from krdl’s perspective.
- **Resume** is “re-run the same command”: existing finals and satisfied canonical keys are skipped; there is no separate state file.
- **GitHub release tag**: version in README/CHANGELOG assumes **`v1.2.0`** is tagged when publishing; until then the release link may 404.

## Security & credentials

- Prefer `.env` or env vars; do not commit secrets.
- Logs partially redact usernames in some print paths—still treat terminal output as sensitive.

## Testing

Tests live under `tests/`:

- `test_krdl_selenium.py` — completion/stall/retry logic, canonical keys, unified scrape picks, **`filter_scrape_rows_not_on_disk`**, quality filter, size parsing (no network).
- `test_core.py`, `test_edge_cases.py` — `csvdl_core` and edge behavior.
- `test_integration.py` — lightweight script/help smoke checks.

There is no separate `testing.md`; use `pytest` and the Contributing guide.

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md).
