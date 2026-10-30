import json
import unittest
from pathlib import Path

from kb.filters import KeywordFilter

CFG = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text(encoding="utf-8"))


def make_filter() -> KeywordFilter:
    return KeywordFilter(
        CFG["positive_patterns"],
        CFG["negation_words"],
        CFG["after_negation_words"],
        CFG["negation_frames"],
    )


ACCEPT = [
    "Job-Center willkommen",
    "Auch Jobcenter-Kunden willkommen",
    "Jobcenter ok",
    "JobCenter erlaubt",
    "Job Center kein Problem, wir freuen uns auf Sie",  # "kein" относится к "Problem", а не к Job Center
    "Mietübernahme durch das Jobcenter möglich",
    "Miete wird vom Jobcenter übernommen",
    "Kostenübernahme durch das Amt ist möglich",
    "Das Amt zahlt die Miete direkt",
    "ARGE akzeptiert",
    "SGB II Empfänger gerne",
    "Jobcentre willkommen",
    "Jobcenters willkommen",
    "JC willkommen",
    "Nicht rauchen. Job-Center willkommen",  # отрицание в другом предложении
    "Haustiere verboten, Jobcenter ok",  # отрицание в другой части предложения
    "Jobcenter nicht ausgeschlossen",  # двойное отрицание
    "Jobcenter-Zahlungen sind willkommen, Haustiere nicht erlaubt",
    "Mit Jobcenter-Hintergrund gerne melden",
    "Wohnung ist für Jobcenter-Empfänger geeignet",
    "Job–Center (mit Gedankenstrich) willkommen",
    "Nur für Jobcenter-Empfänger",
    "Gerne auch an Jobcenter-Empfänger vermieten",
    "Jobcenter-Empfänger willkommen, keine WG",
    "Haustiere nicht erlaubt, Jobcenter willkommen",
    "Keine Makler und Jobcenter ok",
    "Jobcenter ok und keine Haustiere",
    "Jobcenter kein Problem",
    "Keine Probleme mit Jobcenter",
    "Auch für Mieter mit Unterstützung durch das Jobcenter geeignet (vorbehaltlich der Kostenübernahme)",
    "Bitte keine Anfragen per Telefon. Jobcenter ok",
]

REJECT = [
    # прямые отрицания
    "Vermietung nicht an Job-Center",
    "Vermietung nicht an Jobcenter-Empfänger",
    "Keine Jobcenter-Zahlungen",
    "Keine Vermietung an Jobcenter",
    "Kein Jobcenter",
    "Keine Mietübernahme durch das Jobcenter",
    "Wohnung ohne Jobcenter",
    "Ohne Jobcenter-Zahlungen",
    "Keine Zahlungen vom Jobcenter",
    "Jobcenter ausgeschlossen",
    "Jobcenter nein danke",
    "Jobcenter nicht möglich",
    "Jobcenter nicht erwünscht",
    "Jobcenter unerwünscht",
    "Jobcenter abgelehnt",
    "Jobcenter? Nein",
    "Für Jobcenter-Empfänger nicht geeignet",
    "Ausschluss: Jobcenter",
    "Nicht für Bezieher von Jobcenter-Leistungen",
    "Keine Miete über Jobcenter möglich",
    "Mietübernahme durch das Amt ist leider nicht möglich",
    "Kein Amt, keine ARGE",
    "Kein Jobcenter, Haustiere ok",  # отрицание в первой части
    "Vermietung nicht an Menschen mit Jobcenter",
    "Jobcenter ist kein Thema für uns",
    "Keine Transferleistungen, kein Jobcenter",
    "Nur Selbstzahler, kein Jobcenter",
    "Jobcenter-Kunden kommen nicht in Frage",
    "Wohnung nicht für Jobcenter-Empfänger",
    "Kein Jobcenter, aber Haustiere ok",
    "Jobcenter? Leider nein",
    "JC nicht erwünscht",
    "Mietkostenübernahme durch Jobcenter ausgeschlossen",
    "Keine Makler, kein Jobcenter",
    # реальный случай из предпросмотра: запятая не должна снимать отрицание
    "Bitte keine Anfragen von Personen, die Leistungen vom Jobcenter oder Sozialhilfe erhalten, da die Kosten aufgrund der Wohnungsgröße nicht übernommen werden.",
    "Keine Anfragen von Jobcenter-Empfängern",
    "Keine Anfragen von Leistungsempfängern, Jobcenter ist ausgeschlossen",
    "Nur Selbstzahler, Jobcenter ok",
    "Nicht für Personen mit Jobcenter-Zahlungen",
]

NO_KEYWORD = [
    "Schöne 2-Zimmer-Wohnung mit Balkon in Berlin",
    "Bürgergeld willkommen",  # по запросу: только Jobcenter, Bürgergeld не учитываем
    "ALG II und Hartz IV gerne",  # то же самое
    "Keine Transferleistungen",
]


class KeywordFilterTests(unittest.TestCase):
    def setUp(self):
        self.flt = make_filter()

    def test_accepted_phrasings(self):
        for text in ACCEPT:
            with self.subTest(text=text):
                v = self.flt.evaluate(text)
                self.assertTrue(v.accepted, f"should accept: {text!r} ({v.reason})")

    def test_rejected_phrasings(self):
        for text in REJECT:
            with self.subTest(text=text):
                v = self.flt.evaluate(text)
                self.assertFalse(v.accepted, f"should reject: {text!r} ({v.matches})")

    def test_no_keyword(self):
        for text in NO_KEYWORD:
            with self.subTest(text=text):
                v = self.flt.evaluate(text)
                self.assertFalse(v.accepted, f"should not match: {text!r}")


if __name__ == "__main__":
    unittest.main()
