"""Export dashboard tables from gold queries and model results."""

from __future__ import annotations

import json
import time

import pandas as pd

from storefronts.config import REPO_ROOT
from storefronts.gold import query

EXPORTS = REPO_ROOT / "exports"


def aggregate_frame(name):
    f = pd.json_normalize(query(name))
    f.columns = [c.removeprefix("_id.") for c in f.columns]
    return f


def export():
    started = time.monotonic()
    EXPORTS.mkdir(exist_ok=True)
    frames = {
        "yearly_overview": aggregate_frame("eda.yearly"),
        "program_2023_2026": aggregate_frame("eda.program_year"),
        "staleness_by_year": aggregate_frame("eda.staleness"),
        "nta_2025": aggregate_frame("eda.nta"),
        "industry": aggregate_frame("eda.industry"),
    }
    yearly = frames["yearly_overview"].groupby("year").sum(numeric_only=True)
    staleness = frames["staleness_by_year"]
    staleness["year_oob"] = staleness.year.map(yearly.oob)
    staleness["share_of_year_oob"] = staleness.oob / staleness.year_oob
    programs = frames["program_2023_2026"]
    programs["share_of_year_live_oob"] = programs.oob / programs.groupby("year").oob.transform(
        "sum"
    )
    chains = json.loads((REPO_ROOT / "reports/chain_results.json").read_text())
    frames["chain_timelines"] = pd.DataFrame(chains["timelines"]).rename(
        columns={
            "first_closure": "first_oob",
            "last_closure": "last_oob",
            "positive_to_first_closure_days": "positive_to_first_oob_days",
        }
    )
    model = json.loads((REPO_ROOT / "reports/model_metrics.json").read_text())
    frames["model_topk"] = pd.DataFrame(
        [
            {
                "era": m["era"],
                "ranker": m["ranker"],
                "test_visits": m["visits"],
                "test_oob": m["oob"],
                "roc_auc": m["roc_auc"],
                "average_precision": m["average_precision"],
                **k,
            }
            for m in model["models"]
            for k in m["topk"]
        ]
    )
    frames["calibration"] = pd.DataFrame(
        [
            {"era": m["era"], "ranker": m["ranker"], "version": version, **b}
            for m in model["models"]
            for version, bins in [
                ("calibrated", m["calibration"]),
                ("raw", m["calibration_uncalibrated"]),
            ]
            for b in bins
        ]
    )
    ghost = json.loads((REPO_ROOT / "reports/ghost_count.json").read_text())
    nta = pd.DataFrame(ghost["by_nta"])
    unmapped = nta.loc[nta.nta2020 == "UNMAPPED"]
    frames["ghost_by_nta"] = nta.loc[nta.nta2020 != "UNMAPPED"].copy()
    frames["ghost_by_industry"] = pd.DataFrame(ghost["by_industry"])
    summary = {}
    for name, f in frames.items():
        assert not any(isinstance(v, (dict, list)) for v in f.to_numpy().flat)
        f.to_csv(EXPORTS / f"{name}.csv", index=False)
        summary[name] = {"rows": len(f), "columns": f.columns.tolist()}
    summary["ghost_by_nta"].update(
        excluded_unmapped_businesses=int(unmapped.businesses.sum()),
        excluded_unmapped_expected_oob=float(unmapped.expected_oob.sum()),
    )
    summary["timing_seconds"] = round(time.monotonic() - started, 2)
    return summary
