# Minimal passwordless-login email sender.
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_login_email(to: str, link: str, code: str) -> None:
    """Send a minimal login email with one action button and the fallback code."""
    if not settings.smtp_host:
        if settings.env == "dev":
            logger.info("DEV – login link: %s  code: %s", link, code)
        return

    subject = "Login"
    text_body = f"""Login

Open this link to continue:
{link}

Code: {code}

The link expires in 15 minutes.
"""
    html_body = f"""<!doctype html>
<html lang="en"><body>
<p>Login</p>
<p><a href="{link}" style="display:inline-block;padding:10px 14px;background:#f97316;color:#fff;text-decoration:none">Continue</a></p>
<p>Code: <strong>{code}</strong></p>
<p>The link expires in 15 minutes.</p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        port = settings.smtp_port
        if port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, port) as server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_from, [to], msg.as_bytes())
        else:
            with smtplib.SMTP(settings.smtp_host, port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_from, [to], msg.as_bytes())
    except Exception:
        logger.exception("Failed to send login email to %s", to)
