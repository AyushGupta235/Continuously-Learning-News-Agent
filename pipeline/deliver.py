"""
Send the composed digest via Gmail SMTP.
"""

import logging
import re
import smtplib
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import DIGEST_EMAIL, GMAIL_APP_PASSWORD

log = logging.getLogger(__name__)

GMAIL_SMTP = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


def _html_to_plain(html: str) -> str:
    """Very rough HTML → plain text for the fallback MIME part."""
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def send(
    html: str,
    amp_html: str | None = None,
    recipient_email: str | None = None,
    sender_name: str = "Your Digest",
) -> str:
    """
    Send the digest email via Gmail SMTP. Returns a message ID on success.
    Raises on failure — caller should handle and abort the pipeline.

    html:            rendered HTML part (required).
    amp_html:        rendered AMP for Email part (optional; enables interactive
                     feedback buttons in Gmail when Dynamic Email is enabled).
    recipient_email: address to deliver to. Defaults to DIGEST_EMAIL (single-user mode).
    sender_name:     display name in the email subject line.
    """
    if not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_APP_PASSWORD is not set")
    if not DIGEST_EMAIL:
        raise RuntimeError("DIGEST_EMAIL is not set")

    to_addr = recipient_email or DIGEST_EMAIL
    subject = f"{sender_name} — {date.today().strftime('%A, %d %b')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = DIGEST_EMAIL
    msg["To"] = to_addr

    # Parts must go lowest → highest fidelity; email client picks the last it supports.
    msg.attach(MIMEText(_html_to_plain(html), "plain"))
    msg.attach(MIMEText(html, "html"))
    if amp_html:
        msg.attach(MIMEText(amp_html, "x-amp+html"))
        log.info("AMP part attached (%d chars)", len(amp_html))

    try:
        with smtplib.SMTP(GMAIL_SMTP, GMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(DIGEST_EMAIL, GMAIL_APP_PASSWORD)
            server.send_message(msg)

        message_id = msg["Message-ID"] or "unknown"
        log.info("Email sent: to=%s  subject=%s", to_addr, subject)
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
