import numpy as np

from imbuto.monitoring.metrics import psi, summary


def test_psi_is_small_for_same_shape_and_large_for_a_shift():
    rng = np.random.default_rng(0)
    reference = rng.beta(8, 2, 2000).tolist()
    assert psi(reference, rng.beta(8, 2, 2000).tolist()) < 0.1
    assert psi(reference, rng.beta(2, 5, 2000).tolist()) > 0.25


def test_summary_stays_quiet_until_it_has_enough_data(core):
    report = summary(core.store, [0.9] * 50)
    assert report["drift_psi"] is None or report["predictions"] >= 30
