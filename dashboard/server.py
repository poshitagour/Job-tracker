# dashboard/server.py - Poshita Gour Stamp 1G / HR job tracker
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config.profile import PROFILE, INDEED_IE_SEARCHES, IRISHJOBS_SEARCHES, LINKEDIN_SEARCHES_EXTRA

app = FastAPI(title="Poshita Gour - Stamp 1G Job Tracker")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

LOG_FILE = Path("logs/applications.json")
SEEN_JOBS_FILE = Path("seen_jobs.json")
JOURNEY_FILE = Path("journey.json")

DEFAULT_JOURNEY = {
    "goal": "Secure an Ireland HR / HR Technology role during Stamp 1G and transition to a suitable long-term employment permit.",
    "stamp_1g_status": "ACTIVE - exact expiry date to confirm",
    "milestones": [
        {"id": "m1", "name": "Stamp 1G active", "status": "done"},
        {"id": "m2", "name": "Master CV aligned to HRIS / transformation", "status": "done"},
        {"id": "m3", "name": "Start targeted Irish job search", "status": "in_progress"},
        {"id": "m4", "name": "Build HRIS / People Analytics pipeline", "status": "in_progress"},
        {"id": "m5", "name": "Secure HR / HR-tech offer", "status": "pending"},
        {"id": "m6", "name": "Verify permit route before offer acceptance", "status": "pending"},
        {"id": "m7", "name": "Employment permit application", "status": "pending"},
        {"id": "m8", "name": "Long-term immigration permission", "status": "pending"},
    ],
}


def load_apps():
    if not LOG_FILE.exists(): return []
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def load_journey():
    if not JOURNEY_FILE.exists(): return DEFAULT_JOURNEY
    try: return json.loads(JOURNEY_FILE.read_text(encoding="utf-8"))
    except Exception: return DEFAULT_JOURNEY


@app.get("/api/profile")
def get_profile():
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
    }


@app.get("/api/journey")
def get_journey():
    return load_journey()


@app.post("/api/journey/milestone")
def update_milestone(data: dict):
    journey = load_journey()
    mid = data.get("id")
    status = data.get("status")
    if not mid or status not in {"pending", "in_progress", "done"}: return {"ok": False}
    for m in journey["milestones"]:
        if m["id"] == mid: m["status"] = status
    JOURNEY_FILE.write_text(json.dumps(journey, indent=2), encoding="utf-8")
    return {"ok": True, "journey": journey}


@app.get("/api/applications")
def get_applications():
    apps = load_apps()
    stats = {
        "total": len(apps),
        "applied": sum(a.get("status") == "applied" for a in apps),
        "skipped": sum(a.get("status") == "skipped" for a in apps),
        "failed": sum(a.get("status") == "failed" for a in apps),
        "dry_run": sum(a.get("status") == "dry_run" for a in apps),
        "manual_needed": sum(a.get("status") == "manual_needed" for a in apps),
        "interview": sum(a.get("status") == "interview" for a in apps),
        "offer": sum(a.get("status") == "offer" for a in apps),
        "rejected": sum(a.get("status") == "rejected" for a in apps),
    }
    today = datetime.now().strftime("%Y-%m-%d")
    stats["today"] = sum(a.get("timestamp", "").startswith(today) for a in apps)
    stats["csep_candidates"] = sum("CSEP CANDIDATE" in a.get("notes", "") for a in apps)
    stats["gep_candidates"] = sum("GEP CANDIDATE" in a.get("notes", "") for a in apps)
    stats["avoid_permit"] = sum("AVOID - HR administrative" in a.get("notes", "") for a in apps)
    return {"applications": list(reversed(apps)), "stats": stats}


@app.post("/api/update-status")
def update_status(data: dict):
    job_url, new_status = data.get("job_url"), data.get("status")
    if not LOG_FILE.exists() or not job_url or not new_status: return {"ok": False}
    apps = load_apps()
    for entry in apps:
        if entry.get("job_url") == job_url:
            entry["status"] = new_status
            entry["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break
    LOG_FILE.write_text(json.dumps(apps, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


@app.get("/api/irish-searches")
def get_irish_searches():
    return {
        "indeed_ie": [{"keywords": s["keywords"], "location": s["location"], "source": "Indeed IE"} for s in INDEED_IE_SEARCHES],
        "irishjobs": [{"keywords": s["keywords"], "location": s["location"], "source": "IrishJobs"} for s in IRISHJOBS_SEARCHES],
        "linkedin_extra": [{"keywords": s["keywords"], "location": s["location"], "source": "LinkedIn"} for s in LINKEDIN_SEARCHES_EXTRA],
    }


@app.get("/api/jobs-table")
def get_jobs_table():
    apps = load_apps()
    def parse_notes(notes):
        result = {"cv": "", "permit": "", "tier": "", "reason": "", "flags": []}
        if not notes: return result
        for part in notes.split("|"):
            part = part.strip()
            if part.startswith("CV:"): result["cv"] = part[3:].strip()
            elif part.startswith("Permit:"): result["permit"] = part[7:].strip()
            elif part.startswith("Tier:"): result["tier"] = part[5:].strip()
            elif part.startswith("PermitReason:"): result["reason"] = part[13:].strip()
            elif "TARGET" in part or "MATCH" in part: result["flags"].append(part)
        return result
    out=[]
    for a in reversed(apps[-300:]):
        n=parse_notes(a.get("notes", ""))
        out.append({
            "timestamp": a.get("timestamp", ""), "platform": a.get("platform", ""), "company": a.get("company", ""),
            "job_title": a.get("job_title", ""), "location": a.get("location", ""), "job_url": a.get("job_url", ""),
            "fit_score": a.get("ai_score", 0), "cv_rec": n["cv"], "permit_path": n["permit"], "permit_reason": n["reason"],
            "company_tier": n["tier"], "flags": n["flags"], "status": a.get("status", ""), "ai_reason": a.get("ai_reason", "")
        })
    week_ago=(datetime.now()-timedelta(days=7)).strftime("%Y-%m-%d")
    weekly=[a for a in apps if a.get("timestamp","")>=week_ago]
    dedup={}
    if SEEN_JOBS_FILE.exists():
        try: dedup=json.loads(SEEN_JOBS_FILE.read_text()).get("stats", {})
        except Exception: pass
    return {"jobs": out[:100], "stats": {"weekly_found": len(weekly), "alerts_sent": dedup.get("alerts_sent",0), "duplicates_skipped": dedup.get("duplicates_skipped",0), "total_seen": dedup.get("total_seen",0)}}


@app.get("/api/health")
def health(): return {"status": "ok", "time": datetime.now().isoformat()}

if __name__ == "__main__":
    print("Starting Poshita Stamp 1G tracker at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
