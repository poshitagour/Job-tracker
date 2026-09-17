#!/usr/bin/env python3
"""Copy tracker JSON into docs/ so GitHub Pages can serve a static dashboard."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.profile import (  # noqa: E402
    INDEED_IE_SEARCHES,
    IRISHJOBS_SEARCHES,
    LINKEDIN_SEARCHES_EXTRA,
    PROFILE,
)

DOCS = ROOT / "docs"
DATA = DOCS / "data"


def build_profile() -> dict:
    return {
        "name": f"{PROFILE['first_name']} {PROFILE['last_name']}",
        "location": PROFILE["location"],
        "visa_status": PROFILE["visa_status"],
        "stamp_1g_expiry": PROFILE["stamp_1g_expiry"],
        "requires_sponsorship_long_term": PROFILE["requires_sponsorship_long_term"],
        "target_roles": PROFILE["target_roles"],
        "salary_min": PROFILE["salary_min"],
        "preferred_salary": PROFILE["preferred_salary"],
        "cv_version": PROFILE["cv_version"],
        "permit_strategy": PROFILE["permit_strategy"],
        "target_company_tiers": PROFILE["target_company_tiers"],
        "searches": {
            "indeed_ie": [
                {"keywords": s["keywords"], "location": s["location"]}
                for s in INDEED_IE_SEARCHES
            ],
            "irishjobs": [
                {"keywords": s["keywords"], "location": s["location"]}
                for s in IRISHJOBS_SEARCHES
            ],
            "linkedin_extra": [
                {"keywords": s["keywords"], "location": s["location"]}
                for s in LINKEDIN_SEARCHES_EXTRA
            ],
        },
    }


def copy_json(src: Path, dest: Path, default):
    if src.exists():
        shutil.copy2(src, dest)
    else:
        dest.write_text(json.dumps(default, indent=2), encoding="utf-8")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)

    apps_src = ROOT / "logs" / "applications.json"
    apps_default: list = []
    if apps_src.exists():
        try:
            apps_default = json.loads(apps_src.read_text(encoding="utf-8"))
        except Exception:
            apps_default = []

    copy_json(ROOT / "journey.json", DATA / "journey.json", {
        "goal": "Secure an Ireland HR / HR Technology role during Stamp 1G.",
        "stamp_1g_status": "ACTIVE",
        "milestones": [],
    })
    copy_json(ROOT / "seen_jobs.json", DATA / "seen_jobs.json", {
        "seen": [],
        "stats": {"total_seen": 0, "alerts_sent": 0, "duplicates_skipped": 0},
    })
    copy_json(apps_src, DATA / "applications.json", apps_default)

    # Also keep a top-level profile.json for the user's documented path
    profile = build_profile()
    (DATA / "profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    (ROOT / "profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")

    # Convenience copies at docs root (matches plan: docs reads journey.json etc.)
    for name in ("journey.json", "seen_jobs.json", "applications.json", "profile.json"):
        shutil.copy2(DATA / name, DOCS / name)

    # Mirror applications under docs/logs/ for the plan path logs/applications.json
    (DOCS / "logs").mkdir(exist_ok=True)
    shutil.copy2(DATA / "applications.json", DOCS / "logs" / "applications.json")

    print(f"Synced Pages data into {DOCS}")


if __name__ == "__main__":
    main()
