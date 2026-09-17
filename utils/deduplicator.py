# utils/deduplicator.py
# Persists seen job hashes across runs so Telegram alerts are never duplicated.
# seen_jobs.json is committed back to the repo after each GitHub Actions run.

import json
import hashlib
from pathlib import Path

SEEN_JOBS_FILE = Path("seen_jobs.json")


def _load() -> dict:
    if not SEEN_JOBS_FILE.exists():
        return {"seen": [], "stats": {"total_seen": 0, "alerts_sent": 0, "duplicates_skipped": 0}}
    try:
        with open(SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "seen" not in data:
            data["seen"] = []
        if "stats" not in data:
            data["stats"] = {"total_seen": 0, "alerts_sent": 0, "duplicates_skipped": 0}
        return data
    except Exception:
        return {"seen": [], "stats": {"total_seen": 0, "alerts_sent": 0, "duplicates_skipped": 0}}


def _save(data: dict):
    with open(SEEN_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _hash(url: str, title: str, company: str) -> str:
    key = f"{url}|{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()


def is_seen(url: str, title: str, company: str) -> bool:
    data = _load()
    return _hash(url, title, company) in data["seen"]


def mark_seen(url: str, title: str, company: str, alerted: bool = True):
    data = _load()
    h = _hash(url, title, company)
    if h not in data["seen"]:
        data["seen"].append(h)
        data["stats"]["total_seen"] += 1
        if alerted:
            data["stats"]["alerts_sent"] += 1
    _save(data)


def record_duplicate():
    data = _load()
    data["stats"]["duplicates_skipped"] += 1
    _save(data)


def get_stats() -> dict:
    return _load().get("stats", {})


def get_seen_count() -> int:
    return len(_load().get("seen", []))
