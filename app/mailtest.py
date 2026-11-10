"""Mailversand prüfen – zeigt Schritt für Schritt, woran die Anmeldung scheitert.

    python -m app.mailtest                  # nur Verbindung und Anmeldung testen
    python -m app.mailtest --send ADRESSE   # zusätzlich eine Testmail schicken

Das Passwort wird nie angezeigt, nur Hinweise auf typische Tippfehler.
"""
from __future__ import annotations

import argparse
import smtplib
import ssl
import sys
from email.message import EmailMessage

from .config import CONFIG

OK, FAIL, WARN = "  ✔", "  ✘", "  !"


def check_password(pw: str) -> list[str]:
    hints = []
    if not pw:
        hints.append("Das Passwort ist leer.")
        return hints
    if pw != pw.strip():
        hints.append("Das Passwort beginnt oder endet mit Leerzeichen.")
    if " " in pw.strip():
        hints.append("Das Passwort enthält Leerzeichen – beim Kopieren mitgenommen?")
    if any(ord(c) > 127 for c in pw):
        hints.append("Das Passwort enthält Sonderzeichen außerhalb von ASCII (z. B. typografische Anführungszeichen).")
    if pw in ("app-passwort", "passwort", "password"):
        hints.append("Das ist noch der Platzhalter aus config.example.toml.")
    return hints


def main() -> int:
    ap = argparse.ArgumentParser(description="Mailversand prüfen")
    ap.add_argument("--send", metavar="ADRESSE", help="Testmail an diese Adresse schicken")
    args = ap.parse_args()
    s = CONFIG.smtp

    print("Einstellungen aus config.toml:")
    print(f"    Server:     {s.host or '(leer)'}:{s.port}  ({s.security})")
    print(f"    Benutzer:   {s.user or '(leer)'}")
    print(f"    Absender:   {s.sender or '(leer)'}")
    print(f"    Passwort:   {len(s.password)} Zeichen")
    problems = check_password(s.password)
    for p in problems:
        print(WARN, p)
    if s.host.endswith("fastmail.com"):
        if s.security == "ssl" and s.port != 465:
            print(WARN, "Bei Fastmail gehört zu SSL der Port 465.")
        if s.security == "starttls" and s.port != 587:
            print(WARN, "Bei Fastmail gehört zu STARTTLS der Port 587.")
        if s.user and "@" not in s.user:
            print(WARN, "Fastmail erwartet als Benutzer die vollständige Login-Adresse.")
    if not s.host:
        print(FAIL, "Kein Mailserver eingetragen.")
        return 1

    print("\nVerbindung:")
    ctx = ssl.create_default_context()
    try:
        if s.security == "ssl":
            conn = smtplib.SMTP_SSL(s.host, s.port, context=ctx, timeout=30)
        else:
            conn = smtplib.SMTP(s.host, s.port, timeout=30)
            conn.ehlo()
            if s.security != "none":
                conn.starttls(context=ctx)
        conn.ehlo()
        print(OK, f"verbunden mit {s.host}:{s.port}")
    except (OSError, smtplib.SMTPException) as exc:
        print(FAIL, f"keine Verbindung: {exc}")
        print("    → Firewall/Port prüfen, oder security/port passen nicht zusammen.")
        return 1

    with conn:
        auth = conn.esmtp_features.get("auth", "")
        print(OK, f"Server bietet Anmeldung an: {auth.strip() or '(keine)'}")

        print("\nAnmeldung:")
        try:
            conn.login(s.user, s.password)
            print(OK, f"angemeldet als {s.user}")
        except smtplib.SMTPAuthenticationError as exc:
            msg = exc.smtp_error.decode(errors="replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
            print(FAIL, f"abgelehnt – Server sagt: {exc.smtp_code} {msg}")
            print("    Häufigste Ursachen bei Fastmail:")
            print("    1. Normales Passwort statt App-Passwort eingetragen")
            print("    2. App-Passwort ohne SMTP-Zugriff angelegt")
            print("    3. Benutzer ist ein Alias/eigene Domain statt der Fastmail-Login-Adresse")
            print("    4. Sonderzeichen im Passwort in config.toml falsch maskiert")
            return 1
        except smtplib.SMTPException as exc:
            print(FAIL, f"Anmeldung nicht möglich: {exc}")
            return 1

        if args.send:
            print("\nTestmail:")
            msg = EmailMessage()
            msg["Subject"] = "Testmail von lesen.svetho.net"
            msg["From"] = s.sender
            msg["To"] = args.send
            msg.set_content("Wenn diese Mail ankommt, funktioniert der Versand. 🙂\n")
            try:
                refused = conn.send_message(msg)
            except smtplib.SMTPException as exc:
                print(FAIL, f"nicht gesendet: {exc}")
                if "sender" in str(exc).lower() or "from" in str(exc).lower():
                    print("    → Der Absender muss bei Fastmail als Identität/Alias eingerichtet sein.")
                return 1
            if refused:
                print(FAIL, f"abgelehnt: {refused}")
                return 1
            print(OK, f"an {args.send} übergeben")

    print("\nAlles in Ordnung.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
