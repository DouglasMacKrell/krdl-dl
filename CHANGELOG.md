# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/DouglasMacKrell/krdl-dl/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/DouglasMacKrell/krdl-dl/releases/tag/v1.1.0
[1.0.0]: https://github.com/DouglasMacKrell/krdl-dl/releases/tag/v1.0.0
