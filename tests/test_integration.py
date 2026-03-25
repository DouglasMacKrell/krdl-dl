#!/usr/bin/env python3
"""Light integration checks (no Selenium, no network)."""

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestKrdlSeleniumCLI:
    def test_help_exits_zero(self):
        script = REPO_ROOT / "krdl_selenium.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=30,
        )
        assert result.returncode == 0
        assert "--url" in result.stdout
        assert "--target" in result.stdout
