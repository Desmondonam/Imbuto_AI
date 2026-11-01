import numpy as np

from imbuto.monitoring.metrics import psi, summary
from imbuto.monitoring.store import Store


def test_psi_is_small_for_same_shape_and_large_for_a_shift():
    rng = np.random.default_rng(0)
    reference = rng.beta(8, 2, 2000).tolist()
    assert psi(reference, rng.beta(8, 2, 2000).tolist()) < 0.1
    assert psi(reference, rng.beta(2, 5, 2000).tolist()) > 0.25


def _log(store, outcome, count):
    for _ in range(count):
        store.log_prediction(model="m", version="1", channel="t", outcome=outcome, label="x",
                             confidence=0.5, similarity=0.5, latency_ms=1.0)  # fmt: skip


def test_alert_needs_a_full_window(tmp_path):
    store = Store(tmp_path / "x.sqlite", "k")
    _log(store, "unsure", 29)
    assert summary(store, [0.9] * 50)["drift_alert"] is False


def test_recent_shift_alerts_even_after_a_long_healthy_day(tmp_path):
    store = Store(tmp_path / "x.sqlite", "k")
    _log(store, "confident", 500)
    assert summary(store, [0.9] * 50)["drift_alert"] is False
    _log(store, "unsure", 12)
    assert summary(store, [0.9] * 50)["drift_alert"] is True
