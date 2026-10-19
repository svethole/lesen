"""Entwicklungsserver ohne Internet: Wikipedia wird mit den Testartikeln
aus tests/fixtures simuliert, Bilder werden erzeugt.

    LESEN_CONFIG=/pfad/zur/test-config.toml python3 tests/mock_server.py
"""
import io
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app import epub as epub_mod  # noqa: E402
from app import main  # noqa: E402
from app.images import convert_image  # noqa: E402
from app.wiki import Article, WikiError  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
DE = (FIX / "de_ulmer_muenster.html").read_text()
CS = (FIX / "cs_praha.html").read_text()

TITLES = {
    "de": [("Ulmer Münster", "Kirche in Ulm"), ("Freiburger Münster", "Kathedrale in Freiburg im Breisgau"),
           ("Regensburger Dom", "Kathedrale in Regensburg"), ("Kölner Dom", "Kathedrale in Köln"),
           ("Frauenkirche (München)", "Kirche in München"), ("Gotik", "Epoche der europäischen Kunst"),
           ("Ulm", "Stadt in Baden-Württemberg"), ("Reformation", "Kirchliche Erneuerungsbewegung")],
    "cs": [("Praha", "hlavní město Česka"), ("Vltava", "řeka v Česku"), ("Libuše", "pověstná kněžna")],
}


async def fake_search(lang, query, offset=0, limit=20):
    items = TITLES.get(lang, [])
    q = query.lower()
    hits = [t for t in items if q in t[0].lower() or q in t[1].lower()] or items
    results = [{"title": t, "description": d,
                "snippet": f"Das ist ein Ausschnitt über <mark>{query}</mark> im Artikel {t}",
                "words": 1234, "thumb": None} for t, d in hits]
    return {"results": results[offset:offset + limit], "total": len(results), "next_offset": None}


async def fake_fetch(lang, title):
    if title == "Gibt es nicht":
        raise WikiError("Artikel „Gibt es nicht“ nicht gefunden.")
    base = CS if lang == "cs" else DE
    html = base.replace("Ulmer Münster", title) if lang != "cs" else base.replace("Praha", title)
    return Article(lang=lang, title=title, revid=random.randint(1000, 99999), html=html)


async def fake_image(client, url, fallback):
    rnd = random.Random(url)
    im = Image.new("RGB", (900, rnd.choice([600, 700, 1200])),
                   tuple(rnd.randint(60, 200) for _ in range(3)))
    d = ImageDraw.Draw(im)
    for _ in range(12):
        x, y = rnd.randint(0, 800), rnd.randint(0, 600)
        d.ellipse([x, y, x + 150, y + 150], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return convert_image(buf.getvalue())


class _DummyClient:
    async def aclose(self):
        pass


main.search = fake_search
main.fetch_article = fake_fetch
epub_mod.fetch_image = fake_image
epub_mod.make_client = lambda: _DummyClient()

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8077)
