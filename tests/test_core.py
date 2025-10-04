#!/usr/bin/env python3
"""
Unit tests for csvdl_core module.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from csvdl_core import (
    extract_urls_from_text,
    url_matches_extension,
    infer_filename,
    prepare_jobs,
    download_job,
    Job,
    expand
)


class TestURLExtraction:
    """Test URL extraction from text files."""
    
    def test_extract_urls_from_text(self):
        """Test extracting URLs from a text file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("""
            Some text with https://example.com/file.mkv and 
            http://test.org/video.mp4 in it.
            Also https://another.com/path/mkv and https://final.com/file.mkv
            """)
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
    
    def test_extract_urls_deduplication(self):
        """Test that duplicate URLs are removed."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("""
            https://example.com/file.mkv
            https://example.com/file.mkv
            https://test.com/video.mp4
            """)
            temp_path = f.name
        
        try:
            urls = extract_urls_from_text(temp_path)
            assert len(urls) == 2
            assert urls.count("https://example.com/file.mkv") == 1
        finally:
            os.unlink(temp_path)


class TestURLMatching:
    """Test URL extension matching."""
    
    def test_url_matches_extension_direct(self):
        """Test direct extension matching."""
        assert url_matches_extension("https://example.com/file.mkv", "mkv")
        assert url_matches_extension("https://example.com/file.mp4", "mp4")
        assert not url_matches_extension("https://example.com/file.mkv", "mp4")
    
    def test_url_matches_extension_path(self):
        """Test path-based extension matching."""
        assert url_matches_extension("https://example.com/path/mkv", "mkv")
        assert url_matches_extension("https://example.com/path/mp4", "mp4")
        assert url_matches_extension("https://example.com/path/mkv?param=value", "mkv")
        assert url_matches_extension("https://example.com/path/mp4#fragment", "mp4")


class TestFilenameInference:
    """Test filename inference from URLs and headers."""
    
    def test_infer_filename_from_url(self):
        """Test filename inference from URL path."""
        headers = ""
        filename = infer_filename("https://example.com/video.mkv", headers, "mkv")
        assert filename == "video.mkv"
    
    def test_infer_filename_with_content_disposition(self):
        """Test filename inference from Content-Disposition header."""
        headers = "Content-Disposition: attachment; filename=\"download.mkv\""
        filename = infer_filename("https://example.com/stream", headers, "mkv")
        assert filename == "download.mkv"
    
    def test_infer_filename_with_redirect(self):
        """Test filename inference from redirect location."""
        headers = "Location: https://example.com/redirected/video.mkv"
        filename = infer_filename("https://example.com/redirect", headers, "mkv")
        assert filename == "video.mkv"
    
    def test_infer_filename_normalization(self):
        """Test filename normalization to desired extension."""
        headers = ""
        filename = infer_filename("https://example.com/video.mp4", headers, "mkv")
        assert filename == "video.mkv"
    
    def test_infer_filename_fallback(self):
        """Test filename fallback when no clear name is available."""
        headers = ""
        filename = infer_filename("https://example.com/mkv", headers, "mkv")
        assert filename.endswith(".mkv")
        assert "mkv" in filename


class TestJobPreparation:
    """Test job preparation and filtering."""
    
    def test_prepare_jobs_basic(self):
        """Test basic job preparation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            urls = ["https://example.com/file1.mkv", "https://example.com/file2.mp4"]
            
            # Mock the curl headers call
            with patch('csvdl_core._curl_headers') as mock_headers:
                mock_headers.return_value = "Content-Length: 1024"
                
                jobs = prepare_jobs(urls, "mkv", target_dir)
                
                # Both files should be included because the logic normalizes extensions
                assert len(jobs) == 2
                assert jobs[0].url == "https://example.com/file1.mkv"
                assert jobs[0].ext == "mkv"
                assert jobs[0].expected_bytes == 1024
                assert jobs[0].status == "QUEUED"
                assert jobs[1].url == "https://example.com/file2.mp4"
                assert jobs[1].ext == "mkv"  # Normalized to mkv
                assert jobs[1].expected_bytes == 1024
                assert jobs[1].status == "QUEUED"
    
    def test_prepare_jobs_skip_existing(self):
        """Test that existing files are skipped."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            
            # Create an existing file
            existing_file = target_dir / "existing.mkv"
            existing_file.write_text("test content")
            
            urls = ["https://example.com/existing.mkv"]
            
            with patch('csvdl_core._curl_headers') as mock_headers:
                mock_headers.return_value = "Content-Length: 1024"
                
                jobs = prepare_jobs(urls, "mkv", target_dir)
                
                assert len(jobs) == 1
                assert jobs[0].status == "SKIP"


class TestJobExecution:
    """Test job execution and progress tracking."""
    
    def test_download_job_skip(self):
        """Test that SKIP jobs are not downloaded."""
        job = Job(url="https://example.com/test.mkv", status="SKIP")
        result = download_job(job)
        assert result.status == "SKIP"
    
    @patch('csvdl_core.subprocess.Popen')
    def test_download_job_success(self, mock_popen):
        """Test successful job execution."""
        # Mock successful curl process
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc
        
        # Mock file size tracking
        with patch('csvdl_core._current_size') as mock_size:
            mock_size.side_effect = [0, 512, 1024]  # Progress simulation
            
            job = Job(url="https://example.com/test.mkv", out_path=Path("/tmp/test.mkv"))
            progress_calls = []
            
            def progress_cb(job, frac, bytes_done):
                progress_calls.append((frac, bytes_done))
            
            # Mock the process completion
            def mock_poll():
                if len(progress_calls) >= 2:  # After some progress
                    return 0  # Process completed
                return None  # Still running
            
            mock_proc.poll.side_effect = mock_poll
            
            result = download_job(job, progress_cb=progress_cb)
            
            assert result.status == "DONE"
            assert len(progress_calls) > 0  # Progress was tracked


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_expand_path(self):
        """Test path expansion."""
        # Test with tilde
        home = os.path.expanduser("~")
        assert expand("~/test") == os.path.join(home, "test")
        
        # Test with relative path
        current = os.path.abspath(".")
        assert expand("test") == os.path.join(current, "test")
        
        # Test with absolute path
        abs_path = "/absolute/path"
        assert expand(abs_path) == abs_path
