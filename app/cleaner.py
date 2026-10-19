"""Bereinigung von Wikipedia-HTML (Ausgabe von action=parse) zu schlichtem,
wohlgeformtem XHTML, das auch strenge eBook-Reader klaglos anzeigen.

Grundprinzip: Wir *bauen den Baum neu auf*, statt den Originalbaum zu
flicken. Nur Elemente und Attribute aus einer kleinen Positivliste kommen
durch – damit landet garantiert nichts im ePub, was ein Reader nicht kennt.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import unquote

from lxml import etree
from lxml import html as lhtml

XHTML_NS = "http://www.w3.org/1999/xhtml"

# ---------------------------------------------------------------------------
# Abschnitte, die samt Inhalt wegfallen (Vergleich ohne Groß/Kleinschreibung).
# Eigene Ergänzungen sind über config.toml ([drop_sections]) möglich.
# ---------------------------------------------------------------------------
DROP_SECTIONS: dict[str, list[str]] = {
    "de": ["Einzelnachweise", "Anmerkungen", "Literatur", "Weblinks", "Siehe auch",
           "Quellen", "Belege", "Fußnoten", "Weiterführende Literatur",
           "Literatur und Weblinks", "Quellen und Literatur", "Anmerkungen und Einzelnachweise",
           "Anmerkungen und Belege", "Weblinks und Quellen", "Filmografie (Auswahl)"],
    "nl": ["Externe links", "Externe link", "Bronnen", "Bron", "Referenties", "Bronvermelding",
           "Bronvermeldingen", "Zie ook", "Literatuur", "Noten", "Voetnoten", "Noten en referenties"],
    "da": ["Eksterne henvisninger", "Eksterne links", "Kilder", "Referencer", "Se også",
           "Litteratur", "Noter", "Kilder og henvisninger", "Fodnoter"],
    "sv": ["Externa länkar", "Källor", "Referenser", "Se även", "Noter", "Litteratur",
           "Vidare läsning", "Tryckta källor", "Webbkällor", "Fotnoter", "Källhänvisningar"],
    "cs": ["Externí odkazy", "Reference", "Literatura", "Související články", "Odkazy",
           "Poznámky", "Prameny", "Externí odkazy a literatura"],
    "it": ["Collegamenti esterni", "Note", "Bibliografia", "Voci correlate", "Altri progetti",
           "Fonti", "Riferimenti"],
    "fr": ["Liens externes", "Notes et références", "Bibliographie", "Voir aussi",
           "Articles connexes", "Références", "Notes", "Sources", "Annexes"],
    "es": ["Enlaces externos", "Referencias", "Bibliografía", "Véase también", "Notas",
           "Fuentes", "Notas y referencias"],
    "en": ["References", "External links", "See also", "Notes", "Further reading",
           "Bibliography", "Sources", "Citations", "Footnotes", "Notes and references"],
    "pl": ["Przypisy", "Bibliografia", "Linki zewnętrzne", "Zobacz też", "Uwagi"],
    "no": ["Referanser", "Eksterne lenker", "Se også", "Litteratur", "Kilder"],
    "nb": ["Referanser", "Eksterne lenker", "Se også", "Litteratur", "Kilder"],
    "pt": ["Referências", "Ligações externas", "Ver também", "Bibliografia", "Notas"],
}

# Elemente mit diesen Klassen fliegen komplett raus.
DROP_CLASSES = {
    "mw-editsection", "reference", "references", "reflist", "mw-references-wrap",
    "mw-references-columns", "mw-cite-backlink", "navbox", "navbox-styles", "vertical-navbox",
    "navigation-not-searchable", "infobox", "metadata", "noprint", "hatnote", "dablink",
    "ambox", "mbox", "mbox-small", "ombox", "tmbox", "cmbox", "fmbox", "sistersitebox",
    "sisterproject", "coordinates", "geo-default", "geo-nondefault", "mw-empty-elt",
    "catlinks", "toc", "toccolours", "NavFrame", "navframe", "magnify", "sieheauch",
    "hauptartikel", "mw-kartographer-maplink", "mw-kartographer-map", "mw-ext-cite-error",
    "error", "printfooter", "mw-indicators", "shortdescription", "box-Tone",
    "mw-authority-control", "authority-control", "normdaten", "wikidata-link",
    "mw-jump-link", "mw-collapsible-toggle", "plainlinks-print", "sortkey",
    "Vorlage_Lesenswert", "Vorlage_Exzellent", "sisterbox", "side-box", "portal",
    "portalbox", "noexcerpt", "mw-tmh-player", "mediaContainer", "haudio",
    "rt-commentedText-hidden", "IPA-hidden", "mw-graph", "timeline-wrapper",
}
DROP_IDS = {"coordinates", "normdaten", "toc", "catlinks", "siteSub", "contentSub", "jump-to-nav"}
# Diese Tags werden samt Inhalt verworfen (Tabellen auf Wunsch komplett).
DROP_TAGS = {
    "style", "script", "link", "meta", "table", "audio", "video", "source", "track",
    "map", "area", "iframe", "object", "embed", "input", "button", "form", "noscript",
    "svg", "math", "canvas", "template", "select", "textarea", "label", "caption", "colgroup",
}

BLOCK_TAGS = {"p", "ul", "ol", "dl", "blockquote", "pre", "hr", "div", "figure"}
PHRASING_KEEP = {"b", "strong", "i", "em", "u", "s", "del", "ins", "sub", "sup", "small",
                 "kbd", "var", "samp", "abbr", "q", "cite", "dfn", "mark", "bdi"}
HEADINGS = {"h1": 2, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")
_WS_RE = re.compile(r"[ \t\r\n]+")
_SPACE_PUNCT_RE = re.compile(r" +([.,;:!?)\]])")
_THUMB_RE = re.compile(r"/(\d+)px-")


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    return _CTRL_RE.sub("", s)


def norm_title(title: str) -> str:
    """Normalisierte Form eines Artikeltitels zum Vergleichen von Links."""
    t = unquote(title).replace("_", " ").strip()
    t = unicodedata.normalize("NFC", t)
    return t[:1].upper() + t[1:] if t else t


def _norm_heading(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().rstrip(":").strip().casefold()


def classes_of(el) -> set[str]:
    return set((el.get("class") or "").split())


@dataclass
class ImageRef:
    url: str          # Original-URL (absolut)
    fallback: str     # Ersatz-URL, falls `url` nicht klappt
    alt: str
    element: etree._Element = field(repr=False)  # <img> im Ausgabebaum


@dataclass
class Section:
    id: str
    title: str
    level: int


@dataclass
class CleanResult:
    body: etree._Element           # <div> mit dem bereinigten Inhalt (XHTML-Namespace)
    images: list[ImageRef]
    sections: list[Section]


# ---------------------------------------------------------------------------
# Schritt 1: Vorreinigung am Originalbaum
# ---------------------------------------------------------------------------

def _remove(el) -> None:
    """Entfernt ein Element, behält aber den nachfolgenden Text (tail)."""
    parent = el.getparent()
    if parent is None:
        return
    tail = el.tail
    if tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(el)


def _unwrap(el) -> None:
    """Ersetzt ein Element durch seinen Inhalt."""
    parent = el.getparent()
    if parent is None:
        return
    idx = parent.index(el)
    children = list(el)
    text, tail = el.text, el.tail
    if text:
        if idx > 0:
            prev = parent[idx - 1]
            prev.tail = (prev.tail or "") + text
        else:
            parent.text = (parent.text or "") + text
    for i, child in enumerate(children):
        parent.insert(idx + i, child)
    if tail:
        if children:
            children[-1].tail = (children[-1].tail or "") + tail
        elif idx > 0:
            prev = parent[idx - 1]
            prev.tail = (prev.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(el)


def _math_to_text(root) -> None:
    """Formeln: SVG/MathML verstehen viele Reader nicht – wir zeigen den TeX-Text."""
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            continue
        if "mwe-math-element" in classes_of(el):
            alt = ""
            for img in el.iter("img"):
                alt = img.get("alt") or ""
                break
            if not alt:
                for ann in el.iter():
                    if isinstance(ann.tag, str) and ann.tag.endswith("annotation"):
                        alt = ann.text or ""
                        break
            alt = alt.strip()
            m = re.match(r"^\{\\displaystyle\s*(.*)\}$", alt, re.S)
            if m:
                alt = m.group(1).strip()
            new = lhtml.Element("code")
            new.set("class", "math")
            new.text = alt
            new.tail = el.tail
            el.getparent().replace(el, new)


def _drop_hidden_and_junk(root) -> None:
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            # Kommentare / Processing Instructions
            if el.getparent() is not None:
                _remove(el)
            continue
        if el.getparent() is None:
            continue
        tag = el.tag.lower()
        style = (el.get("style") or "").replace(" ", "").lower()
        if (
            tag in DROP_TAGS
            or classes_of(el) & DROP_CLASSES
            or (el.get("id") or "") in DROP_IDS
            or "display:none" in style
            or (el.get("role") == "navigation")
            or el.get("typeof", "").startswith(("mw:File/Audio", "mw:File/Video"))
        ):
            # Nicht entfernen, wenn ein Vorfahre ohnehin schon weg ist (iter läuft weiter)
            _remove(el)


def _flatten_wrappers(root) -> None:
    """Neue (seit 2024) Überschriften stecken in <div class="mw-heading">,
    Parsoid packt Abschnitte in <section>. Beides lösen wir auf, damit
    Überschriften und Inhalt Geschwister auf oberster Ebene sind."""
    changed = True
    while changed:
        changed = False
        for el in list(root):
            if not isinstance(el.tag, str):
                continue
            if el.tag == "section" or "mw-heading" in classes_of(el) or (
                el.tag == "div" and "mw-parser-output" in classes_of(el)
            ):
                _unwrap(el)
                changed = True
    # Alte Überschriften: <h2><span class="mw-headline" id="...">Text</span></h2>
    for span in root.xpath(".//span[contains(concat(' ', normalize-space(@class), ' '), ' mw-headline ')]"):
        h = span.getparent()
        if h is not None and h.tag in HEADINGS and not h.get("id") and span.get("id"):
            h.set("id", span.get("id"))
        _unwrap(span)


def _drop_sections(root, lang: str, extra: list[str]) -> None:
    names = {_norm_heading(n) for n in DROP_SECTIONS.get(lang, []) + DROP_SECTIONS["en"] + extra}
    children = list(root)
    drop_level: int | None = None
    for el in children:
        tag = el.tag if isinstance(el.tag, str) else ""
        level = HEADINGS.get(tag)
        if level is not None and tag != "h1":
            level = int(tag[1])
            if drop_level is not None and level <= drop_level:
                drop_level = None
            if drop_level is None and _norm_heading(el.text_content()) in names:
                drop_level = level
        if drop_level is not None:
            _remove(el)


# ---------------------------------------------------------------------------
# Schritt 2: Neuaufbau als schlichtes XHTML
# ---------------------------------------------------------------------------

def _x(tag: str) -> str:
    return f"{{{XHTML_NS}}}{tag}"


def _abs_url(src: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return "https://upload.wikimedia.org" + src
    return src


def _best_image_url(img) -> tuple[str, str]:
    """Liefert (bevorzugte URL, Ersatz-URL). Für den Reader nehmen wir nach
    Möglichkeit die Standard-Vorschaugröße 960px, sonst die größte aus srcset."""
    src = _abs_url(img.get("src") or "")
    best = src
    srcset = img.get("srcset") or ""
    if srcset:
        last = srcset.split(",")[-1].strip().split(" ")[0]
        if last:
            best = _abs_url(last)
    try:
        file_w = int(img.get("data-file-width") or 0)
    except ValueError:
        file_w = 0
    if "/thumb/" in src and _THUMB_RE.search(src) and file_w >= 960:
        return _THUMB_RE.sub("/960px-", src, count=1), best
    return best, src


def _is_icon(img) -> bool:
    def num(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0
    w, h = num(img.get("width")), num(img.get("height"))
    return (0 < w < 60 and 0 < h < 60) or (0 < w < 30) or (0 < h < 20)


class _Builder:
    def __init__(self, link_resolver, mode: str):
        self.link_resolver = link_resolver   # Titel -> href oder None
        self.mode = mode                     # "epub" oder "preview"
        self.images: list[ImageRef] = []
        self.sections: list[Section] = []
        self.deferred: list = []             # Abbildungen, die in Fließtext standen

    # -- Hilfen -------------------------------------------------------------
    @staticmethod
    def _append_text(out, text: str | None) -> None:
        text = clean_text(text)
        if not text:
            return
        if len(out):
            last = out[-1]
            last.tail = (last.tail or "") + text
        else:
            out.text = (out.text or "") + text

    def _image(self, img, out_parent) -> etree._Element | None:
        if _is_icon(img) or not img.get("src"):
            return None
        url, fallback = _best_image_url(img)
        el = etree.SubElement(out_parent, _x("img"))
        alt = clean_text(img.get("alt") or "")
        el.set("alt", alt)
        if self.mode == "preview":
            el.set("src", url)
            el.set("loading", "lazy")
        else:
            el.set("src", "")  # wird vom ePub-Bauer gesetzt
            self.images.append(ImageRef(url=url, fallback=fallback, alt=alt, element=el))
        return el

    def _figure(self, src_el, out_parent) -> None:
        img = next(iter(src_el.iter("img")), None)
        if img is None or _is_icon(img):
            return
        caption_src = None
        for el in src_el.iter():
            if not isinstance(el.tag, str):
                continue
            c = classes_of(el)
            if el.tag == "figcaption" or "thumbcaption" in c or "gallerytext" in c:
                caption_src = el
                break
        fig = etree.SubElement(out_parent, _x("div"))
        fig.set("class", "figure")
        if self._image(img, fig) is None:
            out_parent.remove(fig)
            return
        if caption_src is not None and caption_src.text_content().strip():
            cap = etree.SubElement(fig, _x("p"))
            cap.set("class", "caption")
            self._children(caption_src, cap, phrasing=True)
            if not "".join(cap.itertext()).strip():
                fig.remove(cap)

    def _link(self, src_el, out, phrasing: bool) -> None:
        href = src_el.get("href") or ""
        target = None
        title = None
        if href.startswith(("/wiki/", "./")) and "redlink=1" not in href:
            path = href.split("#", 1)[0]
            title = path[6:] if path.startswith("/wiki/") else path[2:]
            title = norm_title(title)
            if ":" not in title.split(" ", 1)[0] or not re.match(r"^[^:]+:", title):
                target = self.link_resolver(title) if self.link_resolver else None
        if self.mode == "preview" and title and not re.match(r"^(Datei|File|Bild|Image|Kategorie|Category|Spezial|Special|Hilfe|Help|Wikipedia|Vorlage|Template|Portal):", title):
            a = etree.SubElement(out, _x("a"))
            a.set("href", "#")
            a.set("data-wiki", title)
            self._children(src_el, a, phrasing=True)
        elif target:
            a = etree.SubElement(out, _x("a"))
            a.set("href", target)
            self._children(src_el, a, phrasing=True)
        else:
            # Links ohne Ziel im Buch werden zu normalem Text
            self._children(src_el, out, phrasing)

    # -- Kern ---------------------------------------------------------------
    def _children(self, src, out, phrasing: bool) -> None:
        self._append_text(out, src.text)
        for child in src:
            if isinstance(child.tag, str):
                self._node(child, out, phrasing)
            self._append_text(out, child.tail)

    def _node(self, el, out, phrasing: bool) -> None:
        tag = el.tag.lower()
        cls = classes_of(el)

        # Abbildungen (neues und altes Markup, Galerien)
        is_figure = (
            tag == "figure"
            or (tag == "div" and ("thumb" in cls or "tsingle" in cls) and "thumbinner" not in cls
                and "thumbimage" not in cls)
            or (tag == "li" and "gallerybox" in cls)
        )
        if is_figure:
            if "tmulti" in cls:
                # Mehrfachbild-Vorlage: jedes Bild einzeln
                for img in el.iter("img"):
                    if phrasing:
                        holder = etree.Element(_x("div"))
                        self._figure_from_img(img, holder)
                        self.deferred.extend(list(holder))
                    else:
                        self._figure_from_img(img, out)
                return
            if phrasing:
                holder = etree.Element(_x("div"))
                self._figure(el, holder)
                self.deferred.extend(list(holder))
            else:
                self._figure(el, out)
            return
        if tag == "ul" and "gallery" in cls:
            if phrasing:
                return
            for box in el:
                if isinstance(box.tag, str):
                    self._node(box, out, False)
            return
        if tag in ("ul", "ol") and "gallery" in cls:
            return

        if tag == "img":
            self._image(el, out) if phrasing else self._block_wrap_img(el, out)
            return

        if tag in HEADINGS:
            if phrasing:
                self._children(el, out, True)
                return
            level = HEADINGS[tag]
            text = _WS_RE.sub(" ", el.text_content()).strip()
            if not text:
                return
            sid = f"s{len(self.sections) + 1}"
            h = etree.SubElement(out, _x(f"h{level}"))
            h.set("id", sid)
            h.text = clean_text(text)
            self.sections.append(Section(sid, text, level))
            return

        if tag == "a":
            self._link(el, out, phrasing)
            return

        if tag == "br":
            etree.SubElement(out, _x("br"))
            return

        if tag == "hr":
            if not phrasing:
                etree.SubElement(out, _x("hr"))
            return

        if tag in PHRASING_KEEP:
            new = etree.SubElement(out, _x(tag))
            if tag == "abbr" and el.get("title"):
                new.set("title", clean_text(el.get("title")))
            self._children(el, new, True)
            return

        if tag == "code" or (tag == "tt"):
            new = etree.SubElement(out, _x("code"))
            if "math" in cls:
                new.set("class", "math")
            self._children(el, new, True)
            return

        if tag in ("p", "pre", "dt"):
            if phrasing:
                self._children(el, out, True)
                return
            new = etree.SubElement(out, _x(tag))
            self._children(el, new, True)
            self._flush_deferred(out)
            return

        if tag in ("blockquote", "dd", "li"):
            if phrasing:
                self._children(el, out, True)
                return
            new = etree.SubElement(out, _x(tag))
            self._mixed(el, new)
            return

        if tag in ("ul", "ol", "dl"):
            if phrasing:
                return
            new = etree.SubElement(out, _x(tag))
            for child in el:
                if not isinstance(child.tag, str):
                    continue
                ctag = child.tag.lower()
                if tag in ("ul", "ol") and ctag != "li":
                    li = etree.SubElement(new, _x("li"))
                    self._mixed_single(child, li)
                elif tag == "dl" and ctag not in ("dt", "dd"):
                    dd = etree.SubElement(new, _x("dd"))
                    self._mixed_single(child, dd)
                else:
                    self._node(child, new, False)
            if len(new) == 0:
                out.remove(new)
            return

        # div, span, center, font, section, unbekannte Tags: auspacken
        if phrasing:
            self._children(el, out, True)
        else:
            self._mixed(el, out)

    def _figure_from_img(self, img, out) -> None:
        if _is_icon(img):
            return
        fig = etree.SubElement(out, _x("div"))
        fig.set("class", "figure")
        self._image(img, fig)

    def _block_wrap_img(self, img, out) -> None:
        if _is_icon(img):
            return
        fig = etree.SubElement(out, _x("div"))
        fig.set("class", "figure")
        if self._image(img, fig) is None:
            out.remove(fig)

    def _mixed_single(self, el, container) -> None:
        holder = lhtml.Element("div")
        holder.append(_copy(el))
        self._mixed(holder, container)

    def _mixed(self, src, container) -> None:
        """Inhalt, der Block- und Inline-Elemente mischt (z.B. <li>, <div>).
        Lose Inline-Inhalte werden – wo nötig – in <p> gesammelt."""
        allows_inline = container.tag in (_x("li"), _x("dd"), _x("blockquote"))
        run: etree._Element | None = None

        def inline_target():
            nonlocal run
            if allows_inline:
                return container
            if run is None:
                run = etree.SubElement(container, _x("p"))
            return run

        def close_run():
            nonlocal run
            if run is not None and not _has_content(run):
                container.remove(run)
            run = None
            self._flush_deferred(container)

        text = clean_text(src.text)
        if text.strip() or (text and run is not None):
            self._append_text(inline_target(), text)
        for child in src:
            if isinstance(child.tag, str):
                if _is_block(child):
                    close_run()
                    self._node(child, container, False)
                else:
                    self._node(child, inline_target(), True)
            tail = clean_text(child.tail)
            if tail.strip() or (tail and run is not None) or (tail and allows_inline):
                self._append_text(inline_target(), tail)
        close_run()

    def _flush_deferred(self, out) -> None:
        if not self.deferred:
            return
        # Abbildungen nur in Containern ablegen, die Blockinhalt erlauben
        target = out
        while target is not None and target.tag in (_x("p"), _x("pre"), _x("dt")):
            target = target.getparent()
        if target is None:
            return
        for fig in self.deferred:
            target.append(fig)
        self.deferred = []


def _copy(el):
    import copy
    c = copy.deepcopy(el)
    c.tail = None
    return c


def _is_block(el) -> bool:
    tag = el.tag.lower()
    cls = classes_of(el)
    if tag in BLOCK_TAGS or tag in HEADINGS or tag in ("li", "dd", "dt", "section", "center"):
        return True
    if tag == "span" and ("thumb" in cls or el.get("typeof", "").startswith("mw:File/Thumb")):
        return True
    return False


def _has_content(el) -> bool:
    if "".join(el.itertext()).strip():
        return True
    return any(e.tag == _x("img") for e in el.iter())


def _prune_empty(root) -> None:
    for el in list(root.iter(_x("p"), _x("li"), _x("dd"), _x("dt"), _x("blockquote"),
                             _x("b"), _x("i"), _x("strong"), _x("em"), _x("span"))):
        if el.getparent() is not None and not _has_content(el):
            parent = el.getparent()
            if el.tail:
                prev = el.getprevious()
                if prev is not None:
                    prev.tail = (prev.tail or "") + el.tail
                else:
                    parent.text = (parent.text or "") + el.tail
            parent.remove(el)
    for lst in list(root.iter(_x("ul"), _x("ol"), _x("dl"))):
        if lst.getparent() is not None and len(lst) == 0:
            lst.getparent().remove(lst)
    # Überschriften ohne nachfolgenden Inhalt (bis zur nächsten gleichrangigen) entfernen
    children = list(root)
    for i, el in enumerate(children):
        if el.tag in (_x("h2"), _x("h3"), _x("h4"), _x("h5"), _x("h6")):
            level = int(el.tag[-1])
            nxt = children[i + 1] if i + 1 < len(children) else None
            if nxt is None or (nxt.tag.startswith(f"{{{XHTML_NS}}}h") and len(nxt.tag) == len(el.tag)
                               and nxt.tag[-1].isdigit() and int(nxt.tag[-1]) <= level):
                root.remove(el)


def _tidy_whitespace(root) -> None:
    for el in root.iter():
        if el.tag in (_x("pre"),):
            continue
        if el.text:
            el.text = _SPACE_PUNCT_RE.sub(r"\1", _WS_RE.sub(" ", el.text))
        if el.tail:
            el.tail = _SPACE_PUNCT_RE.sub(r"\1", _WS_RE.sub(" ", el.tail))
    for el in root.iter(_x("p"), _x("li"), _x("dd"), _x("dt"), _x("h2"), _x("h3"), _x("h4"),
                        _x("h5"), _x("h6"), _x("blockquote")):
        if el.text:
            el.text = el.text.lstrip()
        if len(el):
            last = el[-1]
            if last.tail:
                last.tail = last.tail.rstrip()
        elif el.text:
            el.text = el.text.rstrip()


def clean_article(raw_html: str, lang: str, *, mode: str = "epub",
                  link_resolver=None, extra_drop: list[str] | None = None) -> CleanResult:
    """Bereinigt das HTML eines Artikels.

    mode="epub":    Bilder werden als ImageRef gesammelt (src wird später gesetzt),
                    Links nur behalten, wenn link_resolver ein Ziel liefert.
    mode="preview": Bilder behalten ihre Wikimedia-URL, interne Links tragen
                    data-wiki="Titel" für die Vorschau im Browser.
    """
    doc = lhtml.fromstring(f"<div id='__root'>{raw_html}</div>")
    root = doc if doc.get("id") == "__root" else doc.find(".//div[@id='__root']")
    _math_to_text(root)
    _drop_hidden_and_junk(root)
    _flatten_wrappers(root)
    _drop_sections(root, lang, extra_drop or [])

    builder = _Builder(link_resolver, mode)
    out = etree.Element(_x("div"), nsmap={None: XHTML_NS})
    builder._mixed(root, out)
    builder._flush_deferred(out)
    _tidy_whitespace(out)
    _prune_empty(out)
    # Bilder, deren <img> beim Aufräumen verschwunden ist, nicht mehr laden
    alive = {id(e) for e in out.iter(_x("img"))}
    images = [im for im in builder.images if id(im.element) in alive]
    sections = [s for s in builder.sections if out.find(f".//*[@id='{s.id}']") is not None]
    return CleanResult(body=out, images=images, sections=sections)


def to_html_fragment(result_body) -> str:
    """Serialisiert den bereinigten Inhalt (ohne Wrapper-div) als HTML-Fragment."""
    import copy
    import html as _html
    body = copy.deepcopy(result_body)
    for el in body.iter():
        if isinstance(el.tag, str):
            el.tag = etree.QName(el).localname
    etree.cleanup_namespaces(body)
    parts = [_html.escape(body.text or "")]
    for child in body:
        parts.append(lhtml.tostring(child, encoding="unicode", with_tail=True))
    return "".join(parts)
