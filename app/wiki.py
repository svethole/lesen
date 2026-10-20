"""Zugriff auf die Wikipedia-API (Suche und Artikel-HTML)."""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

from .config import CONFIG


class WikiError(Exception):
    pass


@dataclass
class Article:
    lang: str
    title: str
    revid: int
    html: str
    # Andere Sprachversionen: [{"lang": "cs", "title": "…", "autonym": "čeština"}]
    langlinks: list[dict] = field(default_factory=list)

    @property
    def url(self) -> str:
        return article_url(self.lang, self.title)


def article_url(lang: str, title: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='()_,:')}"


def _api(lang: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,15}", lang):
        raise WikiError(f"Ungültiger Sprachcode: {lang}")
    return f"https://{lang}.wikipedia.org/w/api.php"


_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers={"User-Agent": CONFIG.user_agent, "Accept-Encoding": "gzip"},
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
    return _client


async def _get(lang: str, params: dict) -> dict:
    params = {"format": "json", "formatversion": "2", "utf8": "1", **params}
    try:
        r = await client().get(_api(lang), params=params)
    except httpx.HTTPError as exc:
        raise WikiError(f"Wikipedia ist nicht erreichbar ({exc.__class__.__name__}).") from exc
    if r.status_code != 200:
        raise WikiError(f"Wikipedia hat mit Fehler {r.status_code} geantwortet.")
    data = r.json()
    if "error" in data:
        raise WikiError(data["error"].get("info", "Unbekannter Fehler"))
    return data


_TAG_RE = re.compile(r"<[^>]+>")


def _snippet(raw: str) -> str:
    """Suchtreffer-Ausschnitt: nur die Hervorhebungen behalten (als <mark>)."""
    raw = raw.replace('<span class="searchmatch">', "\x01").replace("</span>", "\x02")
    text = html.escape(html.unescape(_TAG_RE.sub("", raw)))
    return text.replace("\x01", "<mark>").replace("\x02", "</mark>")


async def search(lang: str, query: str, offset: int = 0, limit: int = 20) -> dict:
    data = await _get(lang, {
        "action": "query", "list": "search", "srsearch": query, "srlimit": str(limit),
        "sroffset": str(offset), "srprop": "snippet|wordcount", "srinfo": "totalhits",
    })
    hits = data.get("query", {}).get("search", [])
    results = [{
        "title": h["title"],
        "snippet": _snippet(h.get("snippet", "")),
        "words": h.get("wordcount", 0),
        "description": "",
        "thumb": None,
    } for h in hits]

    if results:
        # Kurzbeschreibung und Vorschaubild nachladen (hilft beim Auswählen)
        try:
            extra = await _get(lang, {
                "action": "query", "titles": "|".join(r["title"] for r in results),
                "prop": "description|pageimages", "piprop": "thumbnail",
                "pithumbsize": "120", "pilimit": str(len(results)),
            })
            pages = {p["title"]: p for p in extra.get("query", {}).get("pages", [])}
            for r in results:
                p = pages.get(r["title"], {})
                r["description"] = p.get("description", "")
                if "thumbnail" in p:
                    r["thumb"] = p["thumbnail"]["source"]
        except WikiError:
            pass

    cont = data.get("continue", {}).get("sroffset")
    return {
        "results": results,
        "total": data.get("query", {}).get("searchinfo", {}).get("totalhits", 0),
        "next_offset": cont,
    }


# Kleiner Zwischenspeicher, damit Vorschau und ePub-Erstellung nicht doppelt laden
_CACHE: dict[tuple[str, str], tuple[float, Article]] = {}
_CACHE_TTL = 3600
_CACHE_MAX = 300


async def fetch_article(lang: str, title: str) -> Article:
    key = (lang, title)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    data = await _get(lang, {
        "action": "parse", "page": title, "prop": "text|revid|langlinks", "redirects": "1",
        "disableeditsection": "1", "disabletoc": "1", "disablelimitreport": "1",
    })
    p = data.get("parse") or {}
    if not p.get("text"):
        raise WikiError(f"Artikel „{title}“ nicht gefunden.")
    links = [{"lang": l.get("lang", ""), "title": l.get("title") or l.get("*", ""),
              "autonym": l.get("autonym") or l.get("langname") or l.get("lang", "")}
             for l in p.get("langlinks", [])]
    art = Article(lang=lang, title=p.get("title", title), revid=p.get("revid", 0), html=p["text"],
                  langlinks=links)
    if len(_CACHE) >= _CACHE_MAX:
        for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[: _CACHE_MAX // 3]:
            _CACHE.pop(k, None)
    _CACHE[key] = (time.time(), art)
    _CACHE[(lang, art.title)] = (time.time(), art)
    return art


async def random_title(lang: str) -> str:
    data = await _get(lang, {"action": "query", "list": "random", "rnnamespace": "0", "rnlimit": "1"})
    items = data.get("query", {}).get("random", [])
    if not items:
        raise WikiError("Kein zufälliger Artikel gefunden.")
    return items[0]["title"]
