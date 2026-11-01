import pytest

from imbuto.channels import sms
from imbuto.channels.menu import MAX_SCREEN, Menu, as_ussd
from imbuto.channels.voice import as_voice_xml


def walk(menu, session, phone, digits):
    screen = menu.handle(session, phone, None)
    for digit in digits:
        screen = menu.handle(session, phone, digit)
    return screen


REGISTER = ["3", "1", "1", "1", "1"]  # English, agree, first province, district, commune


def test_new_user_registers_then_gets_rain(core):
    menu = Menu(core, "ussd")
    assert "Imbuto AI" in walk(menu, "s1", "+25761000001", REGISTER).text
    assert core.store.subscriber("+25761000001")["consent"] == 1
    screen = walk(menu, "s2", "+25761000001", ["1"])  # returning user goes straight to main
    assert screen.end and "% of normal" in screen.text


def test_declining_consent_saves_nothing(core):
    screen = walk(Menu(core, "ussd"), "s3", "+25761000002", ["3", "2"])
    assert screen.end and core.store.subscriber("+25761000002") is None


def test_invalid_choice_repeats_the_screen(core):
    screen = walk(Menu(core, "ussd"), "s4", "+25761000003", ["7"])
    assert not screen.end and screen.text.startswith("Hitamwo")


@pytest.mark.parametrize("lang_digit", ["1", "2", "3"])
def test_every_screen_fits_a_ussd_message(core, lang_digit):
    menu = Menu(core, "ussd")
    phone = f"+2576100001{lang_digit}"
    screens = [walk(menu, f"reg{lang_digit}", phone, [lang_digit, "1", "1", "1", "1"])]
    paths = [["1"]] + [["2", str(i)] for i in range(1, 6)] + [["3", str(i)] for i in range(1, 6)]
    paths += [["4", str(i)] for i in range(1, 4)] + [["5"], ["6"], ["2"], ["3"], ["4"]]
    for index, path in enumerate(paths):
        screens.append(walk(menu, f"p{lang_digit}{index}", phone, path))
    assert max(len(s.text) for s in screens) <= MAX_SCREEN


def test_every_commune_page_fits_and_paging_wraps(core):
    menu = Menu(core, "ussd")
    for district in {c["district"] for c in core.communes}:
        state = {"at": "commune", "lang": "en", "district": district, "page": 0}
        pages = (len(core.communes_in(district)) + 5) // 6
        for number in range(pages):
            state["page"] = number
            assert len(menu._render(state).text) <= MAX_SCREEN


def test_ussd_wire_format(core):
    screen = walk(Menu(core, "ussd"), "s5", "+25761000004", [])
    assert as_ussd(screen).startswith("CON ")
    assert as_ussd(walk(Menu(core, "ussd"), "s6", "+25761000005", ["3", "2"])).startswith("END ")


def test_report_flows_into_the_store(core):
    menu = Menu(core, "ussd")
    walk(menu, "s7", "+25761000006", REGISTER)
    assert walk(menu, "s8", "+25761000006", ["4", "2"]).end
    with core.store.db() as con:
        assert con.execute("select count(*) from reports where kind = 'flood'").fetchone()[0] >= 1


def test_ussd_webhook_tracks_a_session_through_accumulated_text(client):
    form = {"sessionId": "w1", "phoneNumber": "+25761000007"}
    assert client.post("/gateway/ussd", data={**form, "text": ""}).text.startswith("CON")
    assert "Agree" in client.post("/gateway/ussd", data={**form, "text": "3"}).text
    assert "province" in client.post("/gateway/ussd", data={**form, "text": "3*1"}).text


def test_sms_flow_and_stop_deletes_the_number(core, client):
    phone = "+25761000008"
    assert "KOMINE" in client.post("/gateway/sms", data={"from": phone, "text": "IMVURA"}).text
    name = core.communes[0]["name"]
    client.post("/gateway/sms", data={"from": phone, "text": f"KOMINE {name}"})
    assert "%" in client.post("/gateway/sms", data={"from": phone, "text": "IMVURA"}).text
    client.post("/gateway/sms", data={"from": phone, "text": "STOP"})
    assert core.store.subscriber(phone) is None


def test_sms_replies_fit_one_plain_segment(core):
    phone = "+25761000009"
    sms.reply(core, phone, f"KOMINE {core.communes[0]['name']}")
    for lang in ("rn", "fr", "en"):
        sms.reply(core, phone, f"LANGUE {lang}")
        for text in ("IMVURA", "IGICIRO MAIS", "INAMA beans rust", "INAMA football", "HELP"):
            body = sms.reply(core, phone, text)
            assert len(body) <= 160 and body.isascii()


def test_gsm7_strips_accents_and_cuts_on_a_word():
    assert sms.gsm7("écarté") == "ecarte"
    assert len(sms.gsm7("word " * 100)) <= 160


def test_voice_keypad_menu_escapes_text(core, client):
    response = client.post("/gateway/voice", data={"sessionId": "v1", "callerNumber": "+2576"})
    assert response.headers["content-type"].startswith("application/xml")
    assert "<GetDigits" in response.text
    xml = as_voice_xml(type("S", (), {"text": "a & b", "end": True, "key": "x"}), "en", "/v")
    assert "a &amp; b" in xml


def test_alerts_reach_only_very_dry_subscribers(core):
    from imbuto.core.alerts import queue_alerts

    dry = next(c for c in core.rain_status["communes"] if c["status"] == "very_dry")
    wet = next(c for c in core.rain_status["communes"] if c["status"] != "very_dry")
    core.store.save_subscriber("+25762000001", "en", dry["commune_id"])
    core.store.save_subscriber("+25762000002", "en", wet["commune_id"])
    queue_alerts(core)
    with core.store.db() as con:
        numbers = {r[0] for r in con.execute("select msisdn from outbox").fetchall()}
    assert "+25762000001" in numbers and "+25762000002" not in numbers
