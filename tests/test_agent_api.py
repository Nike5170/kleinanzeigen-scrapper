import unittest

from kb.agent_api import clean_html, to_listing
from kb.filters import is_tenant_wanted
from kb.telegram import build_messages
from kb.translate import Translator

AD = {
    "ad_id": "3548981912",
    "title": "Neu renovierte 2,5 Zimmer Wohnung",
    "description": "Zeile eins.<br>Jobcenter willkommen &amp; Haustiere erlaubt.",
    "price": {"amount": 850, "currency_code": "EUR", "negotiable": False},
    "images": ["https://img.kleinanzeigen.de/a.jpg", "https://img.kleinanzeigen.de/b.jpg"],
    "ad_url": "https://www.kleinanzeigen.de/s-anzeige/x/3548981912-203-8783",
    "seller": {"type": "PRIVATE"},
    "location": {"zip": "71034", "city": "Böblingen", "state": "Baden-Württemberg"},
    "attributes": [
        {"name": "wohnung_mieten.qm", "label": "Wohnfläche", "values": [{"value": "60", "label": "60"}]},
        {"name": "wohnung_mieten.verfuegbardate", "label": "Verfügbar ab", "values": [{"value": "2026-11", "label": "November 2026"}]},
    ],
}


class AgentMappingTests(unittest.TestCase):
    def test_clean_html(self):
        self.assertEqual(clean_html("a<br>b &amp; c"), "a\nb & c")

    def test_to_listing_maps_fields(self):
        l = to_listing(AD)
        self.assertEqual(l.ad_id, "3548981912")
        self.assertEqual(l.price, "850 €")
        self.assertEqual(l.location, "71034 Baden-Württemberg - Böblingen")
        self.assertIn("Jobcenter willkommen & Haustiere erlaubt.", l.description)
        self.assertEqual(l.attributes[0], ("Wohnfläche", "60"))
        self.assertFalse(l.is_commercial)
        self.assertEqual(l.offer_type, "Angebot")
        self.assertEqual(len(l.photo_urls), 2)

    def test_commercial_seller(self):
        ad = dict(AD, seller={"type": "COMMERCIAL"})
        self.assertTrue(to_listing(ad).is_commercial)

    def test_messages_build_from_api_listing(self):
        msgs = build_messages(to_listing(AD), Translator(""))
        self.assertLessEqual(len(msgs), 2)
        self.assertIn("Площадь: 60", msgs[0])


class TenantFilterTests(unittest.TestCase):
    def test_tenant_ads_are_detected(self):
        self.assertTrue(is_tenant_wanted("Mieterin sucht 1-Zimmer-Wohnung (Jobcenter-Übernahme gesichert)"))
        self.assertTrue(is_tenant_wanted("Suche Wohnung für eine Familie über das Jobcenter"))
        self.assertTrue(is_tenant_wanted("Gesucht: 2 Zimmer"))

    def test_landlord_ads_are_not_tenant(self):
        self.assertFalse(is_tenant_wanted("3,5-Zimmer-Wohnung in Harsefeld zu vermieten"))
        self.assertFalse(is_tenant_wanted("KEIN JOBCENTER - Helle 4-Zi.-Wohnung in Köln"))
        self.assertFalse(is_tenant_wanted("3,5-Zimmer-Wohnung", "Wir suchen nette Mieter – ideal für eine Familie."))
        self.assertFalse(is_tenant_wanted("Nachmieter gesucht – 2 Zimmer"))

    def test_tenant_text_in_description(self):
        self.assertTrue(is_tenant_wanted("Wohnung in Lübeck (Miete über Jobcenter)",
                                         "Wohnungssuche in Lübeck. Liebe Vermieterinnen und Vermieter, wir sind eine Familie"))
        self.assertTrue(is_tenant_wanted("eine kleine Wohnung die das Jobcenter bezahlen kann",
                                         "Ich suche eine Wohnung die vom Jobcenter übernommen werden kann"))


if __name__ == "__main__":
    unittest.main()
