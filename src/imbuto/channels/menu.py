"""The phone menu, shared by USSD and voice. It takes one digit and returns one screen."""

from dataclasses import dataclass

from imbuto.core.service import CROPS, LANGUAGES, Imbuto, t

PAGE = 6
MAX_SCREEN = 182
TOPICS = ("beans", "maize", "banana", "storage", "soil")
PROBLEMS = ("pest", "flood", "dry")


@dataclass
class Screen:
    text: str
    end: bool = False
    key: str = ""  # identifies the recorded audio prompt for this screen


def _numbered(title: str, items: list[str]) -> str:
    lines = [title] + [f"{i} {item}" for i, item in enumerate(items, 1)]
    return "\n".join(lines)


class Menu:
    def __init__(self, app: Imbuto, channel: str):
        self.app = app
        self.channel = channel

    def handle(self, session_id: str, phone: str, digit: str | None) -> Screen:
        state = self.app.store.load_session(session_id)
        if not state:
            known = self.app.store.subscriber(phone)
            state = (
                {"at": "main", "lang": known["lang"], "commune": known["commune_id"]}
                if known and known["commune_id"]
                else {"at": "lang"}
            )
            screen = self._render(state)
        else:
            screen = self._step(state, phone, (digit or "").strip())
        self.app.store.save_session(session_id, state)
        return screen

    def _render(self, state: dict) -> Screen:
        lang, at = state.get("lang", "rn"), state["at"]
        if at == "lang":
            return Screen(
                "Hitamwo / Choisir / Choose\n1 Ikirundi\n2 Francais\n3 English", key="lang"
            )
        if at == "consent":
            return Screen(t(lang, "consent"), key="consent")
        if at == "main":
            return Screen(t(lang, "main"), key="main")
        if at == "province":
            return Screen(_numbered(t(lang, "province"), self.app.provinces()), key="province")
        if at == "district":
            items = self.app.districts(state["province"])
            return Screen(_numbered(t(lang, "district"), items), key="district")
        if at == "commune":
            names = [c["name"] for c in self._page(state)]
            lines = _numbered(t(lang, "commune"), names)
            return Screen(f"{lines}\n9 {t(lang, 'next')}", key="commune")
        if at == "crop":
            items = [t(lang, f"crop_{crop}") for crop in CROPS]
            return Screen(_numbered(t(lang, "choose_crop"), items), key="crop")
        if at == "topic":
            items = [t(lang, f"topic_{topic}") for topic in TOPICS]
            return Screen(_numbered(t(lang, "choose_topic"), items), key="topic")
        items = [t(lang, f"problem_{problem}") for problem in PROBLEMS]
        return Screen(_numbered(t(lang, "choose_problem"), items), key="problem")

    def _page(self, state: dict) -> list[dict]:
        communes = self.app.communes_in(state["district"])
        return communes[state.get("page", 0) * PAGE :][:PAGE]

    def _invalid(self, state: dict) -> Screen:
        screen = self._render(state)
        screen.text = f"{t(state.get('lang', 'rn'), 'invalid')}\n{screen.text}"[:MAX_SCREEN]
        return screen

    def _go(self, state: dict, at: str) -> Screen:
        state["at"] = at
        return self._render(state)

    def _step(self, state: dict, phone: str, digit: str) -> Screen:
        choice = int(digit) if digit.isdigit() else 0
        handler = getattr(self, f"_on_{state['at']}")
        return handler(state, phone, choice) or self._invalid(state)

    def _on_lang(self, state, phone, choice):
        if 1 <= choice <= len(LANGUAGES):
            state["lang"] = LANGUAGES[choice - 1]
            return self._go(state, "consent")

    def _on_consent(self, state, phone, choice):
        if choice == 1:
            return self._go(state, "province")
        if choice == 2:
            return Screen(t(state["lang"], "no_consent"), end=True, key="no_consent")

    def _on_province(self, state, phone, choice):
        provinces = self.app.provinces()
        if 1 <= choice <= len(provinces):
            state["province"] = provinces[choice - 1]
            return self._go(state, "district")

    def _on_district(self, state, phone, choice):
        districts = self.app.districts(state["province"])
        if 1 <= choice <= len(districts):
            state["district"], state["page"] = districts[choice - 1], 0
            return self._go(state, "commune")

    def _on_commune(self, state, phone, choice):
        if choice == 9:
            total = len(self.app.communes_in(state["district"]))
            state["page"] = (state["page"] + 1) % ((total + PAGE - 1) // PAGE)
            return self._render(state)
        page = self._page(state)
        if 1 <= choice <= len(page):
            state["commune"] = page[choice - 1]["id"]
            self.app.store.save_subscriber(phone, state["lang"], state["commune"])
            return self._go(state, "main")

    def _on_main(self, state, phone, choice):
        lang = state["lang"]
        if choice == 1:
            rain = self.app.rain_for(state["commune"], lang)
            return Screen(rain["message"], end=True, key="rain")
        if choice in (2, 3, 4):
            return self._go(state, {2: "crop", 3: "topic", 4: "problem"}[choice])
        if choice == 5:
            self.app.store.log_report(self.channel, state["commune"], "callback")
            return Screen(t(lang, "callback"), end=True, key="callback")
        if choice == 6:
            return self._go(state, "province")

    def _on_crop(self, state, phone, choice):
        if 1 <= choice <= len(CROPS):
            price = self.app.price_for(CROPS[choice - 1], state["commune"], state["lang"])
            return Screen(price["message"], end=True, key="price")

    def _on_topic(self, state, phone, choice):
        if 1 <= choice <= len(TOPICS):
            documents = self.app.advisory.by_topic(TOPICS[choice - 1])
            if documents:
                return Screen(documents[0][state["lang"]], end=True, key=documents[0]["id"])
            return Screen(t(state["lang"], "escalate"), end=True, key="escalate")

    def _on_problem(self, state, phone, choice):
        if 1 <= choice <= len(PROBLEMS):
            self.app.store.log_report(self.channel, state["commune"], PROBLEMS[choice - 1])
            return Screen(t(state["lang"], "report_saved"), end=True, key="report_saved")


def as_ussd(screen: Screen) -> str:
    """The common USSD wire format: CON keeps the session open, END closes it."""
    return f"{'END' if screen.end else 'CON'} {screen.text}"[: MAX_SCREEN + 4]
