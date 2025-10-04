#!/usr/bin/env python3
"""
krdl-dl v1: Direct krdl.moe scraping and downloading.
"""
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv
from csvdl_core import expand, scrape_krdl_page, prepare_jobs, download_queue, login_to_krdl

# Load environment variables from .env file
load_dotenv()

def main():
    ap = argparse.ArgumentParser(description="krdl-dl v1 — Direct krdl.moe scraping")
    ap.add_argument("--url", required=True, help="krdl.moe page URL to scrape (e.g., https://krdl.moe/show/kyouryuu-sentai-zyuranger)")
    ap.add_argument("--target", required=True, help="Directory to save downloads")
    ap.add_argument("--ext", choices=["mkv", "mp4"], default="mkv", help="Which extension to download (default: mkv)")
    ap.add_argument("-j", "--jobs", type=int, default=2, help="Max concurrent downloads (default: 2)")
    ap.add_argument("--username", help="krdl.moe username for authentication")
    ap.add_argument("--password", help="krdl.moe password for authentication")
    args = ap.parse_args()

    target_dir = Path(expand(args.target))
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Handle authentication - use environment variables if available
    auth_cookies = None
    username = args.username or os.getenv('KRDL_USERNAME')
    password = args.password or os.getenv('KRDL_PASSWORD')
    
    if username and password:
        print(f"🔐 Logging in to krdl.moe with username: {username[:3]}***")
        auth_cookies = login_to_krdl(username, password)
        if not auth_cookies:
            print("❌ Login failed. Continuing without authentication...")
        else:
            print("✅ Login successful!")
    elif args.username or args.password:
        print("❌ Both --username and --password are required for authentication")
        return
    else:
        print("⚠️  No credentials provided - trying without authentication...")
    
    print(f"🌐 Scraping krdl.moe page: {args.url}")
    urls = scrape_krdl_page(args.url, auth_cookies)
    
    if not urls:
        print("❌ No download links found on the page")
        return
    
    print(f"📁 Preparing jobs for {args.ext} files...")
    jobs = prepare_jobs(urls, args.ext, target_dir, auth_cookies)
    
    queued_jobs = [j for j in jobs if j.status == "QUEUED"]
    skipped_jobs = [j for j in jobs if j.status == "SKIP"]
    
    print(f"📊 Jobs: {len(queued_jobs)} to download, {len(skipped_jobs)} already exist")
    
    if not queued_jobs:
        print("✅ No new downloads needed.")
        return
    
    # Use the new queue system with proper concurrency control
    completed_jobs = download_queue(queued_jobs, auth_cookies=auth_cookies, max_concurrent=2)
    
    # Summary
    successful = [j for j in completed_jobs if j.status == "DONE"]
    failed = [j for j in completed_jobs if j.status == "FAIL"]
    skipped = [j for j in completed_jobs if j.status == "SKIP"]
    
    print(f"\n📊 Download Summary:")
    print(f"  ✅ Successful: {len(successful)}")
    print(f"  ❌ Failed: {len(failed)}")
    print(f"  ⏭️  Skipped: {len(skipped)}")

if __name__ == "__main__":
    main()
