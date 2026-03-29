# Architecture & design

How krdl-dl is structured, why it uses Selenium, and how scraping, quality selection, and the download queue fit together.

## High-level diagram

```
                    krdl_selenium.py (CLI + orchestration)
 login ─► scrape (tables, sizes) ─► quality filter ─► disk dedupe ─► download_queue
                                              │                    │
         csvdl_core.py (Job, expand, …) ◄──────┴────────────────────┘
                                              │
                                   Chrome / chromedriver ─► krdl.moe + gen.krdl
```

## Main components

### `krdl_selenium.py`

- **`KrdlSeleniumDownloader`**: Chrome profile (download directory prefs), `setup_driver`, `clear_all_data` after launch, `login`, `scrape_download_links`, `download_queue`, completion / stall helpers.
- **Pure helpers** (unit-tested without a browser):
  - `_parse_krdl_size_bytes` — table strings like `244.85 MiB`, `1.19 GiB` → integer bytes.
  - `_canonical_episode_key` — maps a table filename to a stable key (`ep:001`, `movie`, or `unique:…`).
  - `_is_hd_filename` — `_HD_` in the normalized basename.
  - `filter_by_quality_preference` — one `(url, filename, size_bytes)` per key for `hd` or `sd` mode.

### `csvdl_core.py`

Shared utilities: **`Job`** (`url`, `name`, `out_path`, `expected_bytes`, `status`, …), **`expand`**, requests/BeautifulSoup helpers used by tests or alternate flows—not the primary Selenium path.

## End-to-end pipeline

1. **Driver setup**
   Chrome is configured with `download.default_directory` = `--target`, prompts disabled, automation flags toned down. **Incognito is intentionally not used** so download prefs apply; a **fresh session** is approximated by clearing storage/cookies in `clear_all_data()` right after startup.

2. **Login**
   Form fill on `/login`, then check URL/title for success.

3. **Scrape**
   - Open the show `--url`.
   - Locate the DataTables **length** `<select>`, choose **All**, short sleep for redraw.
   - For each `<tr>` with ≥4 `<td>` cells: take **filename** (col 0), **size text** (col 1), **href** (last col).
   - Append `(url, filename, parsed_size_or_None)` when the href matches `/download/…` and the chosen `--ext`.

4. **Quality filter**
   - Group rows by `_canonical_episode_key(filename)`.
   - **`hd`**: `max` by `(size_bytes if known else -1, 1 if _HD_ else 0)`.
   - **`sd`**: `min` by `(size_bytes if known else +inf, 1 if _HD_ else 0)` so non-HD names win ties toward small files.
   - Episodes that only exist in one quality still download (single row in group).

   **Key examples** (regex family, not an exhaustive grammar of every rip on krdl):

   - `_Ep12_…`, `_-_12_…` (Nemet-style), `_12_[hexhash]` before CRC bracket → same `ep:012`.
   - `_The_Movie_…`, `_Movie_[…]`, `(The_)?Movie…_HD_` → `movie` (covers several naming styles including `The_Movie_v2` vs `The_Movie_1080p`).

5. **Disk dedupe**
   - Collect lowercase basenames of existing `*.{ext}` under `--target` only.
   - **Do not** mark an episode “done” because a `*.crdownload` exists—that caused false skips when Chrome removed a partial or a run crashed.
   - Optional **prefix** skip if another file’s name shares the stem (Chrome renames).

6. **Jobs**
   `Job.expected_bytes` is filled from the table when parsing succeeded (optional future use / debugging).

7. **Download queue**
   - At most **`max_concurrent=2`** entries in `running_downloads`.
   - For each job: optionally **delete** `filename.crdownload` if the final `filename` is missing (retry hygiene).
   - Snapshot `*.crdownload` basenames **before** `driver.get(job.url)`; after navigation, `_wait_for_download_begin_signal` requires **gen.krdl** in the URL, a **named** partial, **any new** `.crdownload`, or the final file—before reserving a slot.
   - **Claimed partials**: new `.crdownload` names seen at begin time are stored on the job so stall logic tracks the **right** partial and does not confuse two concurrent Chrome downloads.
   - **`--stagger-seconds`**: sleeps after `waited_for_slot` becomes true—i.e. before kicking off the next file **after** at least one active download finished—reducing back-to-back hits on krdl.
   - If the current URL matches register/premium patterns, **return immediately** (partial queue state; user should cool off).

8. **Completion / abandon**
   Final file detected with Unicode-normalized basename match (NBSP, etc.). Stalls: frozen partial, vanished claimed partial, or “never started” windows—see `_should_abandon_stalled_download` in code.

## Design choices

### Why Selenium?

krdl is a logged-in, JS-heavy site with cookie/session behavior; driving a real browser matches what users do manually and makes redirects observable. **`requests`-only** helpers remain in `csvdl_core` for tests or experimentation, not the main downloader path.

### Why table sizes for “quality”?

Filenames are not always honest (“HD” in the name does not guarantee the larger file). The **site-published size** is used as the primary signal; **`_HD_`** is a tiebreaker when sizes tie or are missing.

### Why one browser tab?

Each `driver.get(download_url)` serializes navigation. Concurrency is **filesystem + server**: up to two transfers in flight in Chrome, not ten parallel tabs.

### Pagination “All”

Default table length hides rows; selecting **All** prevents partial series lists.

## Limitations & gotchas

- **No cross-extension merge**: `--ext mkv` never compares MKV size to MP4 size; choosing container is explicit.
- **Unknown filenames** fall into `unique:…` keys—no dedupe across unrelated rows.
- **Very slow free tier** (e.g. ~400 kbps/file): wall time dominates; stall timeouts assume eventually consistent disk state.
- **Two processes** hitting the same account can exceed “2 downloads” from krdl’s perspective.
- **Resume** is “re-run the same command”: existing finals are skipped; there is no separate state file.

## Security & credentials

- Prefer `.env` or env vars; do not commit secrets.
- Logs partially redact usernames in some print paths—still treat terminal output as sensitive.

## Testing

Tests live under `tests/`:

- `test_krdl_selenium.py` — completion/stall logic, canonical keys, quality filter, size parsing (no network).
- `test_core.py`, `test_edge_cases.py` — `csvdl_core` and edge behavior.
- `test_integration.py` — lightweight script/help smoke checks.

There is no separate `testing.md`; use `pytest` and the Contributing guide.

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md).
