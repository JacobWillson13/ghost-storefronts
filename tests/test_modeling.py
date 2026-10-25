import numpy as np
from sklearn.metrics import average_precision_score

from storefronts.modeling import bootstrap_stat, calibrate, calibrated


def test_bootstrap_ap_handles_score_ties_and_record_multiplicity():
    y = np.array([1, 0, 1, 0, 0, 1])
    score = np.array([0.8, 0.8, 0.4, 0.4, 0.2, 0.1])
    weights = np.array([2, 0, 1, 3, 1, 2])
    ap, p10 = bootstrap_stat(y, score, np.arange(len(y)), weights)
    expected = average_precision_score(np.repeat(y, weights), np.repeat(score, weights))
    assert abs(ap - expected) < 1e-12
    assert p10 == 1


def test_platt_uses_validation_labels_without_changing_ranking():
    raw = np.array([0.01, 0.05, 0.1, 0.2, 0.3, 0.6, 0.7, 0.8, 0.9, 0.99])
    cal = calibrate(raw, np.array([0, 0, 0, 1, 0, 1, 1, 1, 1, 1]))
    p = calibrated(cal, raw)
    assert ((p > 0) & (p < 1)).all()
    assert np.array_equal(np.argsort(raw), np.argsort(p))
