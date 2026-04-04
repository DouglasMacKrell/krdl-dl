<p align="center">
  <img src="assets/readme-header.png" alt="Digital illustration of Red, Blue, Yellow, and Pink Power Rangers in a tug-of-war, trying to save the Pink Ranger from being sucked into a giant, monstrous computer folder vortex." width="720">
</p>

# krdl-dl

A Selenium-based automated downloader for [krdl.moe](https://krdl.moe) (tokusatsu archive). Log in with your account, scrape a show page, dedupe episodes by quality, and download with a two-slot queue that matches the site’s free-tier rules.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/DouglasMacKrell/krdl-dl/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/DouglasMacKrell/krdl-dl/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**Current release:** [v1.2.0](https://github.com/DouglasMacKrell/krdl-dl/releases/tag/v1.2.0) (2026-03-27) — [changelog](CHANGELOG.md).

## Features

- **Authenticated downloads** via Selenium (Chrome) and your krdl credentials
- **Show-page scraping** with pagination set to **All** so long series are fully listed
- **Multi-tab scrape** (default): **`mkv`**, **`mp4`**, and **`avi`** episode tables are loaded and merged; **`--ext`** sets *preference order* (`MKV→MP4→AVI` by default), then **one row per canonical episode** is chosen. Use **`--strict-ext`** for a single tab only (no cross-format merge).
- **Per-episode quality selection** (`--quality hd` default): uses **KRDL table file sizes** (MiB/GiB), **`_vN_`** versioning, and **`_HD_`** in filenames as tie-breakers (`hd` = larger, `sd` = smaller among same-key rows)
- **Canonical episode keys** so multiple releases (different groups, T-N dash names, etc.) collapse to **one** download per episode; movies include **`movie`** vs **`movie:hong_kong`** where applicable; some specials use stable **`special:…`** keys; unknown shapes use **`unique:…`**
- **Two concurrent downloads** (`max_concurrent=2`), aligned with krdl free-tier messaging
- **Configurable stagger** (`--stagger-seconds`) and **tiny-preview / ep 00 cooldown** (`--tiny-preview-cooldown-seconds`, default 600s) before the next job after certain slot frees
- **Duplicate skip**: finished **`mkv` / `mp4` / `avi`** on disk; also **skip by canonical key** so you do not re-fetch an AVI when the same episode is already present as MKV (and vice versa). Stale `.crdownload` files are **not** treated as complete
- **Transient retries** (`--max-download-retries`, default 3): vanished Chrome partials or failed “download began” handoffs re-queue the same job instead of skipping episodes
- **Gap-fill pass** (on by default; **`--no-gap-fill-second-pass`** to disable): optional second pass queues the **next-best alternate** per key still missing on disk after the main run
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

Within each **canonical key**, `hd`/`sd` and size/`_vN_`/`_HD_` rules pick one row. With the default multi-tab scrape, **container preference** follows `--ext` order (e.g. **`--ext mkv`** tries to keep MKV when available). **`--strict-ext`** restricts scraping and comparison to that container only.

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

# Single-format tab only (1 page load, no mkv/mp4/avi merge)
python3 krdl_selenium.py --url "…" --target "…" --ext mkv --strict-ext

# After flaky WiFi: more re-tries and tuning for vanished Chrome partials
python3 krdl_selenium.py --url "…" --target "…" --ext mkv \
  --max-download-retries 5 --vanished-after-progress-grace-seconds 60

# Headless Chrome
python3 krdl_selenium.py --url "…" --target "…" --ext mkv --headless

# Override credentials without editing .env
python3 krdl_selenium.py --url "…" --target "…" --username "…" --password "…"
```

## CLI reference

See `python3 krdl_selenium.py --help` for the full list. Common arguments:

| Argument | Required | Description | Default |
|----------|----------|-------------|---------|
| `--url` | Yes | krdl.moe show page URL | — |
| `--target` | Yes | Directory for downloads (created if needed) | — |
| `--ext` | No | Preferred container: `mkv`, `mp4`, or `avi` (default multi-tab merge uses this as preference order) | `mkv` |
| `--strict-ext` | No | Only scrape the `--ext` tab; no merge/fallback across mkv/mp4/avi | off |
| `--quality` | No | `hd` / `sd` per canonical key (`_vN_`, size, `_HD_` ties) | `hd` |
| `--stagger-seconds` | No | Pause before starting a download **after** waiting for a free slot | `15` (`0` disables) |
| `--tiny-preview-cooldown-seconds` | No | Extra pause after ep 00 / tiny complete file frees a slot | `600` |
| `--gap-fill-second-pass` | No | Boolean: run alternate-release pass for missing keys (use `--no-gap-fill-second-pass`) | on |
| `--max-download-retries` | No | Re-queue a job after transient partial/begin failures | `3` |
| `--vanished-partial-grace-seconds` | No | Abandon if claimed partials vanish **before** byte progress was seen | `300` |
| `--vanished-after-progress-grace-seconds` | No | Abandon if partials vanish **after** data was moving (frees stuck slots) | `75` |
| `--idle-no-claim-grace-seconds` | No | Abandon when nothing to track on disk | `300` |
| `--limit` | No | Max **new** jobs to start this run (after dedupe) | no limit |
| `--headless` | No | Run Chrome headless | off |
| `--username` / `--password` | No | Override `.env` | from `.env` |

## How it works (short)

1. Load `.env`, start Chrome with download directory set to `--target`.
2. Log in to krdl.
3. **Scrape** (default): for each of **`mkv` / `mp4` / `avi`**, open the show’s format tab, set **All** rows, parse **filename**, **size**, **href**; merge and dedupe rows. With **`--strict-ext`**, only one tab.
4. **Unified pick**: group by **canonical episode key**; sort by **`--ext`** preference, `--quality`, `_vN_`, size, `_HD_`; keep **one primary row per key** (plus ranked alternates for gap-fill).
5. **Disk dedupe**: skip exact basenames, stem collisions, and any row whose **canonical key** is already satisfied by **any** video extension on disk.
6. **Queue**: at most two active downloads (`deque` work list); transient failures **re-queue** up to **`--max-download-retries`**; stall windows use **vanished / idle** grace flags (shorter after byte progress when Chrome drops partials).
7. Optional **gap-fill** pass for keys still missing with alternates in the scrape.
8. On premium/register-style URL, **stop** and mark remaining jobs failed.

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

Ideas that are **not** implemented yet: richer TUI, persisted resume state, multi-show batch CLI. Current releases are listed in [CHANGELOG.md](CHANGELOG.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

## Legal & ethics

For **personal use**. Respect [krdl.moe](https://krdl.moe) terms, rate limits, and copyright. Do not use this tool to overload the site or redistribute encodes without permission.

---

**Support:** [Issues](https://github.com/DouglasMacKrell/krdl-dl/issues) · **Upstream:** content belongs to krdl.moe and licensors.
