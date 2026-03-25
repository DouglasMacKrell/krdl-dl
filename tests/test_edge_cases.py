#!/usr/bin/env python3
"""Edge cases for csvdl_core (no legacy curl/download pipeline)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from csvdl_core import extract_urls_from_text, prepare_jobs, scrape_krdl_page


class TestExtractUrlsEdgeCases:
    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as f:
            f.write("")
            temp_path = f.name
        try:
            assert extract_urls_from_text(temp_path) == []
        finally:
            os.unlink(temp_path)

    def test_no_urls(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as f:
            f.write("This is just text with no URLs at all.")
            temp_path = f.name
        try:
            assert extract_urls_from_text(temp_path) == []
        finally:
            os.unlink(temp_path)

    def test_mixed_valid_and_invalid(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as f:
            f.write(
                """
            https://valid.com/file.mkv
            not-a-url
            http://
            https://valid2.com/file.mp4
            """
            )
            temp_path = f.name
        try:
            urls = extract_urls_from_text(temp_path)
            assert len(urls) == 2
            assert "https://valid.com/file.mkv" in urls
            assert "https://valid2.com/file.mp4" in urls
        finally:
            os.unlink(temp_path)


class TestPrepareJobsEdgeCases:
    def test_empty_url_list(self):
        jobs = prepare_jobs([], "mkv", Path(tempfile.mkdtemp()))
        assert jobs == []

    def test_no_matching_extension(self):
        jobs = prepare_jobs(["https://x/y.mp4"], "mkv", Path(tempfile.mkdtemp()))
        assert jobs == []


class TestScrapeKrdlPage:
    """BeautifulSoup fallback scraper — network mocked."""

    HTML_ONE_LINK = """
    <html><body>
    <table>
      <tr>
        <td>file.mkv</td><td>1G</td><td>mkv</td>
        <td><a class="download" href="/download/[Show]_01_[ABC]/mkv">DL</a></td>
      </tr>
    </table>
    </body></html>
    """

    def test_scrape_extracts_absolute_download_urls(self):
        mock_resp = MagicMock()
        mock_resp.text = self.HTML_ONE_LINK
        mock_resp.raise_for_status = MagicMock()
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with patch("csvdl_core.requests.Session", return_value=mock_session):
            links = scrape_krdl_page("https://krdl.moe/show/test-show")

        assert len(links) == 1
        assert links[0].startswith("https://krdl.moe/")
        assert "/download/" in links[0]

    def test_scrape_returns_empty_on_http_error(self):
        import requests

        mock_session = MagicMock()
        mock_session.get.side_effect = requests.RequestException("network down")

        with patch("csvdl_core.requests.Session", return_value=mock_session):
            links = scrape_krdl_page("https://krdl.moe/show/x")

        assert links == []
