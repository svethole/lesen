"""Web-App „Lesen“: Wikipedia-Artikel suchen, sammeln und als ePub ausgeben."""
from __future__ import annotations

import asyncio
import re
import unicodedata
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from lxml import etree
from pydantic import BaseModel, Field

from . import db
from .cleaner import XHTML_NS, clean_article, to_html_fragment
from .config import BASE_DIR, CONFIG
from .epub import build_epub
from .mailer import MailError, send_epub
from .wiki import WikiError, fetch_article, search

STATIC = BASE_DIR / "static"

app = FastAPI(title="Lesen", docs_url=None, redoc_url=None)
db.init()


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def slugify(text: str, maxlen: int = 60) -> str:
    text = text.replace("ß", "ss")
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return (text[:maxlen].rstrip("-") or "wikipedia")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def valid_lang(code: str) -> str:
    code = (code or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,15}", code):
        raise HTTPException(400, "Ungültiger Sprachcode.")
    return code


def book_or_404(book_id: int) -> dict:
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(404, "ePub nicht gefunden.")
    return book


def book_path(book: dict) -> Path:
    return db.books_dir() / book["filename"]


# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------

class Language(BaseModel):
    code: str
    name: str


class SettingsIn(BaseModel):
    languages: list[Language] | None = None
    default_lang: str | None = None
    reader_email: str | None = None


@app.get("/api/settings")
def get_settings():
    s = db.get_settings()
    s["smtp_configured"] = CONFIG.smtp.configured
    s["smtp_sender"] = CONFIG.smtp.sender
    return s


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    values: dict = {}
    if body.languages is not None:
        langs, seen = [], set()
        for lang in body.languages:
            code = valid_lang(lang.code)
            if code in seen:
                continue
            seen.add(code)
            langs.append({"code": code, "name": lang.name.strip() or code})
        if not langs:
            raise HTTPException(400, "Mindestens eine Sprache wird benötigt.")
        values["languages"] = langs
    if body.default_lang is not None:
        values["default_lang"] = valid_lang(body.default_lang)
    if body.reader_email is not None:
        email = body.reader_email.strip()
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise HTTPException(400, "Die E-Mail-Adresse sieht nicht gültig aus.")
        values["reader_email"] = email
    s = db.save_settings(values)
    codes = [l["code"] for l in s["languages"]]
    if s["default_lang"] not in codes:
        s = db.save_settings({"default_lang": codes[0]})
    return get_settings()


# ---------------------------------------------------------------------------
# Suche und Vorschau
# ---------------------------------------------------------------------------

@app.get("/api/search")
async def api_search(q: str, lang: str = "de", offset: int = 0):
    q = q.strip()
    if not q:
        return {"results": [], "total": 0, "next_offset": None}
    try:
        return await search(valid_lang(lang), q, offset=max(0, offset))
    except WikiError as exc:
        raise HTTPException(502, str(exc))


@app.get("/api/preview")
async def api_preview(title: str, lang: str = "de"):
    lang = valid_lang(lang)
    try:
        art = await fetch_article(lang, title)
    except WikiError as exc:
        raise HTTPException(502, str(exc))
    result = await asyncio.to_thread(
        clean_article, art.html, lang, mode="preview",
        extra_drop=CONFIG.extra_drop_sections.get(lang, []))
    return {"title": art.title, "lang": lang, "url": art.url, "html": to_html_fragment(result.body)}


# ---------------------------------------------------------------------------
# ePub-Erstellung (als Hintergrundauftrag mit Fortschrittsanzeige)
# ---------------------------------------------------------------------------

class ArticleRef(BaseModel):
    lang: str
    title: str


class BookIn(BaseModel):
    title: str = ""
    articles: list[ArticleRef] = Field(min_length=1, max_length=200)
    images: bool = True


JOBS: dict[str, dict] = {}


async def _run_job(job_id: str, body: BookIn) -> None:
    job = JOBS[job_id]
    try:
        articles = []
        for i, ref in enumerate(body.articles, 1):
            job["message"] = f"Lade Artikel {i} von {len(body.articles)}: {ref.title}"
            articles.append(await fetch_article(valid_lang(ref.lang), ref.title))
        title = body.title.strip()
        if not title:
            title = articles[0].title
            if len(articles) > 1:
                title += f" und {len(articles) - 1} weitere"

        async def progress(msg: str) -> None:
            job["message"] = msg

        filename = f"{db.next_book_id():04d}-{slugify(title)}-{uuid.uuid4().hex[:6]}.epub"
        res = await build_epub(articles, title, db.books_dir() / filename,
                               with_images=body.images, progress=progress)
        book_id = db.add_book(title, now_iso(), filename, res.size, res.image_count,
                              res.chapters, res.warnings)
        job.update(status="done", message="Fertig!", book_id=book_id, warnings=res.warnings)
    except WikiError as exc:
        job.update(status="error", message=str(exc))
    except Exception as exc:  # noqa: BLE001 – Fehler sichtbar machen statt hängen lassen
        job.update(status="error", message=f"Unerwarteter Fehler: {exc}")


@app.post("/api/books")
async def create_book(body: BookIn):
    # Alte Aufträge aufräumen
    for jid in [k for k, v in JOBS.items() if v["status"] != "running"][:-20]:
        JOBS.pop(jid, None)
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "running", "message": "Starte …", "book_id": None, "warnings": []}
    asyncio.create_task(_run_job(job_id, body))
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Auftrag unbekannt.")
    return job


# ---------------------------------------------------------------------------
# Archiv
# ---------------------------------------------------------------------------

@app.get("/api/books")
def list_books():
    return db.list_books()


@app.get("/api/books/{book_id}")
def get_book(book_id: int):
    return book_or_404(book_id)


@app.delete("/api/books/{book_id}")
def delete_book(book_id: int):
    if not db.delete_book(book_id):
        raise HTTPException(404, "ePub nicht gefunden.")
    return {"ok": True}


@app.get("/api/books/{book_id}/download")
def download_book(book_id: int):
    book = book_or_404(book_id)
    path = book_path(book)
    if not path.exists():
        raise HTTPException(410, "Die Datei fehlt auf dem Server.")
    return FileResponse(path, media_type="application/epub+zip",
                        filename=f"{slugify(book['title'])}.epub")


@app.post("/api/books/{book_id}/send")
async def send_book(book_id: int):
    book = book_or_404(book_id)
    to = db.get_settings().get("reader_email", "")
    try:
        await asyncio.to_thread(send_epub, to, book["title"], book_path(book),
                                f"{slugify(book['title'])}.epub")
    except MailError as exc:
        raise HTTPException(400, str(exc))
    when = now_iso()
    db.mark_sent(book_id, when)
    return {"ok": True, "to": to, "sent_at": when}


# ---------------------------------------------------------------------------
# Lesemodus: Kapitel und Bilder direkt aus der ePub-Datei
# ---------------------------------------------------------------------------

_IMG_NAME = re.compile(r"^(?:img\d{4}\.(?:jpg|png)|cover\.jpg)$")


@app.get("/api/books/{book_id}/chapters/{index}")
def reader_chapter(book_id: int, index: int):
    book = book_or_404(book_id)
    chapters = book["chapters"]
    if not 0 <= index < len(chapters):
        raise HTTPException(404, "Kapitel nicht gefunden.")
    ch = chapters[index]
    files = {c["file"]: i for i, c in enumerate(chapters)}
    try:
        with zipfile.ZipFile(book_path(book)) as z:
            raw = z.read(f"OEBPS/text/{ch['file']}")
    except (OSError, KeyError, zipfile.BadZipFile):
        raise HTTPException(410, "Die Datei fehlt oder ist beschädigt.")
    doc = etree.fromstring(raw)
    body = doc.find(f"{{{XHTML_NS}}}body")
    for img in body.iter(f"{{{XHTML_NS}}}img"):
        name = (img.get("src") or "").rsplit("/", 1)[-1]
        img.set("src", f"/api/books/{book_id}/images/{name}")
        img.set("loading", "lazy")
    for a in body.iter(f"{{{XHTML_NS}}}a"):
        href = a.get("href") or ""
        target, _, frag = href.partition("#")
        if target in files:
            a.set("href", "#")
            a.set("data-chapter", str(files[target]))
            if frag:
                a.set("data-section", frag)
        elif href.startswith("http"):
            a.set("target", "_blank")
            a.set("rel", "noopener")
    return {"index": index, "title": ch["title"], "lang": ch["lang"],
            "html": to_html_fragment(body)}


@app.get("/api/books/{book_id}/images/{name}")
def reader_image(book_id: int, name: str):
    if not _IMG_NAME.match(name):
        raise HTTPException(404)
    book = book_or_404(book_id)
    try:
        with zipfile.ZipFile(book_path(book)) as z:
            data = z.read(f"OEBPS/images/{name}")
    except (OSError, KeyError, zipfile.BadZipFile):
        raise HTTPException(404)
    media = "image/png" if name.endswith(".png") else "image/jpeg"
    return Response(data, media_type=media, headers={"Cache-Control": "public, max-age=31536000"})


# ---------------------------------------------------------------------------
# Seiten
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/lesen/{book_id}")
def reader_page(book_id: int):
    return FileResponse(STATIC / "reader.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
