# Quickstart Guide

Get up and running with krdl-dl in under 5 minutes!

## Prerequisites

- Python 3.8 or higher
- Google Chrome browser installed
- krdl.moe account (free or premium)

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/DouglasMacKrell/krdl-dl.git
   cd krdl-dl
   ```

2. **Create a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up your credentials:**
   
   Create a `.env` file in the project root:
   ```bash
   KRDL_USERNAME=your_email@example.com
   KRDL_PASSWORD=your_password
   ```

## Basic Usage

### Download a complete series

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/kyouryuu-sentai-zyuranger" \
  --target "/path/to/download/folder" \
  --ext mkv
```

### Download only MP4 files

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/choujin-sentai-jetman" \
  --target "/path/to/download/folder" \
  --ext mp4
```

### Test with limited downloads

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/kyouryuu-sentai-zyuranger" \
  --target "/path/to/download/folder" \
  --ext mkv \
  --limit 3
```

## Command-Line Arguments

| Argument | Required | Description | Default |
|----------|----------|-------------|---------|
| `--url` | Yes | URL of the krdl.moe show page | - |
| `--target` | Yes | Directory to save downloads | - |
| `--ext` | No | File extension to download (`mkv` or `mp4`) | `mkv` |
| `--limit` | No | Limit number of downloads (for testing) | None |
| `--username` | No | krdl.moe username (overrides .env) | From .env |
| `--password` | No | krdl.moe password (overrides .env) | From .env |
| `--headless` | No | Run browser in headless mode | False |

## How It Works

1. **Login**: Authenticates with krdl.moe using your credentials
2. **Scrape**: Navigates to the show page and extracts all download links
3. **Filter**: Filters links by your chosen extension (mkv or mp4)
4. **Dedupe**: Checks target directory and skips existing files
5. **Queue**: Downloads up to 2 files concurrently (respects site limits)
6. **Monitor**: Tracks `.crdownload` files and waits for completion
7. **Complete**: Files are automatically saved to your target directory

## Important Notes

### Rate Limiting

krdl.moe has strict rate limits for free users:
- **400kbps** per file download speed
- **2 concurrent downloads** maximum
- **~5 minutes** per file (for typical episode sizes)

**⚠️ Exceeding these limits will temporarily restrict your account!**

The downloader automatically respects these limits by:
- Only running 2 downloads at once
- Waiting for downloads to complete before starting new ones
- Gracefully stopping if redirected to premium/register page

### File Management

- Files download directly to your specified `--target` directory
- Chrome creates temporary `.crdownload` files during download
- Files are automatically renamed when complete
- Duplicate files are skipped (checks filename match)

### Troubleshooting

**"No credentials provided" error:**
- Make sure your `.env` file exists and has correct credentials
- Or pass `--username` and `--password` directly

**Downloads not starting:**
- Check that Chrome is installed
- Verify your krdl.moe credentials are correct
- Make sure you're not already rate-limited

**Browser doesn't open:**
- Add `--headless False` to see the browser window
- Useful for debugging authentication issues

## Next Steps

- Read the [Architecture Guide](architecture.md) to understand how it works
- Check out [Tech Stack](tech-stack.md) for dependency details
- See [Contributing Guide](../CONTRIBUTING.md) for development setup

## Need Help?

- Open an issue on [GitHub](https://github.com/DouglasMacKrell/krdl-dl/issues)
- Check existing issues for similar problems
- Include error messages and your command in the issue
