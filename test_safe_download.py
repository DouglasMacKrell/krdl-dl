#!/usr/bin/env python3
"""
Safe test script - only downloads 2 files to test the new queue system
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from csvdl_core import expand, scrape_krdl_page, prepare_jobs, download_queue, login_to_krdl

# Load environment variables from .env file
load_dotenv()

def main():
    print("🧪 Testing safe download with new queue system...")
    print("⚠️  This will only download 2 files to test the system")
    
    target_dir = Path(expand("./test_downloads"))
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Handle authentication
    auth_cookies = None
    username = os.getenv('KRDL_USERNAME')
    password = os.getenv('KRDL_PASSWORD')
    
    if username and password:
        print(f"🔐 Logging in to krdl.moe with username: {username[:3]}***")
        auth_cookies = login_to_krdl(username, password)
        if not auth_cookies:
            print("❌ Login failed. Exiting...")
            return
        else:
            print("✅ Login successful!")
    else:
        print("❌ No credentials found. Exiting...")
        return
    
    # Scrape the page
    print(f"🌐 Scraping krdl.moe page...")
    download_urls = scrape_krdl_page("https://krdl.moe/show/kyouryuu-sentai-zyuranger", auth_cookies)
    
    if not download_urls:
        print("❌ No download links found on the page")
        return
    
    print(f"📁 Preparing jobs for mkv files...")
    jobs = prepare_jobs(download_urls, "mkv", target_dir, auth_cookies)
    
    # Only take the first 2 jobs for testing
    test_jobs = jobs[:2]
    print(f"🧪 Testing with only {len(test_jobs)} files...")
    
    # Use the new queue system
    completed_jobs = download_queue(test_jobs, auth_cookies=auth_cookies, max_concurrent=2)
    
    # Summary
    successful = [j for j in completed_jobs if j.status == "DONE"]
    failed = [j for j in completed_jobs if j.status == "FAIL"]
    skipped = [j for j in completed_jobs if j.status == "SKIP"]
    
    print(f"\n📊 Test Results:")
    print(f"  ✅ Successful: {len(successful)}")
    print(f"  ❌ Failed: {len(failed)}")
    print(f"  ⏭️  Skipped: {len(skipped)}")
    
    if failed:
        print(f"\n❌ Failed downloads:")
        for job in failed:
            print(f"  - {job.name}: {job.message}")

if __name__ == "__main__":
    main()
