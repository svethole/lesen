"""Konfiguration: wird aus config.toml gelesen (Pfad über LESEN_CONFIG überschreibbar)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class SmtpConfig:
    host: str = ""
    port: int = 465
    security: str = "ssl"  # "ssl" (Port 465), "starttls" (Port 587) oder "none" (lokaler Mailserver)
    user: str = ""
    password: str = ""
    sender: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)


@dataclass
class Config:
    data_dir: Path = BASE_DIR / "data"
    # Wikimedia verlangt einen aussagekräftigen User-Agent mit Kontaktmöglichkeit.
    user_agent: str = "LesenEpub/1.0 (privates Projekt; https://lesen.svetho.net)"
    # Bildgröße im ePub: so, dass etwa 3–4 Bilder auf eine Reader-Seite passen
    image_max_width: int = 600
    image_max_height: int = 450
    jpeg_quality: int = 72
    # Obergrenze für ein ePub; reicht der Platz nicht, werden alle Bilder kleiner
    max_epub_mb: float = 3.0
    smtp: SmtpConfig = field(default_factory=SmtpConfig)
    # Zusätzliche Abschnittstitel je Sprache, die entfernt werden sollen
    # (ergänzt die eingebauten Listen in cleaner.py).
    extra_drop_sections: dict[str, list[str]] = field(default_factory=dict)


def load_config() -> Config:
    path = Path(os.environ.get("LESEN_CONFIG", BASE_DIR / "config.toml"))
    cfg = Config()
    if not path.exists():
        return cfg
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    general = raw.get("general", {})
    if "data_dir" in general:
        p = Path(general["data_dir"])
        cfg.data_dir = p if p.is_absolute() else BASE_DIR / p
    for key in ("user_agent", "image_max_width", "image_max_height", "jpeg_quality", "max_epub_mb"):
        if key in general:
            setattr(cfg, key, general[key])

    smtp = raw.get("smtp", {})
    cfg.smtp = SmtpConfig(
        host=smtp.get("host", ""),
        port=int(smtp.get("port", 465)),
        security=smtp.get("security", "ssl"),
        user=smtp.get("user", ""),
        password=smtp.get("password", ""),
        sender=smtp.get("sender", smtp.get("user", "")),
    )
    cfg.extra_drop_sections = {
        k: list(v) for k, v in raw.get("drop_sections", {}).items()
    }
    return cfg


CONFIG = load_config()
