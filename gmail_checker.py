import os
import sys
import requests
import logging
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ========================= CONFIG =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("GMAIL_CHAT_ID")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN")
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# ========================= LOGGING =========================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========================= ENV CHECK =========================
missing = []
if not TELEGRAM_TOKEN: missing.append("TELEGRAM_TOKEN")
if not CHAT_ID: missing.append("GMAIL_CHAT_ID")
if not GMAIL_REFRESH_TOKEN: missing.append("GMAIL_REFRESH_TOKEN")
if not GMAIL_CLIENT_ID: missing.append("GMAIL_CLIENT_ID")
if not GMAIL_CLIENT_SECRET: missing.append("GMAIL_CLIENT_SECRET")

if missing:
    print(f"ERROR: Missing environment variables: {', '.join(missing)}")
    sys.exit(1)


def get_gmail_service():
    """Authenticate and return Gmail API service."""
    creds = Credentials(
        token=None,
        refresh_token=GMAIL_REFRESH_TOKEN,
        client_id=GMAIL_CLIENT_ID,
        client_secret=GMAIL_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def get_header(msg, name: str) -> str:
    """Extract a specific header from email metadata."""
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def get_recent_emails(service, hours: int = 24):
    """Fetch recent emails."""
    after = int((datetime.now() - timedelta(hours=hours)).timestamp())
    
    results = service.users().messages().list(
        userId="me",
        q=f"after:{after}",
        maxResults=20
    ).execute()

    messages = results.get("messages", [])
    emails = []

    for m in messages:
        msg = service.users().messages().get(
            userId="me", 
            id=m["id"], 
            format="metadata"
        ).execute()

        subject = get_header(msg, "Subject")
        sender = get_header(msg, "From")
        labels = msg.get("labelIds", [])
        unread = "UNREAD" in labels

        is_jobber = any(
            kw in sender.lower() or kw in subject.lower() 
            for kw in ["jobber", "getjobber"]
        )

        emails.append({
            "subject": subject,
            "from": sender,
            "unread": unread,
            "jobber": is_jobber
        })

    return emails


def send_telegram(text: str):
    """Send message to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")


def main():
    logger.info("Checking Gmail...")

    service = get_gmail_service()
    emails = get_recent_emails(service)

    if not emails:
        send_telegram("No new emails in the last 24 hours. Clean inbox, handsome.")
        return

    jobber_emails = [e for e in emails if e["jobber"]]
    other_emails = [e for e in emails if not e["jobber"]]
    unread_count = sum(1 for e in emails if e["unread"])

    lines = [
        f"<b>Email Summary</b> — {len(emails)} new, {unread_count} unread\n"
    ]

    if jobber_emails:
        lines.append("<b>Jobber Updates:</b>")
        for e in jobber_emails:
            marker = "🟢 NEW" if e["unread"] else "🔵 read"
            lines.append(f"{marker} {e['subject']}")
        lines.append("")

    if other_emails:
        lines.append("<b>Other Emails:</b>")
        for e in other_emails[:10]:
            marker = "🟢 NEW" if e["unread"] else "🔵 read"
            sender = e["from"].split("<")[0].strip()
            subject = e["subject"][:60] + "..." if len(e["subject"]) > 60 else e["subject"]
            lines.append(f"{marker} {sender} — {subject}")

    send_telegram("\n".join(lines))
    logger.info("Email summary sent to Telegram!")


if __name__ == "__main__":
    main()
