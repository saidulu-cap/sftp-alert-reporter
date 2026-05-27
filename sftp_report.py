"""
SFTP Transfer Job Alert Reporter
- Authenticates as centralmembershipops@capillarytech.com (OAuth2)
- Checks inbox for 9 specific SFTP job alert emails
- Extracts file names and timestamps from email body HTML table
- Sends a detailed HTML report to configured recipients
"""

import os
import re
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from email import message_from_bytes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR   = Path(__file__).parent
ENV_FILE   = BASE_DIR / ".env"
CREDS_FILE = BASE_DIR / "credentials" / "gmail_oauth.json"
TOKEN_FILE = BASE_DIR / "credentials" / "token.json"

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Job definitions  (day=0 -> current day, day=-1 -> previous day)
# ---------------------------------------------------------------------------

@dataclass
class JobDef:
    label:          str
    subject_base:   str
    day:            int
    expected_files: int   # flag alert if actual file count < this

JOBS: list[JobDef] = [
    JobDef("rbs-brightstar-conversionfiles",        "SFTP Transfer Job rbs-brightstar-conversionfiles",        0,  3),
    JobDef("rbs-assurant-conversionfiles-transfer", "SFTP Transfer Job rbs-assurant-conversionfiles-transfer", 0,  3),
    JobDef("rbs-tengroup-conversionfiles",          "SFTP Transfer Job rbs-tengroup-conversionfiles",          0,  4),
    JobDef("rbs-the-aa-conversionfiles",            "SFTP Transfer Job rbs-the-aa-conversionfiles",            0,  2),
    JobDef("rbs-allianz-conversionfiles",           "SFTP Transfer Job rbs-allianz-conversionfiles",           0,  2),
    JobDef("rbs-allianz-v2-conversionfiles",        "SFTP Transfer Job rbs-allianz-v2-conversionfiles",        0,  3),
    JobDef("rbs-brightstar-benfit-usage-ingestion", "SFTP Transfer Job rbs-brightstar-benfit-usage-ingestion", 0,  1),
    JobDef("rbs-tastecard-extracts",                "SFTP Transfer Job rbs-tastecard-extracts",                -1, 2),
    JobDef("rbs-ss-extracts",                       "SFTP Transfer Job rbs-ss-extracts",                       -1, 3),
]

# ---------------------------------------------------------------------------
# Gmail authentication
# ---------------------------------------------------------------------------


def already_ran_today(service) -> bool:
    """Return True if a report email was already sent today (checks Sent folder)."""
    now_ist  = datetime.now(IST)
    day_start = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    after_ts  = int(day_start.timestamp())
    query  = f'subject:"SFTP Transfer Job Report" in:sent after:{after_ts}'
    result = service.users().messages().list(userId="me", q=query).execute()
    return bool(result.get("messages", []))


def get_gmail_service():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_FILE.exists():
                raise FileNotFoundError(f"Gmail OAuth credentials not found at: {CREDS_FILE}")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), GMAIL_SCOPES)
            creds = flow.run_local_server(
                port=0,
                authorization_prompt_message="Please sign in as centralmembershipops@capillarytech.com",
                login_hint="centralmembershipops@capillarytech.com",
            )
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)

# ---------------------------------------------------------------------------
# Gmail helpers
# ---------------------------------------------------------------------------

def day_window_timestamps(day_offset: int) -> tuple[int, int]:
    now_ist   = datetime.now(IST)
    target    = now_ist + timedelta(days=day_offset)
    day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end   = day_start + timedelta(days=1)
    return int(day_start.timestamp()), int(day_end.timestamp())


def get_email_body(service, msg_id: str) -> tuple[str, str, str]:
    """Return (subject, date, html_body) for a message — prefers HTML part."""
    raw_msg   = service.users().messages().get(userId="me", id=msg_id, format="raw").execute()
    email_msg = message_from_bytes(base64.urlsafe_b64decode(raw_msg["raw"]))

    subject  = email_msg.get("Subject", "")
    date_str = email_msg.get("Date", "")
    html_body = ""
    plain_body = ""

    if email_msg.is_multipart():
        for part in email_msg.walk():
            ct = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            if ct == "text/html":
                html_body = text
            elif ct == "text/plain" and not plain_body:
                plain_body = text
    else:
        payload = email_msg.get_payload(decode=True)
        if payload:
            plain_body = payload.decode(email_msg.get_content_charset() or "utf-8", errors="replace")

    return subject, date_str, html_body or plain_body

# ---------------------------------------------------------------------------
# File info + parsers
# ---------------------------------------------------------------------------

SUBJECT_TS_PATTERN = re.compile(
    r'Timestamp[:\-\s]+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', re.IGNORECASE
)


@dataclass
class FileInfo:
    name:        str
    s3_prefix:   str
    sftp_folder: str


def parse_files_from_html(body: str) -> list[FileInfo]:
    """Extract file rows from the HTML table in the email body."""
    soup  = BeautifulSoup(body, "html.parser")
    table = soup.find("table")
    if not table:
        return []
    files = []
    for row in table.find_all("tr")[1:]:   # skip header
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) >= 3:
            files.append(FileInfo(name=cols[0], s3_prefix=cols[1], sftp_folder=cols[2]))
        elif len(cols) == 1 and cols[0]:
            files.append(FileInfo(name=cols[0], s3_prefix="", sftp_folder=""))
    return files


def extract_subject_timestamp(subject: str) -> str:
    m = SUBJECT_TS_PATTERN.search(subject)
    return m.group(1) if m else ""

# ---------------------------------------------------------------------------
# Job status check
# ---------------------------------------------------------------------------

STATUS_COMPLETED = "completed"
STATUS_FAILED    = "failed"
STATUS_MISSING   = "missing"


@dataclass
class JobResult:
    job:               JobDef
    status:            str
    email_subject:     str
    email_date:        str
    target_date_label: str
    job_timestamp:     str            = ""
    files:             list[FileInfo] = field(default_factory=list)
    file_count_alert:  bool           = False   # True when actual < expected


def check_job(service, job: JobDef) -> JobResult:
    after_ts, before_ts = day_window_timestamps(job.day)
    target_label = "Today" if job.day == 0 else "Yesterday"

    query  = f'subject:"{job.subject_base}" after:{after_ts} before:{before_ts}'
    result = service.users().messages().list(userId="me", q=query).execute()
    msgs   = result.get("messages", [])

    if not msgs:
        return JobResult(job, STATUS_MISSING, "", "", target_label)

    subject, date_str, body = get_email_body(service, msgs[0]["id"])
    job_timestamp = extract_subject_timestamp(subject)
    files         = parse_files_from_html(body)
    subject_lower = subject.lower()

    if "failed" in subject_lower or "failure" in subject_lower or "error" in subject_lower:
        status = STATUS_FAILED
    else:
        status = STATUS_COMPLETED

    file_count_alert = (status == STATUS_COMPLETED) and (len(files) < job.expected_files)

    return JobResult(job, status, subject, date_str, target_label, job_timestamp, files, file_count_alert)

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_ist(date_str: str) -> str:
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(date_str).astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")
    except Exception:
        return date_str


def badge_html(status: str) -> str:
    cfg = {
        STATUS_COMPLETED: ("#e8f5e9", "#2e7d32", "COMPLETED"),
        STATUS_FAILED:    ("#ffebee", "#c62828", "FAILED"),
        STATUS_MISSING:   ("#fff3e0", "#e65100", "MISSING"),
    }
    bg, fg, lbl = cfg[status]
    return (f'<span style="background:{bg};color:{fg};padding:3px 10px;'
            f'border-radius:4px;font-size:12px;font-weight:bold">{lbl}</span>')


def file_table_html(files: list[FileInfo]) -> str:
    if not files:
        return '<em style="color:#999;font-size:12px">No files listed in email</em>'
    rows = "".join(
        f'<tr style="background:{"#fafafa" if i % 2 == 0 else "#fff"}">'
        f'<td style="padding:5px 10px;font-size:12px;color:#777;width:30px">{i}</td>'
        f'<td style="padding:5px 10px;font-family:monospace;font-size:12px;font-weight:bold">{f.name}</td>'
        f'<td style="padding:5px 10px;font-size:11px;color:#777">{f.s3_prefix}</td>'
        f'<td style="padding:5px 10px;font-size:11px;color:#777">{f.sftp_folder}</td>'
        f'</tr>'
        for i, f in enumerate(files, 1)
    )
    return (
        '<table style="width:100%;border-collapse:collapse;margin-top:8px;border:1px solid #e0e0e0">'
        '<thead><tr style="background:#eeeeee">'
        '<th style="padding:6px 10px;text-align:left;font-size:11px;color:#555">#</th>'
        '<th style="padding:6px 10px;text-align:left;font-size:11px;color:#555">File Name</th>'
        '<th style="padding:6px 10px;text-align:left;font-size:11px;color:#555">S3 Folder Prefix</th>'
        '<th style="padding:6px 10px;text-align:left;font-size:11px;color:#555">SFTP Destination Folder</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
    )

# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(results: list[JobResult], logged_in_as: str) -> tuple[str, str]:
    run_time    = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    completed   = [r for r in results if r.status == STATUS_COMPLETED]
    failed      = [r for r in results if r.status == STATUS_FAILED]
    missing     = [r for r in results if r.status == STATUS_MISSING]
    file_alerts = [r for r in results if r.file_count_alert]
    overall_ok  = not failed and not missing and not file_alerts
    total_files = sum(len(r.files) for r in results)

    # ---- Plain text ----
    sep = "=" * 70
    lines = [
        sep,
        f"  SFTP TRANSFER JOB REPORT -- {'ALL OK' if overall_ok else 'ACTION REQUIRED'}",
        f"  Checked at  : {run_time}",
        f"  Inbox       : {logged_in_as}",
        f"  Jobs        : Completed {len(completed)}/9 | Failed {len(failed)} | Missing {len(missing)} | File Count Alerts {len(file_alerts)}",
        f"  Total Files : {total_files}",
        sep, "",
    ]
    for section, label in [(failed, "FAILED"), (missing, "MISSING"), (file_alerts, "FILE COUNT ALERT"), (completed, "COMPLETED")]:
        if not section:
            continue
        lines.append(f"  [{label} JOBS]")
        lines.append("  " + "-" * 66)
        for r in section:
            lines.append(f"  Job        : {r.job.label}")
            lines.append(f"  Status     : {r.status.upper()}")
            lines.append(f"  Email Date : {format_ist(r.email_date) if r.email_date else 'N/A'}")
            if r.job_timestamp:
                lines.append(f"  Job Run At : {r.job_timestamp}")
            fc_flag = f"  *** ALERT: expected {r.job.expected_files}, got {len(r.files)} ***" if r.file_count_alert else ""
            lines.append(f"  File Count : {len(r.files)} / {r.job.expected_files}{fc_flag}")
            for i, f in enumerate(r.files, 1):
                lines.append(f"    {i:>2}. {f.name}")
                if f.s3_prefix:
                    lines.append(f"        S3   : {f.s3_prefix}")
                if f.sftp_folder:
                    lines.append(f"        SFTP : {f.sftp_folder}")
            lines.append("")
    plain_text = "\n".join(lines)

    # ---- HTML ----
    header_color = "#1b5e20" if overall_ok else "#b71c1c"
    header_label = "ALL OK" if overall_ok else "ACTION REQUIRED"

    def job_card(r: JobResult) -> str:
        ts_part = (f'<span style="color:#555;font-size:12px">'
                   f'Job Run At: <strong>{r.job_timestamp}</strong></span> &nbsp;|&nbsp; '
                   if r.job_timestamp else "")

        # File count badge — red with warning if mismatch, blue if OK
        if r.file_count_alert:
            fc_badge = (
                f'<span style="background:#f3e5f5;color:#6a1b9a;padding:2px 10px;'
                f'border-radius:10px;font-size:12px;font-weight:bold;border:1px solid #ce93d8">'
                f'&#9888; {len(r.files)}/{r.job.expected_files} files — COUNT MISMATCH</span>'
            )
        elif r.status == STATUS_MISSING:
            fc_badge = (
                f'<span style="background:#fff3e0;color:#e65100;padding:2px 10px;'
                f'border-radius:10px;font-size:12px;font-weight:bold">'
                f'0/{r.job.expected_files} files expected</span>'
            )
        else:
            fc_badge = (
                f'<span style="background:#e3f2fd;color:#1565c0;padding:2px 10px;'
                f'border-radius:10px;font-size:12px;font-weight:bold">'
                f'{len(r.files)}/{r.job.expected_files} files</span>'
            )

        border_color = "#9c27b0" if r.file_count_alert else "#e0e0e0"
        return (
            f'<div style="border:2px solid {border_color};border-radius:6px;margin:10px 16px;overflow:hidden">'
            f'  <div style="background:#f5f5f5;padding:10px 14px;display:flex;'
            f'              justify-content:space-between;align-items:center">'
            f'    <div>{badge_html(r.status)}'
            f'    <strong style="font-family:monospace;font-size:13px;margin-left:10px">'
            f'{r.job.label}</strong></div>'
            f'    {fc_badge}'
            f'  </div>'
            + (
                f'  <div style="background:#f3e5f5;padding:6px 14px;font-size:12px;'
                f'color:#6a1b9a;font-weight:bold;border-bottom:1px solid #ce93d8">'
                f'  &#9888; FILE COUNT ALERT: Expected {r.job.expected_files} files, '
                f'received only {len(r.files)}. Please investigate.</div>'
                if r.file_count_alert else ""
            ) +
            f'  <div style="padding:8px 14px;font-size:12px;color:#666;border-bottom:1px solid #f0f0f0">'
            f'    {ts_part}'
            f'    <span>Email received: '
            f'    {format_ist(r.email_date) if r.email_date else "<em>Not received</em>"}</span>'
            f'  </div>'
            f'  <div style="padding:8px 14px">{file_table_html(r.files)}</div>'
            f'</div>'
        )

    all_cards = "".join(job_card(r) for r in (failed + missing + file_alerts + completed))

    html = (
        '<!DOCTYPE html><html>'
        '<body style="margin:0;padding:20px;font-family:Arial,sans-serif;background:#f4f4f4">'
        '<div style="max-width:900px;margin:0 auto;background:#fff;border-radius:8px;'
        '     box-shadow:0 2px 8px rgba(0,0,0,.12);overflow:hidden">'

        # Header
        f'<div style="background:{header_color};color:#fff;padding:18px 24px">'
        f'  <div style="font-size:19px;font-weight:bold">'
        f'    SFTP Transfer Job Report &mdash; {header_label}'
        f'  </div>'
        f'  <div style="font-size:13px;margin-top:4px;opacity:.85">'
        f'    Checked at {run_time} &nbsp;|&nbsp; Inbox: {logged_in_as}'
        f'  </div>'
        f'</div>'

        # Summary bar
        f'<div style="display:flex;background:#f9f9f9;border-bottom:1px solid #ddd;'
        f'           padding:14px 24px;gap:40px">'
        f'  <div style="text-align:center">'
        f'    <div style="font-size:28px;font-weight:bold;color:#2e7d32">{len(completed)}/9</div>'
        f'    <div style="font-size:12px;color:#555">Completed</div>'
        f'  </div>'
        f'  <div style="text-align:center">'
        f'    <div style="font-size:28px;font-weight:bold;color:#c62828">{len(failed)}</div>'
        f'    <div style="font-size:12px;color:#555">Failed</div>'
        f'  </div>'
        f'  <div style="text-align:center">'
        f'    <div style="font-size:28px;font-weight:bold;color:#e65100">{len(missing)}</div>'
        f'    <div style="font-size:12px;color:#555">Missing</div>'
        f'  </div>'
        f'  <div style="text-align:center">'
        f'    <div style="font-size:28px;font-weight:bold;color:#1565c0">{total_files}</div>'
        f'    <div style="font-size:12px;color:#555">Total Files</div>'
        f'  </div>'
        f'  <div style="text-align:center">'
        f'    <div style="font-size:28px;font-weight:bold;color:#6a1b9a">{len(file_alerts)}</div>'
        f'    <div style="font-size:12px;color:#555">File Count Alerts</div>'
        f'  </div>'
        f'</div>'

        # Job cards
        f'<div style="padding:6px 0 16px 0">{all_cards}</div>'

        # Footer
        f'<div style="background:#f9f9f9;padding:10px 24px;font-size:11px;color:#999;'
        f'           border-top:1px solid #eee;text-align:center">'
        f'  Auto-generated by SFTP Alert Reporter &nbsp;|&nbsp; {run_time}'
        f'</div>'
        f'</div></body></html>'
    )
    return plain_text, html

# ---------------------------------------------------------------------------
# Google Chat webhook
# ---------------------------------------------------------------------------

def post_to_google_chat(webhook_url: str, results: list, run_time: str) -> None:
    """Post a compact summary card to a Google Chat space via incoming webhook."""
    import requests

    completed   = [r for r in results if r.status == STATUS_COMPLETED]
    failed      = [r for r in results if r.status == STATUS_FAILED]
    missing     = [r for r in results if r.status == STATUS_MISSING]
    file_alerts = [r for r in results if r.file_count_alert]
    overall_ok  = not failed and not missing and not file_alerts
    total_files = sum(len(r.files) for r in results)

    status_icon = "✅" if overall_ok else "🔴"
    status_text = "ALL OK" if overall_ok else "ACTION REQUIRED"

    # Build per-job lines
    job_lines = []
    for r in results:
        if r.status == STATUS_MISSING:
            icon = "⚠️"
        elif r.status == STATUS_FAILED:
            icon = "❌"
        elif r.file_count_alert:
            icon = "🟣"
        else:
            icon = "✅"
        fc = f"{len(r.files)}/{r.job.expected_files} files"
        ts = f" | {r.job_timestamp}" if r.job_timestamp else ""
        job_lines.append(f"{icon} `{r.job.label}` — {fc}{ts}")

    # Alert section
    alert_lines = []
    for r in failed:
        alert_lines.append(f"❌ *FAILED*: `{r.job.label}`")
    for r in missing:
        alert_lines.append(f"⚠️ *MISSING*: `{r.job.label}` (expected {r.target_date_label.lower()})")
    for r in file_alerts:
        alert_lines.append(f"🟣 *FILE COUNT ALERT*: `{r.job.label}` — got {len(r.files)}/{r.job.expected_files} files")

    body_text = (
        f"{status_icon} *SFTP Transfer Job Report — {status_text}*\n"
        f"_Checked at {run_time}_\n"
        f">Completed: *{len(completed)}/9* | Failed: *{len(failed)}* | "
        f"Missing: *{len(missing)}* | File Alerts: *{len(file_alerts)}* | "
        f"Total Files: *{total_files}*\n\n"
    )
    if alert_lines:
        body_text += "*Alerts:*\n" + "\n".join(alert_lines) + "\n\n"
    body_text += "\n".join(job_lines)

    payload = {"text": body_text}
    response = requests.post(
        webhook_url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()

# ---------------------------------------------------------------------------
# Send email via Gmail API
# ---------------------------------------------------------------------------

def send_email(service, from_addr: str, to_addresses: list[str],
               subject: str, plain_text: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(to_addresses)
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    load_dotenv(ENV_FILE)

    report_to = [e.strip() for e in os.getenv("REPORT_TO_EMAILS", "").split(",") if e.strip()]
    if not report_to:
        raise EnvironmentError("REPORT_TO_EMAILS is not set in .env")

    print(f"[{datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}] Authenticating with Gmail...")
    service = get_gmail_service()

    profile      = service.users().getProfile(userId="me").execute()
    logged_in_as = profile.get("emailAddress", "unknown")
    print(f"Logged in as: {logged_in_as}\n")

    now_ist = datetime.now(IST)
    if now_ist.hour < 13:
        print(f"[{now_ist.strftime('%Y-%m-%d %H:%M IST')}] "
              f"Too early (before 1:00 PM IST) — emails not yet received. Skipping.")
        return

    if already_ran_today(service):
        print(f"[{now_ist.strftime('%Y-%m-%d %H:%M IST')}] "
              f"Report already sent today — skipping to avoid duplicate.")
        return

    results: list[JobResult] = []
    for job in JOBS:
        result = check_job(service, job)
        icon   = {"completed": "[OK]     ", "failed": "[FAILED] ", "missing": "[MISSING]"}[result.status]
        ts     = f"  run:{result.job_timestamp}" if result.job_timestamp else ""
        fc     = f"  *** FILE COUNT ALERT: {len(result.files)}/{job.expected_files} ***" if result.file_count_alert else f"  ({len(result.files)}/{job.expected_files} files)"
        print(f"  {icon}  {job.label}{fc}{ts}")
        results.append(result)

    run_time         = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    plain_text, html = generate_report(results, logged_in_as)

    failed      = [r for r in results if r.status == STATUS_FAILED]
    missing     = [r for r in results if r.status == STATUS_MISSING]
    file_alerts = [r for r in results if r.file_count_alert]
    status      = "ACTION REQUIRED" if (failed or missing or file_alerts) else "ALL OK"
    subject     = f"SFTP Transfer Job Report - {status} - {datetime.now(IST).strftime('%d %b %Y')}"

    print("\n--- Preview ---")
    print(plain_text.encode("ascii", errors="replace").decode("ascii"))

    print(f"\nSending email to: {', '.join(report_to)} ...")
    send_email(service, logged_in_as, report_to, subject, plain_text, html)
    print("Email sent.")

    chat_webhook = os.getenv("GOOGLE_CHAT_WEBHOOK_URL", "").strip()
    if chat_webhook:
        print("Posting to Google Chat CMOps space ...")
        post_to_google_chat(chat_webhook, results, run_time)
        print("Google Chat posted.")
    else:
        print("GOOGLE_CHAT_WEBHOOK_URL not set — skipping Chat post.")

    print("\nDone.")


if __name__ == "__main__":
    main()
