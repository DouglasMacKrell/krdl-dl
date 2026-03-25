#!/usr/bin/env python3
"""Unit tests for csvdl_core (current public API)."""

import os
import tempfile
from pathlib import Path

from csvdl_core import Job, expand, extract_urls_from_text, prepare_jobs


class TestURLExtraction:
    def test_extract_urls_from_text(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write(
                """
            Some text with https://example.com/file.mkv and
            http://test.org/video.mp4 in it.
            Also https://another.com/path/mkv and https://final.com/file.mkv
            """
            )
            temp_path = f.name
        try:
            urls = extract_urls_from_text(temp_path)
            assert len(urls) == 4
            assert "https://example.com/file.mkv" in urls
            assert "http://test.org/video.mp4" in urls
            assert "https://another.com/path/mkv" in urls
            assert "https://final.com/file.mkv" in urls
        finally:
            os.unlink(temp_path)

    def test_extract_urls_keeps_duplicates(self):
        """Regex findall returns every match; deduplication is not applied."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write(
                """
            https://example.com/file.mkv
            https://example.com/file.mkv
            https://test.com/video.mp4
            """
            )
            temp_path = f.name
        try:
            urls = extract_urls_from_text(temp_path)
            assert len(urls) == 3
            assert urls.count("https://example.com/file.mkv") == 2
        finally:
            os.unlink(temp_path)


class TestPrepareJobs:
    def test_prepare_jobs_filters_by_extension_mkv(self):
        target_dir = Path(tempfile.mkdtemp())
        urls = [
            "https://krdl.moe/download/foo/mkv",
            "https://example.com/bar.mkv",
            "https://example.com/only.mp4",
        ]
        jobs = prepare_jobs(urls, "mkv", target_dir)
        assert len(jobs) == 2
        assert all(j.ext == "mkv" for j in jobs)
        assert jobs[0].url.endswith("/mkv")
        assert jobs[1].url.endswith(".mkv")

    def test_prepare_jobs_filters_mp4(self):
        target_dir = Path(tempfile.mkdtemp())
        urls = [
            "https://krdl.moe/download/foo/mp4",
            "https://example.com/x.mkv",
        ]
        jobs = prepare_jobs(urls, "mp4", target_dir)
        assert len(jobs) == 1
        assert jobs[0].url.endswith("/mp4")

    def test_prepare_jobs_all_queued(self):
        target_dir = Path(tempfile.mkdtemp())
        jobs = prepare_jobs(["https://x/y/mkv"], "mkv", target_dir)
        assert len(jobs) == 1
        assert jobs[0].status == "QUEUED"
        assert jobs[0].expected_bytes is None


class TestJob:
    def test_job_defaults(self):
        j = Job(url="https://example.com/a/mkv")
        assert j.ext == "mkv"
        assert j.status == "QUEUED"
        assert j.name is None
        assert j.out_path is None


class TestExpand:
    def test_expand_path(self):
        home = os.path.expanduser("~")
        assert expand("~/test") == os.path.join(home, "test")
        current = os.path.abspath(".")
        assert expand("test") == os.path.join(current, "test")
        abs_path = "/absolute/path"
        assert expand(abs_path) == abs_path
