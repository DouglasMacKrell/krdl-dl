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

**What this does (defaults):**

- Loads **`mkv`**, **`mp4`**, and **`avi`** tabs (three page loads), merges the tables, then picks **one row per episode** (canonical key). **`--ext mkv`** means **prefer MKV** when multiple containers exist for the same episode; fall back to mp4/avi as needed.
- **`--quality hd`** (default): among same-key candidates, prefers **larger** reported sizes, higher **`_vN_`**, and **`_HD_`** tie-breaks; **`sd`** prefers smaller / avoids `HD` ties.

## MP4 or AVI preference

`--ext` can be **`mkv`**, **`mp4`**, or **`avi`** — it sets **preference order** when the multi-tab merge is enabled (default).

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/choujin-sentai-jetman" \
  --target "/path/to/folder" \
  --ext mp4 \
  --quality hd
```

## Single tab only (`--strict-ext`)

One format tab, one page load; no mkv/mp4/avi merge (legacy-style behavior).

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/…" \
  --target "/path/to/folder" \
  --ext mkv \
  --strict-ext \
  --quality hd
```

Disk dedupe still considers **all** of `.mkv`/`.mp4`/`.avi` in `--target` for **canonical episode keys**, so you do not re-download an AVI when the MKV for that episode is already there.

## Safer pacing

If the site starts redirecting you to register/premium after many files, increase the delay **between** starting new jobs once a slot frees:

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/…" \
  --target "/path/to/folder" \
  --ext mkv \
  --stagger-seconds 60
```

## Flaky network / vanished downloads

Chrome may drop `.crdownload` files when the link flaps. The tool **re-queues** jobs up to **`--max-download-retries`** (default **3**). Tune stall windows if needed:

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/…" \
  --target "/path/to/folder" \
  --ext mkv \
  --max-download-retries 5 \
  --vanished-after-progress-grace-seconds 60
```

## Smoke test with `--limit`

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/kyouryuu-sentai-zyuranger" \
  --target "/path/to/test-folder" \
  --ext mkv \
  --limit 2
```

`--limit` applies **after** skipping files / canonical keys already satisfied in `--target`.

## Gap-fill pass

By default, after the main queue the script may download **alternate releases** for episode keys still missing on disk. Disable with:

```bash
python3 krdl_selenium.py --url "…" --target "…" --ext mkv --no-gap-fill-second-pass
```

## Common CLI flags

| Flag | Purpose |
|------|---------|
| `--url` | Show page URL (required) |
| `--target` | Output directory (required) |
| `--ext` | `mkv`, `mp4`, or `avi` (preference in merged mode) |
| `--strict-ext` | Single tab for `--ext` only |
| `--quality` | `hd` or `sd` |
| `--stagger-seconds` | Pause before each new start after a slot opens (default `15`) |
| `--tiny-preview-cooldown-seconds` | Extra pause after ep 00 / tiny file frees a slot (default `600`) |
| `--max-download-retries` | Re-queue after transient failures (default `3`) |
| `--vanished-*` / `--idle-no-claim-grace-seconds` | Stall / abandon tuning (see `--help`) |
| `--gap-fill-second-pass` / `--no-gap-fill-second-pass` | Second pass for missing keys (default on) |
| `--limit` | Max new downloads this run |
| `--headless` | Headless Chrome |
| `--username` / `--password` | Override `.env` |

Full list: `python3 krdl_selenium.py --help` or the root [README](../README.md).

## What to expect

1. A Chrome window opens (unless `--headless`), logs in, opens the show page(s).
2. Pagination is set to **All** on each format tab that is scraped.
3. The script builds a queue, skips names and **canonical keys** already satisfied on disk, then downloads with **at most two** active transfers.
4. Interrupted runs: **stale `.crdownload` files are not treated as completed episodes**—re-run to retry. A matching partial is removed when a job starts if the final file is still missing.

## Troubleshooting

| Problem | Things to check |
|---------|-----------------|
| “No credentials” | `.env` in project root, or pass `--username` / `--password` |
| Premium/register redirect | Cool off (often 15+ minutes); increase `--stagger-seconds`; do not run two downloads on the same account in parallel |
| Browser / login | Run without `--headless` and watch the window |
| Wrong rip chosen | Use `--quality sd` or inspect table sizes on krdl; unified mode compares across merged rows |
| Slots stuck / no `.crdownload` | Network hiccup—lower `--vanished-after-progress-grace-seconds` or raise `--max-download-retries`; re-run |
| Duplicate AVI + MKV from an old run | Safe to delete redundant files; new runs skip by **canonical key** |

## Next steps

- [Architecture](architecture.md) — pipeline and design trade‑offs
- [Tech stack](tech-stack.md) — dependencies and CI
- [Contributing](../CONTRIBUTING.md) — dev setup

Need help? Open an [issue](https://github.com/DouglasMacKrell/krdl-dl/issues) with the exact command and message you see.
