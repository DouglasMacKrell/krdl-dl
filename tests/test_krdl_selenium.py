#!/usr/bin/env python3
"""Tests for krdl_selenium download completion logic (no browser)."""

import time
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

    def test_complete_after_partial_removed(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
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

    def test_completed_file_found_when_table_name_has_nbsp(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        """Scraped table text may use NBSP where Chrome uses a normal space — still detect done."""
        on_disk = "[FJ-Earthly] Rumble_01_[ABC12345].mkv"
        (tmp_path / on_disk).write_bytes(b"ok")
        info = self._info("[FJ-Earthly]\u00a0Rumble_01_[ABC12345].mkv")
        assert dl._is_download_finished(info) is True

    def test_named_partial_matches_with_nbsp_expected(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        """Named .crdownload is found when the expected basename differs only by NBSP vs space."""
        partial_path = tmp_path / "[x] y.mkv.crdownload"
        partial_path.write_bytes(b"growing")
        info = self._info("[x]\u00a0y.mkv")
        assert dl._is_download_finished(info) is False
        assert dl._named_partial_path(info["filename"]) == partial_path

    def test_not_complete_while_claimed_chrome_partial(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        fn = "episode.mkv"
        (tmp_path / "Unconfirmed 999.crdownload").write_bytes(b"growing")
        info = self._info(fn)
        info["claimed_crdownloads"] = {"Unconfirmed 999.crdownload"}
        assert dl._is_download_finished(info) is False

    def test_complete_when_mkv_appears_after_claimed_partial(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        fn = "episode.mkv"
        info = self._info(fn)
        info["claimed_crdownloads"] = {"Unconfirmed 999.crdownload"}
        assert dl._is_download_finished(info) is False
        (tmp_path / fn).write_bytes(b"done")
        assert dl._is_download_finished(info) is True


class TestAbandonStalled:
    def test_abandon_after_long_time_no_file_no_named_partial(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        job = Job(url="u", name="ghost.mkv", status="QUEUED")
        info = {
            "job": job,
            "filename": "ghost.mkv",
            "start_time": time.time() - 950,
            "url": "u",
        }
        assert dl._should_abandon_stalled_download(info) is True
        assert job.status == "FAIL"

    def test_abandon_when_claimed_crdownload_vanished(
        self, dl: KrdlSeleniumDownloader, tmp_path: Path
    ):
        job = Job(url="u", name="gone.mkv", status="QUEUED")
        info = {
            "job": job,
            "filename": "gone.mkv",
            "start_time": time.time() - 30,
            "url": "u",
            "claimed_crdownloads": {"Unconfirmed 12345.crdownload"},
            "claim_vanished_since": time.time() - 95,
        }
        assert dl._should_abandon_stalled_download(info) is True
        assert job.status == "FAIL"

    def test_abandon_frozen_named_partial(self, dl: KrdlSeleniumDownloader, tmp_path: Path):
        job = Job(url="u", name="stuck.mkv", status="QUEUED")
        p = tmp_path / "stuck.mkv.crdownload"
        p.write_bytes(b"x")
        info = {
            "job": job,
            "filename": "stuck.mkv",
            "start_time": time.time() - 10000,
            "url": "u",
            "stall_size": 1,
            "stall_since": time.time() - 500,
        }
        assert dl._should_abandon_stalled_download(info) is True
        assert job.status == "FAIL"
