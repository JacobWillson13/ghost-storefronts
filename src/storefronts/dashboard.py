"""Build the Ghost Storefronts data story: one self-contained HTML page.

    uv run python src/storefronts/dashboard.py

Reads the CSV exports and the report JSON files, and writes docs/index.html. Every number
on the page is computed here from those files; none are typed by hand. Charts are Altair
(Vega-Lite) specs embedded in a hand-written HTML template, with Vega bundled in so the
page works offline and can be dropped onto any static site.

Paths default to the repo layout; override with --exports, --reports, --geojson, --out.
"""

from __future__ import annotations

import argparse
import html
import json
import numbers
from pathlib import Path

import altair as alt
import pandas as pd
import vl_convert as vlc
from altair.utils._importers import vl_version_for_vl_convert
from shapely.geometry import mapping, shape

REPO = Path(__file__).resolve().parents[2]

# Links shown on the page. Edit these when the repo is public.
REPO_URL = "https://github.com/JacobWillson13/ghost-storefronts"
NOTEBOOK_URL = REPO_URL + "/blob/main/notebooks/"

# --------------------------------------------------------------------------------------
# Theme. Specs carry "@token" strings; the page swaps in light or dark values at render.
# Values follow a validated palette (categorical colors 1-3, a one-hue ordinal ramp).
# --------------------------------------------------------------------------------------
THEMES = {
    "light": {
        "@surface": "#fcfcfb",
        "@ink": "#0b0b0b",
        "@ink2": "#52514e",
        "@muted": "#898781",
        "@grid": "#e1e0d9",
        "@axis": "#c3c2b7",
        "@context": "#c9c8c1",
        "@nodata": "#e8e7e2",
        "@s1": "#2a78d6",
        "@s2": "#eb6834",
        "@s3": "#1baf7a",
        "@r0": "#86b6ef",
        "@r1": "#5598e7",
        "@r2": "#2a78d6",
        "@r3": "#1c5cab",
        "@r4": "#104281",
        "@m0": "#cde2fb",
        "@m1": "#86b6ef",
        "@m2": "#3987e5",
        "@m3": "#1c5cab",
        "@m4": "#0d366b",
    },
    "dark": {
        "@surface": "#1a1a19",
        "@ink": "#f0efec",
        "@ink2": "#c3c2b7",
        "@muted": "#898781",
        "@grid": "#2c2c2a",
        "@axis": "#383835",
        "@context": "#4a4a46",
        "@nodata": "#2a2a28",
        "@s1": "#3987e5",
        "@s2": "#d95926",
        "@s3": "#199e70",
        "@r0": "#184f95",
        "@r1": "#2a78d6",
        "@r2": "#5598e7",
        "@r3": "#86b6ef",
        "@r4": "#b7d3f6",
        "@m0": "#184f95",
        "@m1": "#256abf",
        "@m2": "#3987e5",
        "@m3": "#86b6ef",
        "@m4": "#cde2fb",
    },
}
RAMP = ["@r0", "@r1", "@r2", "@r3", "@r4"]  # ordinal: fresh -> stale
MAP_RAMP = ["@m0", "@m1", "@m2", "@m3", "@m4"]  # sequential: low -> high share

FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
VEGA_CONFIG = {
    "background": None,
    "font": FONT,
    "view": {"stroke": None},
    "axis": {
        "labelColor": "@ink2",
        "titleColor": "@ink2",
        "labelFontSize": 11,
        "titleFontSize": 11,
        "titleFontWeight": "normal",
        "gridColor": "@grid",
        "domainColor": "@axis",
        "tickColor": "@axis",
        "labelPadding": 4,
    },
    "legend": {
        "labelColor": "@ink2",
        "titleColor": "@ink2",
        "labelFontSize": 11,
        "titleFontSize": 11,
        "titleFontWeight": "normal",
        "symbolStrokeWidth": 0,
    },
    "title": {"color": "@ink", "subtitleColor": "@ink2", "anchor": "start", "fontSize": 13},
    "text": {"color": "@ink2", "fontSize": 11},
}
CONTAINER = {"width": "container", "autosize": {"type": "fit-x", "contains": "padding"}}

INDUSTRY_NAMES = {
    "general_retail": "General retail",
    "personal_services": "Personal services",
    "food_grocery": "Food and grocery",
    "tobacco_vape_cannabis": "Tobacco, vape, cannabis",
    "secondhand_pawn": "Secondhand and pawn",
    "auto_fuel_parking": "Auto, fuel, parking",
    "lodging": "Lodging",
}
RANKER_NAMES = {
    "staleness_rule": "One-line rule",
    "logistic_history": "Logistic regression",
    "lightgbm_history": "LightGBM",
    "lightgbm_planned_type": "LightGBM + program",
}
CHAIN_NAMES = {
    "RadioShack incl General Wireless": "RadioShack",
    "Payless ShoeSource": "Payless ShoeSource",
    "Rite Aid incl Genovese": "Rite Aid",
}
CHAIN_EVENT_LABELS = {
    "RadioShack": "Bankruptcy filing",
    "Payless ShoeSource": "Chain-wide closing",
    "Rite Aid": "Bankruptcy filing",
}
AGE_BINS = [  # (label, source bins) merged so the ordinal ramp stays readable
    ("Under 1 year", ["0-12"]),
    ("1 to 2 years", ["12-24"]),
    ("2 to 3 years", ["24-36"]),
    ("3 to 5 years", ["36-60"]),
    ("5+ years", ["60-120", "120+"]),
    ("No earlier sighting", ["Unknown"]),
]


# ======================================================================================
# Data and facts
# ======================================================================================
def load(exports: Path, reports: Path) -> dict:
    csv = {p.stem: pd.read_csv(p) for p in exports.glob("*.csv")}
    js = {
        n: json.loads((reports / f"{n}.json").read_text())
        for n in ("chain_results", "ghost_count", "model_metrics")
    }
    return {**csv, **js}


def pct(x: float, d: int = 0) -> str:
    return f"{x * 100:.{d}f}%"


def build_facts(D: dict) -> dict:
    """Every number used in the page text."""
    F: dict = {}
    y = D["yearly_overview"].groupby("year")[["visits", "oob", "oob_old36"]].sum()
    F["years"] = (int(y.index.min()), int(y.index.max()))
    F["total_visits"] = int(y["visits"].sum())
    F["share_2025"] = y.loc[2025, "oob"] / y.loc[2025, "visits"]
    F["oob_2025"], F["visits_2025"] = int(y.loc[2025, "oob"]), int(y.loc[2025, "visits"])
    early = y.loc[2010:2013]
    F["share_early"] = early["oob"].sum() / early["visits"].sum()
    F["old36_2025"] = y.loc[2025, "oob_old36"] / y.loc[2025, "oob"]
    covid = y.loc[2020:2022, "visits"].mean() / y.loc[2017:2019, "visits"].mean()
    F["covid_drop"] = 1 - covid

    p = D["program_2023_2026"]
    p25 = p[p.year == 2025].set_index("inspection_type")
    F["patrol_share"] = p25.loc["Patrol", "share_of_year_live_oob"]
    F["patrol_rate"] = p25.loc["Patrol", "oob_share"]
    F["edu_rate"] = p25.loc["Business Education", "oob_share"]

    cr = D["chain_results"]
    chains = {}
    for c in cr["cohorts"]:
        name = CHAIN_NAMES[c["chain"]]
        if c["lookback_months"] != 24:
            continue
        if name not in chains or c["event"] < chains[name]["event"]:
            chains[name] = {
                "event": c["event"][:10],
                "locations": c["locations"],
                "recorded": c["post_event_oob"],
                "detect": c["detection_proxy"],
                "event_to_oob_days": c["event_to_oob_days"]["median"],
            }
    for pc in cr["post_cutoff"]:
        chains[CHAIN_NAMES[pc["chain"]]]["post"] = pc
    F["chains"] = chains
    F["events"] = sorted({(CHAIN_NAMES[c["chain"]], c["event"][:10]) for c in cr["cohorts"]})
    rs, pl = chains["RadioShack"], chains["Payless ShoeSource"]
    F["never_rs_pl"] = 1 - (rs["recorded"] + pl["recorded"]) / (rs["locations"] + pl["locations"])

    mm = {(m["era"], m["ranker"]): m for m in D["model_metrics"]["models"]}
    F["models"] = mm
    F["rule_p10"] = {
        era: mm[(era, "staleness_rule")]["topk"][1]["precision"] for era in ("archive", "live")
    }
    F["base"] = {era: mm[(era, "staleness_rule")]["base_rate"] for era in ("archive", "live")}
    F["best_gain"] = {
        era: max(mm[(era, r)]["delta_p10_rule"] for r in ("logistic_history", "lightgbm_history"))
        for era in ("archive", "live")
    }
    cal = mm[("live", "lightgbm_history")]["calibration"][-1]
    F["cal_top"] = (cal["mean_probability"], cal["observed_share"])

    g = D["ghost_count"]
    F["ghost"] = g["expected_oob"]
    F["ghost_ci"] = g["bootstrap_ci95"]
    F["ghost_pop"] = g["eligible_businesses"]
    F["ghost_full"] = next(
        s for s in g["sensitivities"] if s["variant"] == "full_history_calibrated_sensitivity"
    )
    F["snapshot"] = g["snapshot_date"]

    n = D["nta_2025"]
    F["nta_rec_range"] = (n.oob.div(n.visits).min(), n.oob.div(n.visits).max())
    gb = D["ghost_by_nta"].query("businesses >= 100")
    F["nta_exp_range"] = (gb.mean_probability.min(), gb.mean_probability.max())

    ind = D["industry"].set_index(["period", "industry_group"])
    F["retail"] = (
        ind.loc[("2015-2019", "general_retail"), "oob_share"],
        ind.loc[("2025", "general_retail"), "oob_share"],
    )
    return F


# ======================================================================================
# Charts. Each returns (spec dict, table DataFrame for the "View data" twin).
# ======================================================================================
def tip(field, title, fmt=None, type_="quantitative"):
    return (
        alt.Tooltip(field, title=title, format=fmt, type=type_)
        if fmt
        else alt.Tooltip(field, title=title, type=type_)
    )


def chart_trend(D):
    y = D["yearly_overview"].groupby("year", as_index=False)[["visits", "oob"]].sum()
    y["share"] = y.oob / y.visits
    y["label"] = y.year.astype(str).where(y.year != 2026, "2026 (Jan to Aug)")
    yscale = alt.Scale(domain=[2009.5, 2026.5], nice=False, zero=False)
    x = alt.X(
        "year:Q", title=None, scale=yscale, axis=alt.Axis(format="d", tickCount=9, grid=False)
    )
    base = alt.Chart(y)
    covid = (
        alt.Chart(pd.DataFrame({"a": [2019.6], "b": [2022.4]}))
        .mark_rect(color="@grid", opacity=0.6)
        .encode(x=alt.X("a:Q", scale=yscale, title=None), x2="b:Q")
    )
    covid_t = (
        alt.Chart(pd.DataFrame({"x": [2021], "t": ["Fewer visits"]}))
        .mark_text(dy=-8, fontSize=10, color="@muted")
        .encode(x=alt.X("x:Q", scale=yscale, title=None), y=alt.value(0), text="t:N")
    )
    switch = (
        alt.Chart(pd.DataFrame({"x": [2023.5]}))
        .mark_rule(color="@ink2", strokeWidth=1)
        .encode(x=alt.X("x:Q", scale=yscale, title=None))
    )
    switch_t = (
        alt.Chart(pd.DataFrame({"x": [2023.5], "t": ["New record system"]}))
        .mark_text(align="right", dx=-5, fontSize=10, color="@ink2", baseline="bottom")
        .encode(x=alt.X("x:Q", scale=yscale, title=None), y=alt.value(236), text="t:N")
    )
    line = base.mark_line(color="@s1", strokeWidth=2).encode(
        x=x,
        y=alt.Y(
            "share:Q",
            title=None,
            axis=alt.Axis(format=".0%", tickCount=4, minExtent=36, domain=False, ticks=False),
        ),
    )
    pts = base.mark_point(
        filled=True, size=40, color="@s1", stroke="@surface", strokeWidth=2
    ).encode(
        x=x,
        y="share:Q",
        tooltip=[
            tip("label:N", "Year", type_="nominal"),
            tip("share:Q", "Found closed", ".1%"),
            tip("oob:Q", "Closure records", ","),
            tip("visits:Q", "Visit records", ","),
        ],
    )
    end = (
        base.transform_filter("datum.year == 2025")
        .mark_text(align="left", dx=8, dy=-10, fontSize=12, fontWeight="bold", color="@ink")
        .encode(x=x, y="share:Q", text=alt.Text("share:Q", format=".1%"))
    )
    top = alt.layer(covid, covid_t, switch, switch_t, line, pts, end).properties(
        height=240, **CONTAINER
    )

    bars = base.mark_bar(
        color="@context", cornerRadiusTopLeft=2, cornerRadiusTopRight=2, size=14
    ).encode(
        x=x,
        y=alt.Y(
            "visits:Q",
            title=None,
            axis=alt.Axis(format="~s", tickCount=2, domain=False, ticks=False, minExtent=36),
        ),
        tooltip=[tip("label:N", "Year", type_="nominal"), tip("visits:Q", "Visit records", ",")],
    )
    bottom = bars.properties(
        height=70,
        **CONTAINER,
        title=alt.TitleParams(
            "Visit records per year", fontSize=11, fontWeight="normal", color="@ink2"
        ),
    )
    t = y.assign(share=y.share.map(lambda v: pct(v, 1)))[["label", "visits", "oob", "share"]]
    t.columns = ["Year", "Visit records", "Closure records", "Share found closed"]
    return [top.to_dict(), bottom.to_dict()], t


def chart_staleness(D):
    s = D["staleness_by_year"].query("year >= 2015").copy()
    lookup = {src: label for label, srcs in AGE_BINS for src in srcs}
    order = [label for label, _ in AGE_BINS]
    s["bin"] = s.age_bin.map(lookup)
    s = s.groupby(["year", "bin"], as_index=False).agg(
        oob=("oob", "sum"), total=("year_oob", "first")
    )
    s["share"] = s.oob / s.total
    s["order"] = s.bin.map(order.index)
    s["year_label"] = s.year.astype(str).where(s.year != 2026, "2026*")
    color = alt.Color(
        "bin:N",
        title=None,
        sort=order,
        scale=alt.Scale(domain=order, range=RAMP + ["@nodata"]),
        legend=None,
    )
    c = (
        alt.Chart(s)
        .mark_bar(stroke="@surface", strokeWidth=1.5)
        .encode(
            x=alt.X(
                "year_label:O",
                title=None,
                axis=alt.Axis(labelAngle=0, domain=False, ticks=False, labelOverlap="parity"),
            ),
            y=alt.Y(
                "share:Q",
                stack="normalize",
                title=None,
                axis=alt.Axis(format=".0%", tickCount=5, domain=False, ticks=False),
            ),
            color=color,
            order=alt.Order("order:Q", sort="ascending"),
            tooltip=[
                tip("year_label:N", "Year", type_="nominal"),
                tip("bin:N", "Last seen open", type_="nominal"),
                tip("share:Q", "Share of closure records", ".1%"),
                tip("oob:Q", "Closure records", ","),
            ],
        )
        .properties(height=300, **CONTAINER)
    )
    t = s.pivot(index="year_label", columns="bin", values="share")[order].map(lambda v: pct(v))
    t = t.reset_index().rename(columns={"year_label": "Year"})
    return [c.to_dict()], t


def chart_programs(D):
    p = D["program_2023_2026"].query("year >= 2024 and visits >= 500").copy()
    p["year_s"] = p.year.astype(str)
    p["label"] = p.oob_share.map(lambda v: f"{v * 100:.0f}%")
    year = alt.param(
        name="pyear",
        value="2025",
        bind=alt.binding_radio(
            options=["2024", "2025", "2026"],
            labels=["2024", "2025", "2026 (Jan to Aug)"],
            name=" ",
            element="#ctl-programs",
        ),
    )
    base = alt.Chart(p).transform_filter(alt.datum.year_s == year)
    y = alt.Y(
        "inspection_type:N",
        title=None,
        sort="-x",
        axis=alt.Axis(labelLimit=220, domain=False, ticks=False, labelColor="@ink"),
    )
    bars = base.mark_bar(color="@s1", cornerRadiusEnd=3, height=16).encode(
        x=alt.X(
            "share_of_year_live_oob:Q",
            title=None,
            axis=alt.Axis(format=".0%", tickCount=4, domain=False),
            scale=alt.Scale(domain=[0, 0.8]),
        ),
        y=y,
        tooltip=[
            tip("inspection_type:N", "Program", type_="nominal"),
            tip("share_of_year_live_oob:Q", "Share of closure records", ".1%"),
            tip("oob_share:Q", "Visits that found it closed", ".1%"),
            tip("visits:Q", "Visit records", ","),
        ],
    )
    text = base.mark_text(align="left", dx=6, fontSize=11, color="@ink2").encode(
        x="share_of_year_live_oob:Q", y=y, text="label:N"
    )
    c = alt.layer(bars, text).add_params(year).properties(height=330, **CONTAINER)
    t = p.query("year == 2025").sort_values("share_of_year_live_oob", ascending=False)
    t = pd.DataFrame(
        {
            "Program (2025)": t.inspection_type,
            "Share of closure records": t.share_of_year_live_oob.map(lambda v: pct(v, 1)),
            "Visits that found it closed": t.oob_share.map(lambda v: pct(v, 1)),
            "Visit records": t.visits,
        }
    )
    return [c.to_dict()], t


def chart_chains(D, F):
    t = D["chain_timelines"].copy()
    for col in ("last_positive", "first_oob"):
        t[col] = pd.to_datetime(t[col])
    t["name"] = t.chain.map(CHAIN_NAMES)
    snapshot = pd.Timestamp(F["snapshot"])
    specs, rows = [], []
    for name in ("RadioShack", "Payless ShoeSource", "Rite Aid"):
        ev = pd.Timestamp(F["chains"][name]["event"])
        start = ev - pd.DateOffset(months=24)
        g = t[t.name == name].copy()
        ref = g.last_positive.fillna(g.first_oob)
        g = g[ref >= start].copy()
        g["sort"] = g.last_positive.fillna(g.first_oob)
        g = g.sort_values("sort").reset_index(drop=True)
        g["row"] = g.index
        g["seg_start"] = g[["last_positive", "first_oob"]].min(axis=1)
        g["seg_end"] = g[["last_positive", "first_oob"]].max(axis=1)
        g["status"] = g.first_oob.notna().map(
            {True: "Closure recorded", False: "No closure record"}
        )
        g["open_end"] = snapshot
        for c in ("last_positive", "first_oob", "seg_start", "seg_end", "open_end"):
            g[c + "_s"] = g[c].dt.strftime("%Y-%m-%d")
        g["lp_label"] = g.last_positive.dt.strftime("%b %Y").fillna("never")
        g["oob_label"] = g.first_oob.dt.strftime("%b %Y").fillna("none by Aug 2026")
        g = g.drop(
            columns=[
                "last_seen",
                "last_oob",
                "last_positive",
                "first_oob",
                "seg_start",
                "seg_end",
                "open_end",
                "sort",
                "chain",
            ]
        )
        rows.append(g.assign(chain=name))
        ev_rows = pd.DataFrame(
            [
                {"x": e, "t": f"{CHAIN_EVENT_LABELS[name]}, {pd.Timestamp(e):%b %Y}"}
                for n, e in F["events"]
                if n == name
            ]
        )
        ev_rows["ypx"] = [-28 + 13 * i for i in range(len(ev_rows))]
        end = snapshot + pd.DateOffset(months=2)
        dom = [
            alt.DateTime(year=start.year, month=start.month, date=start.day),
            alt.DateTime(year=end.year, month=end.month, date=end.day),
        ]
        scale = alt.Scale(domain=dom)
        yenc = alt.Y("row:O", axis=None, sort="ascending")
        tooltip = [
            tip("address:N", "Address", type_="nominal"),
            tip("lp_label:N", "Last seen open", type_="nominal"),
            tip("oob_label:N", "First closure record", type_="nominal"),
        ]
        base = alt.Chart(g)
        frame = (
            alt.Chart(pd.DataFrame({"x": [f"{start:%Y-%m-%d}", f"{end:%Y-%m-%d}"]}))
            .mark_point(opacity=0)
            .encode(
                x=alt.X(
                    "x:T",
                    title=None,
                    scale=scale,
                    axis=alt.Axis(format="%Y", tickCount="year", grid=False),
                )
            )
        )
        evr = alt.Chart(ev_rows).mark_rule(color="@ink2", strokeWidth=1).encode(x="x:T")
        evt = (
            alt.Chart(ev_rows)
            .mark_text(align="left", dx=4, fontSize=10, color="@ink2", baseline="top")
            .encode(x="x:T", y=alt.Y("ypx:Q", scale=None, axis=None), text="t:N")
        )
        has_lp = "isValid(datum.last_positive_s)"
        has_oob = "isValid(datum.first_oob_s)"
        open_line = (
            base.transform_filter(f"!({has_oob}) && {has_lp}")
            .mark_rule(color="@s1", strokeWidth=1, opacity=0.4, strokeDash=[2, 2], clip=True)
            .encode(x="last_positive_s:T", x2="open_end_s:T", y=yenc, tooltip=tooltip)
        )
        seg = (
            base.transform_filter(f"{has_oob} && {has_lp}")
            .mark_rule(color="@context", strokeWidth=1.5, clip=True)
            .encode(x="seg_start_s:T", x2="seg_end_s:T", y=yenc, tooltip=tooltip)
        )
        lp = (
            base.transform_filter(has_lp)
            .mark_circle(size=18, color="@s1", opacity=1, clip=True)
            .encode(x="last_positive_s:T", y=yenc, tooltip=tooltip)
        )
        fo = (
            base.transform_filter(has_oob)
            .mark_circle(size=18, color="@s2", opacity=1, clip=True)
            .encode(x="first_oob_s:T", y=yenc, tooltip=tooltip)
        )
        layer = alt.layer(frame, evr, open_line, seg, lp, fo, evt).properties(
            height=max(120, int(len(g) * 3.2)), padding={"top": 30}, **CONTAINER
        )
        specs.append(layer.to_dict())
    allrows = pd.concat(rows)
    table = pd.DataFrame(
        {
            "Chain": allrows.chain,
            "Address": allrows.address,
            "Last seen open": allrows.lp_label,
            "First closure record": allrows.oob_label,
        }
    )
    return specs, table


def chart_model(D, F):
    rows = []
    for (era, ranker), m in F["models"].items():
        lo, hi = m["p10_ci95"]
        dlo, dhi = m["delta_p10_rule_ci95"]
        rows.append(
            {
                "era": "Live system, tested on 2025"
                if era == "live"
                else "Old system, tested on 2019",
                "era_key": era,
                "ranker": RANKER_NAMES[ranker],
                "is_rule": ranker == "staleness_rule",
                "p10": m["topk"][1]["precision"],
                "lo": lo,
                "hi": hi,
                "base": m["base_rate"],
                "label": f"{m['topk'][1]['precision'] * 100:.1f}%",
                "vs_rule": "baseline"
                if ranker == "staleness_rule"
                else (
                    f"{m['delta_p10_rule'] * 100:+.1f} pts "
                    f"(95% CI {dlo * 100:+.1f} to {dhi * 100:+.1f})"
                ),
                "auc": m["roc_auc"],
            }
        )
    df = pd.DataFrame(rows)
    era = alt.param(
        name="era",
        value="live",
        bind=alt.binding_radio(
            options=["live", "archive"],
            labels=["Live system (2025 test)", "Old system (2019 test)"],
            name=" ",
            element="#ctl-model",
        ),
    )
    base = alt.Chart(df).transform_filter(alt.datum.era_key == era)
    order = list(RANKER_NAMES.values())
    y = alt.Y(
        "ranker:N",
        sort=order,
        title=None,
        axis=alt.Axis(domain=False, ticks=False, labelColor="@ink", labelLimit=200),
    )
    x = alt.X(
        "p10:Q",
        title="Top 10% of visits: share found closed",
        scale=alt.Scale(domain=[0, 0.8]),
        axis=alt.Axis(format=".0%", tickCount=4, domain=False),
    )
    color = alt.condition("datum.is_rule", alt.value("@ink2"), alt.value("@s1"))
    tooltip = [
        tip("ranker:N", "Ranker", type_="nominal"),
        tip("p10:Q", "Top-10% precision", ".1%"),
        tip("vs_rule:N", "vs one-line rule", type_="nominal"),
        tip("auc:Q", "ROC AUC", ".3f"),
    ]
    base_rule = (
        base.transform_aggregate(base="max(base)")
        .mark_rule(color="@muted", strokeWidth=1)
        .encode(x="base:Q")
    )
    base_text = (
        base.transform_aggregate(base="max(base)")
        .mark_text(align="left", dx=4, y=-6, fontSize=10, color="@muted")
        .encode(x="base:Q", text=alt.value("Random pick (base rate)"))
    )
    ci = base.mark_rule(strokeWidth=2).encode(x="lo:Q", x2="hi:Q", y=y, color=color)
    dot = base.mark_point(filled=True, size=90, stroke="@surface", strokeWidth=2, opacity=1).encode(
        x=x, y=y, color=color, tooltip=tooltip
    )
    lab = base.mark_text(align="left", dx=12, fontSize=12, fontWeight="bold").encode(
        x="hi:Q", y=y, text="label:N", color=color
    )
    c = (
        alt.layer(base_rule, base_text, ci, dot, lab)
        .add_params(era)
        .properties(height=190, **CONTAINER)
    )

    cal = pd.DataFrame(F["models"][("live", "lightgbm_history")]["calibration"])
    diag = (
        alt.Chart(pd.DataFrame({"a": [0, 0.65], "b": [0, 0.65]}))
        .mark_line(color="@axis", strokeWidth=1)
        .encode(
            x=alt.X(
                "a:Q",
                title="Predicted chance the business is closed",
                scale=alt.Scale(domain=[0, 0.65]),
                axis=alt.Axis(format=".0%", tickCount=4, domain=False),
            ),
            y=alt.Y(
                "b:Q",
                title="Observed share closed",
                scale=alt.Scale(domain=[0, 0.65]),
                axis=alt.Axis(format=".0%", tickCount=4, domain=False),
            ),
        )
    )
    cl = (
        alt.Chart(cal)
        .mark_line(
            color="@s1",
            strokeWidth=2,
            point=alt.OverlayMarkDef(
                filled=True, size=40, color="@s1", stroke="@surface", strokeWidth=2
            ),
        )
        .encode(
            x="mean_probability:Q",
            y="observed_share:Q",
            tooltip=[
                tip("mean_probability:Q", "Predicted", ".1%"),
                tip("observed_share:Q", "Observed", ".1%"),
                tip("visits:Q", "Visits in bin", ","),
            ],
        )
    )
    c2 = alt.layer(diag, cl).properties(height=220, **CONTAINER)
    t = df.sort_values(["era_key", "ranker"])[["era", "ranker", "label", "vs_rule"]]
    t.columns = ["Test", "Ranker", "Top-10% precision", "vs one-line rule"]
    return [c.to_dict(), c2.to_dict()], t


def chart_ghost_years(D):
    g = pd.DataFrame(D["ghost_count"]["full_history_by_last_positive_year"]).sort_values(
        "last_positive_year"
    )
    g["included"] = g.last_positive_year >= 2023
    g["year_s"] = g.last_positive_year.astype(str)
    g["status"] = g.included.map({True: "Counted in the estimate", False: "Left out"})
    bars = (
        alt.Chart(g)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, size=16)
        .encode(
            x=alt.X(
                "year_s:O",
                title="Year the business was last seen open",
                axis=alt.Axis(labelAngle=0, domain=False, ticks=False, labelOverlap=True),
            ),
            y=alt.Y(
                "mean_probability:Q",
                title=None,
                scale=alt.Scale(domain=[0, 0.6]),
                axis=alt.Axis(format=".0%", tickCount=4, domain=False, ticks=False),
            ),
            color=alt.condition("datum.included", alt.value("@s1"), alt.value("@context")),
            tooltip=[
                tip("year_s:N", "Last seen open", type_="nominal"),
                tip("status:N", " ", type_="nominal"),
                tip("mean_probability:Q", "Average predicted chance closed", ".0%"),
                tip("businesses:Q", "Businesses", ","),
                tip("expected_oob:Q", "Expected closed", ",.0f"),
            ],
        )
    )
    c = bars.properties(height=220, **CONTAINER)
    t = g[["year_s", "businesses", "expected_oob", "mean_probability", "status"]].copy()
    t["expected_oob"] = t.expected_oob.round(0).astype(int)
    t["mean_probability"] = t.mean_probability.map(lambda v: pct(v))
    t.columns = ["Last seen open", "Businesses", "Expected closed", "Average chance", "In estimate"]
    return [c.to_dict()], t


def load_boundaries(path: Path, tolerance: float = 0.00015) -> list:
    raw = json.loads(path.read_text())
    out = []
    for f in raw["features"]:
        geom = shape(f["geometry"]).simplify(tolerance, preserve_topology=True)
        p = f["properties"]
        out.append(
            {
                "type": "Feature",
                "geometry": json.loads(
                    json.dumps(mapping(geom)), parse_float=lambda v: round(float(v), 5)
                ),
                "properties": {
                    "nta2020": p["nta2020"],
                    "ntaname": p["ntaname"],
                    "boroname": p["boroname"],
                },
            }
        )
    return out


RECORDED = "Recorded in 2025"
EXPECTED = "Expected by the model"


def chart_map(D):
    r = D["nta_2025"].query("visits >= 500")
    rec = pd.DataFrame(
        {
            "nta2020": r.nta2020,
            "measure": RECORDED,
            "share": r.oob / r.visits,
            "detail": [
                f"{o:,} closure records of {v:,} visits"
                for o, v in zip(r.oob, r.visits, strict=True)
            ],
        }
    )
    g = D["ghost_by_nta"].query("businesses >= 100")
    exp = pd.DataFrame(
        {
            "nta2020": g.nta2020,
            "measure": EXPECTED,
            "share": g.expected_oob / g.businesses,
            "detail": [
                f"about {e:,.0f} expected of {b:,} businesses"
                for e, b in zip(g.expected_oob, g.businesses, strict=True)
            ],
        }
    )
    long = pd.concat([rec, exp], ignore_index=True)
    geo = alt.Data(name="nta_geo")
    measure = alt.param(
        name="measure",
        value=RECORDED,
        bind=alt.binding_radio(options=[RECORDED, EXPECTED], name=" ", element="#ctl-map"),
    )
    picked = alt.selection_point(name="picked", fields=["nta2020"], on="click", clear="dblclick")
    hover = alt.selection_point(
        name="hover", fields=["nta2020"], on="pointerover", clear="pointerout"
    )
    color = alt.Color(
        "share:Q",
        title="Share",
        scale=alt.Scale(domain=[0.08, 0.28], range=MAP_RAMP, clamp=True),
        legend=alt.Legend(
            format=".0%",
            orient="top-left",
            gradientLength=140,
            direction="horizontal",
            titleOrient="top",
        ),
    )
    tooltip = [
        tip("name:N", "Neighborhood", type_="nominal"),
        tip("borough:N", "Borough", type_="nominal"),
        tip("share:Q", "Share", ".1%"),
        tip("detail:N", "Based on", type_="nominal"),
    ]
    background = (
        alt.Chart(geo)
        .mark_geoshape(fill="@nodata", stroke="@surface", strokeWidth=0.5)
        .encode(tooltip=[alt.Tooltip("properties.ntaname:N", title="Too few records")])
    )
    layer = (
        alt.Chart(long)
        .transform_filter(alt.datum.measure == measure)
        .transform_lookup(
            lookup="nta2020", from_=alt.LookupData(geo, key="properties.nta2020"), as_="geo"
        )
        .transform_calculate(
            name="datum.geo.properties.ntaname", borough="datum.geo.properties.boroname"
        )
        .mark_geoshape(strokeJoin="round")
        .encode(
            shape="geo:G",
            color=color,
            stroke=alt.when(picked, empty=False)
            .then(alt.value("@ink"))
            .when(hover, empty=False)
            .then(alt.value("@ink2"))
            .otherwise(alt.value("@surface")),
            strokeWidth=alt.when(picked, empty=False)
            .then(alt.value(2.5))
            .when(hover, empty=False)
            .then(alt.value(1.5))
            .otherwise(alt.value(0.5)),
            tooltip=tooltip,
        )
        .add_params(picked, hover)
    )
    nyc = alt.layer(background, layer).project(type="mercator").properties(width=520, height=520)
    bars = (
        alt.Chart(long)
        .transform_filter(alt.datum.measure == measure)
        .transform_lookup(
            lookup="nta2020",
            from_=alt.LookupData(geo, key="properties.nta2020", fields=["properties"]),
        )
        .transform_calculate(name="datum.properties.ntaname", borough="datum.properties.boroname")
        .transform_window(rank="row_number()", sort=[alt.SortField("share", order="descending")])
        .transform_filter(alt.datum.rank <= 15)
        .mark_bar(color="@s1", cornerRadiusEnd=3, height=13)
        .encode(
            y=alt.Y(
                "name:N",
                sort="-x",
                title=None,
                axis=alt.Axis(labelLimit=210, domain=False, ticks=False, labelColor="@ink"),
            ),
            x=alt.X(
                "share:Q",
                title=None,
                scale=alt.Scale(domain=[0, 0.28]),
                axis=alt.Axis(format=".0%", tickCount=4, domain=False),
            ),
            opacity=alt.when(picked).then(alt.value(1)).otherwise(alt.value(0.35)),
            tooltip=tooltip,
        )
        .add_params(picked)
        .properties(width=240, height=400, title=alt.TitleParams("Highest 15", fontSize=12))
    )
    c = alt.hconcat(nyc, bars, spacing=28).add_params(measure)
    names = pd.concat(
        [D["nta_2025"][["nta2020", "nta_name"]], D["ghost_by_nta"][["nta2020", "nta_name"]]]
    )
    names = names.drop_duplicates("nta2020").set_index("nta2020").nta_name
    t = long.pivot_table(index="nta2020", columns="measure", values="share")
    t = t.reindex(columns=[RECORDED, EXPECTED]).sort_values(
        RECORDED, ascending=False, na_position="last"
    )
    t.insert(0, "Neighborhood", names.reindex(t.index).values)
    for m in (RECORDED, EXPECTED):
        t[m] = t[m].map(lambda v: "" if pd.isna(v) else pct(v, 1))
    t = t.reset_index(drop=True)
    return [c.to_dict()], t


def chart_industry(D):
    ind = D["industry"]
    keep = ind[
        (ind.period == "2025") & (ind.visits >= 500) & ind.industry_group.isin(list(INDUSTRY_NAMES))
    ]
    names = list(keep.industry_group)
    d = ind[ind.industry_group.isin(names)].copy()
    d["industry"] = d.industry_group.map(INDUSTRY_NAMES)
    d["period"] = d.period.map({"2015-2019": "2015 to 2019", "2025": "2025"})
    order = d.query("period == '2025'").sort_values("oob_share", ascending=False).industry.tolist()
    y = alt.Y(
        "industry:N",
        sort=order,
        title=None,
        axis=alt.Axis(domain=False, ticks=False, labelColor="@ink", labelLimit=200),
    )
    x = alt.X(
        "oob_share:Q",
        title="Share of visits found closed",
        scale=alt.Scale(domain=[0, 0.4]),
        axis=alt.Axis(format=".0%", tickCount=4, domain=False),
    )
    base = alt.Chart(d)
    link = base.mark_rule(color="@axis", strokeWidth=2).encode(
        x="min(oob_share):Q", x2="max(oob_share):Q", y=y
    )
    dots = base.mark_point(
        filled=True, size=90, stroke="@surface", strokeWidth=2, opacity=1
    ).encode(
        x=x,
        y=y,
        color=alt.Color(
            "period:N",
            title=None,
            scale=alt.Scale(domain=["2015 to 2019", "2025"], range=["@context", "@s1"]),
            legend=alt.Legend(orient="top", symbolType="circle"),
        ),
        tooltip=[
            tip("industry:N", "Industry", type_="nominal"),
            tip("period:N", "Period", type_="nominal"),
            tip("oob_share:Q", "Found closed", ".1%"),
            tip("visits:Q", "Visit records", ","),
        ],
    )
    c1 = alt.layer(link, dots).properties(height=230, **CONTAINER)

    gi = D["ghost_by_industry"].query("businesses >= 500").copy()
    gi["industry"] = gi.industry_group.map(INDUSTRY_NAMES)
    gi["label"] = gi.expected_oob.map(lambda v: f"{v:,.0f}")
    y2 = alt.Y(
        "industry:N",
        sort="-x",
        title=None,
        axis=alt.Axis(domain=False, ticks=False, labelColor="@ink", labelLimit=200),
    )
    b = (
        alt.Chart(gi)
        .mark_bar(color="@s1", cornerRadiusEnd=3, height=16)
        .encode(
            x=alt.X(
                "expected_oob:Q",
                title="Expected closed, still listed open",
                axis=alt.Axis(format=",.0f", tickCount=4, domain=False),
                scale=alt.Scale(domain=[0, 2400]),
            ),
            y=y2,
            tooltip=[
                tip("industry:N", "Industry", type_="nominal"),
                tip("expected_oob:Q", "Expected closed", ",.0f"),
                tip("businesses:Q", "Businesses listed as open", ","),
                tip("mean_probability:Q", "Average chance closed", ".1%"),
            ],
        )
    )
    tx = (
        alt.Chart(gi)
        .mark_text(align="left", dx=6, fontSize=11, color="@ink2")
        .encode(x="expected_oob:Q", y=y2, text="label:N")
    )
    c2 = alt.layer(b, tx).properties(height=230, **CONTAINER)
    t = d.pivot(index="industry", columns="period", values="oob_share").map(lambda v: pct(v, 1))
    t = t.reset_index().rename(columns={"industry": "Industry"})
    t = t.merge(
        gi[["industry", "label"]].rename(
            columns={"industry": "Industry", "label": "Expected closed, listed open"}
        ),
        how="left",
        on="Industry",
    )
    return [c1.to_dict(), c2.to_dict()], t


# ======================================================================================
# HTML
# ======================================================================================
def table_html(df: pd.DataFrame, max_rows: int = 200) -> str:
    df = df.head(max_rows)
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(f'{v:,}' if isinstance(v, numbers.Integral) else str(v))}</td>"
            for v in row
        )
        + "</tr>"
        for row in df.itertuples(index=False)
    )
    return (
        f'<details class="data"><summary>View data</summary><div class="tbl">'
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></details>"
    )


def chart_div(cid: str, label: str) -> str:
    return f'<div class="chart" id="{cid}" role="img" aria-label="{html.escape(label)}"></div>'


def section(sid, kicker, headline, dek, body, note=""):
    note_html = f'<p class="note">{note}</p>' if note else ""
    return (
        f'<section id="{sid}"><p class="kicker">{kicker}</p><h2>{headline}</h2>'
        f'<p class="dek">{dek}</p>{body}{note_html}</section>'
    )


def build_page(D, F, geo, specs, tables) -> str:
    c = F["chains"]
    lo, hi = F["ghost_ci"]
    y0, y1 = F["years"]

    def chain_stats(name):
        s = c[name]
        yrs = s["event_to_oob_days"] / 365.25
        post = s.get("post", {})
        extra = ""
        if post and post["positive"] == 0 and name != "Rite Aid":
            extra = (
                f"<span>{post['oob']} closure records after {post['cutoff'][:4]}, "
                f"zero open sightings</span>"
            )
        return (
            f'<div class="chain-head"><h3>{name}</h3><div class="chain-stats">'
            f"<span><b>{pct(s['detect'])}</b> of {s['locations']} stores open in the 2 years "
            f"before {pd.Timestamp(s['event']):%b %Y} later got a closure record</span>"
            f"<span>median wait after the event: <b>{yrs:.1f} years</b></span>{extra}</div></div>"
        )

    tiles = [
        (
            "#trend",
            pct(F["share_2025"], 1),
            "of 2025 inspection visits found the business already closed",
        ),
        (
            "#staleness",
            pct(F["old36_2025"]),
            "of those businesses were last seen open 3 or more years earlier",
        ),
        (
            "#chains",
            f"1 in {round(1 / F['never_rs_pl'])}",
            "RadioShack and Payless stores never got a closure record after the chains shut down",
        ),
        (
            "#estimate",
            f"{F['ghost']:,.0f}",
            "businesses still listed as open would likely be found closed if visited today",
        ),
    ]
    tiles_html = "".join(
        f'<a class="tile" href="{h}"><span class="big">{v}</span><span>{t}</span></a>'
        for h, v, t in tiles
    )

    s_trend = section(
        "trend",
        "01 · The record",
        f"In 2025, {pct(F['share_2025'], 1)} of inspection visits found "
        f"the business already closed",
        f"Up from {pct(F['share_early'], 1)} in 2010 to 2013. Each point "
        f"is the share of storefront "
        f"inspections where the inspector recorded the business as out of business.",
        chart_div(
            "c-trend-0",
            "Line chart of the share of visits that found the business closed, 2010 to 2026",
        )
        + chart_div("c-trend-1", "Bar chart of visit records per year")
        + tables["trend"],
        "A closure record needs a visit, so this tracks what inspectors recorded, not how fast "
        f"businesses closed. Visits fell about {pct(F['covid_drop'])} in 2020 to 2022.",
    )
    s_stale = section(
        "staleness",
        "02 · How stale",
        f"{pct(F['old36_2025'])} of 2025 closure records were for "
        f"businesses last seen open 3+ years earlier",
        "Each bar splits a year's closure records by how long it had been since an inspector last "
        "saw the business open.",
        '<div class="key">'
        + "".join(
            f'<span><i class="sq r{i}"></i>{label}</span>'
            for i, (label, _) in enumerate(AGE_BINS[:-1])
        )
        + '<span><i class="sq nd"></i>No earlier sighting</span></div>'
        + chart_div("c-stale-0", "Stacked bars of closure records by time since last seen open")
        + tables["staleness"],
        "Starts in 2015 because the data begin in 2010; earlier years can't show long gaps. "
        "* 2026 runs January to August.",
    )
    s_prog = section(
        "programs",
        "03 · Who finds them",
        f"Patrol visits produce {pct(F['patrol_share'])} of closure records",
        f"Patrol finds a closed business on {pct(F['patrol_rate'])} of visits; Business Education "
        f"on {pct(F['edu_rate'], 1)}. Which program sends the inspector shapes the rate.",
        '<div class="controls" id="ctl-programs"></div>'
        '<div class="key"><span><i class="sq s1"></i>Share of the year\'s closure records</span>'
        '<span><b class="lbl">27%</b>Share of that program\'s visits '
        "that found the business closed</span></div>"
        + chart_div("c-prog-0", "Bar chart of share of closure records by inspection program")
        + tables["programs"],
        "Programs with at least 500 visits in the selected year. Live record system only.",
    )
    chain_body = (
        '<div class="key"><span><i class="dot s1"></i>Last seen open</span>'
        '<span><i class="dot s2"></i>First closure record</span>'
        '<span><i class="dash"></i>No closure record by Aug 2026</span></div>'
        + "".join(
            chain_stats(n) + chart_div(f"c-chain-{i}", f"Timeline of {n} stores")
            for i, n in enumerate(["RadioShack", "Payless ShoeSource", "Rite Aid"])
        )
        + tables["chains"]
    )
    s_chain = section(
        "chains",
        "04 · Proof from known closures",
        f"About 1 in {round(1 / F['never_rs_pl'])} RadioShack and Payless "
        f"stores never got a closure record",
        "Three chains closed NYC stores on known dates. Each row is one store: when it was last "
        "seen open, and when, if ever, an inspector recorded it closed.",
        chain_body,
        "Stores are matched by chain name, legal-name aliases (General Wireless, Genovese) and "
        "address. Event dates are filings or closing announcements, not each store's last day.",
    )
    s_model = section(
        "prediction",
        "05 · Can it be predicted?",
        "A one-line rule does most of the work",
        f"Ranking visits by months since the business was last seen open puts a closed business "
        f"in {pct(F['rule_p10']['live'])} of the top 10%. The best model using the same history "
        f"adds {F['best_gain']['live'] * 100:.1f} points on 2025 data and "
        f"{F['best_gain']['archive'] * 100:.1f} on 2019 data.",
        '<div class="controls" id="ctl-model"></div>'
        + chart_div("c-model-0", "Dot plot of top-10% precision by ranker with 95% intervals")
        + '<div class="sub"><h3>Its probabilities can be read as rates</h3>'
        f"<p>When the LightGBM model says about {pct(F['cal_top'][0])}, "
        f"{pct(F['cal_top'][1])} of those visits find the business closed.</p></div>"
        + chart_div("c-model-1", "Calibration plot of predicted versus observed share closed")
        + tables["prediction"],
        "Models train on earlier years and are tested on a later year they never saw. Lines are "
        '95% intervals from resampling businesses. "+ program" assumes the inspection program '
        "is known before the visit.",
    )
    s_est = section(
        "estimate",
        "06 · How many ghosts",
        f"An estimated {F['ghost']:,.0f} businesses listed as open would be found closed today",
        f"That is {pct(F['ghost'] / F['ghost_pop'])} of the "
        f"{F['ghost_pop']:,} businesses seen open "
        f"since 2023 (95% interval {lo:,.0f} to {hi:,.0f}). Older records are left out: the model "
        "gives them about a coin flip because it never learned from businesses that stale.",
        '<div class="key"><span><i class="sq s1"></i>Counted: seen open since 2023</span>'
        '<span><i class="sq ctx"></i>Left out: older than anything the '
        "model learned from</span></div>"
        + chart_div(
            "c-est-0", "Bar chart of average predicted chance closed by year last seen open"
        )
        + tables["estimate"],
        f"Counting every record back to 2010 gives {F['ghost_full']['expected_oob']:,.0f}, a "
        "number this analysis does not stand behind. The interval covers calibration only. "
        f"Snapshot as of {pd.Timestamp(F['snapshot']):%B %-d, %Y}.",
    )
    r0, r1 = F["nta_rec_range"]
    e0, e1 = F["nta_exp_range"]
    s_map = section(
        "map",
        "07 · Where",
        "Recorded closures vary far more by neighborhood than the model expects",
        f"Recorded: {pct(r0)} to {pct(r1)} of 2025 visits by neighborhood. Expected: "
        f"{pct(e0)} to {pct(e1)} of businesses. Where inspectors go shapes the first map.",
        '<div class="controls" id="ctl-map"></div>'
        + chart_div("c-map-0", "Map of New York City neighborhoods")
        + tables["map"],
        "Gray: too few records (under 500 visits, or under 100 businesses). Hover for detail; "
        "click a neighborhood or bar to highlight it, double-click to clear.",
    )
    s_ind = section(
        "industries",
        "08 · Which industries",
        f"General retail: closed on {pct(F['retail'][1])} of 2025 visits, "
        f"up from {pct(F['retail'][0])}",
        "Left: how often a visit found the business closed. Right: where the expected ghosts are.",
        '<div class="grid2">'
        + chart_div("c-ind-0", "Dot plot of share found closed by industry")
        + chart_div("c-ind-1", "Bar chart of expected closed businesses by industry")
        + "</div>"
        + tables["industries"],
        "Industries with at least 500 visits in 2025 (left) or 500 listed businesses (right).",
    )
    steps = [
        (
            "NYC Open Data",
            "Inspection archive 2010 to 2023, live system 2023 to 2026, plus MongoDB's 2015 sample",
        ),
        ("Raw", "Paged API pulls loaded into MongoDB unchanged"),
        ("Silver", "One schema across both systems; outcome and industry crosswalks"),
        (
            "Geo + identity",
            "2dsphere $geoWithin to neighborhoods; businesses linked across the 2023 switch",
        ),
        (
            "Gold",
            "One row per visit with features from earlier visits only ($setWindowFields, $merge)",
        ),
        ("Models", "Rule, logistic regression, LightGBM; Platt calibration; clustered bootstrap"),
        ("Outputs", "Notebooks, CSV exports, this page"),
    ]
    flow = (
        '<ol class="flow">'
        + "".join(f"<li><b>{a}</b><span>{b}</span></li>" for a, b in steps)
        + "</ol>"
    )
    limits = [
        "A closure record needs a visit. Rates reflect where and why inspectors went.",
        "A business is a linked identity in the record. Name and unit "
        "changes can split one shop into two.",
        "The estimate means recorded closed if visited, from a model "
        "trained on visits the city chose to make.",
        "Tried and dropped because the data could not support them: storefront turnover, "
        "reopenings after padlocks, vacancy, and wasted trips.",
    ]
    s_method = section(
        "method",
        "09 · Method and limits",
        "How this was built",
        f"A Python and MongoDB pipeline over {F['total_visits']:,} storefront inspection records, "
        f"{y0} to {y1}. Every number on this page is generated from the pipeline's outputs.",
        flow
        + '<h3 class="lim">What this does not claim</h3><ul class="limits">'
        + "".join(f"<li>{x}</li>" for x in limits)
        + "</ul>"
        + f'<p class="links"><a href="{REPO_URL}">Code and notebooks on GitHub</a></p>',
    )

    nav = [
        ("trend", "Trend"),
        ("staleness", "Staleness"),
        ("programs", "Programs"),
        ("chains", "Chains"),
        ("prediction", "Prediction"),
        ("estimate", "Estimate"),
        ("map", "Map"),
        ("industries", "Industries"),
        ("method", "Method"),
    ]
    nav_html = "".join(f'<a href="#{i}">{t}</a>' for i, t in nav)

    payload = {
        "specs": specs,
        "themes": THEMES,
        "config": VEGA_CONFIG,
    }
    bundle = vlc.javascript_bundle(vl_version=vl_version_for_vl_convert())
    page = TEMPLATE
    for k, v in {
        "{{NAV}}": nav_html,
        "{{TILES}}": tiles_html,
        "{{SECTIONS}}": s_trend
        + s_stale
        + s_prog
        + s_chain
        + s_model
        + s_est
        + s_map
        + s_ind
        + s_method,
        "{{TOTAL}}": f"{F['total_visits']:,}",
        "{{Y0}}": str(y0),
        "{{Y1}}": str(y1),
        "{{REPO_URL}}": REPO_URL,
        "{{SNAPSHOT}}": f"{pd.Timestamp(F['snapshot']):%B %Y}",
    }.items():
        page = page.replace(k, v)
    page = page.replace(
        "/*{{PAYLOAD}}*/",
        "const PAYLOAD = "
        + json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
        + ";\nconst GEO = "
        + json.dumps(geo, separators=(",", ":"))
        + ";",
    )
    page = page.replace("/*{{VEGA}}*/", bundle)
    return page


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ghost Storefronts</title>
<meta name="description" content="How stale is New York City's record of which businesses are
open? A data story from {{TOTAL}} inspection records.">
<style>
:root{
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --line:rgba(11,11,11,.10); --grid:#e1e0d9; --s1:#2a78d6; --s2:#eb6834; --chip:#efeee9;
--ctx:#c9c8c1; --nd:#e8e7e2;
  --r0:#86b6ef; --r1:#5598e7; --r2:#2a78d6; --r3:#1c5cab; --r4:#104281;
  color-scheme: light;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --plane:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
    --line:rgba(255,255,255,.10); --grid:#2c2c2a; --s1:#3987e5; --s2:#d95926; --chip:#262624;
--ctx:#4a4a46; --nd:#2a2a28;
    --r0:#184f95; --r1:#2a78d6; --r2:#5598e7; --r3:#86b6ef; --r4:#b7d3f6;
    color-scheme: dark;
  }
}
:root[data-theme="dark"]{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
  --line:rgba(255,255,255,.10); --grid:#2c2c2a; --s1:#3987e5; --s2:#d95926; --chip:#262624;
--ctx:#4a4a46; --nd:#2a2a28;
    --r0:#184f95; --r1:#2a78d6; --r2:#5598e7; --r3:#86b6ef; --r4:#b7d3f6;
  color-scheme: dark;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth; scroll-padding-top:64px}
body{margin:0; background:var(--plane); color:var(--ink);
  font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased}
a{color:var(--s1)}
.wrap{max-width:1040px; margin:0 auto; padding:0 20px}
header.top{position:sticky;
   top:0;
   z-index:10;
   background:color-mix(in srgb, var(--plane)
88%, transparent);
  backdrop-filter:blur(8px); border-bottom:1px solid var(--line)}
header.top .wrap{display:flex; align-items:center; gap:16px; height:52px}
header.top .brand{font-weight:650; white-space:nowrap; color:var(--ink); text-decoration:none}
header.top nav{display:flex; gap:4px; overflow-x:auto; scrollbar-width:none; flex:1}
header.top nav::-webkit-scrollbar{display:none}
header.top nav a{color:var(--ink2);
   text-decoration:none;
   font-size:13px;
   padding:6px
9px;
   border-radius:6px;
   white-space:nowrap}
header.top nav a:hover, header.top nav a.on{background:var(--chip); color:var(--ink)}
#theme{border:1px solid var(--line);
   background:var(--surface);
   color:var(--ink2);
border-radius:8px;
  font:13px system-ui,sans-serif; padding:5px 10px; cursor:pointer}
.hero{padding:56px 0 24px}
.hero .eyebrow{font-size:13px;
   letter-spacing:.06em;
   text-transform:uppercase;
color:var(--muted);
   margin:0 0 10px}
.hero h1{font-size:clamp(34px,6vw,56px);
   line-height:1.05;
   letter-spacing:-.02em;
margin:0 0 14px;
   font-weight:750}
.hero .lede{font-size:clamp(17px,2.2vw,20px); color:var(--ink2); max-width:720px; margin:0 0 10px}
.hero .by{font-size:13px; color:var(--muted); margin:0}
.tiles{display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:32px 0 8px}
.tile{display:flex;
   flex-direction:column;
   gap:6px;
   padding:18px;
   border-radius:12px;
background:var(--surface);
  border:1px solid var(--line); text-decoration:none; color:var(--ink2); font-size:14px;
line-height:1.4;
  transition:border-color .15s}
.tile:hover{border-color:var(--s1)}
.tile .big{font-size:34px;
   font-weight:750;
   color:var(--ink);
   letter-spacing:-.02em;
line-height:1.1}
section{background:var(--surface);
   border:1px solid var(--line);
   border-radius:14px;
padding:28px 28px 20px;
   margin:20px 0}
.kicker{font-size:12px;
   letter-spacing:.06em;
   text-transform:uppercase;
   color:var(--s1);
font-weight:650;
   margin:0 0 6px}
h2{font-size:clamp(21px,2.8vw,27px);
   line-height:1.2;
   letter-spacing:-.01em;
   margin:0 0
8px;
   font-weight:700;
   max-width:820px}
.dek{color:var(--ink2); margin:0 0 18px; max-width:760px}
.note{font-size:13px; color:var(--muted); margin:12px 0 0; max-width:820px}
h3{font-size:15px; margin:0}
.chart{width:100%; margin:6px 0}
.chart .vega-embed{width:100%; display:block}
.chart .vega-embed summary{display:none}
.grid2{display:grid; grid-template-columns:1fr 1fr; gap:28px}
.sub{margin:22px 0 4px} .sub p{margin:4px 0 0; color:var(--ink2); font-size:14px}
.controls{min-height:34px; margin:0 0 10px}
.controls .vega-bind{display:flex; flex-wrap:wrap; gap:6px; align-items:center}
.controls .vega-bind-name{display:none}
.controls .vega-bind label{display:inline-flex;
   align-items:center;
   gap:6px;
font-size:13px;
   color:var(--ink2);
  padding:6px 12px; border:1px solid var(--line); border-radius:999px; cursor:pointer;
background:var(--surface)}
.controls .vega-bind label:has(input:checked){background:var(--ink);
   color:var(--surface);
border-color:var(--ink)}
.controls .vega-bind input{position:absolute; opacity:0; pointer-events:none}
.controls .vega-bind label:has(input:focus-visible){outline:2px solid var(--s1); outline-offset:2px}
.key{display:flex; flex-wrap:wrap; gap:18px; font-size:13px; color:var(--ink2); margin:0 0 14px}
.key span{display:inline-flex; align-items:center; gap:7px}
.dot{width:9px; height:9px; border-radius:50%; display:inline-block}
.dot.s1{background:var(--s1)} .dot.s2{background:var(--s2)}
.sq{width:10px; height:10px; border-radius:2px; display:inline-block}
.sq.s1{background:var(--s1)} .sq.ctx{background:var(--ctx)} .sq.nd{background:var(--nd)}
.sq.r0{background:var(--r0)} .sq.r1{background:var(--r1)} .sq.r2{background:var(--r2)}
.sq.r3{background:var(--r3)} .sq.r4{background:var(--r4)}
.key b.lbl{font-size:12px; color:var(--ink2)}
.dash{width:22px; border-top:1.5px dashed var(--s1); opacity:.6; display:inline-block}
.chain-head{display:flex;
   flex-wrap:wrap;
   align-items:baseline;
   gap:6px 16px;
margin:18px 0 2px;
   padding-top:14px;
   border-top:1px solid var(--line)}
.chain-head:first-of-type{border-top:0}
.chain-stats{display:flex; flex-wrap:wrap; gap:4px 16px; font-size:13px; color:var(--ink2)}
.chain-stats b{color:var(--ink)}
details.data{margin:10px 0 0}
details.data summary{font-size:13px; color:var(--muted); cursor:pointer; width:max-content}
details.data .tbl{max-height:320px;
   overflow:auto;
   margin-top:8px;
   border:1px solid
var(--line);
   border-radius:8px}
table{border-collapse:collapse; width:100%; font-size:13px; font-variant-numeric:tabular-nums}
th,td{text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); white-space:nowrap}
th{position:sticky; top:0; background:var(--surface); color:var(--ink2); font-weight:600}
ol.flow{list-style:none;
   padding:0;
   margin:6px 0 20px;
   display:grid;
grid-template-columns:repeat(7,1fr);
   gap:8px;
   counter-reset:s}
ol.flow li{background:var(--chip);
   border-radius:10px;
   padding:12px;
   font-size:12.5px;
color:var(--ink2);
   position:relative;
   line-height:1.4}
ol.flow li b{display:block; color:var(--ink); font-size:13px; margin-bottom:4px}
ol.flow li:not(:last-child)::after{content:"\2192";
   position:absolute;
   right:-9px;
top:50%;
   transform:translateY(-50%);
   color:var(--muted);
   font-size:13px}
.lim{margin:8px 0 6px}
ul.limits{margin:0 0 8px;
   padding-left:20px;
   color:var(--ink2);
   max-width:820px}
ul.limits li{margin:4px 0}
.links{font-size:14px}
footer{color:var(--muted); font-size:13px; padding:20px 0 48px}
#vg-tooltip-element.custom-theme{background:var(--surface);
   color:var(--ink);
   border:1px
solid var(--line);
  border-radius:8px; box-shadow:0 6px 24px rgba(0,0,0,.14); font:12.5px/1.45 system-ui,sans-serif;
padding:8px 10px}
#vg-tooltip-element.custom-theme td.key{color:var(--muted); padding-right:10px}
@media (max-width:860px){
  .tiles{grid-template-columns:1fr 1fr}
  .grid2{grid-template-columns:1fr}
  ol.flow{grid-template-columns:1fr 1fr}
  ol.flow li::after{display:none}
  section{padding:22px 16px 16px}
  .wrap{padding:0 16px}
}
@media (max-width:480px){ .tile .big{font-size:28px} header.top .brand{display:none} }
</style>
</head>
<body>
<header class="top"><div class="wrap">
  <a class="brand" href="#">Ghost Storefronts</a>
  <nav>{{NAV}}</nav>
  <button id="theme" type="button" aria-label="Toggle dark mode">Dark</button>
</div></header>
<main class="wrap">
  <div class="hero">
    <p class="eyebrow">NYC inspection records, {{Y0}} to {{Y1}}</p>
    <h1>Ghost Storefronts</h1>
    <p class="lede">New York City's list of open businesses is only as current as the last
inspection. This is how stale it gets, how to tell before a visit, and how many closed businesses
are probably still on the books.</p>
    <p class="by">{{TOTAL}} storefront inspection records · Snapshot {{SNAPSHOT}}</p>
    <div class="tiles">{{TILES}}</div>
  </div>
  {{SECTIONS}}
  <footer>Data: NYC Department of Consumer and Worker Protection inspections, via NYC Open Data.
Built with Python, MongoDB, scikit-learn, LightGBM and Vega-Lite. <a
href="{{REPO_URL}}">Source</a>.</footer>
</main>
<script>/*{{VEGA}}*/</script>
<script>
/*{{PAYLOAD}}*/
(function(){
  const root = document.documentElement;
  const mq = matchMedia('(prefers-color-scheme: dark)');
  let stored = null; try { stored = localStorage.getItem('gs-theme'); } catch(e) {}
  if (stored) root.dataset.theme = stored;
  const themeName = () => root.dataset.theme || (mq.matches ? 'dark' : 'light');
  const resolve = (o, t) => {
    if (typeof o === 'string') return (o[0] === '@' && o in t) ? t[o] : o;
    if (Array.isArray(o)) return o.map(x => resolve(x, t));
    if (o && typeof o === 'object') { const r = {}; for (const k in o) r[k] = resolve(o[k], t);
    return r; }
    return o;
  };
  const merge = (a, b) => { const r = Object.assign({}, a); for (const k in b) {
    r[k] = (b[k] && typeof b[k] === 'object' && !Array.isArray(b[k]) && a[k]) ? merge(a[k],
    b[k]) : b[k]; } return r; };

  // Map layout: side by side when there is room, stacked on narrow screens.
  function layoutMap(spec, w) {
    const s = JSON.parse(JSON.stringify(spec));
    const parts = s.hconcat;
    if (w >= 820) {
      const mw = Math.min(560, Math.round(w * 0.56));
      parts[0].width = mw; parts[0].height = mw;
      parts[1].width = Math.max(140, w - mw - 270);
    } else {
      // Narrow screens: the map alone (the ranked list is in "View data").
      const m = parts[0];
      m.width = w - 12; m.height = Math.round((w - 12) * 1.05);
      return Object.assign({}, m, {$schema: s.$schema, datasets: s.datasets, config: s.config,
                                   params: (m.params || []).concat(s.params || [])});
    }
    return s;
  }
  const views = {};
  let lastMapWide = null;
  async function render(id) {
    const el = document.getElementById(id); if (!el) return;
    const t = PAYLOAD.themes[themeName()];
    let spec = resolve(PAYLOAD.specs[id], t);
    spec.config = merge(resolve(PAYLOAD.config, t), spec.config || {});
    if (id === 'c-map-0') {
      spec.datasets = Object.assign({}, spec.datasets, {nta_geo: GEO});
      spec = layoutMap(spec, el.clientWidth);
    }
    if (views[id]) { views[id].finalize(); }
    // keep any bound controls: Vega re-creates them in the same element
    (JSON.stringify(spec).match(/#ctl-[a-z]+/g) || []).forEach(sel => {
      const c = document.querySelector(sel); if (c) c.innerHTML = ''; });
    try {
      const res = await vegaEmbed(el, spec, {actions:false, renderer:'svg',
    tooltip:{theme:'custom'}});
      views[id] = res;
    } catch (e) { console.error(id, e); }
  }
  async function renderAll() { for (const id of Object.keys(PAYLOAD.specs)) await render(id); }
  function setButton(){ document.getElementById('theme').textContent = themeName() === 'dark' ?
    'Light' : 'Dark'; }
  document.getElementById('theme').addEventListener('click', () => {
    root.dataset.theme = themeName() === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem('gs-theme', root.dataset.theme); } catch(e) {}
    setButton(); renderAll();
  });
  mq.addEventListener('change', () => { if (!root.dataset.theme) { setButton(); renderAll(); } });
  let rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => {
    const w = document.getElementById('c-map-0').clientWidth >= 820;
    if (w !== lastMapWide) { lastMapWide = w; render('c-map-0'); }
  }, 200); });
  // highlight current section in the nav
  const links = [...document.querySelectorAll('header.top nav a')];
  const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) {
    links.forEach(a => a.classList.toggle('on', a.getAttribute('href') === '#' + e.target.id));
    } }),
    {rootMargin: '-45% 0px -50% 0px'});
  document.querySelectorAll('section').forEach(s => io.observe(s));
  setButton();
  lastMapWide = document.getElementById('c-map-0').clientWidth >= 820;
  renderAll();
})();
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exports", type=Path, default=REPO / "exports")
    ap.add_argument("--reports", type=Path, default=REPO / "reports")
    ap.add_argument("--geojson", type=Path, default=REPO / "data/boundaries/nta2020.geojson")
    ap.add_argument("--out", type=Path, default=REPO / "docs/index.html")
    a = ap.parse_args()

    D = load(a.exports, a.reports)
    F = build_facts(D)
    specs, tables = {}, {}
    for key, (parts, table) in {
        "trend": chart_trend(D),
        "staleness": chart_staleness(D),
        "programs": chart_programs(D),
        "chains": chart_chains(D, F),
        "prediction": chart_model(D, F),
        "estimate": chart_ghost_years(D),
        "map": chart_map(D),
        "industries": chart_industry(D),
    }.items():
        prefix = {
            "trend": "c-trend",
            "staleness": "c-stale",
            "programs": "c-prog",
            "chains": "c-chain",
            "prediction": "c-model",
            "estimate": "c-est",
            "map": "c-map",
            "industries": "c-ind",
        }[key]
        for i, spec in enumerate(parts):
            specs[f"{prefix}-{i}"] = spec
        tables[key] = table_html(table)
    page = build_page(D, F, load_boundaries(a.geojson), specs, tables)
    if "\u2014" in page.replace(vlc.javascript_bundle(vl_version=vl_version_for_vl_convert()), ""):
        raise SystemExit("em dash found in page text")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(page)
    print(f"wrote {a.out} ({a.out.stat().st_size / 1e6:.2f} MB, {len(specs)} charts)")


if __name__ == "__main__":
    main()
