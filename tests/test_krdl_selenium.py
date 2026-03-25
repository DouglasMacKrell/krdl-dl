#!/usr/bin/env python3
"""Tests for krdl_selenium download completion logic (no browser)."""

from pathlib import Path

import pytest

from csvdl_core import Job
from krdl_selenium import KrdlSeleniumDownloader


@pytest.fixture
def dl(tmp_path: Path) -> KrdlSeleniumDownloader:
    return KrdlSeleniumDownloader(tmp_path, headless=True)


class TestSavedFilePath:
    def test_exact_match(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        name = "Episode_01.mkv"
        p = tmp_path / name
        p.write_bytes(b"x")
        assert dl._saved_file_path(name) == p

    def test_case_insensitive_basename(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        (tmp_path / "Episode_01.MKV").write_bytes(b"data")
        found = dl._saved_file_path("episode_01.mkv")
        assert found is not None
        assert found.name.lower() == "episode_01.mkv"

    def test_missing_returns_none(self, dl: KrdlSeleniumDownloader):
        assert dl._saved_file_path("nope.mkv") is None


class TestNamedPartialPath:
    def test_exact_crdownload(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        fn = "Show_01.mkv"
        partial = tmp_path / f"{fn}.crdownload"
        partial.write_bytes(b"partial")
        assert dl._named_partial_path(fn) == partial

    def test_case_insensitive_crdownload(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        (tmp_path / "Show_01.MKV.crdownload").write_bytes(b"p")
        found = dl._named_partial_path("show_01.mkv")
        assert found is not None
        assert found.name.lower().endswith(".mkv.crdownload")


class TestIsDownloadFinished:
    def _info(self, filename: str) -> dict:
        return {
            "filename": filename,
            "job": Job(url="https://example.com/x/mkv", name=filename),
            "start_time": 0.0,
            "url": "https://example.com/x/mkv",
        }

    def test_complete_when_file_present(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        fn = "done.mkv"
        (tmp_path / fn).write_bytes(b"12345")
        info = self._info(fn)
        assert dl._is_download_finished(info) is True
        assert "completed" in info

    def test_not_complete_while_partial(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        fn = "busy.mkv"
        (tmp_path / f"{fn}.crdownload").write_bytes(b"growing")
        info = self._info(fn)
        assert dl._is_download_finished(info) is False

    def test_complete_after_partial_removed(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        """Second folder check: file appears when no named .crdownload."""
        fn = "late.mkv"
        info = self._info(fn)
        assert dl._is_download_finished(info) is False
        (tmp_path / fn).write_bytes(b"done")
        assert dl._is_download_finished(info) is True

    def test_final_file_wins_if_partial_still_present(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        """If the .mkv exists, we are done even if a stale .crdownload remains."""
        fn = "x.mkv"
        (tmp_path / fn).write_bytes(b"full")
        (tmp_path / f"{fn}.crdownload").write_bytes(b"stale")
        info = self._info(fn)
        assert dl._is_download_finished(info) is True
