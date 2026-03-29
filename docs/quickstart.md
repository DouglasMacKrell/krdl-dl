# Quickstart

Get **krdl-dl** running in a few minutes.

## Prerequisites

- **Python 3.9+**
- **Google Chrome** installed
- A **krdl.moe** account

## Install

```bash
git clone https://github.com/DouglasMacKrell/krdl-dl.git
cd krdl-dl
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Credentials

Create `.env` in the repo root:

```
KRDL_USERNAME=your_email@example.com
KRDL_PASSWORD=your_password
```

Never commit `.env` (it is listed in `.gitignore`).

## First download

Replace the URL with any **show** page on krdl (e.g. `https://krdl.moe/show/…`).

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/kyouryuu-sentai-zyuranger" \
  --target "/path/to/download/folder" \
  --ext mkv \
  --quality hd
```

- **`--ext`**: only `mkv` or `mp4` links from the table are collected.  
- **`--quality hd`** (default): for each **episode number** (or movie key) found in filenames, the script keeps the row with the **largest** size reported in the table; if sizes tie, it prefers filenames containing `_HD_`. If only one rip exists for that episode, it is used.  
- **`--quality sd`**: prefers **smaller** sizes (and ties toward names **without** `_HD_`), still falling back when only one row exists.

## MP4 only

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/choujin-sentai-jetman" \
  --target "/path/to/folder" \
  --ext mp4 \
  --quality hd
```

## Safer pacing

If the site starts redirecting you to register/premium after many files, increase the delay **between** starting new jobs once a slot frees:

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/…" \
  --target "/path/to/folder" \
  --ext mkv \
  --stagger-seconds 60
```

## Smoke test with `--limit`

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/kyouryuu-sentai-zyuranger" \
  --target "/path/to/test-folder" \
  --ext mkv \
  --limit 2
```

`--limit` applies **after** skipping files that already exist in `--target`.

## Common CLI flags

| Flag | Purpose |
|------|---------|
| `--url` | Show page URL (required) |
| `--target` | Output directory (required) |
| `--ext` | `mkv` or `mp4` |
| `--quality` | `hd` or `sd` |
| `--stagger-seconds` | Pause before each new start after a slot opens (default `15`) |
| `--limit` | Max new downloads this run |
| `--headless` | Headless Chrome |
| `--username` / `--password` | Override `.env` |

Full list: `python3 krdl_selenium.py --help` or the root [README](../README.md).

## What to expect

1. A Chrome window opens (unless `--headless`), logs in, opens the show page.  
2. Pagination is set to **All** so every table row is visible.  
3. The script builds a queue, skips names that already exist as finished `*.{ext}`, then downloads with **at most two** active transfers.  
4. Interrupted runs: **stale `.crdownload` files are not treated as completed episodes**—re-run to retry. A matching partial is removed when a job starts if the final file is still missing.

## Troubleshooting

| Problem | Things to check |
|---------|-----------------|
| “No credentials” | `.env` in project root, or pass `--username` / `--password` |
| Premium/register redirect | Cool off (often 15+ minutes); increase `--stagger-seconds`; do not run two downloads on the same account in parallel |
| Browser / login | Run without `--headless` and watch the window |
| Wrong rip chosen | Use `--quality sd` or inspect table sizes on krdl; only the chosen `--ext` is compared |

## Next steps

- [Architecture](architecture.md) — pipeline and design trade‑offs  
- [Tech stack](tech-stack.md) — dependencies and CI  
- [Contributing](../CONTRIBUTING.md) — dev setup  

Need help? Open an [issue](https://github.com/DouglasMacKrell/krdl-dl/issues) with the exact command and message you see.
