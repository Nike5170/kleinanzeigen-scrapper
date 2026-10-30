import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    search_url: str
    max_pages: int
    interval_minutes: int
    jitter_minutes: int
    seed_on_first_run: bool
    max_photos: int
    positive_patterns: list[str]
    negation_frames: list[str]
    negation_words: list[str]
    after_negation_words: list[str]
    telegram_token: str
    telegram_chat_id: str
    db_path: Path


def load_config(path: Path = ROOT / "config.json") -> Config:
    load_dotenv(ROOT / ".env")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Config(
        search_url=raw["search_url"].strip(),
        max_pages=int(raw.get("max_pages", 2)),
        interval_minutes=int(raw.get("interval_minutes", 15)),
        jitter_minutes=int(raw.get("jitter_minutes", 3)),
        seed_on_first_run=bool(raw.get("seed_on_first_run", True)),
        max_photos=int(raw.get("max_photos", 20)),
        positive_patterns=raw["positive_patterns"],
        negation_frames=raw.get("negation_frames", []),
        negation_words=raw["negation_words"],
        after_negation_words=raw["after_negation_words"],
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        db_path=ROOT / "seen.db",
    )
