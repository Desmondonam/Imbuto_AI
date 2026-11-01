"""SMS commands. Replies fit one GSM-7 segment, because every extra segment costs the sender."""

import unicodedata

from imbuto.core.service import CROPS, Imbuto, t

MAX_SMS = 160
CROP_WORDS = {
    "beans": {"BEANS", "IBIHARAGE", "HARICOTS", "HARICOT"},
    "maize": {"MAIZE", "IBIGORI", "MAIS"},
    "cassava": {"CASSAVA", "IMYUMBATI", "MANIOC"},
    "bananas": {"BANANAS", "BANANA", "IBITOKE", "BANANES"},
    "potatoes": {"POTATOES", "IBIRAYA", "POMMES"},
}


def gsm7(text: str, limit: int = MAX_SMS) -> str:
    """Strip accents, which would otherwise force costly UCS-2, and cut at a word boundary."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    plain = " ".join(plain.split())
    return plain if len(plain) <= limit else plain[: limit - 3].rsplit(" ", 1)[0] + "..."


def reply(app: Imbuto, phone: str, message: str) -> str:
    subscriber = app.store.subscriber(phone)
    lang = subscriber["lang"] if subscriber else "rn"
    commune_id = subscriber["commune_id"] if subscriber else None
    words = message.split()
    command = words[0].upper() if words else ""
    rest = " ".join(words[1:])

    if command == "STOP":
        app.store.forget_subscriber(phone)
        return gsm7(t(lang, "stop_ok"))
    if command in {"KOMINE", "COMMUNE"} and rest:
        commune = app.find_commune(rest)
        if commune is None:
            return gsm7(t(lang, "sms_area_unknown"))
        app.store.save_subscriber(phone, lang, commune["id"])
        return gsm7(t(lang, "saved_area", commune=commune["name"]))
    if command in {"LANGUE", "URURIMI", "LANGUAGE"} and rest.lower() in ("rn", "fr", "en"):
        app.store.save_subscriber(phone, rest.lower(), commune_id)
        return gsm7(t(rest.lower(), "sms_help"))
    if command in {"IMVURA", "RAIN", "PLUIE"}:
        rain = app.rain_for(commune_id, lang) if commune_id else None
        return gsm7(rain["message"] if rain else t(lang, "sms_need_area"))
    if command in {"IGICIRO", "PRICE", "PRIX"}:
        wanted = next(
            (crop for crop in CROPS if rest.upper().split()[:1] and
             rest.upper().split()[0] in CROP_WORDS[crop]), "beans",
        )  # fmt: skip
        return gsm7(app.price_for(wanted, commune_id, lang)["message"])
    if command in {"INAMA", "ADVICE", "CONSEIL"} and rest:
        return gsm7(app.ask(rest, lang, "sms").text)
    return gsm7(t(lang, "sms_help"))
