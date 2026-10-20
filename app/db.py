"""SQLite-Speicher für erstellte ePubs und Einstellungen."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import CONFIG

DEFAULT_LANGUAGES = [
    {"code": "de", "name": "Deutsch"},
    {"code": "nl", "name": "Niederländisch"},
    {"code": "da", "name": "Dänisch"},
    {"code": "sv", "name": "Schwedisch"},
    {"code": "cs", "name": "Tschechisch"},
    {"code": "it", "name": "Italienisch"},
    {"code": "fr", "name": "Französisch"},
    {"code": "es", "name": "Spanisch"},
]
DEFAULT_SETTINGS = {
    "languages": DEFAULT_LANGUAGES,
    "default_lang": "de",
    "reader_email": "",
}


def db_path() -> Path:
    return CONFIG.data_dir / "lesen.sqlite3"


def books_dir() -> Path:
    return CONFIG.data_dir / "books"


@contextmanager
def connect():
    CONFIG.data_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    books_dir().mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                filename TEXT NOT NULL,
                size INTEGER NOT NULL,
                image_count INTEGER NOT NULL DEFAULT 0,
                chapters TEXT NOT NULL,
                warnings TEXT NOT NULL DEFAULT '[]',
                sent_at TEXT
            );
            -- Wikipedia-Lesemodus: Verlauf (last_read) und Favoriten (fav_at) in einem
            CREATE TABLE IF NOT EXISTS reading (
                lang TEXT NOT NULL,
                title TEXT NOT NULL,
                excerpt TEXT NOT NULL DEFAULT '',
                last_read TEXT,
                frac REAL NOT NULL DEFAULT 0,
                fav_at TEXT,
                PRIMARY KEY (lang, title)
            );
            CREATE INDEX IF NOT EXISTS reading_last ON reading(last_read);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)


def _book(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["chapters"] = json.loads(d["chapters"])
    d["warnings"] = json.loads(d["warnings"])
    return d


def list_books() -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT * FROM books ORDER BY created_at DESC, id DESC").fetchall()
    return [_book(r) for r in rows]


def get_book(book_id: int) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return _book(row) if row else None


def add_book(title: str, created_at: str, filename: str, size: int, image_count: int,
             chapters: list, warnings: list) -> int:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO books (title, created_at, filename, size, image_count, chapters, warnings) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, created_at, filename, size, image_count,
             json.dumps(chapters, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False)))
        return cur.lastrowid


def next_book_id() -> int:
    with connect() as con:
        row = con.execute("SELECT seq FROM sqlite_sequence WHERE name = 'books'").fetchone()
    return (row[0] if row else 0) + 1


def mark_sent(book_id: int, when: str) -> None:
    with connect() as con:
        con.execute("UPDATE books SET sent_at = ? WHERE id = ?", (when, book_id))


def delete_book(book_id: int) -> dict | None:
    book = get_book(book_id)
    if not book:
        return None
    with connect() as con:
        con.execute("DELETE FROM books WHERE id = ?", (book_id,))
    (books_dir() / book["filename"]).unlink(missing_ok=True)
    return book


def get_settings() -> dict:
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    with connect() as con:
        for row in con.execute("SELECT key, value FROM settings"):
            out[row["key"]] = json.loads(row["value"])
    return out


def save_settings(values: dict) -> dict:
    with connect() as con:
        for key, value in values.items():
            if key in DEFAULT_SETTINGS:
                con.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                            (key, json.dumps(value, ensure_ascii=False)))
    return get_settings()


# ---------------------------------------------------------------------------
# Wikipedia-Lesemodus
# ---------------------------------------------------------------------------

def get_reading(lang: str, title: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM reading WHERE lang = ? AND title = ?", (lang, title)).fetchone()
    return dict(row) if row else None


def touch_reading(lang: str, title: str, excerpt: str, when: str) -> dict:
    """Artikel wurde geöffnet: in den Verlauf aufnehmen (oder nach oben schieben)."""
    with connect() as con:
        con.execute(
            "INSERT INTO reading (lang, title, excerpt, last_read) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(lang, title) DO UPDATE SET last_read = excluded.last_read, "
            "excerpt = CASE WHEN excluded.excerpt != '' THEN excluded.excerpt ELSE reading.excerpt END",
            (lang, title, excerpt, when))
    return get_reading(lang, title)


def update_reading(lang: str, title: str, *, frac: float | None = None,
                   favorite: bool | None = None, when: str = "") -> dict | None:
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO reading (lang, title) VALUES (?, ?)", (lang, title))
        if frac is not None:
            con.execute("UPDATE reading SET frac = ? WHERE lang = ? AND title = ?",
                        (max(0.0, min(1.0, frac)), lang, title))
        if favorite is not None:
            con.execute("UPDATE reading SET fav_at = ? WHERE lang = ? AND title = ?",
                        (when if favorite else None, lang, title))
        con.execute("DELETE FROM reading WHERE last_read IS NULL AND fav_at IS NULL")
    return get_reading(lang, title)


def list_reading(kind: str, limit: int = 200) -> list[dict]:
    col = "fav_at" if kind == "favorites" else "last_read"
    with connect() as con:
        rows = con.execute(f"SELECT * FROM reading WHERE {col} IS NOT NULL ORDER BY {col} DESC LIMIT ?",
                           (limit,)).fetchall()
    return [dict(r) for r in rows]


def forget_history(lang: str | None = None, title: str | None = None) -> None:
    """Eintrag (oder ganzen Verlauf) entfernen; Favoriten bleiben erhalten."""
    with connect() as con:
        if lang and title:
            con.execute("UPDATE reading SET last_read = NULL, frac = 0 WHERE lang = ? AND title = ?",
                        (lang, title))
        else:
            con.execute("UPDATE reading SET last_read = NULL, frac = 0")
        con.execute("DELETE FROM reading WHERE last_read IS NULL AND fav_at IS NULL")
