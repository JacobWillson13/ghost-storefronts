"""Snapshot estimates conditional on the visited-business model and calibration sample."""

from __future__ import annotations

import time

import joblib
import numpy as np
import pandas as pd
from scipy.special import expit, logit

from storefronts.config import REPO_ROOT
from storefronts.gold import query, write_json
from storefronts.modeling import MODEL_DIR, SEED, calibrate, calibrated, frame


def grouped(f, by):
    out = (
        f.groupby(by, dropna=False)
        .agg(
            businesses=("business_id", "size"),
            expected_oob=("probability", "sum"),
            mean_probability=("probability", "mean"),
        )
        .reset_index()
    )
    return out.sort_values("expected_oob", ascending=False).to_dict(orient="records")


def run(resamples=500):
    started = time.monotonic()
    f = frame(query("ghost_rows", "business_status"))
    assert f.business_id.is_unique
    bundle = joblib.load(MODEL_DIR / "live_lightgbm_history.joblib")
    raw = bundle["model"].predict_proba(f)[:, 1]
    p = calibrated(bundle["calibrator"], raw)
    f["probability"] = p
    no_chain = joblib.load(MODEL_DIR / "live_history_no_chain.joblib")
    no_chain_p = calibrated(no_chain["calibrator"], no_chain["model"].predict_proba(f)[:, 1])
    recent = f.last_positive >= pd.Timestamp("2023-01-01")
    groups, ids = pd.factorize(bundle["validation_business_id"], sort=True)
    rng = np.random.default_rng(SEED)
    values = []
    x = logit(np.clip(raw, 1e-6, 1 - 1e-6))
    for _ in range(resamples):
        multiplicity = np.bincount(rng.integers(0, len(ids), len(ids)), minlength=len(ids))
        cal = calibrate(
            bundle["validation_score"], bundle["validation_y"], sample_weight=multiplicity[groups]
        )
        values.append(float(expit(cal.coef_[0, 0] * x[recent] + cal.intercept_[0]).sum()))
    primary = f.loc[recent].copy()
    result = {
        "snapshot_date": "2026-08-23",
        "exclusive_as_of": "2026-08-24T00:00:00",
        "population": "Positive observation since 2023-01-01 and no unresolved OOB",
        "eligible_businesses": len(primary),
        "expected_oob": float(p[recent].sum()),
        "bootstrap_ci95": np.quantile(values, [0.025, 0.975]).tolist(),
        "bootstrap_method": (
            f"{resamples} business-cluster resamples of Oct-Dec 2024 calibration rows; "
            "refit Platt calibrator only, freeze base model and snapshot population. "
            "Calibration uncertainty only; excludes base-model fitting, population selection, "
            "stale identities and future drift."
        ),
        "probability_min_mean_max": [
            float(p[recent].min()),
            float(p[recent].mean()),
            float(p[recent].max()),
        ],
        "sensitivities": [
            {
                "variant": "positive_since_2023_primary",
                "businesses": len(primary),
                "expected_oob": float(p[recent].sum()),
            },
            {
                "variant": "positive_since_2023_uncalibrated",
                "businesses": len(primary),
                "expected_oob": float(raw[recent].sum()),
            },
            {
                "variant": "full_history_calibrated_sensitivity",
                "businesses": len(f),
                "expected_oob": float(p.sum()),
            },
            {
                "variant": "positive_since_2023_refit_without_chain_flag",
                "businesses": len(primary),
                "expected_oob": float(no_chain_p[recent].sum()),
            },
        ],
        "by_industry": grouped(primary, ["industry_group"]),
        "by_nta": grouped(
            primary.fillna({"nta2020": "UNMAPPED", "nta_name": "UNMAPPED"}),
            ["nta2020", "nta_name"],
        ),
        "by_last_positive_year": grouped(
            primary.assign(last_positive_year=primary.last_positive.dt.year),
            ["last_positive_year"],
        ),
        "full_history_by_last_positive_year": grouped(
            f.assign(last_positive_year=f.last_positive.dt.year), ["last_positive_year"]
        ),
        "timing_seconds": round(time.monotonic() - started, 2),
    }
    primary[["business_id", "last_positive", "probability"]].to_csv(
        MODEL_DIR / "ghost_scores.csv.gz", index=False
    )
    write_json(REPO_ROOT / "reports/ghost_count.json", result)
    return result
