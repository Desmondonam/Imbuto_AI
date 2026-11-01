"""Voice menu rendered as gateway XML. Keypad only, so it needs no speech recognition.

Kirundi needs recorded prompts: no reliable Kirundi text-to-speech exists yet. When a file for
the screen is present it is played; otherwise the text is read by the gateway's voice, which is
only acceptable for French and English testing.
"""

from xml.sax.saxutils import escape, quoteattr

from imbuto.channels.menu import Screen
from imbuto.settings import ROOT

AUDIO = ROOT / "src" / "imbuto" / "api" / "static" / "audio"


def as_voice_xml(screen: Screen, lang: str, callback_url: str) -> str:
    recording = AUDIO / lang / f"{screen.key}.mp3"
    if recording.exists():
        prompt = f"<Play url={quoteattr(f'/static/audio/{lang}/{screen.key}.mp3')}/>"
    else:
        prompt = f"<Say>{escape(screen.text)}</Say>"
    if screen.end:
        return f'<?xml version="1.0"?><Response>{prompt}</Response>'
    return (
        f'<?xml version="1.0"?><Response><GetDigits timeout="10" numDigits="1" '
        f"callbackUrl={quoteattr(callback_url)}>{prompt}</GetDigits></Response>"
    )
