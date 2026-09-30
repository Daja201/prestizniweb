# Email sending for login magic links and codes.
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_login_email(to: str, link: str, code: str) -> None:
    """Send a passwordless login email with a magic link and 6-digit code."""
    if not settings.smtp_host:
        if settings.env == "dev":
            logger.info("DEV – login link: %s  code: %s", link, code)
        return

    subject = "Přihlášení do komunity SPŠE Ostrava"

    text_body = f"""\
Přihlášení do komunity SPŠE Ostrava
=====================================

Klikni na odkaz níže nebo zadej kód {code} na stránce ověření.

Odkaz: {link}

Kód: {code}

Odkaz vyprší za 15 minut a lze jej použít pouze jednou.
Pokud ses o přihlášení nepokusil(a), tento email ignoruj.
"""

    html_body = f"""\
<!DOCTYPE html>
<html lang="cs">
<head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;max-width:480px;margin:auto">
  <h2>Přihlášení do komunity SPŠE&nbsp;Ostrava</h2>
  <p>Klikni na tlačítko nebo zadej kód na stránce ověření.</p>
  <p>
    <a href="{link}"
       style="display:inline-block;padding:10px 20px;background:#2563eb;
              color:#fff;text-decoration:none;border-radius:6px">
      Přihlásit se
    </a>
  </p>
  <p>Nebo zadej kód: <strong style="font-size:1.4em;letter-spacing:.15em">{code}</strong></p>
  <p style="color:#555;font-size:.85em">
    Odkaz vyprší za 15&nbsp;minut a lze jej použít pouze jednou.<br>
    Pokud ses o přihlášení nepokusil(a), tento email ignoruj.
  </p>
</body>
</html>
"""

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