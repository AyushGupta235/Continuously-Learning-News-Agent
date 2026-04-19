"""
Send the composed digest via the Resend API.
"""

import logging
from datetime import date

import resend

from config import DIGEST_EMAIL, RESEND_API_KEY

log = logging.getLogger(__name__)


def send(html: str) -> str:
    """
    Send the digest email. Returns the Resend email ID on success.
    Raises on failure — caller should handle and abort the pipeline.
    """
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY is not set")
    if not DIGEST_EMAIL:
        raise RuntimeError("DIGEST_EMAIL is not set")

    resend.api_key = RESEND_API_KEY

    subject = f"Your digest — {date.today().strftime('%A, %d %b')}"

    params: resend.Emails.SendParams = {
        "from": f"Your Digest <{DIGEST_EMAIL}>",
        "to": [DIGEST_EMAIL],
        "subject": subject,
        "html": html,
    }

    result = resend.Emails.send(params)
    email_id = result.get("id", "unknown")
    log.info("Email sent: id=%s  to=%s  subject=%s", email_id, DIGEST_EMAIL, subject)
    return email_id


if __name__ == "__main__":
    # Quick send test with a minimal HTML payload
    html = "<h1>Test digest</h1><p>Pipeline smoke test.</p>"
    try:
        eid = send(html)
        print(f"Sent! id={eid}")
    except Exception as e:
        print(f"Send failed: {e}")
