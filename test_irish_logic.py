"""
test_irish_logic.py
Quick smoke test for job_scorer, deduplicator, and Telegram alert format.
Run: python test_irish_logic.py
"""

import sys, json, asyncio
from pathlib import Path

# ── 1. job_scorer ───────────────────────────────────────────────────────────
from core.job_scorer import calculate_fit_score, get_cv_recommendation, get_company_flags

CV_A = "CV-A: Backend/AI Engineer"
CV_B = "CV-B: Data Analytics"

SCORER_CASES = [
    # (title, description_snippet, expected_min_score, expected_cv, note)
    (
        "Aviation Data Analyst",
        "We are AerCap, looking for a data analyst with Python and SQL to support fleet analytics. "
        "KPI reporting, Excel dashboards. Dublin office.",
        65, CV_B, "Aviation + data -> CV-B, high score",
    ),
    (
        "Junior Backend Engineer",
        "FastAPI, Python, REST API design. Docker, MongoDB. Junior/graduate welcome. Dublin.",
        55, CV_A, "Backend engineer -> CV-A",
    ),
    (
        "Clinical Data Intern",
        "Data entry, Excel, pivot tables. Reporting to clinical operations team. Internship.",
        20, CV_B, "Clinical data -> CV-B (lower score expected)",
    ),
    (
        "Senior Director of Engineering",
        "10+ years required. Lead engineering org of 50+. Principal architect role.",
        0, None, "Heavy senior penalty -> score near 0",
    ),
    (
        "BI Developer Junior",
        "Power BI, SQL, dashboards, KPI reporting. Graduate level. Dublin.",
        55, CV_B, "BI developer -> CV-B",
    ),
    (
        "AI Engineer",
        "RAG systems, Python, vector databases, LLMs. Dublin startup. junior/grad welcome.",
        55, CV_A, "AI engineer -> CV-A (rag+python+llm boost)",
    ),
]

print("=" * 60)
print("PART 1 -- Scoring & CV Recommendation")
print("=" * 60)

all_passed = True
for title, desc, min_score, expected_cv, note in SCORER_CASES:
    score = calculate_fit_score(title, desc)
    cv    = get_cv_recommendation(title, desc)
    ok_score = score >= min_score
    ok_cv    = (expected_cv is None) or (cv == expected_cv)
    status = "PASS" if (ok_score and ok_cv) else "FAIL"
    if status == "FAIL":
        all_passed = False
    print(f"  [{status}] {title}")
    print(f"         score={score}  (expected>={min_score})  cv={cv}  (expected={expected_cv})")
    print(f"         {note}")

# ── 2. company flags ─────────────────────────────────────────────────────────
print()
print("=" * 60)
print("PART 2 -- Company Flags")
print("=" * 60)

FLAG_CASES = [
    ("AerCap",    ["AVIATION MATCH"]),
    ("Avolon",    ["AVIATION MATCH"]),
    ("Version 1", ["TARGET COMPANY"]),
    ("Stripe",    ["TARGET COMPANY"]),
    ("Random Co", []),
]

for company, expected_keywords in FLAG_CASES:
    flags = get_company_flags(company)
    flags_str = " ".join(flags)
    ok = all(kw in flags_str for kw in expected_keywords) and (bool(flags) == bool(expected_keywords))
    if not ok:
        all_passed = False
    print(f"  [{'PASS' if ok else 'FAIL'}] {company} -> {flags}")

# ── 3. deduplicator ──────────────────────────────────────────────────────────
print()
print("=" * 60)
print("PART 3 -- Deduplicator")
print("=" * 60)

TEMP_SEEN = Path("seen_jobs_test_tmp.json")
TEMP_SEEN.write_text(json.dumps({"seen": [], "stats": {"total_seen": 0, "alerts_sent": 0, "duplicates_skipped": 0}}))

import utils.deduplicator as dedup
_orig_file = dedup.SEEN_JOBS_FILE
dedup.SEEN_JOBS_FILE = TEMP_SEEN

url1, title1, company1 = "https://ie.indeed.com/viewjob?jk=abc123", "Data Analyst", "AerCap"
url2, title2, company2 = "https://ie.indeed.com/viewjob?jk=xyz999", "Software Engineer", "Stripe"

seen1_before = dedup.is_seen(url1, title1, company1)
dedup.mark_seen(url1, title1, company1, alerted=True)
seen1_after  = dedup.is_seen(url1, title1, company1)
seen2 = dedup.is_seen(url2, title2, company2)
dedup.record_duplicate()
stats = dedup.get_stats()

ok_dedup = (not seen1_before) and seen1_after and (not seen2) and stats["duplicates_skipped"] == 1
if not ok_dedup:
    all_passed = False

print(f"  [{'PASS' if not seen1_before else 'FAIL'}] First check: url1 not seen before mark_seen")
print(f"  [{'PASS' if seen1_after else 'FAIL'}] After mark_seen: url1 is seen")
print(f"  [{'PASS' if not seen2 else 'FAIL'}] url2 not seen (different job)")
print(f"  [{'PASS' if stats['duplicates_skipped']==1 else 'FAIL'}] record_duplicate incremented -> {stats}")

dedup.SEEN_JOBS_FILE = _orig_file
TEMP_SEEN.unlink(missing_ok=True)

# ── 4. Telegram alert format ─────────────────────────────────────────────────
print()
print("=" * 60)
print("PART 4 -- Telegram Alert Format (visual check)")
print("=" * 60)

async def preview_alert():
    flags = ["AVIATION MATCH"]
    flag_line = "\n".join(flags) + "\n"
    title    = "Aviation Data Analyst"
    company  = "AerCap"
    location = "Dublin, Ireland"
    score    = 78
    cv_rec   = "CV-B: Data Analytics"
    url      = "https://ie.indeed.com/viewjob?jk=abc123"
    posted   = "2026-08-14"
    source   = "Indeed IE"
    msg = (
        f"{flag_line}"
        f"NEW JOB ALERT\n"
        f"--------------------\n"
        f"Role: {title}\n"
        f"Company: {company}\n"
        f"Location: {location}\n"
        f"Fit Score: {score}%\n"
        f"CV to Use: {cv_rec}\n"
        f"Apply: {url}\n"
        f"Posted: {posted}\n"
        f"Source: {source}\n"
        f"--------------------"
    )
    return msg

msg = asyncio.run(preview_alert())
print(msg)
ok_format = all(x in msg for x in ["NEW JOB ALERT", "AerCap", "78%", "CV-B", "AVIATION MATCH"])
if not ok_format:
    all_passed = False
print(f"\n  [{'PASS' if ok_format else 'FAIL'}] Alert contains all required fields")

# ── 5. Final result ──────────────────────────────────────────────────────────
print()
print("=" * 60)
print(f"RESULT: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
print("=" * 60)
sys.exit(0 if all_passed else 1)
