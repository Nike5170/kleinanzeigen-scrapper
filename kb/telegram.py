import logging
import textwrap
import time
from dataclasses import dataclass
from html import escape

import requests

from kb.scraper import Listing

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
CAPTION_LIMIT = 1024  # видимых символов в подписи к альбому (Telegram)
TEXT_LIMIT = 4096  # видимых символов в одном сообщении
CAPTION_BUDGET = 950  # запас, т.к. лимит считается по видимому тексту
TEXT_BUDGET = 3800
ALBUM_SIZE = 10  # Telegram: максимум 10 фото в альбоме
SEND_PAUSE = 1.2  # пауза между сообщениями, чтобы не словить 429


class TelegramError(RuntimeError):
    pass


@dataclass
class _Piece:
    kind: str  # "title" | "text" | "link"
    text: str


def build_messages(listing: Listing) -> list[str]:
    """Собирает HTML-сообщения. Первое — под подпись к альбому (до 1024 символов),
    остальные — отдельные текстовые сообщения (до 4096). Длинный текст режется по строкам."""
    pieces: list[_Piece] = [_Piece("title", listing.title)]
    if listing.price:
        pieces.append(_Piece("text", f"💶 Preis: {listing.price}"))
    if listing.location:
        pieces.append(_Piece("text", f"📍 Ort: {listing.location}"))

    if listing.attributes:
        pieces.append(_Piece("text", ""))
        pieces.append(_Piece("text", "🏠 Details:"))
        for label, value in listing.attributes:
            pieces.append(_Piece("text", f"• {label}: {value}"))

    if listing.description:
        pieces.append(_Piece("text", ""))
        pieces.append(_Piece("text", "📝 Beschreibung:"))
        for line in listing.description.splitlines():
            pieces.append(_Piece("text", line))

    pieces.append(_Piece("text", ""))
    pieces.append(_Piece("link", listing.url))

    # Длинные строки режем, чтобы каждая помещалась в бюджет сообщения.
    exploded: list[_Piece] = []
    for p in pieces:
        if p.kind == "text" and len(p.text) > TEXT_BUDGET:
            exploded += [_Piece("text", part) for part in textwrap.wrap(p.text, TEXT_BUDGET, break_long_words=True)]
        else:
            exploded.append(p)

    chunks: list[list[_Piece]] = []
    current: list[_Piece] = []
    size = 0
    budget = CAPTION_BUDGET
    for p in exploded:
        cost = len(p.text) + 1
        if current and size + cost > budget:
            chunks.append(current)
            current, size = [], 0
            budget = TEXT_BUDGET
        current.append(p)
        size += cost
    if current:
        chunks.append(current)

    return [_render(c) for c in chunks]


def _render(pieces: list[_Piece]) -> str:
    lines = []
    for p in pieces:
        if p.kind == "title":
            lines.append(f"<b>{escape(p.text)}</b>")
        elif p.kind == "link":
            lines.append(f'🔗 <a href="{escape(p.text)}">Zur Anzeige</a>')
        else:
            lines.append(escape(p.text))
    return "\n".join(lines)


class TelegramClient:
    def __init__(self, token: str, chat_id: str, session: requests.Session | None = None):
        self.token = token
        self.chat_id = chat_id
        self.session = session or requests.Session()

    def _call(self, method: str, payload: dict, retries: int = 3) -> dict:
        url = API.format(token=self.token, method=method)
        for _ in range(retries):
            resp = self.session.post(url, json=payload, timeout=60)
            data = resp.json()
            if resp.status_code == 429:
                wait = data.get("parameters", {}).get("retry_after", 5)
                logger.warning("Telegram rate limit, waiting %ss", wait)
                time.sleep(wait + 1)
                continue
            if data.get("ok"):
                return data["result"]
            raise TelegramError(data.get("description", "unknown error"))
        raise TelegramError("Telegram: retries exhausted")

    def send_text(self, html: str) -> None:
        self._call(
            "sendMessage",
            {"chat_id": self.chat_id, "text": html[:TEXT_LIMIT], "parse_mode": "HTML", "disable_web_page_preview": True},
        )

    def send_album(self, photo_urls: list[str], caption: str | None) -> None:
        media = [{"type": "photo", "media": u} for u in photo_urls]
        if caption:
            media[0]["caption"] = caption
            media[0]["parse_mode"] = "HTML"
        self._call("sendMediaGroup", {"chat_id": self.chat_id, "media": media})

    def send_listing(self, messages: list[str], photo_urls: list[str]) -> None:
        """Сначала альбомы (первый с подписью), затем остальной текст отдельными сообщениями.
        Если Telegram не смог загрузить фото, отправляем текст без фото, чтобы объявление не потерялось."""
        rest = list(messages)
        if photo_urls:
            caption = rest.pop(0)
            albums = [photo_urls[i : i + ALBUM_SIZE] for i in range(0, len(photo_urls), ALBUM_SIZE)]
            try:
                self.send_album(albums[0], caption)
                for album in albums[1:]:
                    time.sleep(SEND_PAUSE)
                    self.send_album(album, None)
            except TelegramError as exc:
                logger.warning("Photo album failed (%s), sending text only", exc)
                rest.insert(0, caption)

        for msg in rest:
            time.sleep(SEND_PAUSE)
            self.send_text(msg)
