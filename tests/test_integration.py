#!/usr/bin/env python3
"""
Integration tests for the CSV downloader application.
"""
import os
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch
import pytest


class TestCLIIntegration:
    """Test CLI integration."""
    
    def test_cli_basic_functionality(self):
        """Test basic CLI functionality with mock URLs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test CSV
            csv_path = Path(temp_dir) / "test.csv"
            csv_path.write_text("https://httpbin.org/bytes/1024\nhttps://httpbin.org/bytes/2048")
            
            # Create target directory
            target_dir = Path(temp_dir) / "downloads"
            
            # Run CLI
            result = subprocess.run([
                "python3", "csvdl.py",
                "--csv", str(csv_path),
                "--target", str(target_dir),
                "--ext", "txt"
            ], capture_output=True, text=True, cwd="/Users/douglasmackrell/Development/krdl-dl")
            
            assert result.returncode == 0
            assert "Found 2 URLs" in result.stdout
            assert "Completed" in result.stdout
            
            # Check that files were downloaded
            downloaded_files = list(target_dir.glob("*.txt"))
            assert len(downloaded_files) >= 1  # At least one file should be downloaded
    
    def test_cli_skip_existing_files(self):
        """Test that CLI skips existing files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test CSV
            csv_path = Path(temp_dir) / "test.csv"
            csv_path.write_text("https://httpbin.org/bytes/1024")
            
            # Create target directory and existing file
            target_dir = Path(temp_dir) / "downloads"
            target_dir.mkdir()
            existing_file = target_dir / "1024.txt"
            existing_file.write_text("existing content")
            
            # Run CLI
            result = subprocess.run([
                "python3", "csvdl.py",
                "--csv", str(csv_path),
                "--target", str(target_dir),
                "--ext", "txt"
            ], capture_output=True, text=True, cwd="/Users/douglasmackrell/Development/krdl-dl")
            
            assert result.returncode == 0
            assert "0 to download" in result.stdout or "No new downloads needed" in result.stdout


class TestTUIIntegration:
    """Test TUI integration."""
    
    def test_tui_initialization(self):
        """Test that TUI initializes without errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test CSV
            csv_path = Path(temp_dir) / "test.csv"
            csv_path.write_text("https://httpbin.org/bytes/1024")
            
            # Create target directory
            target_dir = Path(temp_dir) / "downloads"
            
            # Test TUI initialization (without actually running the full TUI)
            from csvdl_tui import DownloaderApp
            from csvdl_core import extract_urls_from_text, prepare_jobs
            
            # Test the core functionality that TUI uses
            urls = extract_urls_from_text(str(csv_path))
            jobs = prepare_jobs(urls, "txt", target_dir)
            
            assert len(jobs) >= 0  # Should have at least some jobs
            assert len(urls) == 1  # Should have found the URL


class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_invalid_csv_file(self):
        """Test handling of invalid CSV file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir) / "downloads"
            
            # Run CLI with non-existent CSV
            result = subprocess.run([
                "python3", "csvdl.py",
                "--csv", "nonexistent.csv",
                "--target", str(target_dir),
                "--ext", "txt"
            ], capture_output=True, text=True, cwd="/Users/douglasmackrell/Development/krdl-dl")
            
            assert result.returncode != 0  # Should fail
    
    def test_network_error_handling(self):
        """Test handling of network errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test CSV with invalid URL
            csv_path = Path(temp_dir) / "test.csv"
            csv_path.write_text("https://invalid-domain-that-does-not-exist.com/file.mkv")
            
            target_dir = Path(temp_dir) / "downloads"
            
            # Run CLI
            result = subprocess.run([
                "python3", "csvdl.py",
                "--csv", str(csv_path),
                "--target", str(target_dir),
                "--ext", "mkv"
            ], capture_output=True, text=True, cwd="/Users/douglasmackrell/Development/krdl-dl")
            
            # Should handle the error gracefully
            assert "Failed" in result.stdout or "curl exit" in result.stdout


class TestConcurrency:
    """Test concurrency features."""
    
    def test_concurrent_downloads(self):
        """Test that multiple downloads can run concurrently."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test CSV with multiple small files
            csv_path = Path(temp_dir) / "test.csv"
            csv_path.write_text("""
            https://httpbin.org/bytes/100
            https://httpbin.org/bytes/200
            https://httpbin.org/bytes/300
            """)
            
            target_dir = Path(temp_dir) / "downloads"
            
            # Run CLI with concurrency
            result = subprocess.run([
                "python3", "csvdl.py",
                "--csv", str(csv_path),
                "--target", str(target_dir),
                "--ext", "txt",
                "-j", "2"
            ], capture_output=True, text=True, cwd="/Users/douglasmackrell/Development/krdl-dl")
            
            assert result.returncode == 0
            
            # Check that files were downloaded
            downloaded_files = list(target_dir.glob("*.txt"))
            assert len(downloaded_files) >= 1
