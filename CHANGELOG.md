# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-25

### Added

- Selenium-based downloader for [krdl.moe](https://krdl.moe): login, show-page scrape, “show all” pagination, MKV/MP4 filtering, 2-concurrent queue, rate-limit handling.
- **`csvdl_core`**: `Job`, path `expand`, `extract_urls_from_text`, `prepare_jobs`, `login_to_krdl`, `scrape_krdl_page` (requests/BeautifulSoup fallback).
- Download completion detection using the **target directory**: case-insensitive final filenames and `*.crdownload` partials (no reliance on Chrome alone).
- **Tests** aligned with current code (`csvdl_core`, `krdl_selenium` helpers, mocked scrape, CLI `--help`).
- **Pre-commit** (Ruff lint/format + hygiene hooks) and **GitHub Actions** CI (pre-commit + pytest on Python 3.9, 3.11, 3.12).
- **`requirements-dev.txt`** for local development tooling.

[1.0.0]: https://github.com/DouglasMacKrell/krdl-dl/releases/tag/v1.0.0
