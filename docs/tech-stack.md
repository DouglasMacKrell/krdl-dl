# Tech stack & dependencies

What krdl-dl runs on and how the repo is wired for development and CI.

## Runtime

| Piece | Role |
|-------|------|
| **Python 3.9+** | Matches `pyproject.toml` (`target-version = "py39"`) and CI matrix |
| **Google Chrome** | Browser under automation; downloads land in `--target` via prefs |
| **ChromeDriver** | Supplied by **webdriver-manager** at runtime |

## Python dependencies (`requirements.txt`)

| Package | Role |
|---------|------|
| **selenium** | WebDriver control, page navigation, element queries |
| **webdriver-manager** | Download/match ChromeDriver to installed Chrome |
| **python-dotenv** | Load `KRDL_USERNAME` / `KRDL_PASSWORD` from `.env` |
| **requests** | HTTP in `csvdl_core` (login/scrape helpers, tests) |
| **beautifulsoup4** | HTML parsing in `csvdl_core` fallback scraper |

The primary CLI path is **`krdl_selenium.py`** (multi-tab scrape, unified episode pick, 2-slot queue with optional retries). **`csvdl_core.Job`** carries download state including **`krdl_retries_left`** for transient re-queues.

Exact minimum versions are pinned in `requirements.txt`.

## Development (`requirements-dev.txt`)

| Tool | Role |
|------|------|
| **pytest** (+ **pytest-asyncio**, **pytest-mock**) | Test runner and fixtures |
| **pre-commit** | Git hooks |
| **ruff** | Lint + format (config in `pyproject.toml`) |

Install everything for local dev:

```bash
pip install -r requirements-dev.txt
pre-commit install
```

## CI (GitHub Actions)

Workflow: `.github/workflows/ci.yml`

1. **pre-commit** job — runs `pre-commit run --all-files` on Python 3.12.
2. **test** job — matrix **Python 3.9, 3.11, 3.12** on Ubuntu: `pip install -r requirements-dev.txt` then `python -m pytest tests/`.

Triggers: push and pull request to **`main`** and **`develop`**.

## Code quality

- **Ruff** replaces separate black/flake8/isort for this repo.
- Rules under `[tool.ruff.lint]` in `pyproject.toml`; line length 100 with pragmatic `E501` ignore.

Run manually:

```bash
ruff check .
ruff format .
```

## Optional / future tooling

The repo may reference **textual** / **rich** in comments or older docs for a hypothetical TUI—they are **not** required for the current CLI. If a TUI is added, `requirements.txt` would gain those dependencies explicitly.

## OS support

Developed and tested primarily on **macOS** and **Linux** CI. **Windows** should work with Chrome + Python venv paths adjusted; issues are less frequently exercised in automation.

## Resource expectations

- **Chrome**: on the order of hundreds of MB RAM.
- **Disk**: episodes often hundreds of MiB to GiB each; target volume needs free space plus headroom for concurrent `.crdownload` files.
- **Network**: bounded by krdl free-tier throughput when downloading.

## Useful links

- [Selenium documentation](https://www.selenium.dev/documentation/)
- [Ruff](https://docs.astral.sh/ruff/)
- [pytest](https://docs.pytest.org/)
