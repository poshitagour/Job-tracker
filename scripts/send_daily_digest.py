#!/usr/bin/env python3
"""Send a weekday Gmail digest of new jobs + Stamp 1G journey status."""

from __future__ import annotations

import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def status_counts(apps: list) -> dict:
    keys = [
        "applied", "manual_needed", "interview", "offer",
        "skipped", "failed", "dry_run", "rejected",
    ]
    counts = {k: sum(1 for a in apps if a.get("status") == k) for k in keys}
    counts["total"] = len(apps)
    return counts


def recent_jobs(apps: list, hours: int = 36) -> list:
    cutoff = datetime.now() - timedelta(hours=hours)
    out = []
    for a in apps:
        ts = a.get("timestamp") or a.get("updated_at") or ""
        try:
            dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                continue
        if dt >= cutoff:
            out.append(a)
    out.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return out


def html_escape(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_html(journey: dict, apps: list, seen: dict, pages_url: str) -> str:
    counts = status_counts(apps)
    new_jobs = recent_jobs(apps, hours=36)
    milestones = journey.get("milestones") or []
    seen_stats = seen.get("stats") or {}

    ms_rows = "".join(
        f"<tr><td>{html_escape(m.get('name',''))}</td>"
        f"<td><b>{html_escape(m.get('status',''))}</b></td></tr>"
        for m in milestones
    ) or "<tr><td colspan='2'>No milestones</td></tr>"

    if new_jobs:
        job_rows = "".join(
            "<tr>"
            f"<td>{html_escape(j.get('company',''))}</td>"
            f"<td>{html_escape(j.get('job_title',''))}</td>"
            f"<td>{html_escape(str(j.get('ai_score','')))}</td>"
            f"<td>{html_escape(j.get('status',''))}</td>"
            f"<td><a href=\"{html_escape(j.get('job_url',''))}\">Open</a></td>"
            "</tr>"
            for j in new_jobs[:25]
        )
    else:
        job_rows = "<tr><td colspan='5'>No new jobs in the last 36 hours.</td></tr>"

    return f"""<!DOCTYPE html>
<html><body style="font-family:Segoe UI,Arial,sans-serif;color:#1a1a1a;line-height:1.5">
  <h2>Stamp 1G Job Tracker — Daily Digest</h2>
  <p style="color:#555">{datetime.now().strftime('%A %d %b %Y, %H:%M')}</p>
  <p>{html_escape(journey.get('goal', ''))}</p>
  <p><b>Stamp 1G:</b> {html_escape(journey.get('stamp_1g_status', ''))}</p>

  <h3>Pipeline</h3>
  <ul>
    <li>Total logged: {counts['total']}</li>
    <li>Applied: {counts['applied']} · Manual needed: {counts['manual_needed']}</li>
    <li>Interview: {counts['interview']} · Offer: {counts['offer']}</li>
    <li>Seen jobs: {seen_stats.get('total_seen', 0)} · Alerts sent: {seen_stats.get('alerts_sent', 0)}</li>
  </ul>

  <h3>Journey milestones</h3>
  <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
    <tr><th align="left">Milestone</th><th align="left">Status</th></tr>
    {ms_rows}
  </table>

  <h3>New / updated jobs (last 36h)</h3>
  <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
    <tr>
      <th align="left">Company</th><th align="left">Role</th>
      <th>Score</th><th>Status</th><th>Link</th>
    </tr>
    {job_rows}
  </table>

  <p style="margin-top:24px">
    <a href="{html_escape(pages_url)}">Open live dashboard</a>
  </p>
  <p style="color:#888;font-size:12px">Sent by GitHub Actions · Gmail SMTP digest</p>
</body></html>"""


def build_text(journey: dict, apps: list, seen: dict, pages_url: str) -> str:
    counts = status_counts(apps)
    new_jobs = recent_jobs(apps, hours=36)
    lines = [
        "Stamp 1G Job Tracker — Daily Digest",
        datetime.now().strftime("%A %d %b %Y, %H:%M"),
        "",
        journey.get("goal", ""),
        f"Stamp 1G: {journey.get('stamp_1g_status', '')}",
        "",
        f"Total: {counts['total']} | Applied: {counts['applied']} | Manual: {counts['manual_needed']}",
        f"Interview: {counts['interview']} | Offer: {counts['offer']}",
        f"Seen: {(seen.get('stats') or {}).get('total_seen', 0)}",
        "",
        "Milestones:",
    ]
    for m in journey.get("milestones") or []:
        lines.append(f"  - [{m.get('status')}] {m.get('name')}")
    lines.append("")
    lines.append("New jobs (36h):")
    if not new_jobs:
        lines.append("  (none)")
    else:
        for j in new_jobs[:25]:
            lines.append(
                f"  - {j.get('company')} — {j.get('job_title')} "
                f"(score {j.get('ai_score')}, {j.get('status')})"
            )
            if j.get("job_url"):
                lines.append(f"    {j['job_url']}")
    lines += ["", f"Dashboard: {pages_url}"]
    return "\n".join(lines)


def send_email(subject: str, text: str, html: str) -> None:
    # App passwords are often copied with spaces; SMTP needs the 16 chars only.
    user = os.environ["GMAIL_ADDRESS"].strip()
    password = "".join(os.environ["GMAIL_APP_PASSWORD"].split())
    to_addr = (os.environ.get("EMAIL_TO") or user).strip()

    if len(password) != 16:
        raise SystemExit(
            f"GMAIL_APP_PASSWORD should be 16 characters after removing spaces "
            f"(got {len(password)}). Create one at https://myaccount.google.com/apppasswords"
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.sendmail(user, [to_addr], msg.as_string())
    print(f"Digest sent to {to_addr}")


def main() -> int:
    required = ["GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Missing secrets: {', '.join(missing)}", file=sys.stderr)
        return 1

    journey = load_json(ROOT / "journey.json", {})
    apps = load_json(ROOT / "logs" / "applications.json", [])
    if not isinstance(apps, list):
        apps = []
    seen = load_json(ROOT / "seen_jobs.json", {})

    repo = os.environ.get("GITHUB_REPOSITORY", "poshitagour/Job-tracker")
    owner, _, name = repo.partition("/")
    pages_url = os.environ.get(
        "PAGES_URL",
        f"https://{owner}.github.io/{name}/",
    )

    subject = f"Stamp 1G digest — {datetime.now().strftime('%d %b %Y')}"
    text = build_text(journey, apps, seen, pages_url)
    html = build_html(journey, apps, seen, pages_url)
    send_email(subject, text, html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
