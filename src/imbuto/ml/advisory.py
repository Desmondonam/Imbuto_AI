"""Grounded advice: retrieve one approved passage, or hand the question to a person.

Kirundi words change form with prefixes and suffixes, and no off-the-shelf tokeniser handles
them well, so matching uses overlapping character 4-grams rather than whole words. Answers are
quoted from the knowledge base, never generated, so nothing unvetted can reach a farmer.
"""

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

MIN_COVERAGE = 0.30
_NGRAM = 4


def _grams(text: str) -> list[str]:
    normalised = unicodedata.normalize("NFKD", text.lower())
    words = re.findall(r"[a-z']+", normalised.encode("ascii", "ignore").decode())
    grams = []
    for word in words:
        padded = f" {word} "
        grams += [padded[i : i + _NGRAM] for i in range(max(len(padded) - _NGRAM + 1, 1))]
    return grams


@dataclass
class Answer:
    text: str | None
    source_id: str | None
    score: float
    escalate: bool


class Advisory:
    def __init__(self, path: Path, allow_drafts: bool):
        documents = json.loads(path.read_text())
        self.documents = [d for d in documents if allow_drafts or d["status"] == "approved"]
        self.index = []
        for doc in self.documents:
            searchable = " ".join([doc["keywords"], doc["en"], doc["fr"], doc["rn"]])
            self.index.append(set(_grams(searchable)))
        count = max(len(self.index), 1)
        frequency = Counter(g for grams in self.index for g in grams)
        self.idf = {g: math.log(1 + count / n) for g, n in frequency.items()}
        self.unknown_idf = math.log(1 + count)

    def by_topic(self, topic: str) -> list[dict]:
        return [d for d in self.documents if d["topic"] == topic]

    def answer(self, question: str, lang: str) -> Answer:
        """Score documents by the informative share of the question they cover."""
        grams = set(_grams(question))
        total = sum(self.idf.get(g, self.unknown_idf) for g in grams)
        if not grams or not self.documents:
            return Answer(None, None, 0.0, True)
        scores = [sum(self.idf[g] for g in grams & doc) / total for doc in self.index]
        best = max(range(len(scores)), key=scores.__getitem__)
        score = round(scores[best], 3)
        if score < MIN_COVERAGE:
            return Answer(None, None, score, True)
        document = self.documents[best]
        return Answer(document[lang], document["id"], score, False)
