"""Versand eines ePubs per E-Mail (z.B. an die Send-to-PocketBook-Adresse)."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .config import CONFIG


class MailError(Exception):
    pass


def send_epub(to_addr: str, title: str, path: Path, download_name: str) -> None:
    smtp = CONFIG.smtp
    if not smtp.configured:
        raise MailError("Der Mailversand ist noch nicht eingerichtet (Abschnitt [smtp] in config.toml).")
    if not to_addr:
        raise MailError("Es ist noch keine Empfängeradresse für den Reader hinterlegt (Einstellungen).")

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = smtp.sender
    msg["To"] = to_addr
    msg.set_content(f"„{title}“ – erstellt mit lesen.svetho.net.\n")
    msg.add_attachment(path.read_bytes(), maintype="application", subtype="epub+zip",
                       filename=download_name)

    ctx = ssl.create_default_context()
    try:
        if smtp.security == "ssl":
            with smtplib.SMTP_SSL(smtp.host, smtp.port, context=ctx, timeout=60) as s:
                if smtp.user:
                    s.login(smtp.user, smtp.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(smtp.host, smtp.port, timeout=60) as s:
                if smtp.security != "none":  # "none" nur für einen lokalen Mailserver
                    s.starttls(context=ctx)
                if smtp.user:
                    s.login(smtp.user, smtp.password)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("Anmeldung beim Mailserver fehlgeschlagen – Benutzer/App-Passwort prüfen.") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Versand fehlgeschlagen: {exc}") from exc
