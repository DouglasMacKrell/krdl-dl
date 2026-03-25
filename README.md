# krdl-dl

A Selenium-based automated downloader for krdl.moe (tokusatsu media archive). Download complete series with proper authentication, rate limiting, and queue management.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/DouglasMacKrell/krdl-dl/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/DouglasMacKrell/krdl-dl/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## ✨ Features

- 🔐 **Authenticated Downloads**: Secure login with krdl.moe credentials
- 🌐 **Direct Site Scraping**: Automatically extracts all download links from show pages
- 📊 **Smart Pagination**: Handles "Show All" to get complete episode lists (50+ episodes)
- 🎯 **Extension Filtering**: Download only MKV or MP4 files
- ⚡ **Queue Management**: Respects site's 2-concurrent download limit
- 🔄 **Duplicate Detection**: Skips existing files automatically
- 📈 **Progress Monitoring**: Real-time download status tracking
- 🛡️ **Rate Limit Handling**: Gracefully stops on rate limit detection
- 🧪 **Testing Support**: `--limit` flag for testing without full downloads

## 📚 Documentation

### Quick Links

- **[Quickstart Guide](docs/quickstart.md)** - Get started in 5 minutes
- **[Architecture & Design](docs/architecture.md)** - How it works and why
- **[Tech Stack](docs/tech-stack.md)** - Dependencies and tools
- **[Contributing Guide](CONTRIBUTING.md)** - How to contribute

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/DouglasMacKrell/krdl-dl.git
cd krdl-dl

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up credentials
echo "KRDL_USERNAME=your_email@example.com" > .env
echo "KRDL_PASSWORD=your_password" >> .env
```

### Basic Usage

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/kyouryuu-sentai-zyuranger" \
  --target "/path/to/downloads" \
  --ext mkv
```

## 📖 Usage Examples

### Download a Complete Series

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/kyouryuu-sentai-zyuranger" \
  --target "~/Downloads/Super Sentai/Season 16" \
  --ext mkv
```

### Download Only MP4 Files

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/choujin-sentai-jetman" \
  --target "~/Downloads/Super Sentai/Season 15" \
  --ext mp4
```

### Test with Limited Downloads

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/kyouryuu-sentai-zyuranger" \
  --target "~/Downloads/test" \
  --ext mkv \
  --limit 3
```

### Use Headless Mode

```bash
python3 krdl_selenium.py \
  --url "https://krdl.moe/show/kyouryuu-sentai-zyuranger" \
  --target "~/Downloads/Super Sentai/Season 16" \
  --ext mkv \
  --headless
```

## 🎮 Command-Line Arguments

| Argument | Required | Description | Default |
|----------|----------|-------------|---------|
| `--url` | ✅ | URL of the krdl.moe show page | - |
| `--target` | ✅ | Directory to save downloads | - |
| `--ext` | ❌ | File extension (`mkv` or `mp4`) | `mkv` |
| `--limit` | ❌ | Limit number of downloads (testing) | None |
| `--username` | ❌ | krdl.moe username (overrides .env) | From .env |
| `--password` | ❌ | krdl.moe password (overrides .env) | From .env |
| `--headless` | ❌ | Run browser in headless mode | False |

## ⚙️ How It Works

1. **🔐 Login**: Authenticates with krdl.moe using Selenium
2. **🌐 Navigate**: Goes to the show page
3. **📊 Paginate**: Clicks "All" to show all episodes (not just 25)
4. **🔍 Scrape**: Extracts download links from tables
5. **🎯 Filter**: Keeps only your chosen extension (mkv/mp4)
6. **✅ Dedupe**: Checks target directory, skips existing files
7. **⚡ Queue**: Downloads 2 files concurrently (respects site limits)
8. **📈 Monitor**: Tracks `.crdownload` files for completion
9. **✨ Complete**: Files appear in your target directory

## ⚠️ Important Notes

### Rate Limiting

krdl.moe enforces strict limits for free users:

- **400kbps** per file download speed
- **2 concurrent downloads** maximum
- **~5 minutes** per episode (typical size)

**The downloader automatically respects these limits!**

### What Happens on Rate Limit

If you exceed limits, krdl.moe redirects to `/premium` or `/register`:

```
🚨 RATE LIMIT DETECTED - STOPPING DOWNLOADS
⏰ Wait 15 minutes before retrying
```

The downloader gracefully stops to protect your account.

## 📦 Requirements

- **Python 3.9+**
- **Google Chrome** (latest version)
- **krdl.moe account** (free or premium)
- **~500MB disk space** for dependencies
- **Internet connection**

## 🧪 Testing

```bash
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run specific file
pytest tests/test_krdl_selenium.py

# Lint & format (same as CI pre-commit)
pre-commit run --all-files
```

Pull requests run **[GitHub Actions](https://github.com/DouglasMacKrell/krdl-dl/actions)** (`pre-commit` + `pytest` on Python 3.9, 3.11, and 3.12).

## 🏗️ Project Structure

```
krdl-dl/
├── krdl_selenium.py      # Main Selenium downloader
├── csvdl_core.py         # Shared utilities (Job, login, etc.)
├── pyproject.toml        # pytest + Ruff configuration
├── requirements.txt      # Runtime dependencies
├── requirements-dev.txt  # Dev tools (pre-commit, pytest, Ruff)
├── .pre-commit-config.yaml
├── .github/workflows/    # CI
├── .env                  # Credentials (gitignored)
├── docs/                 # Documentation
│   ├── quickstart.md
│   ├── architecture.md
│   └── tech-stack.md
├── tests/                # Test suite
│   ├── test_core.py
│   ├── test_krdl_selenium.py
│   ├── test_integration.py
│   └── test_edge_cases.py
├── CONTRIBUTING.md       # Contribution guidelines
├── LICENSE               # MIT License
└── README.md             # This file
```

## 🛠️ Tech Stack

- **[Selenium](https://www.selenium.dev/)** - Browser automation
- **[webdriver-manager](https://github.com/SergeyPirogov/webdriver_manager)** - ChromeDriver management
- **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/)** - HTML parsing
- **[requests](https://requests.readthedocs.io/)** - HTTP client
- **[python-dotenv](https://github.com/theskumar/python-dotenv)** - Environment variables
- **[pytest](https://pytest.org/)** - Testing framework
- **[Ruff](https://github.com/astral-sh/ruff)** - Lint & format
- **[pre-commit](https://pre-commit.com/)** - Git hooks for consistent quality

See [Tech Stack Documentation](docs/tech-stack.md) for details.

## 🗺️ Roadmap

### Current (v1.0)

- ✅ Selenium-based downloader
- ✅ Authentication & session management
- ✅ Direct site scraping
- ✅ Queue management
- ✅ Rate limit handling
- ✅ Comprehensive documentation
- ✅ Pre-commit (Ruff + hygiene hooks) and GitHub Actions CI

### Planned (v1.1)

- 🔲 Modern TUI with real-time progress
- 🔲 Multi-OS testing (Linux, macOS, Windows)

### Future (v2.0)

- 🔲 Resume capability (save/restore state)
- 🔲 Batch processing (multiple series)
- 🔲 Smart retry with exponential backoff
- 🔲 Bandwidth monitoring
- 🔲 Download scheduling

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Quick Contribution Steps

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run `pre-commit run --all-files` and `pytest`
5. Commit your changes (`git commit -m 'feat: add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **krdl.moe** - For providing an amazing tokusatsu archive
- **Selenium** - For making browser automation possible
- **Python Community** - For excellent libraries and tools

## 📧 Support

- **Issues**: [GitHub Issues](https://github.com/DouglasMacKrell/krdl-dl/issues)
- **Discussions**: [GitHub Discussions](https://github.com/DouglasMacKrell/krdl-dl/discussions)
- **Email**: [Your email if you want to provide it]

## ⚖️ Legal

This tool is for **personal use only**. Please respect krdl.moe's terms of service and rate limits. Do not use this tool to:

- Redistribute downloaded content
- Circumvent premium membership benefits
- Overload the site's servers
- Violate copyright laws

**Use responsibly and support the creators!** 🎬
