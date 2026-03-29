# krdl-dl

A Selenium-based automated downloader for [krdl.moe](https://krdl.moe) (tokusatsu archive). Log in with your account, scrape a show page, dedupe episodes by quality, and download with a two-slot queue that matches the site’s free-tier rules.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/DouglasMacKrell/krdl-dl/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/DouglasMacKrell/krdl-dl/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**Current release:** [v1.1.0](https://github.com/DouglasMacKrell/krdl-dl/releases/tag/v1.1.0) (2026-03-28) — [changelog](CHANGELOG.md).

## Features

- **Authenticated downloads** via Selenium (Chrome) and your krdl credentials  
- **Show-page scraping** with pagination set to **All** so long series are fully listed  
- **Extension filter**: `--ext mkv` or `--ext mp4` (only links matching that type are queued)  
- **Per-episode quality selection** (`--quality hd` default): uses **KRDL table file sizes** (MiB/GiB) as the main signal; `hd` prefers the **larger** file per episode, `sd` the **smaller**; filenames containing `_HD_` break ties  
- **Canonical episode keys** so multiple releases (e.g. SD + HD, different groups) collapse to **one** download per episode when both map to the same number; specials/movies use dedicated keys (including `_The_Movie_` style names)  
- **Two concurrent downloads** (`max_concurrent=2`), aligned with krdl free-tier messaging  
- **Configurable stagger** (`--stagger-seconds`) before starting the next job after a slot frees—helps avoid aggressive back-to-back hits when chaining many files  
- **Duplicate skip** using **finished** `*.{ext}` files only (stale `.crdownload` partials are **not** treated as “already downloaded”); optional removal of a matching stale partial before retry  
- **Download tracking** via final filenames plus `*.crdownload` (including per-job **claimed** partials from Chrome)  
- **Rate-limit / premium redirect** detection: stops the queue instead of hammering the site  
- **`--limit`** for dry runs or sampling  

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/quickstart.md](docs/quickstart.md) | Install, `.env`, first command |
| [docs/architecture.md](docs/architecture.md) | Pipeline, design choices, edge cases |
| [docs/tech-stack.md](docs/tech-stack.md) | Dependencies, CI, tooling |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, style, PRs |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |

## Quick start

### Install

```bash
git clone https://github.com/DouglasMacKrell/krdl-dl.git
cd krdl-dl
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Credentials

Create `.env` in the project root (file is gitignored):

```bash
KRDL_USERNAME=your_email@example.com
KRDL_PASSWORD=your_password
```

### Typical command

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/your-show-slug" \
  --target "/path/to/out" \
  --ext mkv \
  --quality hd
```

Shows that list both a small and a large MKV for the same episode (e.g. old rip vs HD) will select the **larger** row when `--quality hd` is used. Use `--quality sd` if you explicitly want the smaller rips. Only rows for the chosen `--ext` participate in comparison.

### Gentle pacing (after rate kicks)

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/your-show-slug" \
  --target "/path/to/out" \
  --ext mkv \
  --quality hd \
  --stagger-seconds 60
```

### Other useful flags

```bash
# Cap how many new files this run will start (existing files on disk still skipped first)
python3 krdl_selenium.py --url "…" --target "…" --ext mkv --limit 3

# Headless Chrome
python3 krdl_selenium.py --url "…" --target "…" --ext mkv --headless

# Override credentials without editing .env
python3 krdl_selenium.py --url "…" --target "…" --username "…" --password "…"
```

## CLI reference

| Argument | Required | Description | Default |
|----------|----------|-------------|---------|
| `--url` | Yes | krdl.moe show page URL | — |
| `--target` | Yes | Directory for downloads (created if needed) | — |
| `--ext` | No | `mkv` or `mp4` | `mkv` |
| `--quality` | No | `hd` = prefer larger table size per episode (tie: `_HD_` in name); `sd` = prefer smaller (tie: avoid `_HD_`); missing tier still picks the only row | `hd` |
| `--stagger-seconds` | No | Seconds to sleep before starting a download **after** waiting for a free slot | `15` (`0` disables) |
| `--limit` | No | Max **new** jobs to start this run (after dedupe) | no limit |
| `--headless` | No | Run Chrome headless | off |
| `--username` / `--password` | No | Override `.env` | from `.env` |

## How it works (short)

1. Load `.env`, start Chrome with download directory set to `--target`.  
2. Log in to krdl; navigate to `--url`.  
3. Set the DataTables-style length menu to **All**; read each row’s **filename**, **size**, and **download** link for the requested extension.  
4. **Quality pass**: group rows by a parsed **canonical episode/movie key**; keep one row per key per `--quality` rules.  
5. **Disk dedupe**: skip any file whose final `*.{ext}` already exists (prefix rules avoid obvious collisions).  
6. **Queue**: at most two active downloads; each job hits its download URL in the same tab; wait for gen.krdl / partial / file signals before counting a slot full.  
7. On premium/register-style URL, **stop** the run.

See [docs/architecture.md](docs/architecture.md) for detail and limitations.

## krdl.moe limits (free tier)

Typical messages on the site include **~400 kbps per file** and **at most two simultaneous downloads**. This tool enforces the **two-slot** rule in one process. It does **not** speed up transfers. Long runs or multiple parallel **processes** can still trigger throttling—use **`--stagger-seconds`** and avoid overlapping runs.

## Requirements

- **Python 3.9+**  
- **Google Chrome** (current stable; ChromeDriver via webdriver-manager)  
- **krdl.moe account**  
- Network and disk suitable for multi‑GB series  

## Testing & CI

```bash
pip install -r requirements-dev.txt
pytest
pre-commit run --all-files
```

GitHub Actions runs **pre-commit** and **pytest** on Python **3.9, 3.11, 3.12** for pushes/PRs to `main` and `develop`.

## Project layout

```
krdl-dl/
├── krdl_selenium.py       # CLI + Selenium downloader + quality/scrape helpers
├── csvdl_core.py          # Job, expand, requests/BS4 helpers
├── pyproject.toml         # pytest + Ruff
├── requirements.txt
├── requirements-dev.txt
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── docs/
├── tests/
├── CONTRIBUTING.md
├── CHANGELOG.md
└── README.md
```

## Roadmap (high level)

Ideas that are **not** implemented yet: richer TUI, persisted resume state, multi-show batch CLI, stronger automated retry policies. Current releases are listed in [CHANGELOG.md](CHANGELOG.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

## Legal & ethics

For **personal use**. Respect [krdl.moe](https://krdl.moe) terms, rate limits, and copyright. Do not use this tool to overload the site or redistribute encodes without permission.

---

**Support:** [Issues](https://github.com/DouglasMacKrell/krdl-dl/issues) · **Upstream:** content belongs to krdl.moe and licensors.
