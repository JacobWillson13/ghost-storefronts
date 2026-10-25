"""Load versioned MQL definitions, rebuild gold only, and independently audit history."""

from __future__ import annotations

import json
import time
from datetime import datetime
from importlib import import_module

from storefronts.config import REPO_ROOT
from storefronts.db import get_db

GOLD = ("gold_chain_dates", "visit_features", "business_status")


def pipeline(name, **kwargs):
    namespace, _, function = name.partition(".")
    if not function:
        namespace, function = "gold", namespace
    return getattr(import_module(f"storefronts.{namespace}"), function)(**kwargs)


def query(name, collection="visit_features", db=None, **kwargs):
    db = get_db() if db is None else db
    return list(db[collection].aggregate(pipeline(name, **kwargs), allowDiskUse=True))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False) + "\n")


def audit(db=None, path=None):
    db = get_db() if db is None else db
    report = {
        "invalid_visit_rows": query("audit_invalid", db=db),
        "invalid_status_rows": query("audit_invalid", "business_status", db=db),
        "inconsistent_timestamp_blocks": query("audit_blocks", db=db),
        "source_eligible": query("eligible_count", "inspections", db=db)[0]["n"],
        "gold_visits": db.visit_features.count_documents({}),
        "independent_checks": 0,
        "independent_status_checks": 0,
    }
    for row in query("sample_rows", db=db):
        result = query(
            "source_prior",
            "inspections",
            db=db,
            business_id=row["business_id"],
            timestamp=row["inspected_at"],
        )
        expected = (
            result[0]
            if result
            else {
                "prior_visits": 0,
                "prior_oob": 0,
                "prior_violations": 0,
                "industry_group": "UNKNOWN",
                "borough": "UNKNOWN",
            }
        )
        for field in [
            "prior_visits",
            "prior_oob",
            "prior_violations",
            "last_positive",
            "last_oob",
            "last_visit",
            "industry_group",
            "borough",
        ]:
            assert row.get(field) == expected.get(field), (
                row["_id"],
                field,
                row.get(field),
                expected,
            )
        report["independent_checks"] += 1
    for row in query("sample_status", "business_status", db=db):
        expected = query(
            "source_prior",
            "inspections",
            db=db,
            business_id=row["business_id"],
            timestamp=row["inspected_at"],
        )[0]
        for field in [
            "prior_visits",
            "prior_oob",
            "prior_violations",
            "last_positive",
            "last_oob",
            "last_visit",
            "industry_group",
            "borough",
        ]:
            assert row.get(field) == expected.get(field), (row["_id"], field)
        report["independent_status_checks"] += 1
    report["excluded_storefront_records_without_id"] = (
        query("storefront_count", "inspections", db=db)[0]["n"] - report["source_eligible"]
    )
    report["passed"] = (
        not report["invalid_visit_rows"]
        and not report["invalid_status_rows"]
        and not report["inconsistent_timestamp_blocks"]
        and report["source_eligible"] == report["gold_visits"]
    )
    write_json(path or REPO_ROOT / "reports/gold_audit.json", report)
    assert report["passed"], report
    return report


def build(db=None, audit_path=None):
    db = get_db() if db is None else db
    before = query("inventory", "inspections", db=db)
    source_counts = {
        name: db[name].estimated_document_count()
        for name in [
            "inspections",
            "raw_archive",
            "raw_live",
            "raw_sample_2015",
            "nta2020",
            "business_links",
        ]
    }
    source_indexes = {name: db[name].index_information() for name in source_counts}
    timings = {}
    for target, definition in zip(GOLD, ["chain_dates", "visits", "status"], strict=True):
        started = time.monotonic()
        db[target].drop()  # Full replacement prevents stale rows after source corrections.
        query(definition, "inspections", db=db)
        timings[target] = round(time.monotonic() - started, 2)
        print(f"{target}: {db[target].count_documents({}):,} rows; {timings[target]}s", flush=True)
    db.visit_features.create_index([("business_id", 1), ("inspected_at", 1)])
    db.visit_features.create_index("split")
    db.visit_features.create_index("year")
    db.business_status.create_index("nta2020")
    result = audit(db, audit_path)
    assert before == query("inventory", "inspections", db=db)
    assert source_counts == {name: db[name].estimated_document_count() for name in source_counts}
    assert source_indexes == {name: db[name].index_information() for name in source_counts}
    result["source_indexes_unchanged"] = True
    result.update(
        timings_seconds=timings,
        source_counts_unchanged=source_counts,
        source_inventory=before,
        snapshot_date="2026-08-23",
        exclusive_as_of="2026-08-24T00:00:00",
        chain_names=db.gold_chain_dates.count_documents({}),
    )
    write_json(audit_path or REPO_ROOT / "reports/gold_audit.json", result)
    return result


UNIT = {"industry.is_storefront": True, "business_id": {"$type": "string", "$ne": ""}}
HISTORY = {"business_id": {"$type": "string", "$ne": ""}}
POSITIVE = ["compliant", "violation", "warning"]
# Inclusive snapshot DATE, exclusive hypothetical visit INSTANT. No 23 August records omitted.
AS_OF = datetime(2026, 8, 24)
MONTH_MS = 86400000 * 30.4375


def count(condition):
    return {"$sum": {"$cond": [condition, 1, 0]}}


def unresolved(positive="$last_positive", oob="$last_oob"):
    return {
        "$and": [
            {"$ne": [oob, None]},
            {"$or": [{"$eq": [positive, None]}, {"$lte": [positive, oob]}]},
        ]
    }


def finish(target):
    return {
        "$merge": {
            "into": target,
            "on": "_id",
            "whenMatched": "replace",
            "whenNotMatched": "insert",
        }
    }


def chain_dates():
    return [
        {
            "$match": {
                **UNIT,
                "business.name_norm": {"$nin": [None, ""]},
                "storefront_key": {"$nin": [None, ""]},
            }
        },
        {
            "$group": {
                "_id": {"name": "$business.name_norm", "sf": "$storefront_key"},
                "first": {"$min": "$inspected_at"},
            }
        },
        {
            "$setWindowFields": {
                "partitionBy": "$_id.name",
                "sortBy": {"first": 1},
                "output": {"rank": {"$documentNumber": {}}},
            }
        },
        {"$match": {"rank": 10}},
        {"$project": {"_id": "$_id.name", "chain_at": "$first"}},
        finish("gold_chain_dates"),
    ]


def join_chain(name, timestamp):
    return [
        {
            "$lookup": {
                "from": "gold_chain_dates",
                "localField": name,
                "foreignField": "_id",
                "as": "chain",
            }
        },
        {"$set": {"chain_at": {"$ifNull": [{"$first": "$chain.chain_at"}, None]}}},
        {
            "$set": {
                "chain_flag": {
                    "$and": [{"$ne": ["$chain_at", None]}, {"$lt": ["$chain_at", timestamp]}]
                }
            }
        },
    ]


def feature_flags(timestamp):
    return {
        "$set": {
            "has_prior_positive": {"$ne": ["$last_positive", None]},
            "is_first_visit": {"$eq": ["$prior_visits", 0]},
            "prior_oob_unresolved": unresolved(),
            "months_since_last_positive": {
                "$cond": [
                    {"$ne": ["$last_positive", None]},
                    {"$divide": [{"$subtract": [timestamp, "$last_positive"]}, MONTH_MS]},
                    None,
                ]
            },
            **{
                f"old{m}": {
                    "$and": [
                        {"$ne": ["$last_positive", None]},
                        {
                            "$lt": [
                                "$last_positive",
                                {
                                    "$dateSubtract": {
                                        "startDate": timestamp,
                                        "unit": "month",
                                        "amount": m,
                                    }
                                },
                            ]
                        },
                    ]
                }
                for m in [12, 24, 36]
            },
        }
    }


def visits():
    previous = {"documents": ["unbounded", -1]}
    return [
        {"$match": HISTORY},
        {"$sort": {"business_id": 1, "inspected_at": 1, "_id": 1}},
        {
            "$group": {
                "_id": {"bid": "$business_id", "t": "$inspected_at"},
                "n": {"$sum": 1},
                "c": count("$is_closure"),
                "v": count({"$eq": ["$outcome", "violation"]}),
                "p": count({"$in": ["$outcome", POSITIVE]}),
                "pt": {"$max": {"$cond": [{"$in": ["$outcome", POSITIVE]}, "$inspected_at", None]}},
                "ct": {"$max": {"$cond": ["$is_closure", "$inspected_at", None]}},
                "context": {
                    "$last": {
                        "industry": "$industry.group",
                        "borough": "$borough",
                        "name": "$business.name_norm",
                    }
                },
                "rows": {
                    "$push": {
                        "id": "$_id",
                        "eligible": "$industry.is_storefront",
                        "source": "$source",
                        "year": "$year",
                        "type": "$inspection_type",
                        "nta": "$nta2020",
                        "nta_name": "$nta2020_name",
                        "oob": "$is_closure",
                        "violation": {"$eq": ["$outcome", "violation"]},
                    }
                },
            }
        },
        {
            "$setWindowFields": {
                "partitionBy": "$_id.bid",
                "sortBy": {"_id.t": 1},
                "output": {
                    **{
                        k: {"$sum": v, "window": previous}
                        for k, v in {
                            "prior_visits": "$n",
                            "prior_oob": "$c",
                            "prior_violations": "$v",
                            "prior_positive": "$p",
                        }.items()
                    },
                    "last_positive": {"$max": "$pt", "window": previous},
                    "last_oob": {"$max": "$ct", "window": previous},
                    "last_visit": {"$shift": {"output": "$_id.t", "by": -1}},
                    "past": {"$shift": {"output": "$context", "by": -1}},
                },
            }
        },
        *join_chain("past.name", "$_id.t"),
        {"$unwind": "$rows"},
        {"$match": {"rows.eligible": True}},
        {
            "$project": {
                "_id": "$rows.id",
                "business_id": "$_id.bid",
                "inspected_at": "$_id.t",
                "year": "$rows.year",
                "month": {"$month": "$_id.t"},
                "source": "$rows.source",
                "inspection_type": {
                    "$cond": [{"$eq": ["$rows.source", "live"]}, "$rows.type", "$$REMOVE"]
                },
                "industry_group": {"$ifNull": ["$past.industry", "UNKNOWN"]},
                "borough": {"$ifNull": ["$past.borough", "UNKNOWN"]},
                "name_norm_prior": "$past.name",
                "nta2020": "$rows.nta",
                "nta_name": "$rows.nta_name",
                "target_oob": "$rows.oob",
                "target_violation": "$rows.violation",
                **{
                    k: 1
                    for k in [
                        "prior_visits",
                        "prior_oob",
                        "prior_violations",
                        "prior_positive",
                        "last_positive",
                        "last_oob",
                        "last_visit",
                        "chain_at",
                        "chain_flag",
                    ]
                },
                "timestamp_block_size": "$n",
                "split": {
                    "$switch": {
                        "branches": [
                            {
                                "case": {
                                    "$and": [
                                        {"$eq": ["$rows.source", s]},
                                        {"$gte": ["$rows.year", lo]},
                                        {"$lte": ["$rows.year", hi]},
                                    ]
                                },
                                "then": label,
                            }
                            for s, lo, hi, label in [
                                ("archive", 2015, 2018, "archive_train_2015_2018"),
                                ("archive", 2019, 2019, "archive_test_2019"),
                                ("live", 2024, 2024, "live_train_2024"),
                                ("live", 2025, 2025, "live_test_2025"),
                            ]
                        ],
                        "default": "other",
                    }
                },
            }
        },
        feature_flags("$inspected_at"),
        finish("visit_features"),
    ]


def status(as_of=AS_OF):
    return [
        {"$match": {**HISTORY, "inspected_at": {"$lt": as_of}}},
        {"$sort": {"business_id": 1, "inspected_at": 1, "_id": 1}},
        {
            "$group": {
                "_id": "$business_id",
                "last_visit": {"$max": "$inspected_at"},
                "last_positive": {
                    "$max": {"$cond": [{"$in": ["$outcome", POSITIVE]}, "$inspected_at", None]}
                },
                "last_oob": {"$max": {"$cond": ["$is_closure", "$inspected_at", None]}},
                "ever_storefront": {"$max": "$industry.is_storefront"},
                "prior_visits": {"$sum": 1},
                "prior_oob": count("$is_closure"),
                "prior_violations": count({"$eq": ["$outcome", "violation"]}),
                "prior_positive": count({"$in": ["$outcome", POSITIVE]}),
                "industry_group": {"$last": "$industry.group"},
                "borough": {"$last": "$borough"},
                "nta2020": {"$last": "$nta2020"},
                "nta_name": {"$last": "$nta2020_name"},
                "name_norm_prior": {"$last": "$business.name_norm"},
            }
        },
        {"$match": {"ever_storefront": True}},
        {
            "$set": {
                "business_id": "$_id",
                "inspected_at": as_of,
                "snapshot_date": "2026-08-23",
                "year": as_of.year,
                "month": as_of.month,
            }
        },
        *join_chain("name_norm_prior", as_of),
        feature_flags(as_of),
        {"$set": {"oob_unresolved": "$prior_oob_unresolved"}},
        {"$unset": "chain"},
        finish("business_status"),
    ]


def inventory():
    return [
        {
            "$group": {
                "_id": "$source",
                "n": {"$sum": 1},
                "first": {"$min": "$inspected_at"},
                "last": {"$max": "$inspected_at"},
            }
        },
        {"$sort": {"_id": 1}},
    ]


def eligible_count():
    return [{"$match": UNIT}, {"$count": "n"}]


def audit_invalid(snapshot=False):
    return [
        {
            "$match": {
                "$expr": {
                    "$or": [
                        {
                            "$and": [
                                {"$ne": [{"$ifNull": [f"${f}", None]}, None]},
                                {"$gte": [f"${f}", "$inspected_at"]},
                            ]
                        }
                        for f in ["last_visit", "last_positive", "last_oob"]
                    ]
                    + [
                        {
                            "$and": [
                                "$is_first_visit",
                                {
                                    "$or": [
                                        {"$ne": ["$prior_oob", 0]},
                                        {"$ne": ["$prior_violations", 0]},
                                        "$has_prior_positive",
                                        "$chain_flag",
                                    ]
                                },
                            ]
                        },
                        {"$and": ["$chain_flag", {"$gte": ["$chain_at", "$inspected_at"]}]},
                        {
                            "$and": [
                                {"$ne": ["$months_since_last_positive", None]},
                                {"$lt": ["$months_since_last_positive", 0]},
                            ]
                        },
                    ]
                }
            }
        },
        {"$count": "n"},
    ]


def audit_blocks():
    fields = [
        "prior_visits",
        "prior_oob",
        "prior_violations",
        "last_positive",
        "last_oob",
        "industry_group",
        "borough",
        "chain_flag",
    ]
    return [
        {
            "$group": {
                "_id": {"bid": "$business_id", "t": "$inspected_at"},
                **{f: {"$addToSet": f"${f}"} for f in fields},
            }
        },
        {"$match": {"$expr": {"$or": [{"$gt": [{"$size": f"${f}"}, 1]} for f in fields]}}},
        {"$count": "n"},
    ]


def source_prior(business_id, timestamp):
    return [
        {"$match": {"business_id": business_id, "inspected_at": {"$lt": timestamp}}},
        {"$sort": {"inspected_at": 1, "_id": 1}},
        {
            "$group": {
                "_id": None,
                "prior_visits": {"$sum": 1},
                "prior_oob": count("$is_closure"),
                "prior_violations": count({"$eq": ["$outcome", "violation"]}),
                "last_positive": {
                    "$max": {"$cond": [{"$in": ["$outcome", POSITIVE]}, "$inspected_at", None]}
                },
                "last_oob": {"$max": {"$cond": ["$is_closure", "$inspected_at", None]}},
                "last_visit": {"$max": "$inspected_at"},
                "industry_group": {"$last": "$industry.group"},
                "borough": {"$last": "$borough"},
            }
        },
    ]


def sample_rows():
    return [
        {"$sort": {"_id": 1}},
        {
            "$group": {
                "_id": {
                    "year": "$year",
                    "cold": "$is_first_visit",
                    "repeat": "$prior_oob_unresolved",
                },
                "row": {"$first": "$$ROOT"},
            }
        },
        {"$replaceWith": "$row"},
    ]


def model_rows(era):
    return [
        {
            "$match": {
                "source": era,
                "year": {
                    "$in": [2015, 2016, 2017, 2018, 2019] if era == "archive" else [2024, 2025]
                },
            }
        },
        {"$sort": {"_id": 1}},
    ]


def ghost_rows():
    return [
        {"$match": {"oob_unresolved": False, "has_prior_positive": True}},
        {"$sort": {"_id": 1}},
    ]


def links():
    return [{"$project": {"_id": 0, "archive_key": 1}}]


def storefront_count():
    return [{"$match": {"industry.is_storefront": True}}, {"$count": "n"}]


def sample_status():
    return [
        {"$sort": {"_id": 1}},
        {
            "$group": {
                "_id": {"group": "$industry_group", "unresolved": "$oob_unresolved"},
                "row": {"$first": "$$ROOT"},
            }
        },
        {"$replaceWith": "$row"},
    ]
