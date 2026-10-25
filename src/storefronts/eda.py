"""Presentation aggregates over audited visit features; counts always accompany rates."""


def count(condition):
    return {"$sum": {"$cond": [condition, 1, 0]}}


def summary(dimensions, match=None):
    group = {
        "_id": {d: f"${d}" for d in dimensions},
        "visits": {"$sum": 1},
        "oob": count("$target_oob"),
        "violations": count("$target_violation"),
        "first_visits": count("$is_first_visit"),
        "oob_unknown_positive": count({"$and": ["$target_oob", {"$not": ["$has_prior_positive"]}]}),
        "repeat_unresolved_oob": count({"$and": ["$target_oob", "$prior_oob_unresolved"]}),
        **{f"oob_old{m}": count({"$and": ["$target_oob", f"$old{m}"]}) for m in [12, 24, 36]},
    }
    return ([{"$match": match}] if match else []) + [
        {"$group": group},
        {
            "$set": {
                "oob_share": {"$divide": ["$oob", "$visits"]},
                "violation_share": {"$divide": ["$violations", "$visits"]},
            }
        },
        {"$sort": {f"_id.{d}": 1 for d in dimensions}},
    ]


def yearly():
    return summary(["year", "source"])


def programs():
    return summary(["inspection_type"], {"source": "live"}) + [{"$sort": {"oob": -1}}]


def program_year():
    return summary(["year", "inspection_type"], {"source": "live"})


def staleness():
    return [
        {"$match": {"target_oob": True}},
        {
            "$set": {
                "age_bin": {
                    "$switch": {
                        "branches": [
                            {
                                "case": {"$eq": ["$months_since_last_positive", None]},
                                "then": "Unknown",
                            },
                            *[
                                {
                                    "case": {"$lte": ["$months_since_last_positive", n]},
                                    "then": label,
                                }
                                for n, label in [
                                    (12, "0-12"),
                                    (24, "12-24"),
                                    (36, "24-36"),
                                    (60, "36-60"),
                                    (120, "60-120"),
                                ]
                            ],
                        ],
                        "default": "120+",
                    }
                }
            }
        },
        {"$group": {"_id": {"year": "$year", "age_bin": "$age_bin"}, "oob": {"$sum": 1}}},
        {"$sort": {"_id.year": 1, "_id.age_bin": 1}},
    ]


def industry():
    return [
        {"$match": {"$or": [{"year": 2025}, {"year": {"$gte": 2015, "$lte": 2019}}]}},
        {"$set": {"period": {"$cond": [{"$eq": ["$year", 2025]}, "2025", "2015-2019"]}}},
        *summary(["period", "industry_group"]),
    ]


def nta():
    return summary(["nta2020", "nta_name"], {"year": 2025, "nta2020": {"$nin": [None, ""]}}) + [
        {"$match": {"visits": {"$gte": 500}}},
        {"$sort": {"oob_share": -1}},
    ]


def lineage():
    return [{"$match": {"source": "archive", "in_teaching_sample": True}}, {"$count": "matched"}]


def sample_count():
    return [{"$count": "sample_docs"}]


def timestamp_blocks():
    return [
        {
            "$group": {
                "_id": {
                    "year": "$year",
                    "source": "$source",
                    "bid": "$business_id",
                    "t": "$inspected_at",
                },
                "records": {"$sum": 1},
                "outcomes": {"$addToSet": "$target_oob"},
            }
        },
        {
            "$group": {
                "_id": {"year": "$_id.year", "source": "$_id.source"},
                "blocks": {"$sum": 1},
                "records": {"$sum": "$records"},
                "repeated_block_records": {
                    "$sum": {"$cond": [{"$gt": ["$records", 1]}, "$records", 0]}
                },
            }
        },
        {"$sort": {"_id.year": 1, "_id.source": 1}},
    ]


def monthly_2023():
    return summary(["source", "month"], {"year": 2023})


def prior_age_counts():
    return [
        {"$match": {"year": 2025}},
        {
            "$group": {
                "_id": None,
                "visits": {"$sum": 1},
                "known_old24_visits": count("$old24"),
                "known_old24_oob": count({"$and": ["$old24", "$target_oob"]}),
            }
        },
    ]


def sample_formats():
    return [
        {
            "$group": {
                "_id": None,
                "documents": {"$sum": 1},
                "fields": {
                    "$addToSet": {
                        "$map": {
                            "input": {"$objectToArray": "$$ROOT"},
                            "as": "field",
                            "in": "$$field.k",
                        }
                    }
                },
                "date_types": {"$addToSet": {"$type": "$date"}},
                "certificate_types": {"$addToSet": {"$type": "$certificate_number"}},
                "integer_certificates": count({"$eq": [{"$type": "$certificate_number"}, "int"]}),
                "string_certificates": count({"$eq": [{"$type": "$certificate_number"}, "string"]}),
                "address_fields": {
                    "$addToSet": {
                        "$map": {
                            "input": {"$objectToArray": "$address"},
                            "as": "field",
                            "in": "$$field.k",
                        }
                    }
                },
                "padded_day_dates": count(
                    {
                        "$regexMatch": {
                            "input": {
                                "$convert": {
                                    "input": "$date",
                                    "to": "string",
                                    "onError": "",
                                    "onNull": "",
                                }
                            },
                            "regex": r"\s{2}\d\s",
                        }
                    }
                ),
            }
        }
    ]
