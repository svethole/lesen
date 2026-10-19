"""Baut Test-ePubs aus den Fixtures (ohne Netzwerk) und prüft sie mit epubcheck."""
import asyncio
import io
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.epub import build_epub  # noqa: E402
from app.images import convert_image  # noqa: E402
from app.wiki import Article  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def fake_image(kind: str) -> bytes:
    """Erzeugt Testbilder in schwierigen Formaten."""
    buf = io.BytesIO()
    if kind == "png":  # transparente Strichzeichnung
        im = Image.new("RGBA", (1200, 1600), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rectangle([100, 100, 1100, 1500], outline=(0, 0, 0, 255), width=12)
        im.save(buf, "PNG")
    elif kind == "webp":
        im = Image.new("RGB", (900, 1200), (120, 80, 40))
        im.save(buf, "WEBP")
    else:  # CMYK-JPEG, progressiv – klassischer Reader-Killer
        im = Image.new("CMYK", (2000, 1500), (10, 80, 160, 20))
        im.save(buf, "JPEG", progressive=True)
    return buf.getvalue()


async def fetcher(url, fallback):
    if "Chor" in url:
        return None  # simuliert ein nicht ladbares Bild
    kind = "png" if url.endswith(".png") and "webp" not in url else ("webp" if "webp" in url else "jpg")
    return convert_image(fake_image(kind))


def epubcheck_jar() -> str:
    """epubcheck kommt per `pip install epubcheck` mit (braucht Java)."""
    import epubcheck
    return str(Path(epubcheck.__file__).parent / "epubcheck.jar")


def main(outdir: Path) -> int:
    de = Article("de", "Ulmer Münster", 123456, (FIX / "de_ulmer_muenster.html").read_text())
    cs = Article("cs", "Praha", 98765, (FIX / "cs_praha.html").read_text())
    rc = 0
    for name, arts, imgs in (("test_mit_bildern.epub", [de, cs], True),
                             ("test_ohne_bilder.epub", [cs, de], False)):
        out = outdir / name
        res = asyncio.run(build_epub(arts, "Ulm & Prag – <Testbuch>", out, with_images=imgs,
                                     image_fetcher=fetcher, progress=lambda m: None))
        print(f"{name}: {res.size} Bytes, {res.image_count} Bilder, Warnungen: {res.warnings}")
        with zipfile.ZipFile(out) as z:
            first = z.infolist()[0]
            assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
            assert first.extra == b""
        r = subprocess.run(["java", "-jar", epubcheck_jar(), str(out)], capture_output=True, text=True)
        print("\n".join(l for l in (r.stdout + r.stderr).splitlines() if "JAVA_TOOL" not in l))
        rc |= r.returncode
    return rc


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "out"))
