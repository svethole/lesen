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
