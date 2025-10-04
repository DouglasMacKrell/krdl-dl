#!/usr/bin/env python3
"""
Plain CLI for CSV bulk downloads (uses csvdl_core).
"""
import argparse
from pathlib import Path
from csvdl_core import expand, extract_urls_from_text, prepare_jobs, download_job

def main():
    ap = argparse.ArgumentParser(description="CSV Bulk Downloader — CLI")
    ap.add_argument("--csv", required=True, help="Path to CSV/text file with URLs")
    ap.add_argument("--target", required=True, help="Directory to save downloads")
    ap.add_argument("--ext", choices=["mkv", "mp4"], default="mkv", help="Which extension to download (default: mkv)")
    ap.add_argument("-j", "--jobs", type=int, default=2, help="Max concurrent downloads (default: 2)")
    args = ap.parse_args()

    target_dir = Path(expand(args.target))
    target_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Extracting URLs from {args.csv}...")
    urls = extract_urls_from_text(args.csv)
    print(f"Found {len(urls)} URLs")
    
    print(f"Preparing jobs for {args.ext} files...")
    jobs = prepare_jobs(urls, args.ext, target_dir)
    
    queued_jobs = [j for j in jobs if j.status == "QUEUED"]
    skipped_jobs = [j for j in jobs if j.status == "SKIP"]
    
    print(f"Jobs: {len(queued_jobs)} to download, {len(skipped_jobs)} already exist")
    
    if not queued_jobs:
        print("No new downloads needed.")
        return
    
    print(f"Starting downloads with {args.jobs} concurrent workers...")
    
    # Simple sequential download for now
    for i, job in enumerate(queued_jobs, 1):
        print(f"[{i}/{len(queued_jobs)}] Downloading {job.name}...")
        
        def progress_cb(job, frac, bytes_done):
            if job.expected_bytes:
                percent = int(frac * 100)
                print(f"  Progress: {percent}% ({bytes_done}/{job.expected_bytes} bytes)")
        
        result = download_job(job, progress_cb=progress_cb)
        if result.status == "DONE":
            print(f"  ✓ Completed: {result.name}")
        else:
            print(f"  ✗ Failed: {result.name} - {result.message}")

if __name__ == "__main__":
    main()
