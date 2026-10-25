"""Temporal model comparison, validation-only calibration, paired business bootstrap."""

from __future__ import annotations

import hashlib
import math
import time
import warnings

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from scipy.special import logit
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from storefronts.config import REPO_ROOT
from storefronts.gold import query, write_json

NUMERIC = [
    "months_since_last_positive",
    "prior_visits",
    "prior_oob",
    "prior_violations",
    "prior_oob_unresolved",
    "has_prior_positive",
    "chain_flag",
]
CATEGORICAL = ["industry_group", "borough", "month"]
BUDGETS = [0.05, 0.10, 0.20]
SEED = 42
MODEL_DIR = REPO_ROOT / "models"


def frame(rows):
    f = pd.DataFrame(rows)
    for col in ["industry_group", "borough", "inspection_type"]:
        if col not in f:
            f[col] = "UNKNOWN"
        f[col] = f[col].fillna("UNKNOWN").astype(str)
    f["month"] = f.month.astype(str)
    for col in NUMERIC:
        f[col] = pd.to_numeric(f[col], errors="coerce").astype(float)
    f["tie"] = f._id.map(
        lambda x: int.from_bytes(hashlib.sha256(str(x).encode()).digest()[:8], "big")
    )
    return f


def ranking(score, tie):
    return np.lexsort((np.asarray(tie), -np.asarray(score)))


def model(kind, planned=False, no_chain=False):
    numbers = [c for c in NUMERIC if not (no_chain and c == "chain_flag")]
    prepare = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        (
                            "impute",
                            SimpleImputer(strategy="constant", fill_value=0, add_indicator=True),
                        ),
                        ("scale", StandardScaler()),
                    ]
                ),
                numbers,
            ),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore"),
                CATEGORICAL + (["inspection_type"] if planned else []),
            ),
        ]
    )
    estimator = (
        LogisticRegression(max_iter=1000)
        if kind == "logistic"
        else LGBMClassifier(n_jobs=4, random_state=SEED, verbosity=-1)
    )
    return Pipeline([("prepare", prepare), ("classifier", estimator)])


def platt_feature(score, probability=True):
    score = np.asarray(score, dtype=float)
    return (logit(np.clip(score, 1e-6, 1 - 1e-6)) if probability else score).reshape(-1, 1)


def calibrate(score, y, probability=True, sample_weight=None):
    calibrator = LogisticRegression(C=1e6, max_iter=1000)
    calibrator.fit(platt_feature(score, probability), y, sample_weight=sample_weight)
    return calibrator


def calibrated(calibrator, score, probability=True):
    return calibrator.predict_proba(platt_feature(score, probability))[:, 1]


def metrics(f, score):
    y = f.target_oob.to_numpy(dtype=int)
    violation = f.target_violation.to_numpy(dtype=int)
    order = ranking(score, f.tie)
    result = {
        "visits": len(f),
        "oob": int(y.sum()),
        "violations": int(violation.sum()),
        "base_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, score)) if len(np.unique(y)) > 1 else None,
        "average_precision": float(average_precision_score(y, score)),
        "topk": [],
    }
    for fraction in BUDGETS:
        k = math.ceil(fraction * len(f))
        top, rest = order[:k], order[k:]
        tp = int(y[top].sum())
        v, rv = int(violation[top].sum()), int(violation[rest].sum())
        result["topk"].append(
            {
                "budget": fraction,
                "selected": k,
                "oob": tp,
                "precision": tp / k,
                "recall": tp / int(y.sum()) if y.sum() else 0,
                "violations": v,
                "rest_visits": len(rest),
                "rest_oob": int(y[rest].sum()),
                "rest_violations": rv,
                "violation_rate": v / k,
                "rest_violation_rate": rv / len(rest),
                "scenario_net_violations_per_1000": 1000 * (rv / len(rest) - v / k),
            }
        )
    top = result["topk"][1]
    result["confusion_top10"] = {
        "tp": top["oob"],
        "fp": top["selected"] - top["oob"],
        "fn": int(y.sum()) - top["oob"],
        "tn": len(y) - top["selected"] - int(y.sum()) + top["oob"],
    }
    return result


def bootstrap_stat(y, score, tie, row_weights):
    """Exact weighted AP with score ties; exact top ceil(10%) under resampled multiplicities."""
    order = ranking(score, tie)
    s, ys = np.asarray(score)[order], np.asarray(y)[order]
    w = np.asarray(row_weights)[order]
    starts = np.r_[0, np.flatnonzero(s[1:] != s[:-1]) + 1]
    group_w, group_y = np.add.reduceat(w, starts), np.add.reduceat(w * ys, starts)
    cum_w, cum_y = np.cumsum(group_w), np.cumsum(group_y)
    precision = np.divide(cum_y, cum_w, out=np.zeros_like(cum_y, dtype=float), where=cum_w > 0)
    ap = float(np.sum(precision * group_y) / max(1, group_y.sum()))
    k = math.ceil(w.sum() * 0.1)
    remaining = np.clip(k - np.r_[0, np.cumsum(w)[:-1]], 0, w)
    return ap, float(np.sum(remaining * ys) / max(1, k))


def bootstrap(f, scores, resamples=500):
    # Pre-sort once per ranker; weighted AP calculation below avoids repeated sklearn sorting.
    groups, unique = pd.factorize(f.business_id, sort=True)
    rng = np.random.default_rng(SEED)
    y = f.target_oob.to_numpy(dtype=int)
    prepared = {}
    for name, s in scores.items():
        order = ranking(s, f.tie)
        ss = np.asarray(s)[order]
        prepared[name] = (order, np.r_[0, np.flatnonzero(ss[1:] != ss[:-1]) + 1])
    results = {name: [] for name in scores}
    for _ in range(resamples):
        multiplicity = np.bincount(rng.integers(0, len(unique), len(unique)), minlength=len(unique))
        weights = multiplicity[groups]
        for name, (order, starts) in prepared.items():
            w, yy = weights[order], y[order]
            gw, gy = np.add.reduceat(w, starts), np.add.reduceat(w * yy, starts)
            cw, cy = np.cumsum(gw), np.cumsum(gy)
            p = np.divide(cy, cw, out=np.zeros_like(cy, dtype=float), where=cw > 0)
            ap = float(np.sum(p * gy) / max(1, gy.sum()))
            k = math.ceil(w.sum() * 0.1)
            take = np.clip(k - np.r_[0, np.cumsum(w)[:-1]], 0, w)
            results[name].append([ap, float(np.sum(take * yy) / max(1, k))])
    rule = np.array(results["staleness_rule"])
    output = {}
    for name, samples in results.items():
        a = np.asarray(samples)
        output[name] = {
            "average_precision_ci95": np.quantile(a[:, 0], [0.025, 0.975]).tolist(),
            "p10_ci95": np.quantile(a[:, 1], [0.025, 0.975]).tolist(),
            "delta_ap_rule_ci95": np.quantile(a[:, 0] - rule[:, 0], [0.025, 0.975]).tolist(),
            "delta_p10_rule_ci95": np.quantile(a[:, 1] - rule[:, 1], [0.025, 0.975]).tolist(),
        }
    return output


def calibration_bins(y, p):
    data = pd.DataFrame({"y": np.asarray(y, dtype=int), "p": p})
    data["bin"] = pd.qcut(data.p, 10, duplicates="drop")
    return [
        {
            "bin": str(b),
            "visits": len(g),
            "oob": int(g.y.sum()),
            "mean_probability": float(g.p.mean()),
            "observed_share": float(g.y.mean()),
        }
        for b, g in data.groupby("bin", observed=True)
    ]


def program_tradeoff(f, score):
    top = np.zeros(len(f), dtype=bool)
    top[ranking(score, f.tie)[: math.ceil(0.2 * len(f))]] = True
    rows = []
    for program in sorted(f.inspection_type.unique()):
        mask = f.inspection_type.to_numpy() == program
        a, b = f.loc[mask & top], f.loc[mask & ~top]
        rows.append(
            {
                "program": program,
                "top_visits": len(a),
                "top_oob": int(a.target_oob.sum()),
                "top_violations": int(a.target_violation.sum()),
                "rest_visits": len(b),
                "rest_oob": int(b.target_oob.sum()),
                "rest_violations": int(b.target_violation.sum()),
            }
        )
    comparable = [r for r in rows if r["top_visits"] and r["rest_visits"]]
    n = sum(r["top_visits"] for r in comparable)
    gain = sum(
        r["top_visits"] * r["rest_violations"] / r["rest_visits"] - r["top_violations"]
        for r in comparable
    )
    return {
        "programs": rows,
        "comparable_top_visits": n,
        "scenario_same_program_net_per_1000": 1000 * gain / n if n else None,
    }


def importance(pipe, test):
    import matplotlib.pyplot as plt

    prep, estimator = pipe.named_steps["prepare"], pipe.named_steps["classifier"]
    names = prep.get_feature_names_out().tolist()
    gain = estimator.booster_.feature_importance(importance_type="gain")
    rows = sorted(
        [{"feature": n, "gain": float(g)} for n, g in zip(names, gain, strict=True)],
        key=lambda x: x["gain"],
        reverse=True,
    )
    shap_rows = []
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="IProgress not found.*")
            warnings.filterwarnings(
                "ignore", message="LightGBM binary classifier with TreeExplainer shap values.*"
            )
            import shap

            x = prep.transform(test.sample(min(500, len(test)), random_state=SEED))
            if hasattr(x, "toarray"):
                x = x.toarray()
            values = shap.TreeExplainer(estimator).shap_values(x)
            if isinstance(values, list):
                values = values[1]
            shap_rows = sorted(
                [
                    {"feature": name, "mean_absolute_shap": float(magnitude)}
                    for name, magnitude in zip(names, np.abs(values).mean(axis=0), strict=True)
                ],
                key=lambda row: row["mean_absolute_shap"],
                reverse=True,
            )
            shap.summary_plot(values, x, feature_names=names, show=False, max_display=15, rng=SEED)
            plt.title("Live history-only LightGBM: SHAP on 500 held-out records")
            method = "SHAP TreeExplainer; 500 seeded held-out records; descriptive only"
    except Exception as exc:
        from sklearn.inspection import permutation_importance

        sample = test.sample(min(2000, len(test)), random_state=SEED)
        perm = permutation_importance(
            pipe,
            sample,
            sample.target_oob,
            n_repeats=3,
            random_state=SEED,
            scoring="average_precision",
            n_jobs=1,
        )
        selected = np.argsort(perm.importances_mean)[-15:]
        plt.barh(sample.columns[selected], perm.importances_mean[selected])
        method = f"Permutation AP fallback: {type(exc).__name__}: {exc}"
    plt.gcf().set_size_inches(10, 7)
    plt.gcf().text(
        0.01, 0.01, "Source: DCWP; frozen live history-only model; test 2025.", fontsize=8
    )
    plt.savefig(REPO_ROOT / "reports/model_shap.png", bbox_inches="tight", dpi=120)
    plt.close("all")
    return {"gain": rows, "shap_mean_absolute": shap_rows, "explanation_method": method}


def run(resamples=500):
    MODEL_DIR.mkdir(exist_ok=True)
    result = {
        "protocol": (
            "No hyperparameter search. Fit archive 2015-2017 / calibrate 2018 / test 2019; "
            "fit live Jan-Sep 2024 / calibrate Oct-Dec 2024 / test 2025. "
            "Base estimators are not refit on calibration rows. Default LGBM; "
            "logistic max_iter=1000 for convergence."
        ),
        "bootstrap": (
            f"{resamples} paired business_id cluster resamples; "
            "frozen models; percentile 95% intervals."
        ),
        "models": [],
        "splits": [],
        "sensitivities": [],
    }
    linked = {r["archive_key"] for r in query("links", "business_links")}
    for era in ["archive", "live"]:
        started = time.monotonic()
        data = frame(query("model_rows", era=era))
        test_year = 2019 if era == "archive" else 2025
        train = data.loc[data.year < test_year].copy()
        validation_start = pd.Timestamp("2018-01-01" if era == "archive" else "2024-10-01")
        fit = train.loc[train.inspected_at < validation_start].copy()
        validation = train.loc[train.inspected_at >= validation_start].copy()
        test = data.loc[data.year == test_year].copy().reset_index(drop=True)
        for split, f in [
            ("train_total", train),
            ("fit", fit),
            ("validation", validation),
            ("test", test),
        ]:
            result["splits"].append(
                {
                    "era": era,
                    "split": split,
                    "visits": len(f),
                    "oob": int(f.target_oob.sum()),
                    "oob_share": float(f.target_oob.mean()),
                    "businesses": f.business_id.nunique(),
                    "first": str(f.inspected_at.min()),
                    "last": str(f.inspected_at.max()),
                }
            )
        scores = {"staleness_rule": test.months_since_last_positive.fillna(-1).to_numpy()}
        predicted = test[
            [
                "_id",
                "business_id",
                "inspected_at",
                "inspection_type",
                "target_oob",
                "target_violation",
                "prior_visits",
                "tie",
            ]
        ].copy()
        calibrators, probabilities = {}, {}
        rule_cal = calibrate(
            validation.months_since_last_positive.fillna(-1), validation.target_oob, False
        )
        calibrators["staleness_rule"] = rule_cal
        probabilities["staleness_rule"] = calibrated(rule_cal, scores["staleness_rule"], False)
        variants = [
            ("logistic_history", "logistic", False),
            ("lightgbm_history", "lightgbm", False),
        ]
        if era == "live":
            variants.append(("lightgbm_planned_type", "lightgbm", True))
        pipes, training_warnings = {}, {}
        for name, kind, planned in variants:
            pipe = model(kind, planned)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                pipe.fit(fit, fit.target_oob.astype(int))
                val_p = pipe.predict_proba(validation)[:, 1]
                scores[name] = pipe.predict_proba(test)[:, 1]
            training_warnings[name] = sorted({str(w.message) for w in caught})
            print(era, name, "fitted", flush=True)
            cal = calibrate(val_p, validation.target_oob.astype(int))
            probabilities[name] = calibrated(cal, scores[name])
            calibrators[name], pipes[name] = cal, pipe
            if era == "live":
                joblib.dump(
                    {
                        "model": pipe,
                        "calibrator": cal,
                        "validation_score": val_p,
                        "validation_y": validation.target_oob.to_numpy(dtype=int),
                        "validation_business_id": validation.business_id.to_numpy(),
                        "protocol": result["protocol"],
                        "warnings": sorted({str(w.message) for w in caught}),
                    },
                    MODEL_DIR / f"live_{name}.joblib",
                )
        intervals = bootstrap(test, scores, resamples)
        baseline = metrics(test, scores["staleness_rule"])
        for name, s in scores.items():
            p = probabilities[name]
            m = metrics(test, s)
            row = {
                "era": era,
                "ranker": name,
                "training_warnings": training_warnings.get(name, []),
                **m,
                **intervals[name],
                "delta_ap_rule": m["average_precision"] - baseline["average_precision"],
                "delta_p10_rule": m["topk"][1]["precision"] - baseline["topk"][1]["precision"],
                "brier_calibrated": float(brier_score_loss(test.target_oob, p)),
                "brier_uncalibrated": float(brier_score_loss(test.target_oob, s))
                if name != "staleness_rule"
                else None,
                "calibration": calibration_bins(test.target_oob, p),
                "calibration_uncalibrated": calibration_bins(test.target_oob, s)
                if name != "staleness_rule"
                else [],
                "program_tradeoff": program_tradeoff(test, s),
            }
            result["models"].append(row)
            predicted[name], predicted[name + "_calibrated"] = s, p
            masks = {
                "one_per_business_timestamp": ~test.duplicated(["business_id", "inspected_at"]),
                "has_prior_history": test.prior_visits > 0,
                "cold_start": test.prior_visits == 0,
                "exclude_cross_switch_links": ~test.business_id.isin(linked),
            }
            for subset, mask in masks.items():
                result["sensitivities"].append(
                    {
                        "era": era,
                        "ranker": name,
                        "subset": subset,
                        **metrics(test.loc[mask], np.asarray(s)[mask]),
                    }
                )
        predicted.to_csv(MODEL_DIR / f"predictions_{era}.csv.gz", index=False)
        if era == "live":
            result["importance"] = importance(pipes["lightgbm_history"], test)
            # Actual refit without the chain input, rather than setting it to zero at scoring.
            no_chain = model("lightgbm", no_chain=True).fit(fit, fit.target_oob.astype(int))
            val = no_chain.predict_proba(validation)[:, 1]
            joblib.dump(
                {"model": no_chain, "calibrator": calibrate(val, validation.target_oob)},
                MODEL_DIR / "live_history_no_chain.joblib",
            )
        result.setdefault("timings_seconds", {})[era] = round(time.monotonic() - started, 2)
        write_json(REPO_ROOT / "reports/model_metrics.json", result)
        print(era, "complete", result["timings_seconds"][era], "seconds", flush=True)
    return result
