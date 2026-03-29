# Contributing to krdl-dl

Thank you for your interest in contributing to krdl-dl! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Code Style](#code-style)
- [Commit Messages](#commit-messages)

## Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inclusive environment for all contributors, regardless of experience level, background, or identity.

### Expected Behavior

- Be respectful and considerate
- Welcome newcomers and help them get started
- Focus on constructive feedback
- Respect differing viewpoints and experiences

### Unacceptable Behavior

- Harassment, discrimination, or offensive comments
- Trolling or insulting/derogatory comments
- Public or private harassment
- Publishing others' private information

## Getting Started

### Prerequisites

- **Python 3.9+** (aligned with `pyproject.toml` and CI)
- Git
- Google Chrome
- GitHub account

Default integration branch is **`develop`**; **`main`** may trail or track releases. Base PRs on `develop` unless a maintainer directs otherwise.

### Finding Issues to Work On

1. Check the [Issues](https://github.com/DouglasMacKrell/krdl-dl/issues) page
2. Look for issues labeled `good first issue` or `help wanted`
3. Comment on the issue to let others know you're working on it
4. Ask questions if anything is unclear

## Development Setup

### 1. Fork and Clone

```bash
# Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/krdl-dl.git
cd krdl-dl

# Add upstream remote
git remote add upstream https://github.com/DouglasMacKrell/krdl-dl.git
```

### 2. Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies

```bash
# Install production dependencies
pip install -r requirements.txt

# Install development dependencies (pytest, pre-commit, Ruff, …)
pip install -r requirements-dev.txt

# Install git hooks (runs Ruff + checks on every commit)
pre-commit install
```

### 4. Set Up Credentials

Create a `.env` file for testing:
```bash
KRDL_USERNAME=your_test_account@example.com
KRDL_PASSWORD=your_test_password
```

**⚠️ Use a test account, not your personal account!**

### 5. Verify Setup

```bash
# Run tests
pytest

# Run the same lint/format checks as CI
pre-commit run --all-files
```

## Making Changes

### 1. Create a Branch

```bash
# Update your fork (use develop if that is the integration branch)
git checkout develop
git pull upstream develop

# Create a feature branch
git checkout -b feature/your-feature-name
```

**Branch Naming:**
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Test additions/changes

### 2. Make Your Changes

- Write clear, readable code
- Add comments for complex logic
- Update documentation if needed
- Add tests for new functionality

### 3. Test Your Changes

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_core.py

# Run with coverage (pytest-cov is in requirements-dev.txt)
pytest --cov=krdl_selenium --cov=csvdl_core --cov-report=term-missing
```

### 4. Format and Lint Your Code

```bash
# Fix issues and format (Ruff; same tooling as pre-commit)
ruff check . --fix
ruff format .

# Or run the full hook set on all files
pre-commit run --all-files
```

## Testing

### Running Tests

```bash
# All tests
pytest

# Specific test
pytest tests/test_krdl_selenium.py::TestSavedFilePath::test_exact_match

# With verbose output
pytest -v

# With coverage
pytest --cov=. --cov-report=term-missing
```

### Writing Tests

**Unit Tests:**
```python
def test_expand_path():
    """Test path expansion with tilde"""
    result = expand("~/Downloads")
    assert result.startswith("/")
    assert "Downloads" in result
```

**Integration Tests:**
```python
def test_login_flow(mocker):
    """Test complete login flow"""
    mock_session = mocker.patch('requests.Session')
    result = login_to_krdl("user@test.com", "password")
    assert result is not None
```

**Test Guidelines:**
- One test per function/behavior
- Clear, descriptive test names
- Use fixtures for setup
- Mock external dependencies
- Test edge cases and errors

## Submitting Changes

### 1. Commit Your Changes

```bash
git add .
git commit -m "feat: add new download feature"
```

See [Commit Messages](#commit-messages) for formatting guidelines.

### 2. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

### 3. Create Pull Request

1. Go to your fork on GitHub
2. Click "Pull Request"
3. Select your branch
4. Fill out the PR template:
   - Clear description of changes
   - Link to related issues
   - Screenshots if applicable
   - Testing performed

### 4. Code Review

- Address reviewer feedback promptly
- Make requested changes in new commits
- Push updates to the same branch
- Be open to suggestions

### 5. Merge

Once approved:
- Maintainer will merge your PR
- Your branch will be deleted
- Changes will appear in the next release

## Code Style

### Python Style Guide

We follow [PEP 8](https://pep8.org/) with some modifications. **Ruff** (via `pre-commit`) enforces lint rules and formatting; configuration lives in `pyproject.toml`.

**Line Length:** 100 characters (not 79), with long strings allowed where needed (`E501` ignored for pragmatism)

**Imports:**
```python
# Standard library
import os
import time

# Third-party
import requests
from selenium import webdriver

# Local
from csvdl_core import Job, expand
```

**Type Hints:**
```python
def download_file(url: str, target: Path) -> Optional[Job]:
    """Download a file from URL to target directory"""
    pass
```

**Docstrings:**
```python
def login_to_krdl(username: str, password: str) -> Optional[str]:
    """
    Login to krdl.moe and return session cookies.

    Args:
        username: User's email address
        password: User's password

    Returns:
        Cookie string if successful, None if failed

    Raises:
        RequestException: If network error occurs
    """
    pass
```

### Linting and formatting

**Ruff** (configured under `[tool.ruff]` in `pyproject.toml`):

```bash
ruff check .
ruff format .
```

On commit, **pre-commit** runs Ruff with autofix plus file hygiene hooks (trailing whitespace, YAML/TOML validation, etc.).

## Commit Messages

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Test additions/changes
- `chore`: Build process, dependencies, etc.

### Examples

**Feature:**
```
feat(downloader): add support for MP4 downloads

- Add --ext argument for file type selection
- Filter download links by extension
- Update tests for MP4 handling
```

**Bug Fix:**
```
fix(queue): prevent duplicate downloads

Fixes #123

- Check existing files before queueing
- Add case-insensitive filename comparison
- Skip files that already exist in target directory
```

**Documentation:**
```
docs(readme): update installation instructions

- Add virtual environment setup
- Clarify Python version requirement
- Add troubleshooting section
```

### Guidelines

- Use present tense ("add feature" not "added feature")
- Use imperative mood ("move cursor to..." not "moves cursor to...")
- First line ≤ 50 characters
- Body wrapped at 72 characters
- Reference issues and PRs in footer

## Questions?

- Open an issue for discussion
- Ask in pull request comments
- Check existing documentation
- Review closed issues for similar questions

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (see [LICENSE](LICENSE)).

## Thank You!

Your contributions make krdl-dl better for everyone. We appreciate your time and effort! 🎉
