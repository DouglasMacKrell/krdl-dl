#!/usr/bin/env python3
"""
Test runner script for the CSV downloader application.
"""
import subprocess
import sys
from pathlib import Path

def run_tests():
    """Run all tests and display results."""
    print("🧪 Running CSV Downloader Tests")
    print("=" * 50)
    
    # Check if we're in a virtual environment
    if not hasattr(sys, 'real_prefix') and not (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("⚠️  Warning: Not running in a virtual environment")
        print("   Consider running: python3 -m venv .venv && source .venv/bin/activate")
        print()
    
    # Run pytest
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"
        ], check=True, capture_output=False)
        
        print("\n✅ All tests passed!")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Tests failed with exit code {e.returncode}")
        return False
    except FileNotFoundError:
        print("❌ pytest not found. Please install dependencies:")
        print("   pip install -r requirements.txt")
        return False

def run_specific_test(test_name):
    """Run a specific test."""
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest", f"tests/{test_name}", "-v"
        ], check=True)
        return True
    except subprocess.CalledProcessError:
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Run specific test
        test_name = sys.argv[1]
        success = run_specific_test(test_name)
    else:
        # Run all tests
        success = run_tests()
    
    sys.exit(0 if success else 1)
