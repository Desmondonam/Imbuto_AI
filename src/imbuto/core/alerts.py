"""Queue rainfall alerts for subscribers in very dry communes. Run after each data refresh."""

from imbuto.channels.sms import gsm7
from imbuto.core.service import Imbuto


def queue_alerts(app: Imbuto) -> int:
    with app.store.db() as con:
        subscribers = con.execute(
            "select msisdn, lang, commune_id from subscribers where consent = 1"
        ).fetchall()
    sent = 0
    for person in subscribers:
        rain = app.rain_for(person["commune_id"], person["lang"])
        if person["msisdn"] and rain and rain["status"] == "very_dry":
            app.store.queue_sms(person["msisdn"], gsm7(rain["message"]))
            sent += 1
    return sent


if __name__ == "__main__":
    print(f"Queued {queue_alerts(Imbuto())} alerts")
