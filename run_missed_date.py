"""
One-off script to run the report for a missed date.
Shifts all job date offsets by -1 so:
  - Jobs 1-7 (normally today)    -> check yesterday  (19 Apr)
  - Jobs 8-9 (normally yesterday) -> check 2 days ago (18 Apr)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Import everything from the main script
from sftp_report import (
    JOBS, JobDef, get_gmail_service, check_job, generate_report,
    send_email, post_to_google_chat, STATUS_FAILED, STATUS_MISSING,
    IST, ENV_FILE
)
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(ENV_FILE)

# Shift all jobs by -1 day
MISSED_DATE_JOBS = [
    JobDef(j.label, j.subject_base, j.day - 1, j.expected_files)
    for j in JOBS
]

report_to   = [e.strip() for e in os.getenv("REPORT_TO_EMAILS", "").split(",") if e.strip()]
chat_webhook = os.getenv("GOOGLE_CHAT_WEBHOOK_URL", "").strip()

print(f"[{datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}] Authenticating with Gmail...")
service = get_gmail_service()

profile      = service.users().getProfile(userId="me").execute()
logged_in_as = profile.get("emailAddress", "unknown")
print(f"Logged in as: {logged_in_as}")
print(f"Running MISSED DATE report (19 Apr 2026)\n")

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

results = []
for job in MISSED_DATE_JOBS:
    result = check_job(service, job)
    icon   = {"completed": "[OK]     ", "failed": "[FAILED] ", "missing": "[MISSING]"}[result.status]
    fc     = f"  *** FILE COUNT ALERT: {len(result.files)}/{job.expected_files} ***" if result.file_count_alert else f"  ({len(result.files)}/{job.expected_files} files)"
    print(f"  {icon}  {job.label}{fc}")
    results.append(result)

run_time         = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
plain_text, html = generate_report(results, logged_in_as)

failed      = [r for r in results if r.status == STATUS_FAILED]
missing     = [r for r in results if r.status == STATUS_MISSING]
file_alerts = [r for r in results if r.file_count_alert]
status      = "ACTION REQUIRED" if (failed or missing or file_alerts) else "ALL OK"
subject     = f"SFTP Transfer Job Report [19 Apr 2026] - {status} - MISSED RUN"

print(f"\nSending missed date report to: {', '.join(report_to)} ...")
send_email(service, logged_in_as, report_to, subject, plain_text, html)
print("Email sent.")

if chat_webhook:
    print("Posting to Google Chat CMOps space ...")
    post_to_google_chat(chat_webhook, results, f"19 Apr 2026 (missed run, sent {run_time})")
    print("Google Chat posted.")

print("\nDone.")
