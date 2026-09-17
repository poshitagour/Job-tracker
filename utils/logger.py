# utils/logger.py
# Logs every application attempt with full details

import csv
import json
import os
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("logs")
OUTPUT_DIR = Path("output")
LOG_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

CSV_FILE = LOG_DIR / "applications.csv"
JSON_FILE = LOG_DIR / "applications.json"

CSV_HEADERS = [
    "timestamp", "platform", "company", "job_title", "location",
    "job_url", "ai_score", "ai_reason", "status",
    "cover_letter_saved", "notes"
]


def _ensure_csv():
    if not CSV_FILE.exists():
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()


def log_application(
    platform: str,
    company: str,
    job_title: str,
    location: str,
    job_url: str,
    ai_score: int,
    ai_reason: str,
    status: str,  # "applied", "skipped", "failed", "dry_run"
    cover_letter_path: str = "",
    notes: str = ""
):
    _ensure_csv()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = {
        "timestamp": now,
        "platform": platform,
        "company": company,
        "job_title": job_title,
        "location": location,
        "job_url": job_url,
        "ai_score": ai_score,
        "ai_reason": ai_reason,
        "status": status,
        "cover_letter_saved": cover_letter_path,
        "notes": notes
    }

    # CSV
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerow(row)

    # JSON (append to array)
    existing = []
    if JSON_FILE.exists():
        try:
            with open(JSON_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    existing.append(row)
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    # Console
    status_icon = {"applied": "✓", "skipped": "–", "failed": "✗", "dry_run": "◉"}.get(status, "?")
    print(f"  [{status_icon}] [{platform.upper()}] {company} | {job_title} | Score: {ai_score}/10 | {status.upper()}")


def save_cover_letter(company: str, job_title: str, content: str) -> str:
    """Save a cover letter to the output folder. Returns file path."""
    from utils.helpers import sanitize_filename
    filename = sanitize_filename(f"{company}_{job_title}") + ".txt"
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Company: {company}\n")
        f.write(f"Role: {job_title}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("-" * 60 + "\n\n")
        f.write(content)
    return str(path)


def print_session_summary():
    """Print end-of-session stats."""
    if not JSON_FILE.exists():
        print("\nNo applications logged this session.")
        return

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        all_apps = json.load(f)

    # Today only
    today = datetime.now().strftime("%Y-%m-%d")
    today_apps = [a for a in all_apps if a["timestamp"].startswith(today)]

    applied = [a for a in today_apps if a["status"] == "applied"]
    skipped = [a for a in today_apps if a["status"] == "skipped"]
    failed  = [a for a in today_apps if a["status"] == "failed"]
    dry_run = [a for a in today_apps if a["status"] == "dry_run"]

    print("\n" + "=" * 50)
    print(f"SESSION SUMMARY — {today}")
    print("=" * 50)
    print(f"  Applied:   {len(applied)}")
    print(f"  Skipped:   {len(skipped)} (low AI score or excluded)")
    print(f"  Failed:    {len(failed)} (form errors)")
    print(f"  Dry run:   {len(dry_run)}")
    print(f"  Total:     {len(today_apps)}")

    if applied:
        print("\n  Applied to:")
        for a in applied:
            print(f"    • {a['company']} — {a['job_title']} (score: {a['ai_score']})")

    print(f"\n  Full log: {CSV_FILE}")
    print("=" * 50)
