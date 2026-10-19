"""Bilder laden und reader-freundlich machen: nur Baseline-JPEG oder PNG,
RGB/Graustufen, keine Transparenz, auf Reader-Größe verkleinert."""
from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

import httpx
from PIL import Image, ImageOps

from .config import CONFIG

Image.MAX_IMAGE_PIXELS = 80_000_000


@dataclass
class ConvertedImage:
    data: bytes
    ext: str           # "jpg" oder "png"
    media_type: str
    width: int
    height: int


def convert_image(raw: bytes, max_w: int | None = None, max_h: int | None = None,
                  quality: int | None = None) -> ConvertedImage:
    max_w = max_w or CONFIG.image_max_width
    max_h = max_h or CONFIG.image_max_height
    quality = quality or CONFIG.jpeg_quality

    im = Image.open(io.BytesIO(raw))
    src_format = (im.format or "").upper()
    try:
        im.seek(0)  # animierte GIFs/WebPs: erstes Bild
    except EOFError:
        pass
    im = ImageOps.exif_transpose(im)

    # Transparenz auf weißen Hintergrund legen
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    elif im.mode not in ("RGB", "L"):
        im = im.convert("RGB")

    im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

    # Strichzeichnungen/Diagramme (wenige Farben) als PNG, Fotos als JPEG
    few_colors = im.getcolors(maxcolors=256) is not None
    out = io.BytesIO()
    if few_colors and src_format in ("PNG", "GIF", "WEBP", "BMP"):
        if im.mode == "RGB":
            im = im.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        im.save(out, "PNG", optimize=True)
        return ConvertedImage(out.getvalue(), "png", "image/png", im.width, im.height)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.save(out, "JPEG", quality=quality, optimize=True, progressive=False)
    return ConvertedImage(out.getvalue(), "jpg", "image/jpeg", im.width, im.height)


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": CONFIG.user_agent},
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    )


async def fetch_bytes(client: httpx.AsyncClient, url: str, attempts: int = 3) -> bytes | None:
    for attempt in range(attempts):
        try:
            r = await client.get(url)
        except httpx.HTTPError:
            await asyncio.sleep(1 + attempt * 2)
            continue
        if r.status_code == 200:
            return r.content
        if r.status_code in (429, 503):
            retry = r.headers.get("retry-after")
            await asyncio.sleep(min(float(retry) if retry and retry.isdigit() else 2 + attempt * 3, 20))
            continue
        return None
    return None


async def fetch_image(client: httpx.AsyncClient, url: str, fallback: str | None) -> ConvertedImage | None:
    for candidate in [url] + ([fallback] if fallback and fallback != url else []):
        raw = await fetch_bytes(client, candidate)
        if raw is None:
            continue
        try:
            return await asyncio.to_thread(convert_image, raw)
        except Exception:  # kaputtes oder exotisches Bildformat
            continue
    return None
