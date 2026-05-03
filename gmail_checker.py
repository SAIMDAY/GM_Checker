import os
import sys
import requests
import logging
import base64
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ========================= CONFIG =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("GMAIL_CHAT_ID")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN")
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
LETTA_API_KEY = os.getenv("LETTA_API_KEY")
AGENT_ID = os.getenv("AGENT_ID")
LETTA_API_BASE_URL = os.getenv("LETTA_API_BASE_URL", "https://api.letta.com")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# ========================= LOGGING =========================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ========================= ENV CHECK =========================
missing = []
for var, name in [
    (TELEGRAM_TOKEN, "TELEGRAM_TOKEN"),
    (CHAT_ID, "GMAIL_CHAT_ID"),
    (GMAIL_REFRESH_TOKEN, "GMAIL_REFRESH_TOKEN"),
    (GMAIL_CLIENT_ID, "GMAIL_CLIENT_ID"),
    (GMAIL_CLIENT_SECRET, "GMAIL_CLIENT_SECRET"),
    (LETTA_API_KEY, "LETTA_API_KEY"),
    (AGENT_ID, "AGENT_ID"),
]:
    if not var:
        missing.append(name)

if missing:
    print(f"ERROR: Missing environment variables: {', '.join(missing)}")
    sys.exit(1)


def get_gmail_service():
    """Build Gmail API service with refreshed credentials."""
    try:
        creds = Credentials(
            token=None,
            refresh_token=GMAIL_REFRESH_TOKEN,
            client_id=GMAIL_CLIENT_ID,
            client_secret=GMAIL_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
        creds.refresh(Request())
        return build("gmail", "v1", credentials=creds)
    except Exception as e:
        logger.error(f"Failed to build Gmail service: {e}")
        raise


def get_header(msg, name: str) -> str:
    """Extract header value by name (case-insensitive)."""
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def get_email_body(msg) -> str:
    """Extract plain text or HTML body, handling nested parts."""
    def decode_part(part):
        data = part.get("body", {}).get("data")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return ""

    payload = msg.get("payload", {})

    # Direct body
    if payload.get("body", {}).get("data"):
        return decode_part(payload)

    # Check parts (including nested)
    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain":
            return decode_part(part)
        if part.get("mimeType") == "text/html":
            return decode_part(part)

        # Handle nested multipart
        if part.get("parts"):
            for subpart in part.get("parts", []):
                if subpart.get("mimeType") == "text/plain":
                    return decode_part(subpart)

    return ""


def get_recent_emails(service, hours: int = 24):
    """Fetch recent emails."""
    after_timestamp = int((datetime.now() - timedelta(hours=hours)).timestamp())

    try:
        results = service.users().messages().list(
            userId="me",
            q=f"after:{after_timestamp}",
            maxResults=20,
            includeSpamTrash=False,
        ).execute()

        messages = results.get("messages", [])
        emails = []

        for m in messages:
            try:
                msg = service.users().messages().get(
                    userId="me", id=m["id"], format="full"
                ).execute()

                subject = get_header(msg, "Subject")
                sender = get_header(msg, "From")
                body = get_email_body(msg)[:2000]
                labels = msg.get("labelIds", [])

                is_unread = "UNREAD" in labels
                is_jobber = any(
                    kw in (sender.lower() + " " + subject.lower())
                    for kw in ["jobber", "getjobber"]
                )

                emails.append({
                    "subject": subject or "(No Subject)",
                    "from": sender or "(Unknown)",
                    "body": body,
                    "unread": is_unread,
                    "jobber": is_jobber,
                    "id": m["id"],
                })
            except HttpError as e:
                logger.warning(f"Failed to fetch message {m['id']}: {e}")

        return emails

    except HttpError as e:
        logger.error(f"Gmail API error: {e}")
        return []


def send_to_sammie(text: str):
    """Send message to Letta agent."""
    url = f"{LETTA_API_BASE_URL}/v1/agents/{AGENT_ID}/messages"
    headers = {
        "Authorization": f"Bearer {LETTA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"input": text}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()

        reply = ""
        for msg in data.get("messages", []):
            if msg.get("message_type") == "assistant_message" and msg.get("content"):
                reply += msg["content"] + "\n"

        return reply.strip() or None

    except Exception as e:
        logger.error(f"Failed to send to Sammie: {e}")
        return None


def send_telegram(text: str):
    """Send message via Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")


def main():
    logger.info("Starting Gmail check...")

    try:
        service = get_gmail_service()
        emails = get_recent_emails(service)

        if not emails:
            send_telegram("✅ No new emails in the last 24h. Clean inbox!")
            logger.info("No new emails.")
            return

        jobber_emails = [e for e in emails if e["jobber"]]
        other_unread = [e for e in emails if not e["jobber"] and e["unread"]]

        # === JOBBER EMAILS ===
        for e in jobber_emails:
            email_text = (
                f"[AUTOMATED] Jobber Email\n"
                f"From: {e['from']}\n"
                f"Subject: {e['subject']}\n\n"
                f"{e['body']}"
            )
            reply = send_to_sammie(email_text)
            if reply:
                send_telegram(
                    f"🛠️ <b>Jobber Update</b>\n"
                    f"<b>{e['subject']}</b>\n\n"
                    f"{reply}"
                )
            else:
                logger.warning(f"No reply from Sammie for Jobber email: {e['subject']}")

        # === OTHER UNREAD EMAILS ===
        if other_unread:
            summaries = []
            for e in other_unread[:8]:  # Limit to avoid huge messages
                summaries.append(
                    f"From: {e['from']}\n"
                    f"Subject: {e['subject']}\n"
                    f"{e['body'][:400]}..."
                )

            combined = (
                "[AUTOMATED] Unread Emails\n\n"
                + "\n\n---\n\n".join(summaries)
            )

            reply = send_to_sammie(combined)
            if reply:
                send_telegram(f"📬 <b>Email Triage</b>\n\n{reply}")

        logger.info(f"Gmail check complete. Processed {len(emails)} emails.")

    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        send_telegram("⚠️ Gmail check failed. Check logs.")


if __name__ == "__main__":
    main()
