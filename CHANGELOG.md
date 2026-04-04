# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0] - 2026-03-27

### Added

- **Multi-format show scrape** (default): loads **`.mkv`**, **`.mp4`**, and **`.avi`** tabs (3 page loads), merges rows, then **`pick_episodes_from_unified_scrape`** — one queue row per canonical key with container preference **`MKV → MP4 → AVI`** (from `--ext` order) plus `--quality` / `_vN_` / `_HD_` tie-breaks.
- **`--strict-ext`**: single-tab scrape for `--ext` only; no cross-format merge or fallback.
- **`--ext avi`**: `avi` is a first-class choice alongside `mkv` and `mp4`.
- **`--gap-fill-second-pass` / `--no-gap-fill-second-pass`** (default on): after the main queue, queue the next-best alternate per **missing** canonical key (when alternates exist in the scrape).
- **`--tiny-preview-cooldown-seconds`** (default 600): long pause after ep **00** or a very small finished file frees a slot (rate-limit friendly).
- **Cross-format disk dedupe**: **`filter_scrape_rows_not_on_disk`** skips a row when its **canonical episode key** already exists under **`--target`** as any of `.mkv`/`.mp4`/`.avi` — avoids re-downloading T-N AVI when GS MKV is already present (also used when `--strict-ext` so MKV on disk still blocks redundant AVI).
- **Transient download recovery**: **`Job.krdl_retries_left`** and **`--max-download-retries`** (default 3) re-queue the same job after vanished partials or failed begin handoffs; work queue uses a **`deque`** so retries respect the 2-slot limit.
- **Stall tuning**: **`--vanished-partial-grace-seconds`** (default 300, “no bytes yet”), **`--vanished-after-progress-grace-seconds`** (default 75, after partial was growing then Chrome removed `.crdownload` files), **`--idle-no-claim-grace-seconds`** (default 300).
- **`_had_byte_progress`**, **`movie:hong_kong`** vs theatrical **`movie`**, T-N-style **`_-_NN[…]`** / **`_-_Movie[`** / VS Boukenger **special** keys for cleaner grouping.
- **Download summary**: failures whose canonical keys are still missing on disk are called out with tuning hints.
- Tests: unified scrape picks, **`filter_scrape_rows_not_on_disk`** canonical skip, vanished-partial abandon behavior.

### Fixed

- **Completed job accounting**: successful downloads set **`DONE`** and append to the completed list (summary counts were misleading before).
- **Rate-limit stop**: pending jobs in the work queue are marked **`FAIL`** and recorded instead of being dropped silently.
- **Deadlock**: shortened abandon window **after byte progress** when all claimed partials vanish (previously could wait the full 300s with both slots “busy” and no data moving).

### Changed

- **`build_gap_fill_rows`** and canonical-key checks scan **all** container extensions on disk for “already have this episode,” not only the active scrape extensions.

## [1.1.0] - 2026-03-28

### Added

- **`--quality hd|sd`**: Per canonical episode/movie key, keep one table row—**size-first** from KRDL’s size column, with **`_HD_`** in the filename as tiebreaker (`hd` = prefer larger, `sd` = prefer smaller).
- **`_parse_krdl_size_bytes`**: Parses MiB/GiB/etc. from episode tables; scrape returns `(url, filename, size_bytes | None)`; **`Job.expected_bytes`** populated when known.
- **`_canonical_episode_key`**: Groups `EpNN`, `_-_NN_`, `_NN_[crc]`-style stems, movie patterns including **`_The_Movie_`** (e.g. multiple movie encodes).
- **`--stagger-seconds`**: Cooldown before starting the next download after a queue slot frees (default 15s).
- **Per-job claimed** `.crdownload` tracking in stall/completion logic to reduce cross-talk when two files are active.
- Tests: quality filter, size parsing, canonical keys, claimed-partial behavior.

### Fixed

- **Pre-queue dedupe**: Only finished `*.{ext}` count as “already have file”—**do not** skip because a stale **`*.crdownload`** exists (avoids missing episodes after failed runs).
- **Retry hygiene**: Remove matching **`filename.crdownload`** when starting a job if the final **`filename`** is still missing.

### Documentation

- README, quickstart, architecture, and tech stack updated for `--quality`, table sizes, dedupe, stagger, and queue behavior; CONTRIBUTING notes **`develop`** as integration branch.

## [1.0.0] - 2026-03-25

### Added

- Selenium-based downloader for [krdl.moe](https://krdl.moe): login, show-page scrape, “show all” pagination, MKV/MP4 filtering, 2-concurrent queue, rate-limit handling.
- **`csvdl_core`**: `Job`, path `expand`, `extract_urls_from_text`, `prepare_jobs`, `login_to_krdl`, `scrape_krdl_page` (requests/BeautifulSoup fallback).
- Download completion detection using the **target directory**: case-insensitive final filenames and `*.crdownload` partials.
- **Tests** for `csvdl_core`, `krdl_selenium` helpers, mocked scrape, CLI `--help`.
- **Pre-commit** (Ruff + hygiene hooks) and **GitHub Actions** CI (pre-commit + pytest on Python 3.9, 3.11, 3.12).
- **`requirements-dev.txt`** for local development tooling.

[Unreleased]: https://github.com/DouglasMacKrell/krdl-dl/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/DouglasMacKrell/krdl-dl/releases/tag/v1.2.0
[1.1.0]: https://github.com/DouglasMacKrell/krdl-dl/releases/tag/v1.1.0
[1.0.0]: https://github.com/DouglasMacKrell/krdl-dl/releases/tag/v1.0.0
