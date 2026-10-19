"""ePub direkt auf der Kommandozeile erstellen – praktisch zum Testen.

    python3 -m app.cli "Ulmer Münster" "Praha@cs" -t "Testbuch" -o test.epub

Ein Artikel ohne @sprache wird aus der deutschsprachigen Wikipedia geholt.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .epub import build_epub
from .wiki import fetch_article


async def _main(args) -> None:
    articles = []
    for spec in args.articles:
        title, _, lang = spec.rpartition("@") if "@" in spec else (spec, "", args.lang)
        print(f"Lade {lang}:{title} …")
        articles.append(await fetch_article(lang or args.lang, title))
    res = await build_epub(articles, args.title or articles[0].title, Path(args.output),
                           with_images=not args.no_images, progress=lambda m: print("  " + m))
    print(f"Fertig: {res.path} ({res.size // 1024} KB, {res.image_count} Bilder)")
    for w in res.warnings:
        print("Hinweis:", w)


def main() -> None:
    p = argparse.ArgumentParser(description="Wikipedia-Artikel als ePub")
    p.add_argument("articles", nargs="+", help='Artikeltitel, optional mit Sprache: "Praha@cs"')
    p.add_argument("-l", "--lang", default="de", help="Standardsprache (de)")
    p.add_argument("-t", "--title", help="Buchtitel")
    p.add_argument("-o", "--output", default="wikipedia.epub")
    p.add_argument("--no-images", action="store_true", help="ohne Bilder")
    asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    main()
