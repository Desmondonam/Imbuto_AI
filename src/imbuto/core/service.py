"""The application core. Every channel calls this; none of it knows about HTTP, USSD or SMS."""

import json
import time
from dataclasses import dataclass
from functools import lru_cache

from imbuto.ml.advisory import Advisory, Answer
from imbuto.ml.bundle import load_bundle
from imbuto.ml.crop_health import CropHealthModel, Diagnosis
from imbuto.monitoring import metrics
from imbuto.monitoring.store import Store
from imbuto.settings import ARTIFACTS, KNOWLEDGE, LOCALE, Settings

LANGUAGES = ("rn", "fr", "en")
CROPS = ("beans", "maize", "cassava", "bananas", "potatoes")


@lru_cache
def _catalogue(lang: str) -> dict:
    return json.loads((LOCALE / f"{lang}.json").read_text())


def t(lang: str, key: str, **values) -> str:
    text = _catalogue(lang if lang in LANGUAGES else "rn")[key]
    return text.format(**values) if values else text


@dataclass
class Prediction:
    id: int
    diagnosis: Diagnosis
    message: str


class Imbuto:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.settings.validate()
        self.store = Store(self.settings.db_path, self.settings.phone_hash_key)
        self.crop_model = CropHealthModel(ARTIFACTS / "crop_health")
        self.rain_bundle = load_bundle(ARTIFACTS / "rain")
        self.reference_bundle = load_bundle(ARTIFACTS / "reference")
        self.rain_status = json.loads((ARTIFACTS / "rain" / "rain_status.json").read_text())
        self.communes = json.loads((ARTIFACTS / "reference" / "communes.json").read_text())
        self.prices = json.loads((ARTIFACTS / "reference" / "prices.json").read_text())
        self.advisory = Advisory(KNOWLEDGE / "kb.json", allow_drafts=self.settings.demo_content)
        self.commune_by_id = {c["id"]: c for c in self.communes}
        self.rain_by_id = {c["commune_id"]: c for c in self.rain_status["communes"]}

    # Places
    def provinces(self) -> list[str]:
        return sorted({c["province"] for c in self.communes})

    def districts(self, province: str) -> list[str]:
        return sorted({c["district"] for c in self.communes if c["province"] == province})

    def communes_in(self, district: str) -> list[dict]:
        return [c for c in self.communes if c["district"] == district]

    def find_commune(self, name: str) -> dict | None:
        wanted = name.strip().casefold()
        return next((c for c in self.communes if c["name"].casefold() == wanted), None)

    # Answers
    def rain_for(self, commune_id: str, lang: str) -> dict | None:
        status = self.rain_by_id.get(commune_id)
        if status is None:
            return None
        message = t(
            lang, "rain_msg", commune=self.commune_by_id[commune_id]["name"],
            rain=round(status["rain_mm"]), percent=status["percent_of_normal"],
            status=t(lang, status["status"]), through=self.rain_status["observed_through"],
        )  # fmt: skip
        through, source = self.rain_status["observed_through"], self.rain_status["source"]
        return {**status, "message": message, "observed_through": through, "source": source}

    def price_for(self, crop: str, commune_id: str | None, lang: str) -> dict:
        commune = self.commune_by_id.get(commune_id or "")
        table = self.prices.get(crop, {})
        area = commune["district"] if commune and commune["district"] in table else "Burundi"
        entry = table.get(area)
        name = t(lang, f"crop_{crop}")
        if entry is None:
            return {"crop": crop, "message": t(lang, "no_price", crop=name)}
        message = t(lang, "price_msg", crop=name, price=f"{entry['price']:,}".replace(",", " "),
                    area=area, month=entry["month"])  # fmt: skip
        return {"crop": crop, "area": area, **entry, "message": message}

    def ask(self, question: str, lang: str, channel: str) -> Answer:
        metrics.REQUESTS.labels(channel).inc()
        answer = self.advisory.answer(question, lang)
        if answer.escalate:
            metrics.ESCALATIONS.inc()
            answer.text = t(lang, "escalate")
        self.store.log_question(
            channel, lang, question, answer.source_id, answer.score, answer.escalate
        )
        return answer

    def diagnose(self, image: bytes, lang: str, channel: str) -> Prediction:
        metrics.REQUESTS.labels(channel).inc()
        started = time.perf_counter()
        diagnosis = self.crop_model.predict(image)
        elapsed = time.perf_counter() - started
        metrics.LATENCY.observe(elapsed)
        metrics.PREDICTIONS.labels(diagnosis.outcome).inc()
        prediction_id = self.store.log_prediction(
            model="crop_health", version=self.crop_model.version, channel=channel,
            outcome=diagnosis.outcome, label=diagnosis.label, confidence=diagnosis.confidence,
            similarity=diagnosis.similarity, latency_ms=round(elapsed * 1000, 2),
        )  # fmt: skip
        message = {
            "confident": t(lang, "diag_confident", label=t(lang, diagnosis.label)),
            "unsure": t(lang, "diag_unsure"),
            "not_a_leaf": t(lang, "diag_not_leaf"),
        }[diagnosis.outcome]
        return Prediction(prediction_id, diagnosis, message)

    def ops_summary(self) -> dict:
        reference = self.crop_model.card["metrics"]["reference_confidence"]
        return metrics.summary(self.store, reference)
