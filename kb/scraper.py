import logging
import random
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.kleinanzeigen.de"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
}


@dataclass
class Stub:
    ad_id: str
    url: str
    title: str


@dataclass
class Listing(Stub):
    price: str = ""
    location: str = ""
    description: str = ""
    photo_urls: list[str] = field(default_factory=list)
    is_commercial: bool = False
    offer_type: str = ""  # "Angebot" или "Gesuch"
    attributes: list[tuple[str, str]] = field(default_factory=list)  # ("Wohnfläche", "78 m²"), ...


class DegradedPage(RuntimeError):
    """Страница объявления пришла неполной даже после повторов. Объявление не помечаем, проверим в следующем цикле."""


class Scraper:
    def __init__(self, delay=(8.0, 14.0), session: requests.Session | None = None):
        self.delay = delay
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)

    def _fetch_text(self, url: str) -> str:
        time.sleep(random.uniform(*self.delay))
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        return resp.text

    def _get(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self._fetch_text(url), "html.parser")

    def search(self, search_url: str, max_pages: int, is_known=None) -> list[Stub]:
        """Проходит по страницам результатов поиска (ссылки вида /seite:N/).

        Выдача отсортирована от новых к старым. Если передан is_known и на странице
        все объявления уже известны, дальше не листаем: новее их ничего нет.
        max_pages — верхний предел на случай, если новых объявлений очень много.
        """
        stubs: list[Stub] = []
        ids: set[str] = set()  # при сдвиге выдачи одно объявление может попасть на две страницы
        url = search_url
        for page in range(1, max_pages + 1):
            soup = self._get(url)
            page_stubs: list[Stub] = []
            for art in soup.select("article[data-adid]"):
                if art.get("data-adid") in ids:
                    continue
                href = art.get("data-href") or ""
                if "/s-anzeige/" not in href:
                    continue
                # В карточке несколько ссылок (картинка, заголовок) — берём самый длинный текст.
                titles = [a.get_text(strip=True) for a in art.select(f'a[href*="/s-anzeige/"]')]
                ids.add(art["data-adid"])
                page_stubs.append(
                    Stub(
                        ad_id=art["data-adid"],
                        url=urljoin(BASE_URL, href),
                        title=max(titles, key=len, default=""),
                    )
                )
            stubs.extend(page_stubs)
            if is_known and page_stubs and all(is_known(s) for s in page_stubs):
                logger.info("Page %d has only known ads, stopping", page)
                break
            next_link = soup.select_one(f'a[href*="seite:{page + 1}"]')
            if not next_link:
                break
            url = urljoin(BASE_URL, next_link["href"])
        logger.info("Search returned %d ads", len(stubs))
        return stubs

    def fetch_details(self, stub: Stub) -> Listing:
        # Иногда сайт отдаёт урезанную страницу (без галереи и характеристик) — повторяем с паузой.
        for attempt in range(1, 4):
            resp_text = self._fetch_text(stub.url)
            soup = BeautifulSoup(resp_text, "html.parser")
            if soup.select("li.addetailslist--detail") or soup.select(".galleryimage-element img"):
                break
            logger.warning("Incomplete page for %s (attempt %d), backing off", stub.ad_id, attempt)
            time.sleep(30 * attempt)
        else:
            raise DegradedPage(stub.ad_id)

        desc_el = soup.select_one("#viewad-description-text")
        description = desc_el.get_text("\n", strip=True) if desc_el else ""

        title_el = soup.select_one("#viewad-title") or soup.select_one("h1")
        title = title_el.get_text(strip=True) if title_el else stub.title

        price_el = soup.select_one("#viewad-price")
        price = price_el.get_text(" ", strip=True) if price_el else ""

        loc_el = soup.select_one("#viewad-locality")
        location = loc_el.get_text(" ", strip=True) if loc_el else ""

        photos: list[str] = []
        seen_ids: set[str] = set()
        for img in soup.select(".galleryimage-element img"):
            src = img.get("data-imgsrc") or img.get("src") or ""
            if src.startswith("//"):
                src = "https:" + src
            if "img.kleinanzeigen.de" not in src:
                continue
            # Один и тот же снимок приходит в разных размерах (?rule=$_59, $_35...) — берём один.
            base = src.split("?")[0]
            if base not in seen_ids:
                seen_ids.add(base)
                photos.append(src)

        # Характеристики: Wohnfläche, Zimmer, Warmmiete, Kaution, Verfügbar ab и т.д.
        attributes: list[tuple[str, str]] = []
        for li in soup.select("li.addetailslist--detail"):
            value_el = li.select_one(".addetailslist--detail--value")
            if not value_el:
                continue
            label = " ".join(li.find_all(string=True, recursive=False)).strip()
            value = value_el.get_text(" ", strip=True)
            if label and value:
                attributes.append((label, value))

        # Тип продавца и тип объявления лежат в JSON на странице: "Verkaeufer":"privat", "Angebotstyp":"Angebot".
        seller = _first(r'"Verkaeufer":"(\w+)"', resp_text)
        offer_type = _first(r'"Angebotstyp":"(\w+)"', resp_text)

        return Listing(
            ad_id=stub.ad_id,
            url=stub.url,
            title=title,
            price=price,
            location=location,
            description=description,
            photo_urls=photos,
            is_commercial=(seller or "").lower() == "gewerblich",
            offer_type=offer_type or "",
            attributes=attributes,
        )


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None
