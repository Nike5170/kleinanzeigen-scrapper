import re
from dataclasses import dataclass, field

# Предложения: точка, восклицание, точка с запятой, перенос строки, скобки.
# Вопросительный знак намеренно не делит: "Jobcenter? Nein danke" должно отрицаться.
_SENTENCE_BREAK = re.compile(r"[.!;\n()\[\]]+")

# Части предложения: запятая, двоеточие, союзы. Отрицание обычно относится к своей части:
# "Haustiere verboten, Jobcenter ok", "Keine Makler und Jobcenter ok".
_CLAUSE_BREAK = re.compile(
    r"[,/|•]+|\b(?:und|oder|sowie|bzw|aber|jedoch|sondern|allerdings|hingegen|trotzdem|dagegen|wobei|dafür|dafuer)\b",
    re.IGNORECASE,
)

# Сильные союзы противопоставления: отрицание до них на позитив после них не распространяется.
_STRONG_BREAK = re.compile(
    r"\b(?:aber|jedoch|sondern|allerdings|hingegen|trotzdem|dagegen|wobei|dafür|dafuer)\b",
    re.IGNORECASE,
)

# "Ausschluss: Jobcenter" — метка с двоеточием относится ко всей фразе, двоеточие убираем.
_NEG_LABEL = re.compile(r"\b(ausschluss|ausgeschlossen|kein|keine|nicht|verboten|nein)\s*:", re.IGNORECASE)

# Двойные отрицания и "kein Problem" (= "без проблем", то есть позитив).
_NORMALIZE = [
    (re.compile(r"\bnicht\s+(?:ausgeschlossen|abgelehnt|unerwünscht|unerwuenscht|verboten)\b", re.IGNORECASE), "erlaubt"),
    (re.compile(r"\bkeine?\s+(?:probleme?|hindernisse?|bedenken)\b", re.IGNORECASE), "erlaubt"),
    (re.compile(r"\bkein\s+problem\b", re.IGNORECASE), "erlaubt"),
    (_NEG_LABEL, r"\1 "),
]

# Отрицания, которые работают и ПОСЛЕ слова: "Jobcenter ist kein Thema", "Jobcenter nicht möglich".
_NEG_TOKENS_AFTER = ["nicht", "kein", "keine", "keinen", "keiner", "keinem", "nie", "niemals", "nein"]

_DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-"})


@dataclass
class Verdict:
    accepted: bool
    reason: str
    matches: list[str] = field(default_factory=list)


class KeywordFilter:
    """Проверка, что в объявлении прямо разрешено или предполагается аренда по Jobcenter.

    Позитивное совпадение (jobcenter / arge / sgb ii / "Miete vom Amt" и т.п.) засчитывается,
    только если рядом нет отрицания. Отрицание ищется в той же части предложения:
    перед словом ("keine", "nicht an", "ohne", "ausschluss") или сразу после него
    ("ausgeschlossen", "nicht erwünscht", "nein", "nicht möglich", ...).
    """

    def __init__(self, positive_patterns, negation_words, after_negation_words, negation_frames=()):
        self.positive = [re.compile(p, re.IGNORECASE) for p in positive_patterns]
        # Фразы-рамки ("keine Anfragen von Personen, die …"), которые действуют на всё предложение
        # до сильного союза (aber/jedoch/sondern), даже если между ними есть запятая.
        self.frames = [re.compile(p, re.IGNORECASE) for p in negation_frames]
        self.neg_before = re.compile(
            r"(?<!\w)(" + "|".join(map(re.escape, negation_words)) + r")(?!\w)", re.IGNORECASE
        )
        self.neg_after = re.compile(
            r"(?<!\w)(" + "|".join(map(re.escape, list(after_negation_words) + _NEG_TOKENS_AFTER)) + r")(?!\w)",
            re.IGNORECASE,
        )

    def evaluate(self, text: str) -> Verdict:
        text = text.translate(_DASHES)
        for pattern, repl in _NORMALIZE:
            text = pattern.sub(repl, text)

        accepted, negated = [], []
        for sentence in _SENTENCE_BREAK.split(text):
            for pattern in self.positive:
                for m in pattern.finditer(sentence):
                    before = self._clause_before(sentence, m.start())
                    after = self._clause_after(sentence, m.end())
                    framed = self._framed_negation(sentence[: m.start()])
                    if framed or self.neg_before.search(before) or self.neg_after.search(after):
                        negated.append(m.group(0))
                    else:
                        accepted.append(m.group(0))

        if accepted:
            return Verdict(True, "positive keyword", accepted)
        if negated:
            return Verdict(False, "only negated keyword", negated)
        return Verdict(False, "no keyword")

    def _framed_negation(self, head: str) -> bool:
        # Берём текст предложения до совпадения, но только после последнего сильного союза.
        cut = 0
        for m in _STRONG_BREAK.finditer(head):
            cut = m.end()
        segment = head[cut:]
        return any(f.search(segment) for f in self.frames)

    @staticmethod
    def _clause_before(sentence: str, pos: int) -> str:
        head = sentence[:pos]
        cut = None
        for m in _CLAUSE_BREAK.finditer(head):
            cut = m.end()
        return head[cut:] if cut is not None else head

    @staticmethod
    def _clause_after(sentence: str, pos: int) -> str:
        tail = sentence[pos:]
        m = _CLAUSE_BREAK.search(tail)
        return tail[: m.start()] if m else tail
