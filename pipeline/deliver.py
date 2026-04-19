"""
Send the composed digest via Gmail SMTP.
"""

import logging
import smtplib
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import DIGEST_EMAIL, GMAIL_APP_PASSWORD

log = logging.getLogger(__name__)

GMAIL_SMTP = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


def send(html: str) -> str:
    """
    Send the digest email via Gmail SMTP. Returns a message ID on success.
    Raises on failure — caller should handle and abort the pipeline.
    """
    if not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_APP_PASSWORD is not set")
    if not DIGEST_EMAIL:
        raise RuntimeError("DIGEST_EMAIL is not set")

    subject = f"Your digest — {date.today().strftime('%A, %d %b')}"

    # Create email message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = DIGEST_EMAIL
    msg["To"] = DIGEST_EMAIL

    # Attach HTML content
    part = MIMEText(html, "html")
    msg.attach(part)

    # Send via Gmail SMTP
    try:
        with smtplib.SMTP(GMAIL_SMTP, GMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(DIGEST_EMAIL, GMAIL_APP_PASSWORD)
            server.send_message(msg)

        message_id = msg["Message-ID"] or "unknown"
        log.info("Email sent: to=%s  subject=%s", DIGEST_EMAIL, subject)
        return message_id
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError(
            "Gmail authentication failed. Check GMAIL_APP_PASSWORD. "
            "Generate one at https://myaccount.google.com/apppasswords"
        )
    except smtplib.SMTPException as e:
        raise RuntimeError(f"Gmail SMTP error: {e}")


if __name__ == "__main__":
    # Quick send test with a minimal HTML payload
    html = "<h1>Test digest</h1><p>Pipeline smoke test.</p>"
    try:
        eid = send(html)
        print(f"Sent! id={eid}")
    except Exception as e:
        print(f"Send failed: {e}")
