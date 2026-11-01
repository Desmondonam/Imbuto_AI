import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from imbuto.api.main import create_app
from imbuto.core.service import Imbuto
from imbuto.settings import Settings


def jpeg(colour=(40, 120, 40), size=(320, 320)):
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, "JPEG")
    return buffer.getvalue()


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["models"]["crop_health"] == "1.0.0"


def test_rain_api_never_exposes_the_withheld_forecast(client):
    body = client.get("/api/v1/rain/BI001?lang=en").json()
    assert "experimental_shortfall_probability" not in body
    assert "% of normal" in body["message"]
    assert client.get("/api/v1/rain/NOPE").status_code == 404


def test_prices_fall_back_to_national(client):
    assert client.get("/api/v1/prices/beans").json()["area"] == "Burundi"
    assert client.get("/api/v1/prices/gold").status_code == 404


def test_advice_answers_from_the_knowledge_base(client):
    body = client.post("/api/v1/advice", json={"question": "beans leaves orange rust",
                                               "lang": "en"}).json()  # fmt: skip
    assert body["source"] == "bean-rust" and body["escalated"] is False


def test_off_topic_question_goes_to_a_person(client):
    body = client.post("/api/v1/advice", json={"question": "what pesticide dose for tomatoes",
                                               "lang": "en"}).json()  # fmt: skip
    assert body["escalated"] is True and body["source"] is None


def test_diagnose_flags_non_leaf_and_records_it(client):
    response = client.post("/api/v1/diagnose", files={"image": ("a.jpg", jpeg(), "image/jpeg")})
    assert response.status_code == 200 and response.json()["outcome"] == "not_a_leaf"
    prediction = response.json()["prediction_id"]
    assert client.post("/api/v1/feedback", json={"prediction_id": prediction,
                                                 "correct": False}).status_code == 200  # fmt: skip


def test_garbage_upload_is_rejected(client):
    files = {"image": ("a.jpg", b"not an image", "image/jpeg")}
    assert client.post("/api/v1/diagnose", files=files).status_code == 422


def test_oversized_upload_is_rejected(client):
    files = {"image": ("a.jpg", b"x" * 2_000_001, "image/jpeg")}
    assert client.post("/api/v1/diagnose", files=files).status_code == 413


def test_web_works_without_javascript(client):
    page = client.post("/ask", data={"question": "maize caterpillars"})
    assert page.status_code == 200 and "maize-armyworm" in page.text
    photo = client.post("/photo", files={"image": ("a.jpg", jpeg(), "image/jpeg")})
    assert photo.status_code == 200


def test_template_escapes_user_text(client):
    page = client.post("/ask", data={"question": "<script>alert(1)</script>"})
    assert "<script>alert(1)" not in page.text


@pytest.mark.parametrize("path", ["/", "/area", "/prices", "/ask", "/photo", "/dashboard",
                                  "/simulator", "/ops", "/offline", "/sw.js", "/metrics",
                                  "/api/docs"])  # fmt: skip
def test_every_page_loads(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("lang", ["rn", "fr", "en"])
def test_every_language_renders(client, lang):
    assert client.get(f"/?lang={lang}").status_code == 200


def test_production_refuses_default_secrets(tmp_path):
    with pytest.raises(RuntimeError, match="IMBUTO_PHONE_HASH_KEY"):
        Imbuto(Settings(env="production", db_path=tmp_path / "x.sqlite"))


def test_tokens_protect_gateways_and_ops(tmp_path):
    settings = Settings(db_path=tmp_path / "x.sqlite", gateway_token="g", ops_token="o")
    client = TestClient(create_app(Imbuto(settings)))
    form = {"sessionId": "1", "phoneNumber": "+25769", "text": ""}
    assert client.post("/gateway/ussd", data=form).status_code == 401
    assert client.post("/gateway/ussd", data=form, headers={"x-token": "g"}).status_code == 200
    assert client.get("/metrics").status_code == 401
    assert client.get("/ops", headers={"x-token": "o"}).status_code == 200


def test_simulator_cannot_register_numbers_in_production(tmp_path):
    settings = Settings(env="production", db_path=tmp_path / "x.sqlite", phone_hash_key="k",
                        gateway_token="g", ops_token="o")  # fmt: skip
    client = TestClient(create_app(Imbuto(settings)))
    assert client.get("/simulator").status_code == 404
    form = {"session": "s", "phone": "+25769", "digit": ""}
    assert client.post("/simulator/ussd", data=form).status_code == 404
    assert client.post("/simulator/sms", data={"phone": "+25769", "text": "HI"}).status_code == 404


def test_rate_limit_applies(tmp_path):
    client = TestClient(create_app(Imbuto(Settings(db_path=tmp_path / "x.sqlite"))))
    codes = [client.post("/ask", data={"question": "beans"}).status_code for _ in range(31)]
    assert codes[-1] == 429
