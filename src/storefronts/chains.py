"""Chain cohorts and independent court roster; filing dates are not trading-end dates."""

import re
from collections import defaultdict
from datetime import datetime, timedelta

from storefronts.config import REPO_ROOT
from storefronts.gold import query, write_json
from storefronts.normalize import normalize_building

PATTERNS = {
    "RadioShack incl General Wireless": r"^(?:RADIO ?SHACK|GENERAL WIRELESS)(?: |$)",
    "Payless ShoeSource": r"^PAYLESS SHOE ?SOURCE(?: |$)",
    "Rite Aid incl Genovese": r"^(?:RITE AID|GENOVESE DRUG STORES?|GENOVESE DRUG SORES)(?: |$)",
}
POS = {"compliant", "violation", "warning"}


def quantiles(xs):
    xs = sorted(xs)
    if not xs:
        return {"n": 0}

    def q(p):
        i = (len(xs) - 1) * p
        lo = int(i)
        hi = min(lo + 1, len(xs) - 1)
        return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)

    return {
        "n": len(xs),
        "min": min(xs),
        "p25": q(0.25),
        "median": q(0.5),
        "p75": q(0.75),
        "p90": q(0.9),
        "max": max(xs),
    }


def make_location(chain, key, docs):
    docs.sort(key=lambda x: (x["inspected_at"], x["_id"]))
    closes = [d for d in docs if d["is_closure"]]
    non = [d for d in docs if not d["is_closure"]]
    pos = [d for d in docs if d["outcome"] in {"compliant", "violation", "warning"}]
    first_close = closes[0]["inspected_at"] if closes else None
    preclose = [d for d in pos if first_close and d["inspected_at"] < first_close]
    a = docs[-1]["address"]
    return {
        "chain": chain,
        "location": key,
        "address": f"{a.get('building', '')} {a.get('street_norm', '')} {a.get('zip', '')}",
        "bbls": sorted({d["bbl"] for d in docs if d.get("bbl")}),
        "addresses": sorted(
            {
                f"{d['address'].get('zip')}|{normalize_building(d['address'].get('building'))}|{d['address'].get('street_norm')}"
                for d in docs
            }
        ),
        "business_ids": sorted({d.get("business_id") or d["business_key"] for d in docs}),
        "names": sorted({d["name"] for d in docs}),
        "n": len(docs),
        "first_seen": docs[0]["inspected_at"],
        "last_seen": docs[-1]["inspected_at"],
        "last_nonclosure": non[-1]["inspected_at"] if non else None,
        "last_positive": pos[-1]["inspected_at"] if pos else None,
        "first_closure": first_close,
        "last_closure": closes[-1]["inspected_at"] if closes else None,
        "last_positive_before_first_closure": preclose[-1]["inspected_at"] if preclose else None,
        "closure_minus_last_seen_days": (first_close - docs[-1]["inspected_at"]).days
        if first_close
        else None,
        "positive_to_first_closure_days": (first_close - preclose[-1]["inspected_at"]).days
        if preclose
        else None,
        "positive_after_first_closure": bool(
            first_close and pos and pos[-1]["inspected_at"] > first_close
        ),
        "sf_keys": sorted({d["storefront_key"] for d in docs}),
    }


ROSTER = [
    ("4873", "55-60", "MYRTLE AVENUE", "11385", "2025-05-09", 75),
    ("10577", "8222", "18TH AVENUE", "11214", "2025-05-09", 75),
    ("3766", "5901", "BAY PARKWAY", "11204", "2025-05-09", 75),
    ("10600", "50-15", "ROOSEVELT AVENUE", "11377", "2025-05-09", 75),
    ("10601", "60-26", "WOODSIDE AVENUE", "11377", "2025-05-09", 75),
    ("10585", "2064", "MILL AVENUE", "11234", "2025-06-06", 6),
    ("2010", "4046", "BROADWAY", "10032", "2025-06-06", 7),
]


def address_key(d):
    a = d["address"]
    building = normalize_building(a.get("building"))
    return (
        f"ADDR:{a.get('zip')}|{building}|{a.get('street_norm')}"
        if a.get("zip") and building and a.get("street_norm")
        else d["storefront_key"]
    )


def analyze():
    docs = query("chains.histories", "inspections")
    locations, cohorts, timelines, post_cutoff, court = [], [], [], [], []
    location_docs = {}
    for chain, pattern in PATTERNS.items():
        chain_docs = [d for d in docs if re.match(pattern, d["name"])]
        address_bbls = defaultdict(set)
        for d in chain_docs:
            if d.get("bbl"):
                address_bbls[address_key(d)].add(d["bbl"])
        buckets = defaultdict(list)
        for d in chain_docs:
            bs = address_bbls[address_key(d)]
            bbl = d.get("bbl") or (next(iter(bs)) if len(bs) == 1 else None)
            key = f"BBL:{bbl}" if bbl else address_key(d)
            buckets[key].append(d)
        for key, ds in sorted(buckets.items()):
            loc = make_location(chain, key, ds)
            locations.append(loc)
            location_docs[chain, key] = ds
            timelines.append(
                {
                    k: loc[k]
                    for k in [
                        "chain",
                        "location",
                        "address",
                        "last_seen",
                        "last_positive",
                        "first_closure",
                        "last_closure",
                        "positive_to_first_closure_days",
                    ]
                }
            )
        cutoff = {
            "RadioShack incl General Wireless": datetime(2018, 1, 1),
            "Payless ShoeSource": datetime(2020, 1, 1),
            "Rite Aid incl Genovese": datetime(2026, 1, 1),
        }[chain]
        after = [d for d in chain_docs if d["inspected_at"] >= cutoff]
        post_cutoff.append(
            {
                "chain": chain,
                "cutoff": cutoff,
                "visit_records": len(after),
                "oob": sum(d["is_closure"] for d in after),
                "positive": sum(d["outcome"] in POS for d in after),
                "other": sum(not d["is_closure"] and d["outcome"] not in POS for d in after),
            }
        )
    events = [
        ("RadioShack incl General Wireless", datetime(2015, 2, 5)),
        ("RadioShack incl General Wireless", datetime(2017, 3, 8)),
        ("Payless ShoeSource", datetime(2019, 2, 25)),
        ("Rite Aid incl Genovese", datetime(2023, 10, 15)),
        ("Rite Aid incl Genovese", datetime(2025, 5, 5)),
    ]
    for chain, event in events:
        for months, days in [(12, 365), (24, 730)]:
            eligible, gaps, event_gaps = [], [], []
            for loc in [x for x in locations if x["chain"] == chain]:
                ds = location_docs[chain, loc["location"]]
                pre = [
                    d
                    for d in ds
                    if d["outcome"] in POS
                    and event - timedelta(days=days) <= d["inspected_at"] < event
                ]
                if not pre:
                    continue
                post_oob = [
                    d["inspected_at"] for d in ds if d["is_closure"] and d["inspected_at"] >= event
                ]
                eligible.append(bool(post_oob))
                if post_oob:
                    first = min(post_oob)
                    positive = max(
                        d["inspected_at"]
                        for d in ds
                        if d["outcome"] in POS and d["inspected_at"] < first
                    )
                    gaps.append((first - positive).days)
                    event_gaps.append((first - event).days)
            cohorts.append(
                {
                    "chain": chain,
                    "event": event,
                    "lookback_months": months,
                    "locations": len(eligible),
                    "post_event_oob": sum(eligible),
                    "detection_proxy": sum(eligible) / len(eligible) if eligible else None,
                    "positive_to_oob_days": quantiles(gaps),
                    "event_to_oob_days": quantiles(event_gaps),
                }
            )
    rite = [d for d in docs if re.match(PATTERNS["Rite Aid incl Genovese"], d["name"])]
    for number, building, street, zip5, notice, page in ROSTER:
        candidates = [
            x
            for x in locations
            if x["chain"] == "Rite Aid incl Genovese"
            and any(
                a.split("|")[:2] == [zip5, normalize_building(building)] for a in x["addresses"]
            )
        ]
        bbls = {b for x in candidates for b in x["bbls"]}
        ds = [d for d in rite if d.get("bbl") in bbls]
        assert ds, number
        first = min(
            (
                d["inspected_at"]
                for d in ds
                if d["is_closure"] and d["inspected_at"] >= datetime.fromisoformat(notice)
            ),
            default=None,
        )
        court.append(
            {
                "store": number,
                "address": f"{building} {street} {zip5}",
                "notice": notice,
                "pdf_page": page,
                "matched_bbls": sorted(bbls),
                "candidate_locations": len(candidates),
                "last_seen": max(d["inspected_at"] for d in ds),
                "last_positive": max(
                    (d["inspected_at"] for d in ds if d["outcome"] in POS), default=None
                ),
                "first_oob_after_notice": first,
                "notice_to_record_days": (first - datetime.fromisoformat(notice)).days
                if first
                else None,
            }
        )
    result = {
        "locations": locations,
        "cohorts": cohorts,
        "timelines": timelines,
        "post_cutoff": post_cutoff,
        "court": court,
        "court_detected": sum(x["first_oob_after_notice"] is not None for x in court),
        "court_notice_gap": quantiles(
            [x["notice_to_record_days"] for x in court if x["notice_to_record_days"] is not None]
        ),
    }
    write_json(REPO_ROOT / "reports/chain_results.json", result)
    return result


def histories():
    return [
        {
            "$match": {
                "industry.is_storefront": True,
                "business_id": {"$type": "string", "$ne": ""},
                "business.name_norm": {
                    "$regex": r"^(RADIO ?SHACK|GENERAL WIRELESS|RITE AID|GENOVESE DRUG|PAYLESS)"
                },
            }
        },
        {
            "$project": {
                "name": "$business.name_norm",
                "business_id": 1,
                "business_key": 1,
                "storefront_key": 1,
                "bbl": 1,
                "address": 1,
                "inspected_at": 1,
                "is_closure": 1,
                "outcome": 1,
                "source": 1,
            }
        },
        {"$sort": {"inspected_at": 1, "_id": 1}},
    ]
