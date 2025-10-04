# krdl-dl

A Python application for bulk downloading video files from krdl.moe, with both CLI and TUI interfaces. Currently supports CSV-based downloads with plans for direct site scraping in v1.

## Current Features (MVP)

- **CSV-Based Downloads**: Extract URLs from user-generated CSV files and download them in parallel
- **Video File Filtering**: Filter downloads by video file extension (mkv, mp4)
- **Resume Support**: Automatically resume interrupted downloads using curl's `-C -` flag
- **Progress Tracking**: Real-time progress updates based on file size vs expected content length
- **Dual Interface**: Both command-line (CLI) and text-based user interface (TUI) options
- **Concurrent Downloads**: Configurable parallelism for faster downloads
- **Smart Filename Inference**: Automatically infer filenames from Content-Disposition headers, redirects, or URL paths
- **Skip Existing**: Automatically skip files that already exist

## Planned Features (v1)

- **Direct Site Scraping**: Automatically scrape krdl.moe pages to extract video download links
- **Table-Based Link Extraction**: Parse structured table data from krdl.moe pages for video files
- **Simplified Interface**: Just provide target directory, optional video file type override, and krdl.moe URL
- **Automatic CSV Generation**: Generate CSV internally from scraped video links
- **Enhanced Link Detection**: Specialized parsing for krdl.moe's video file structure

## Installation

1. Clone or download the project files
2. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Current Usage (MVP - CSV Required)

#### TUI (Recommended)

The TUI provides a visual interface with progress bars and status updates:

```bash
python3 csvdl_tui.py \
  --csv "/path/to/your/krdl_urls.csv" \
  --target "/path/to/download/directory" \
  --ext mkv \
  -j 2
```

**TUI Controls:**
- `Enter` = Start downloads
- `P` = Pause (stops after current downloads finish)
- `Q` = Quit

#### CLI (Command Line)

For scripted or automated usage:

```bash
python3 csvdl.py \
  --csv "/path/to/your/krdl_urls.csv" \
  --target "/path/to/download/directory" \
  --ext mkv \
  -j 2
```

#### Parameters

- `--csv`: Path to CSV/text file containing krdl.moe URLs
- `--target`: Directory to save downloaded files
- `--ext`: Video file extension to download (mkv, mp4)
- `-j, --jobs`: Number of concurrent downloads (default: 2)

### Planned Usage (v1 - Direct Site Scraping)

```bash
# Future v1 interface - direct krdl.moe URL
python3 krdl_dl.py \
  --url "https://krdl.moe/series/super-sentai" \
  --target "/path/to/download/directory" \
  --ext mkv \
  -j 2
```

## CSV Format (Current MVP)

The CSV file should contain krdl.moe video URLs, one per line or separated by commas. The application will automatically extract HTTP/HTTPS URLs from the text:

```
https://krdl.moe/download/series1-episode1.mkv
https://krdl.moe/download/series1-episode2.mkv
https://krdl.moe/download/series1-episode3.mp4
```

**Note**: In v1, this CSV generation will be automated by scraping the krdl.moe page directly for video files.

## Testing

The project includes comprehensive tests covering:

- **Unit Tests**: Core functionality, URL extraction, filename inference, job preparation
- **Integration Tests**: End-to-end CLI and TUI functionality
- **Edge Case Tests**: Error handling, network failures, malformed URLs, empty files

Run tests with:
```bash
python -m pytest tests/ -v
```

### Test Coverage

- ✅ URL extraction from various text formats
- ✅ File extension matching and filtering
- ✅ Filename inference from headers, redirects, and URLs
- ✅ Job preparation and status management
- ✅ Download execution with progress tracking
- ✅ Error handling and network failure scenarios
- ✅ Concurrent download management
- ✅ Resume functionality for interrupted downloads
- ✅ Skip existing files
- ✅ CLI and TUI interface testing

## Architecture

### Core Components

1. **`csvdl_core.py`**: Core download logic and utilities
   - URL extraction and filtering
   - Filename inference
   - Job management
   - Download execution with curl

2. **`csvdl_tui.py`**: Textual-based TUI interface
   - Visual progress tracking
   - Interactive controls
   - Real-time status updates

3. **`csvdl.py`**: Command-line interface
   - Simple CLI for automation
   - Progress reporting
   - Batch processing

### Key Features

- **Resume Support**: Uses curl's `-C -` flag to resume partial downloads
- **Progress Tracking**: Monitors file size on disk vs expected Content-Length
- **Smart Filtering**: Filters URLs by extension and normalizes filenames
- **Concurrent Downloads**: Configurable parallelism with asyncio
- **Error Handling**: Graceful handling of network errors and timeouts

## Dependencies

- `textual>=0.58`: TUI framework
- `rich>=13.7`: Rich text and progress display
- `pytest>=7.0.0`: Testing framework
- `pytest-asyncio>=0.21.0`: Async testing support
- `pytest-mock>=3.10.0`: Mocking utilities

## Notes

- Resume support is handled by curl's `-C -` flag; partial files are reused
- Filename inference handles `/mkv` path style and normalizes `.mkv/.mp4`
- If you prefer to avoid curl dependency, the code can be migrated to aiohttp for pure-Python streaming
- The application follows redirects and retries failed downloads automatically

## Development Roadmap

### v1 (Next Release)
- **Direct krdl.moe Scraping**: Parse krdl.moe pages to extract download links automatically
- **Table Structure Parsing**: Handle krdl.moe's specific table layout for link extraction
- **Simplified Interface**: Just provide target directory, optional file type, and krdl.moe URL
- **Automatic CSV Generation**: Generate CSV internally from scraped links
- **Enhanced Link Detection**: Specialized parsing for krdl.moe's page structure

### Future Enhancements
- Parallelism throttle control from within the TUI
- Per-file error logs and "retry failed" action
- pyproject.toml for pipx installation as a global tool
- Pure Python download implementation (aiohttp) as an alternative to curl
- Support for other similar sites with table-based link structures
