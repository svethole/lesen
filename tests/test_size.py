"""Belastungstest: ein Artikel mit sehr vielen Fotos muss unter der
Größengrenze (max_epub_mb) bleiben und trotzdem gültig sein.

    python3 tests/test_size.py FOTO1.jpg FOTO2.jpg ...   (echte Fotos als Vorlage)
"""
import asyncio
import io
import random
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import CONFIG  # noqa: E402
from app.epub import build_epub  # noqa: E402
from app.images import convert_image  # noqa: E402
from app.wiki import Article  # noqa: E402
from test_build import epubcheck_jar  # noqa: E402

N = 110


def article_html(n: int) -> str:
    parts = ['<div class="mw-parser-output"><p>Einleitung mit <b>vielen</b> Bildern.</p>']
    for i in range(n):
        parts.append(
            f'<figure typeof="mw:File/Thumb"><a href="/wiki/Datei:F{i}.jpg"><img '
            f'src="//upload.wikimedia.org/wikipedia/commons/thumb/a/aa/F{i}.jpg/250px-F{i}.jpg" '
            f'width="250" height="180" data-file-width="4000" data-file-height="3000"></a>'
            f'<figcaption>Bild Nummer {i + 1}</figcaption></figure><p>Absatz {i + 1}.</p>')
    return "".join(parts) + "</div>"


def main(photos: list[str]) -> int:
    sources = [Image.open(p).convert("RGB") for p in photos]

    async def fetcher(url, fallback):
        rnd = random.Random(url)
        src = rnd.choice(sources)
        w, h = src.size
        cw, ch = int(w * rnd.uniform(0.5, 1)), int(h * rnd.uniform(0.5, 1))
        x, y = rnd.randint(0, w - cw), rnd.randint(0, h - ch)
        im = src.crop((x, y, x + cw, y + ch)).resize((960, int(960 * ch / cw)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=87)  # etwa wie Wikimedia-Vorschaubilder
        return convert_image(buf.getvalue())

    art = Article("de", "Bilderreicher Artikel", 1, article_html(N))
    out = ROOT / "tests" / "out" / "test_viele_bilder.epub"
    res = asyncio.run(build_epub([art], "Viele Bilder", out, image_fetcher=fetcher,
                                 progress=lambda m: None))
    mb = res.size / 1024 / 1024
    with zipfile.ZipFile(out) as z:
        sizes = [i.file_size for i in z.infolist() if i.filename.startswith("OEBPS/images/img")]
        dims = Image.open(io.BytesIO(z.read("OEBPS/images/img0001.jpg"))).size
    print(f"{N} Bilder: {mb:.2f} MB (Grenze {CONFIG.max_epub_mb} MB), "
          f"Ø {sum(sizes) / len(sizes) / 1024:.0f} KB pro Bild, erstes Bild {dims[0]}×{dims[1]} px")
    print("Hinweise:", res.warnings)
    r = subprocess.run(["java", "-jar", epubcheck_jar(), str(out)], capture_output=True, text=True)
    print([l for l in r.stdout.splitlines() if l.startswith("Messages")])
    return 0 if (mb <= CONFIG.max_epub_mb and r.returncode == 0) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
