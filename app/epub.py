"""ePub-Erzeugung.

Ziel ist maximale Verträglichkeit mit eBook-Readern (PocketBook, Tolino,
Kobo, Adobe-RMSDK, KOReader …):

* EPUB 3.0 mit zusätzlichem EPUB-2-Inhaltsverzeichnis (toc.ncx) und <guide>
* `mimetype` als erste Datei, unkomprimiert, ohne Extra-Felder
* jedes Kapitel ist wohlgeformtes XHTML, erzeugt mit lxml (keine HTML-Entities)
* nur JPEG/PNG-Bilder, eindeutige, einfache IDs und Dateinamen
* schlichtes CSS ohne Schriftvorgaben – der Reader entscheidet
"""
from __future__ import annotations

import asyncio
import io
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from xml.sax.saxutils import escape, quoteattr

from lxml import etree
from PIL import Image, ImageDraw, ImageFont

from .cleaner import XHTML_NS, clean_article, norm_title
from .config import CONFIG
from .images import ConvertedImage, convert_image, fetch_image, make_client
from .wiki import Article

EPUB_NS = "http://www.idpf.org/2007/ops"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

LANG_NAMES = {
    "de": "Deutsch", "nl": "Niederländisch", "da": "Dänisch", "sv": "Schwedisch",
    "cs": "Tschechisch", "it": "Italienisch", "fr": "Französisch", "es": "Spanisch",
    "en": "Englisch",
}

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]

STYLESHEET = """\
/* Bewusst schlicht: Schriftart und -größe bestimmt der Reader. */
body { margin: 0; padding: 0; line-height: 1.4; }
h1 { font-size: 1.6em; line-height: 1.2; margin: 0 0 0.8em 0; text-align: left; page-break-after: avoid; }
h2 { font-size: 1.3em; line-height: 1.2; margin: 1.4em 0 0.4em 0; text-align: left; page-break-after: avoid; }
h3 { font-size: 1.15em; margin: 1.2em 0 0.3em 0; text-align: left; page-break-after: avoid; }
h4, h5, h6 { font-size: 1em; margin: 1em 0 0.3em 0; text-align: left; page-break-after: avoid; }
p { margin: 0 0 0.6em 0; text-indent: 0; }
ul, ol { margin: 0.3em 0 0.8em 0; padding-left: 1.4em; }
li { margin: 0 0 0.25em 0; }
dl { margin: 0.5em 0; }
dt { font-weight: bold; margin-top: 0.4em; }
dd { margin: 0 0 0.3em 1.2em; }
blockquote { margin: 0.8em 1.2em; font-style: italic; }
pre { white-space: pre-wrap; font-size: 0.85em; }
code.math { font-family: monospace; font-size: 0.9em; }
a { color: inherit; text-decoration: underline; }
div.figure { margin: 1em 0; text-align: center; page-break-inside: avoid; }
/* Bilder klein halten: etwa drei bis vier passen auf eine Reader-Seite.
   em für ältere Lese-Engines, vh für neuere (die das em-Maß überschreiben). */
div.figure img { max-width: 100%; max-height: 13em; max-height: 26vh; width: auto; height: auto; }
p.caption { font-size: 0.85em; font-style: italic; text-align: center; margin: 0.3em 0 0 0; }
p.lang { font-size: 0.8em; margin: -0.5em 0 1.2em 0; }
p.source { font-size: 0.75em; margin-top: 2.5em; padding-top: 0.5em; border-top: 1px solid #888; }
div.titlepage { text-align: center; margin-top: 3em; }
div.titlepage h1 { text-align: center; font-size: 2em; }
p.subtitle { font-size: 1.1em; margin-bottom: 2em; }
ol.contents { text-align: left; margin: 1.5em 0; }
p.license { font-size: 0.75em; margin-top: 3em; text-align: left; }
div.cover { text-align: center; margin: 0; padding: 0; }
div.cover img { max-width: 100%; max-height: 100%; }
"""


@dataclass
class Chapter:
    article: Article
    filename: str
    doc: etree._Element | None = None
    sections: list = field(default_factory=list)


@dataclass
class BuildResult:
    path: Path
    size: int
    chapters: list[dict]
    image_count: int
    warnings: list[str]


ProgressFn = Callable[[str], Awaitable[None] | None]


def german_date(d: datetime) -> str:
    return f"{d.day}. {MONTHS[d.month - 1]} {d.year}"


def _x(tag: str) -> str:
    return f"{{{XHTML_NS}}}{tag}"


def _new_doc(title: str, lang: str) -> tuple[etree._Element, etree._Element]:
    html = etree.Element(_x("html"), nsmap={None: XHTML_NS, "epub": EPUB_NS})
    html.set(XML_LANG, lang)
    html.set("lang", lang)
    head = etree.SubElement(html, _x("head"))
    t = etree.SubElement(head, _x("title"))
    t.text = title
    link = etree.SubElement(head, _x("link"))
    link.set("rel", "stylesheet")
    link.set("type", "text/css")
    link.set("href", "../style.css")
    body = etree.SubElement(html, _x("body"))
    return html, body


def _serialize(html: etree._Element) -> bytes:
    return (b'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            + etree.tostring(html, encoding="utf-8", pretty_print=True))


def _remove_img(img: etree._Element) -> None:
    parent = img.getparent()
    if parent is None:
        return
    if parent.tag == _x("div") and parent.get("class") == "figure":
        gp = parent.getparent()
        if gp is not None:
            gp.remove(parent)
            return
    if img.tail:
        prev = img.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + img.tail
        else:
            parent.text = (parent.text or "") + img.tail
    parent.remove(img)


# ---------------------------------------------------------------------------
# Titelbild
# ---------------------------------------------------------------------------

def _font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSerif.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        test = f"{line} {w}".strip()
        if draw.textlength(test, font=font) <= max_width or not line:
            line = test
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def make_cover(title: str, chapter_titles: list[str], date: datetime) -> bytes:
    W, H = 1200, 1600
    palette = [(46, 64, 87), (84, 56, 71), (52, 78, 65), (93, 74, 46), (60, 60, 92)]
    bg = palette[sum(map(ord, title)) % len(palette)]
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    d.rectangle([60, 60, W - 60, H - 60], outline=(235, 225, 205), width=4)
    d.text((W // 2, 170), "WIKIPEDIA", font=_font(46), fill=(235, 225, 205), anchor="mm")
    d.text((W // 2, 228), "Lesesammlung", font=_font(36), fill=(210, 200, 180), anchor="mm")

    size = 96
    while True:
        f = _font(size, bold=True)
        lines = _wrap(d, title, f, W - 260)
        if len(lines) <= 4 or size <= 48:
            break
        size -= 8
    lines = lines[:5]
    y = 330
    for ln in lines:
        d.text((W // 2, y), ln, font=f, fill=(255, 250, 240), anchor="ma")
        y += int(size * 1.2)
    y += 40
    d.line([160, y, W - 160, y], fill=(235, 225, 205), width=3)
    y += 80
    # Kapitel auflisten, so viele wie hinpassen
    f2 = _font(40)
    step = 60
    room = max(0, (H - 260 - y) // step)
    shown = chapter_titles[:room] if len(chapter_titles) <= room else chapter_titles[:max(room - 1, 0)]
    for ct in shown:
        line = ct
        while d.textlength(line, font=f2) > W - 320 and len(line) > 4:
            line = line[:-2].rstrip() + "…" if not line.endswith("…") else line[:-2].rstrip() + "…"
        d.text((W // 2, y), line, font=f2, fill=(225, 215, 195), anchor="mm")
        y += step
    if len(chapter_titles) > len(shown):
        d.text((W // 2, y), f"… und {len(chapter_titles) - len(shown)} weitere", font=f2,
               fill=(200, 190, 170), anchor="mm")
    d.text((W // 2, H - 150), german_date(date), font=_font(36), fill=(235, 225, 205), anchor="mm")
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85, optimize=True, progressive=False)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

async def _call(progress: ProgressFn | None, msg: str) -> None:
    if progress is None:
        return
    res = progress(msg)
    if asyncio.iscoroutine(res):
        await res


async def build_epub(articles: list[Article], title: str, out_path: Path, *,
                     with_images: bool = True, progress: ProgressFn | None = None,
                     image_fetcher=None) -> BuildResult:
    """Baut ein ePub aus bereits geladenen Artikeln.

    image_fetcher(url, fallback) -> ConvertedImage|None kann für Tests ersetzt werden.
    """
    if not articles:
        raise ValueError("Keine Artikel ausgewählt.")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    book_lang = articles[0].lang
    book_id = f"urn:uuid:{uuid.uuid4()}"
    warnings: list[str] = []

    chapters = [Chapter(a, f"ch{i + 1:03d}.xhtml") for i, a in enumerate(articles)]
    link_map = {(c.article.lang, norm_title(c.article.title)): c.filename for c in chapters}

    # --- Kapitel bereinigen -------------------------------------------------
    pending_images = []  # (chapter, ImageRef)
    for idx, ch in enumerate(chapters, 1):
        await _call(progress, f"Bereinige Artikel {idx} von {len(chapters)}: {ch.article.title}")
        lang = ch.article.lang

        def resolver(t, _lang=lang, _self=ch.filename):
            target = link_map.get((_lang, norm_title(t)))
            return None if target == _self else target

        result = await asyncio.to_thread(
            clean_article, ch.article.html, lang, mode="epub", link_resolver=resolver,
            extra_drop=CONFIG.extra_drop_sections.get(lang, []))
        html, body = _new_doc(ch.article.title, lang)
        h1 = etree.SubElement(body, _x("h1"))
        h1.set("id", "top")
        h1.text = ch.article.title
        if lang != book_lang:
            pl = etree.SubElement(body, _x("p"))
            pl.set("class", "lang")
            pl.text = f"Wikipedia, {LANG_NAMES.get(lang, lang)}"
        content = result.body
        if content.text and content.text.strip():
            p = etree.SubElement(body, _x("p"))
            p.text = content.text
        for child in list(content):
            body.append(child)
        src = etree.SubElement(body, _x("p"))
        src.set("class", "source")
        src.text = (f"Quelle: Wikipedia ({lang}), Artikel „{ch.article.title}“, "
                    f"Stand {german_date(now)} (Version {ch.article.revid}). "
                    "Text verfügbar unter der Lizenz CC BY-SA 4.0; die Autorinnen und Autoren "
                    "sind in der Versionsgeschichte aufgeführt: ")
        a = etree.SubElement(src, _x("a"))
        a.set("href", ch.article.url)
        a.text = ch.article.url
        ch.doc = html
        ch.sections = result.sections
        if with_images:
            pending_images.extend((ch, im) for im in result.images)
        else:
            for im in result.images:
                _remove_img(im.element)

    # --- Bilder laden ---------------------------------------------------------
    image_files: list[tuple[str, ConvertedImage]] = []
    if pending_images:
        total = len(pending_images)
        done = 0
        sem = asyncio.Semaphore(4)
        client = None if image_fetcher else make_client()
        converted: dict[str, ConvertedImage | None] = {}   # URL -> Bild
        inflight: dict[str, asyncio.Future] = {}
        unique_urls: list[str] = []

        async def load(ref) -> None:
            if image_fetcher:
                conv = await image_fetcher(ref.url, ref.fallback)
            else:
                conv = await fetch_image(client, ref.url, ref.fallback)
            converted[ref.url] = conv

        async def work(ref):
            nonlocal done
            if ref.url not in inflight:
                unique_urls.append(ref.url)

                async def guarded(r=ref):
                    async with sem:
                        await load(r)
                inflight[ref.url] = asyncio.ensure_future(guarded())
            await inflight[ref.url]
            done += 1
            if done % 3 == 0 or done == total:
                await _call(progress, f"Lade Bilder: {done} von {total}")

        try:
            await asyncio.gather(*(work(ref) for _, ref in pending_images))
        finally:
            if client is not None:
                await client.aclose()

        # Gesamtgröße begrenzen: bei Bedarf alle Bilder kleiner und stärker komprimiert
        loaded = [u for u in unique_urls if converted.get(u) is not None]
        budget = max(0, int(CONFIG.max_epub_mb * 1024 * 1024) - 400 * 1024)  # Platz für Text + Titelbild
        if loaded and budget:
            await _call(progress, "Verkleinere Bilder …")
            for quality, scale in ((None, 1.0), (65, 0.85), (60, 0.7), (55, 0.58), (50, 0.48), (45, 0.4)):
                size = sum(len(converted[u].data) for u in loaded)
                if size <= budget:
                    break
                for u in loaded:
                    src = converted[u]
                    converted[u] = await asyncio.to_thread(
                        convert_image, src.source,
                        max(160, int(CONFIG.image_max_width * scale)),
                        max(120, int(CONFIG.image_max_height * scale)),
                        quality)
            size = sum(len(converted[u].data) for u in loaded)
            if size > budget:
                warnings.append("Das Buch ist trotz verkleinerter Bilder größer als "
                                f"{CONFIG.max_epub_mb:g} MB – eventuell ohne Bilder erstellen.")

        names: dict[str, str] = {}
        for u in loaded:
            conv = converted[u]
            name = f"img{len(image_files) + 1:04d}.{conv.ext}"
            names[u] = name
            image_files.append((name, conv))

        failed = 0
        for _, ref in pending_images:
            if ref.url in names:
                ref.element.set("src", f"../images/{names[ref.url]}")
                if not ref.element.get("alt"):
                    ref.element.set("alt", "")
            else:
                _remove_img(ref.element)
                failed += 1
        if failed:
            warnings.append(f"{failed} Bild(er) konnten nicht geladen werden und wurden weggelassen.")

    await _call(progress, "Schreibe ePub-Datei …")
    cover = make_cover(title, [c.article.title for c in chapters], now)
    data = _assemble(title, book_id, book_lang, now, chapters, image_files, cover)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(out_path)
    return BuildResult(
        path=out_path,
        size=len(data),
        chapters=[{"title": c.article.title, "lang": c.article.lang, "url": c.article.url,
                   "file": c.filename,
                   "sections": [{"id": s.id, "title": s.title, "level": s.level} for s in c.sections]}
                  for c in chapters],
        image_count=len(image_files),
        warnings=warnings,
    )


def _titlepage(title: str, lang: str, now: datetime, chapters: list[Chapter]) -> bytes:
    html, body = _new_doc(title, lang)
    div = etree.SubElement(body, _x("div"))
    div.set("class", "titlepage")
    h1 = etree.SubElement(div, _x("h1"))
    h1.text = title
    sub = etree.SubElement(div, _x("p"))
    sub.set("class", "subtitle")
    sub.text = f"Artikel aus der Wikipedia, zusammengestellt am {german_date(now)}"
    if len(chapters) > 1:
        ol = etree.SubElement(div, _x("ol"))
        ol.set("class", "contents")
        for ch in chapters:
            li = etree.SubElement(ol, _x("li"))
            a = etree.SubElement(li, _x("a"))
            a.set("href", ch.filename)
            a.text = ch.article.title
    lic = etree.SubElement(div, _x("p"))
    lic.set("class", "license")
    lic.text = ("Die Texte stammen aus der Wikipedia und stehen unter der Lizenz "
                "Creative Commons Namensnennung – Weitergabe unter gleichen Bedingungen 4.0 "
                "(CC BY-SA 4.0). Bilder stammen aus Wikimedia Commons bzw. der Wikipedia und "
                "unterliegen den dort jeweils angegebenen Lizenzen. Quellenangaben stehen am "
                "Ende jedes Kapitels.")
    return _serialize(html)


def _coverpage(title: str, lang: str) -> bytes:
    html, body = _new_doc(title, lang)
    div = etree.SubElement(body, _x("div"))
    div.set("class", "cover")
    img = etree.SubElement(div, _x("img"))
    img.set("src", "images/cover.jpg")
    img.set("alt", title)
    # Deckblatt liegt im Hauptordner, daher Stylesheet-Pfad anpassen
    html.find(f".//{_x('link')}").set("href", "style.css")
    return _serialize(html)


def _nav(title: str, lang: str, chapters: list[Chapter]) -> bytes:
    html, body = _new_doc(title, lang)
    html.find(f".//{_x('link')}").set("href", "style.css")
    nav = etree.SubElement(body, _x("nav"))
    nav.set(f"{{{EPUB_NS}}}type", "toc")
    nav.set("id", "toc")
    h = etree.SubElement(nav, _x("h1"))
    h.text = "Inhalt"
    ol = etree.SubElement(nav, _x("ol"))
    li = etree.SubElement(ol, _x("li"))
    a = etree.SubElement(li, _x("a"))
    a.set("href", "text/titlepage.xhtml")
    a.text = "Titelseite"
    for ch in chapters:
        li = etree.SubElement(ol, _x("li"))
        a = etree.SubElement(li, _x("a"))
        a.set("href", f"text/{ch.filename}")
        a.text = ch.article.title
        subs = [s for s in ch.sections if s.level == 2]
        if subs:
            sol = etree.SubElement(li, _x("ol"))
            for s in subs:
                sli = etree.SubElement(sol, _x("li"))
                sa = etree.SubElement(sli, _x("a"))
                sa.set("href", f"text/{ch.filename}#{s.id}")
                sa.text = s.title
    # Orientierungspunkte
    lm = etree.SubElement(body, _x("nav"))
    lm.set(f"{{{EPUB_NS}}}type", "landmarks")
    lm.set("hidden", "hidden")
    lol = etree.SubElement(lm, _x("ol"))
    for etype, href, label in (("cover", "cover.xhtml", "Titelbild"),
                               ("titlepage", "text/titlepage.xhtml", "Titelseite"),
                               ("bodymatter", f"text/{chapters[0].filename}", "Beginn")):
        li = etree.SubElement(lol, _x("li"))
        a = etree.SubElement(li, _x("a"))
        a.set(f"{{{EPUB_NS}}}type", etype)
        a.set("href", href)
        a.text = label
    return _serialize(html)


def _ncx(title: str, book_id: str, chapters: list[Chapter]) -> bytes:
    order = 0
    points = []

    def np(label: str, src: str, children: str = "") -> str:
        nonlocal order
        order += 1
        return (f'<navPoint id="np{order}" playOrder="{order}"><navLabel><text>{escape(label)}'
                f'</text></navLabel><content src={quoteattr(src)}/>{children}</navPoint>')

    points.append(np("Titelseite", "text/titlepage.xhtml"))
    for ch in chapters:
        # Kapitel zuerst nummerieren, dann die Unterpunkte
        order += 1
        my = order
        subs = "".join(np(s.title, f"text/{ch.filename}#{s.id}") for s in ch.sections if s.level == 2)
        points.append(f'<navPoint id="np{my}" playOrder="{my}"><navLabel><text>'
                      f'{escape(ch.article.title)}</text></navLabel>'
                      f'<content src="text/{ch.filename}"/>{subs}</navPoint>')
    depth = 2 if any(ch.sections for ch in chapters) else 1
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        f'<head><meta name="dtb:uid" content={quoteattr(book_id)}/>'
        f'<meta name="dtb:depth" content="{depth}"/>'
        '<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>\n'
        f'<docTitle><text>{escape(title)}</text></docTitle>\n'
        f'<navMap>{"".join(points)}</navMap>\n</ncx>\n'
    ).encode("utf-8")


def _opf(title: str, book_id: str, lang: str, now: datetime, chapters: list[Chapter],
         images: list[tuple[str, ConvertedImage]]) -> bytes:
    modified = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    langs = sorted({c.article.lang for c in chapters} - {lang})
    meta = [
        f'<dc:identifier id="bookid">{escape(book_id)}</dc:identifier>',
        f'<dc:title>{escape(title)}</dc:title>',
        f'<dc:language>{escape(lang)}</dc:language>',
        *[f'<dc:language>{escape(l)}</dc:language>' for l in langs],
        '<dc:creator>Wikipedia-Autorinnen und -Autoren</dc:creator>',
        '<dc:publisher>Wikipedia</dc:publisher>',
        '<dc:rights>CC BY-SA 4.0</dc:rights>',
        f'<dc:date>{now.strftime("%Y-%m-%d")}</dc:date>',
        '<dc:subject>Wikipedia</dc:subject>',
        f'<meta property="dcterms:modified">{modified}</meta>',
        '<meta name="cover" content="cover-image"/>',
    ]
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
        '<item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>',
        '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="titlepage" href="text/titlepage.xhtml" media-type="application/xhtml+xml"/>',
    ]
    for ch in chapters:
        cid = ch.filename.rsplit(".", 1)[0]
        manifest.append(f'<item id="{cid}" href="text/{ch.filename}" media-type="application/xhtml+xml"/>')
    for name, conv in images:
        iid = "i" + name.rsplit(".", 1)[0]
        manifest.append(f'<item id="{iid}" href="images/{name}" media-type="{conv.media_type}"/>')
    spine = ['<itemref idref="cover" linear="yes"/>', '<itemref idref="titlepage"/>']
    spine += [f'<itemref idref="{ch.filename.rsplit(".", 1)[0]}"/>' for ch in chapters]
    guide = ('<guide><reference type="cover" title="Titelbild" href="cover.xhtml"/>'
             '<reference type="title-page" title="Titelseite" href="text/titlepage.xhtml"/>'
             f'<reference type="text" title="Beginn" href="text/{chapters[0].filename}"/></guide>')
    nl = "\n    "
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="{lang}">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n    '
        + nl.join(meta) + '\n  </metadata>\n  <manifest>\n    '
        + nl.join(manifest) + '\n  </manifest>\n  <spine toc="ncx">\n    '
        + nl.join(spine) + f'\n  </spine>\n  {guide}\n</package>\n'
    ).encode("utf-8")


CONTAINER_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _assemble(title, book_id, lang, now, chapters, images, cover) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        # 1. mimetype: zuerst, unkomprimiert
        info = zipfile.ZipInfo("mimetype", date_time=now.timetuple()[:6])
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, b"application/epub+zip")

        def add(name: str, data: bytes, stored: bool = False) -> None:
            zi = zipfile.ZipInfo(name, date_time=now.timetuple()[:6])
            zi.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data)

        add("META-INF/container.xml", CONTAINER_XML)
        add("OEBPS/content.opf", _opf(title, book_id, lang, now, chapters, images))
        add("OEBPS/toc.ncx", _ncx(title, book_id, chapters))
        add("OEBPS/nav.xhtml", _nav(title, lang, chapters))
        add("OEBPS/style.css", STYLESHEET.encode("utf-8"))
        add("OEBPS/cover.xhtml", _coverpage(title, lang))
        add("OEBPS/text/titlepage.xhtml", _titlepage(title, lang, now, chapters))
        for ch in chapters:
            add(f"OEBPS/text/{ch.filename}", _serialize(ch.doc))
        # JPEG/PNG sind bereits komprimiert
        add("OEBPS/images/cover.jpg", cover, stored=True)
        for name, conv in images:
            add(f"OEBPS/images/{name}", conv.data, stored=True)
    return buf.getvalue()
