import html
import logging
import re
import time

import requests

from kb.scraper import Listing

logger = logging.getLogger(__name__)

BASE_URL = "https://api.kleinanzeigen-agent.de/api/v2/kleinanzeigen"

_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


class AgentError(RuntimeError):
    pass


class CreditsExhausted(AgentError):
    """Кредиты кончились (HTTP 402). Дальше запросы бессмысленны, цикл надо остановить."""


def clean_html(text: str | None) -> str:
    text = _BR.sub("\n", text or "")
    text = _TAG.sub("", text)
    return html.unescape(text).strip()


class AgentClient:
    """Клиент kleinanzeigen-agent.de. Каждый запрос списывает кредиты: поиск 1, карточка объявления 1."""

    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"klaz_key": api_key})

    def _get(self, path: str, params: dict | None = None, retries: int = 2) -> dict:
        for attempt in range(retries + 1):
            resp = self.session.get(BASE_URL + path, params=params, timeout=30)
            if resp.status_code == 429 and attempt < retries:
                wait = int(resp.headers.get("ratelimit-reset", 60))
                logger.warning("API rate limit, waiting %ss", wait)
                time.sleep(wait)
                continue
            body = resp.json() if resp.content else {}
            if resp.status_code == 402:
                raise CreditsExhausted(body.get("message", "insufficient credits"))
            if resp.status_code != 200 or not body.get("success"):
                raise AgentError(f"HTTP {resp.status_code} {body.get('error_code', '')} {body.get('message', '')}")
            return body["data"]
        raise AgentError("API rate limit retries exhausted")

    def search(self, query: str, category_id: int, size: int = 100) -> dict:
        """Живой поиск: только частные объявления-предложения (Angebot)."""
        params = {
            "category_id": category_id,
            "ad_type": "OFFER",
            "poster_type": "PRIVATE",
            "size": size,
        }
        if query:
            params["q"] = query
        return self._get("/search", params)

    def ad(self, ad_id: str) -> dict:
        """Полная карточка с полным описанием и характеристиками."""
        return self._get(f"/ads/{ad_id}")["ad"]


def to_listing(ad: dict) -> Listing:
    """Преобразует объявление API в Listing (тот же формат, что у парсера сайта)."""
    price = ad.get("price") or {}
    amount = price.get("amount")
    price_txt = f"{amount} €" if amount is not None else ""
    if price_txt and price.get("negotiable"):
        price_txt += " VB"

    loc = ad.get("location") or {}
    # Формат "ZIP Bundesland - Stadt" — его понимает location_ru() для перевода.
    location = ""
    if loc.get("zip") or loc.get("city"):
        location = f"{loc.get('zip', '')} {loc.get('state', '')} - {loc.get('city', '')}".strip()

    attributes: list[tuple[str, str]] = []
    for attr in ad.get("attributes") or []:
        label = attr.get("label")
        values = [v.get("label") for v in attr.get("values") or [] if v.get("label")]
        if label and values:
            attributes.append((label, ", ".join(values)))

    return Listing(
        ad_id=str(ad["ad_id"]),
        url=ad.get("ad_url") or (ad.get("links") or [{}])[0].get("href", ""),
        title=ad.get("title", ""),
        price=price_txt,
        location=location,
        description=clean_html(ad.get("description")),
        photo_urls=list(ad.get("images") or []),
        is_commercial=(ad.get("seller") or {}).get("type") == "COMMERCIAL",
        offer_type="Angebot" if ad.get("ad_type", "OFFER") == "OFFER" else "Gesuch",
        attributes=attributes,
    )
