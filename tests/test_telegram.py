import unittest

from kb.scraper import Listing
from kb.telegram import build_messages
from kb.translate import Translator, location_ru, value_ru


def sample(description: str = "Kurze Beschreibung.") -> Listing:
    return Listing(
        ad_id="1",
        url="https://www.kleinanzeigen.de/s-anzeige/x/1",
        title="3,5-Zimmer-Wohnung",
        price="1.200 €",
        location="21698 Niedersachsen - Harsefeld",
        description=description,
        attributes=[("Wohnfläche", "95 m²"), ("Verfügbar ab", "September 2026"), ("Online-Besichtigung", "Nicht möglich")],
    )


class BuildMessagesTests(unittest.TestCase):
    def setUp(self):
        self.tr = Translator("")  # без ключа: текст остаётся немецким, но структура та же

    def test_short_listing_fits_two_messages_with_single_link(self):
        msgs = build_messages(sample(), self.tr)
        self.assertLessEqual(len(msgs), 2)
        joined = "\n".join(msgs)
        self.assertEqual(joined.count("https://www.kleinanzeigen.de/s-anzeige/x/1"), 1, "link must appear once")

    def test_link_is_in_first_message(self):
        msgs = build_messages(sample(), self.tr)
        self.assertIn("Открыть объявление", msgs[0])

    def test_russian_labels(self):
        text = build_messages(sample(), self.tr)[0]
        self.assertIn("💶 Цена: 1.200 €", text)
        self.assertIn("Площадь: 95 m²", text)
        self.assertIn("Доступно с: Сентябрь 2026", text)
        self.assertIn("Онлайн-просмотр: Нет", text)

    def test_long_description_is_split_not_truncated(self):
        long = "\n".join(f"Zeile {i} mit etwas Text." for i in range(300))
        msgs = build_messages(sample(long), self.tr)
        self.assertGreater(len(msgs), 2)
        self.assertIn("Zeile 299 mit etwas Text.", "\n".join(msgs))

    def test_location_and_values(self):
        self.assertEqual(location_ru("21698 Niedersachsen - Harsefeld"), "21698 Harsefeld (Нижняя Саксония)")
        self.assertEqual(value_ru("Etagenwohnung", self.tr), "Квартира на этаже")
        self.assertEqual(value_ru("Kein Tausch", self.tr), "Без обмена")


if __name__ == "__main__":
    unittest.main()
