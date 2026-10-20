# Lesen

Wikipedia-Artikel suchen, zu einem Sammelband zusammenstellen und als ePub für den eBook-Reader ausgeben – oder gleich im Browser lesen.

- **Suchen** in der Wikipedia mit einstellbaren Sprachen (Standard: Deutsch, Niederländisch, Dänisch, Schwedisch, Tschechisch, Italienisch, Französisch, Spanisch)
- **Vorschau** jedes Artikels im Overlay, so wie er später im Buch steht; Links darin öffnen weitere Artikel
- **Sammelband** mit Reihenfolge, Buchtitel und Bildern ein/aus
- **Bibliothek** aller erstellten ePubs, neueste zuerst: herunterladen, per E-Mail an den Reader schicken, im Browser lesen
- **Lesemodus** fürs Handy: Schriftart, Schriftgröße bis 48 px, Hintergrund (auch eigene Farbe und das warme „Glut“ für die Nacht), zusätzliches Abdunkeln unter die geringste Bildschirmhelligkeit, Zeilenabstand, Seitenrand, Blocksatz; die Leseposition wird gemerkt
- **Wikipedia lesen** unter `/wiki`: Artikel direkt suchen und bereinigt im Lesemodus lesen – mit Verlauf (inkl. Leseposition), Favoriten, Inhaltsverzeichnis, denselben Artikel in den anderen eingestellten Sprachen, zufälligem Artikel und „In den Sammelband“. Verlauf und Favoriten liegen auf dem Server, Handy und Rechner sehen also dasselbe. Die Darstellung teilt sich der Wikipedia-Lesemodus mit dem ePub-Reader.

## Was beim ePub beachtet wird

Damit die Bücher auch auf strengen Readern (PocketBook, Tolino, Kobo, Adobe-Engine) laufen:

- EPUB 3 *plus* EPUB-2-Inhaltsverzeichnis (`toc.ncx`) und `<guide>` für ältere Lese-Engines
- `mimetype` als erste, unkomprimierte Datei
- jedes Kapitel ist wohlgeformtes XHTML, das aus einer Positivliste von Elementen neu aufgebaut wird – keine HTML-Entities, keine unbekannten Tags, keine Inline-Styles
- Bilder werden immer neu kodiert: Baseline-JPEG (Fotos) oder PNG (Grafiken), RGB, ohne Transparenz, max. 1000 × 1400 px. WebP, SVG, CMYK, progressive JPEGs und animierte GIFs kommen so nie im Buch an
- schlichtes CSS ohne Schriftvorgaben – Schrift und Größe bestimmt der Reader
- ein generiertes Titelbild
- jede Datei wird in den Tests mit [EPUBCheck](https://www.w3.org/publishing/epubcheck/) geprüft

Entfernt werden: Bearbeiten-Links, Einzelnachweise und Fußnotenzeichen, Literatur, Weblinks, „Siehe auch“, Anmerkungen, Infoboxen, alle Tabellen, Navigationsleisten, Normdaten, Koordinaten, Begriffsklärungshinweise, Wartungsbausteine, Audio und Video. Formeln erscheinen als TeX-Text. Links auf Artikel, die im selben Buch stehen, bleiben als Sprung zum Kapitel erhalten; alle anderen werden zu normalem Text. Die Abschnittsnamen dafür kennt das Programm für alle voreingestellten Sprachen (plus Englisch, Polnisch, Norwegisch, Portugiesisch); eigene lassen sich in `config.toml` ergänzen.

## Installation auf dem Server

Voraussetzung: Python 3.11 oder neuer, nginx, certbot (Debian 12/13: `sudo apt install git python3-venv apache2-utils certbot python3-certbot-nginx`) und ein DNS-Eintrag für die Subdomain.

```bash
# Programm holen
sudo useradd --system --home /opt/lesen --shell /usr/sbin/nologin lesen
sudo git clone https://github.com/svethole/lesen.git /opt/lesen
cd /opt/lesen
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt

# Konfiguration
sudo cp config.example.toml config.toml
sudo nano config.toml            # User-Agent mit Kontaktadresse, SMTP-Daten
sudo mkdir -p data
sudo chown -R lesen:lesen data
sudo chown root:lesen config.toml && sudo chmod 640 config.toml

# Erst einmal von Hand testen (holt echte Artikel inkl. Bilder)
sudo -u lesen LESEN_CONFIG=/opt/lesen/config.toml .venv/bin/python -m app.cli "Ulmer Münster" "Praha@cs" -o /tmp/test.epub

# Dienst einrichten
sudo cp deploy/lesen.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lesen
systemctl status lesen

# nginx mit Passwortschutz
sudo htpasswd -c /etc/nginx/.htpasswd-lesen DEINNAME
sudo cp deploy/nginx-lesen.conf /etc/nginx/sites-available/lesen.svetho.net
sudo ln -s /etc/nginx/sites-available/lesen.svetho.net /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# HTTPS: certbot ergänzt Zertifikat und Weiterleitung selbst in der nginx-Datei
sudo certbot --nginx -d lesen.svetho.net
```

Aktualisieren: `cd /opt/lesen && sudo git pull && sudo .venv/bin/pip install -r requirements.txt && sudo systemctl restart lesen`

## An den PocketBook schicken

1. In der PocketBook Cloud bzw. am Gerät unter *Send-to-PocketBook* die eigene Empfangsadresse nachschauen (endet auf `@pbsync.com`).
2. Dort die Absenderadresse aus `config.toml` (`sender`) als **vertrauenswürdigen Absender** eintragen – sonst verwirft PocketBook die Mail.
3. In „Lesen“ unter *Einstellungen* die Empfangsadresse eintragen.

Für Fastmail im Abschnitt `[smtp]` ein **App-Passwort** verwenden (Einstellungen → Datenschutz & Sicherheit → App-Passwörter, Zugriff „SMTP“).

## Entwicklung

```bash
pip install -r requirements.txt epubcheck aiosmtpd   # epubcheck braucht Java
python3 tests/test_build.py               # Test-ePubs aus den Fixtures bauen und prüfen
python3 tests/mock_server.py              # Oberfläche ohne Internet (simulierte Wikipedia)
```

Aufbau:

| Datei | Aufgabe |
|---|---|
| `app/wiki.py` | Wikipedia-API: Suche, Artikel-HTML (`action=parse`) |
| `app/cleaner.py` | Bereinigung und Neuaufbau als XHTML |
| `app/images.py` | Bilder laden und reader-tauglich umwandeln |
| `app/epub.py` | ePub zusammenbauen, Titelbild |
| `app/main.py` | Web-Schnittstelle (FastAPI) |
| `app/db.py` | SQLite: Bibliothek und Einstellungen |
| `app/mailer.py` | Versand per SMTP |
| `static/index.html`, `app.js` | Suche, Sammelband, Bibliothek, Einstellungen |
| `static/reader-common.js` | gemeinsame Darstellungs-Einstellungen beider Lesemodi |
| `static/reader.*` | Lesemodus für erstellte ePubs |
| `static/wiki.*` | Wikipedia-Lesemodus mit Verlauf und Favoriten |

Die Texte der Wikipedia stehen unter CC BY-SA 4.0; jedes Kapitel nennt am Ende Quelle, Version und Link.
