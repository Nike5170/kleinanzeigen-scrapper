import logging
import re

import requests

logger = logging.getLogger(__name__)

DEEPL_URL = "https://api-free.deepl.com/v2/translate"

# Названия полей из блока характеристик.
LABELS = {
    "Wohnfläche": "Площадь",
    "Zimmer": "Комнаты",
    "Schlafzimmer": "Спальни",
    "Badezimmer": "Ванные",
    "Etage": "Этаж",
    "Wohnungstyp": "Тип жилья",
    "Verfügbar ab": "Доступно с",
    "Online-Besichtigung": "Онлайн-просмотр",
    "Tauschangebot": "Обмен",
    "Nebenkosten": "Коммунальные",
    "Heizkosten": "Отопление",
    "Warmmiete": "Общая аренда",
    "Kaltmiete": "Холодная аренда",
    "Kaution / Genoss.-Anteile": "Залог / паевой взнос",
    "Kaution": "Залог",
    "Baujahr": "Год постройки",
    "Energieausweis": "Энергопаспорт",
}

# Частые значения. Остальное переводит сервис.
VALUES = {
    "Etagenwohnung": "Квартира на этаже",
    "Erdgeschosswohnung": "Квартира на первом этаже",
    "Dachgeschosswohnung": "Мансардная квартира",
    "Souterrain": "Цокольный этаж",
    "Hochparterre": "Бельэтаж",
    "Penthouse": "Пентхаус",
    "Nicht möglich": "Нет",
    "Kein Tausch": "Без обмена",
    "Ja": "Да",
    "Nein": "Нет",
    "Angebot": "Предложение",
}

MONTHS = {
    "Januar": "Январь", "Februar": "Февраль", "März": "Март", "April": "Апрель",
    "Mai": "Май", "Juni": "Июнь", "Juli": "Июль", "August": "Август",
    "September": "Сентябрь", "Oktober": "Октябрь", "November": "Ноябрь", "Dezember": "Декабрь",
}

STATES = {
    "Baden-Württemberg": "Баден-Вюртемберг",
    "Bayern": "Бавария",
    "Berlin": "Берлин",
    "Brandenburg": "Бранденбург",
    "Bremen": "Бремен",
    "Hamburg": "Гамбург",
    "Hessen": "Гессен",
    "Mecklenburg-Vorpommern": "Мекленбург-Передняя Померания",
    "Niedersachsen": "Нижняя Саксония",
    "Nordrhein-Westfalen": "Северный Рейн-Вестфалия",
    "Rheinland-Pfalz": "Рейнланд-Пфальц",
    "Saarland": "Саар",
    "Sachsen-Anhalt": "Саксония-Анхальт",
    "Sachsen": "Саксония",
    "Schleswig-Holstein": "Шлезвиг-Гольштейн",
    "Thüringen": "Тюрингия",
}

_MONTH_RE = re.compile(r"^(" + "|".join(MONTHS) + r")\s+(\d{4})$")
_LOCATION_RE = re.compile(r"^(\d{4,5})\s+(.+?)\s+-\s+(.+)$")


def label_ru(label: str, translator: "Translator") -> str:
    return LABELS.get(label) or translator.translate(label)


def value_ru(value: str, translator: "Translator") -> str:
    if value in VALUES:
        return VALUES[value]
    m = _MONTH_RE.match(value)
    if m:
        return f"{MONTHS[m.group(1)]} {m.group(2)}"
    return translator.translate(value)


def location_ru(location: str) -> str:
    """"31832 Niedersachsen - Springe" -> "31832 Springe (Нижняя Саксония)". Названия городов не переводим."""
    m = _LOCATION_RE.match(location)
    if m and m.group(2) in STATES:
        return f"{m.group(1)} {m.group(3)} ({STATES[m.group(2)]})"
    return location


class Translator:
    """Перевод немецкого текста на русский. Без ключа DeepL текст остаётся немецким,
    и бот всё равно работает. Ошибки сервиса тоже не ломают публикацию."""

    def __init__(self, api_key: str = "", session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.cache: dict[str, str] = {}
        self._warned = False

    def _warn_once(self, msg: str) -> None:
        if not self._warned:
            logger.warning(msg)
            self._warned = True

    def translate(self, text: str) -> str:
        return self.translate_many([text])[0]

    def translate_many(self, texts: list[str]) -> list[str]:
        out = [t for t in texts]
        pending = sorted({t for t in texts if t.strip() and t not in self.cache})
        if pending and self.api_key:
            try:
                resp = self.session.post(
                    DEEPL_URL,
                    headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
                    data={"text": pending, "source_lang": "DE", "target_lang": "RU"},
                    timeout=30,
                )
                resp.raise_for_status()
                for src, item in zip(pending, resp.json()["translations"]):
                    self.cache[src] = item["text"]
            except Exception as exc:  # сеть, лимиты, неверный ключ — публикуем немецкий текст
                logger.warning("Translation failed, keeping German text: %s", exc)
        elif pending:
            self._warn_once("DEEPL_API_KEY is not set: texts stay in German")
        return [self.cache.get(t, t) for t in out]
