"""The 2G budget from docs/ARCHITECTURE.md. A failure here means a real user just got slower."""

import gzip
import json
import statistics

import pytest

from imbuto.settings import ARTIFACTS

FIRST_LOAD_BUDGET = 14_000
UPLOAD_BUDGET = 15_000


@pytest.mark.parametrize("path", ["/", "/ask", "/prices", "/photo"])
def test_farmer_pages_fit_the_first_load_budget(client, path):
    assert len(gzip.compress(client.get(path).content, 9)) < FIRST_LOAD_BUDGET


def test_area_picker_is_within_budget_despite_119_communes(client):
    assert len(gzip.compress(client.get("/area").content, 9)) < FIRST_LOAD_BUDGET


def test_gzip_is_on_for_text(client):
    response = client.get("/", headers={"accept-encoding": "gzip"})
    assert response.headers.get("content-encoding") == "gzip"


def test_home_page_needs_no_javascript_file(client):
    assert "<script src" not in client.get("/").text


def test_upload_budget_recorded_at_training():
    card = json.loads((ARTIFACTS / "crop_health" / "bundle.json").read_text())["card"]
    assert card["metrics"]["median_upload_bytes"] < UPLOAD_BUDGET


def test_ussd_is_fast_enough_for_operator_timeouts(client):
    import time

    samples = []
    for index in range(20):
        started = time.perf_counter()
        client.post("/gateway/ussd", data={"sessionId": f"t{index}", "phoneNumber": "+2576"})
        samples.append(time.perf_counter() - started)
    assert statistics.median(samples) < 0.2
