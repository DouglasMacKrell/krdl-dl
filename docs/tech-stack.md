# Tech Stack & Dependencies

Complete overview of the technologies, libraries, and tools used in krdl-dl.

## Core Technologies

### Python 3.8+

**Why Python?**
- Excellent web scraping ecosystem
- Rich library support for automation
- Easy to read and maintain
- Cross-platform compatibility

**Version Requirement:** Python 3.8 or higher
- Uses modern type hints (Optional, List, etc.)
- Dataclasses (Python 3.7+)
- f-strings for formatting

### Google Chrome

**Why Chrome?**
- Most reliable Selenium support
- Built-in download manager
- Developer tools for debugging
- Wide availability across platforms

**Alternatives Considered:**
- Firefox: Less reliable download handling
- Safari: Limited automation support
- Edge: Similar to Chrome but less common

## Dependencies

### Production Dependencies

#### Selenium (>=4.15.0)

**Purpose:** Browser automation and web scraping

**Key Features Used:**
- WebDriver for Chrome control
- Element finding (By.CSS_SELECTOR, By.XPATH)
- Wait conditions (WebDriverWait, EC)
- Page navigation and interaction

**Example Usage:**
```python
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = webdriver.Chrome(options=chrome_options)
element = driver.find_element(By.CSS_SELECTOR, "a.download")
wait = WebDriverWait(driver, 10)
wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
```

**Why Selenium 4?**
- Improved stability
- Better error messages
- Native support for Chrome DevTools Protocol
- Relative locators

#### webdriver-manager (>=4.0.0)

**Purpose:** Automatic ChromeDriver management

**Key Features:**
- Auto-downloads correct ChromeDriver version
- Matches installed Chrome version
- Caches drivers locally
- Cross-platform support

**Example Usage:**
```python
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service)
```

**Why This Matters:**
- ✅ No manual ChromeDriver downloads
- ✅ Always compatible with user's Chrome
- ✅ Automatic updates
- ✅ Works on any OS

#### requests (>=2.31.0)

**Purpose:** HTTP requests for authentication and fallback scraping

**Key Features Used:**
- Session management
- Cookie handling
- POST requests (login forms)
- Custom headers

**Example Usage:**
```python
import requests

session = requests.Session()
response = session.post(login_url, data=login_data, headers=headers)
cookies = session.cookies
```

**Why requests?**
- Industry standard for HTTP in Python
- Excellent session management
- Simple, intuitive API
- Robust error handling

#### BeautifulSoup4 (>=4.12.0)

**Purpose:** HTML parsing for fallback scraper

**Key Features Used:**
- HTML parsing
- CSS selector support
- Tag finding and navigation
- Text extraction

**Example Usage:**
```python
from bs4 import BeautifulSoup

soup = BeautifulSoup(html, 'html.parser')
tables = soup.find_all('table')
links = table.find_all('a', class_='download')
```

**Why BeautifulSoup?**
- Most popular Python HTML parser
- Forgiving of malformed HTML
- Multiple parser backends
- Excellent documentation

#### python-dotenv (>=1.0.0)

**Purpose:** Environment variable management

**Key Features:**
- Load variables from `.env` file
- Override system environment
- Type conversion support

**Example Usage:**
```python
from dotenv import load_dotenv
import os

load_dotenv()
username = os.getenv('KRDL_USERNAME')
password = os.getenv('KRDL_PASSWORD')
```

**Why dotenv?**
- ✅ Keeps secrets out of code
- ✅ Easy local development
- ✅ Standard practice for credentials
- ✅ .env file gitignored by default

### Development Dependencies

#### pytest (>=7.0.0)

**Purpose:** Testing framework

**Key Features:**
- Simple test writing
- Fixtures for setup/teardown
- Parametrized tests
- Rich assertion introspection

**Example Usage:**
```python
import pytest

def test_login_success():
    result = login_to_krdl("user@example.com", "password")
    assert result is not None

@pytest.fixture
def mock_driver():
    driver = Mock()
    yield driver
    driver.quit()
```

**Why pytest?**
- Most popular Python testing framework
- Less boilerplate than unittest
- Excellent plugin ecosystem
- Great error messages

#### pytest-asyncio (>=0.21.0)

**Purpose:** Async test support

**Usage:** Future-proofing for async operations

**Example:**
```python
@pytest.mark.asyncio
async def test_async_download():
    result = await async_download_file(url)
    assert result.status == "DONE"
```

#### pytest-mock (>=3.10.0)

**Purpose:** Mocking and patching in tests

**Key Features:**
- Mock objects and functions
- Spy on calls
- Patch imports
- Assertion helpers

**Example Usage:**
```python
def test_download_with_mock(mocker):
    mock_driver = mocker.patch('selenium.webdriver.Chrome')
    mock_driver.return_value.current_url = "https://krdl.moe/"
    
    result = download_file(url)
    assert mock_driver.called
```

## Future Dependencies

### Planned Additions

#### textual (>=0.58)

**Purpose:** Modern TUI (Text User Interface)

**Features:**
- Rich terminal UI
- Real-time progress bars
- Interactive widgets
- Responsive layout

**Status:** Commented out in requirements.txt, will be added when TUI is implemented.

#### rich (>=13.7)

**Purpose:** Rich terminal formatting

**Features:**
- Progress bars
- Tables
- Syntax highlighting
- Markdown rendering

**Status:** Commented out, will be added with TUI.

## System Requirements

### Operating Systems

**Supported:**
- ✅ macOS 10.15+
- ✅ Linux (Ubuntu 20.04+, Debian 10+, etc.)
- ✅ Windows 10+

**Requirements:**
- Python 3.8+ installed
- Google Chrome installed
- Internet connection
- ~500MB disk space for dependencies

### Hardware Requirements

**Minimum:**
- 2GB RAM
- 1GB free disk space (for downloads)
- Dual-core processor

**Recommended:**
- 4GB+ RAM
- 10GB+ free disk space
- Quad-core processor
- SSD for faster file operations

## Development Tools

### Version Control

**Git:** Source code management
- Branch-based workflow
- Conventional commits
- Pull request reviews

**GitHub:** Remote repository and CI/CD
- Issue tracking
- GitHub Actions for CI
- Release management

### Code Quality

**Pre-commit Hooks:** (Planned)
- Code formatting (black)
- Linting (flake8, pylint)
- Type checking (mypy)
- Import sorting (isort)

**CI/CD:** (Planned)
- Automated testing on push
- Multi-OS testing (Linux, macOS, Windows)
- Code coverage reporting
- Automated releases

### Documentation

**Markdown:** Documentation format
- Easy to read and write
- GitHub rendering
- Version controlled

**Docstrings:** In-code documentation
- Google-style docstrings
- Type hints
- Usage examples

## Dependency Management

### Installation

**pip:** Package installer
```bash
pip install -r requirements.txt
```

**Virtual Environment:** Isolation
```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows
```

### Version Pinning

**Strategy:** Minimum version requirements
- `>=` allows patch updates
- Avoids breaking changes
- Balances security and stability

**Example:**
```
selenium>=4.15.0  # Allows 4.15.1, 4.16.0, etc.
```

### Security Updates

**Process:**
1. Dependabot alerts for vulnerabilities
2. Review and test updates
3. Update requirements.txt
4. Run full test suite
5. Commit and deploy

## Browser Compatibility

### ChromeDriver Versions

**Automatic Management:** webdriver-manager handles versioning

**Compatibility Matrix:**
| Chrome Version | ChromeDriver Version | Status |
|---------------|---------------------|--------|
| 120.x | 120.x | ✅ Tested |
| 121.x | 121.x | ✅ Tested |
| 140.x | 140.x | ✅ Current |

### Browser Options

**Configured Options:**
```python
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920,1080")
```

**Why These Options?**
- Avoid automation detection
- Improve stability in containers
- Consistent window size
- Better performance

## Performance Considerations

### Memory Usage

**Typical Usage:**
- Chrome: ~200-300MB
- Python: ~50-100MB
- Total: ~250-400MB

**Peak Usage:**
- During downloads: +500MB per concurrent download
- Large series: Up to 1-2GB total

### Network Usage

**Bandwidth:**
- Scraping: Minimal (<1MB)
- Downloads: 400kbps per file (site limit)
- Total: ~800kbps for 2 concurrent downloads

**Data Transfer:**
- Typical episode: 200-300MB
- Full series (50 episodes): 10-15GB
- Misc files: 50-700MB each

## Troubleshooting

### Common Issues

**ChromeDriver version mismatch:**
```bash
# Clear webdriver-manager cache
rm -rf ~/.wdm/
```

**Import errors:**
```bash
# Reinstall dependencies
pip install --force-reinstall -r requirements.txt
```

**Selenium errors:**
```bash
# Update Chrome to latest version
# Restart terminal/IDE
# Check Chrome is in PATH
```

## Resources

### Official Documentation

- [Selenium Docs](https://www.selenium.dev/documentation/)
- [Python Docs](https://docs.python.org/3/)
- [pytest Docs](https://docs.pytest.org/)
- [BeautifulSoup Docs](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)

### Community Resources

- [Selenium Python Bindings](https://selenium-python.readthedocs.io/)
- [Real Python Tutorials](https://realpython.com/)
- [Stack Overflow](https://stackoverflow.com/questions/tagged/selenium)

### Related Projects

- [youtube-dl](https://github.com/ytdl-org/youtube-dl) - Video downloader
- [gallery-dl](https://github.com/mikf/gallery-dl) - Image gallery downloader
- [scrapy](https://scrapy.org/) - Web scraping framework
