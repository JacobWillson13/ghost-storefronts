"""Data-quality report: writes reports/data_quality.md and reports/data_quality.json.

Run it after every silver build. The quality sections list exactly what to fix in
config/outcome_crosswalk.yaml and config/industry_crosswalk.yaml.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pymongo.database import Database

from storefronts.config import REPO_ROOT
from storefronts.db import INSPECTIONS, RAW_ARCHIVE, RAW_LIVE, RAW_SAMPLE


def _agg(db: Database, coll: str, pipeline: list) -> list[dict]:
    return list(db[coll].aggregate(pipeline, allowDiskUse=True))


def _table(rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return "_none_\n"
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, float):
                v = f"{v:.1%}" if 0 <= v <= 1 else f"{v:,.2f}"
            elif isinstance(v, bool):
                v = str(v)
            elif isinstance(v, int):
                v = str(v) if c == "year" else f"{v:,}"
            elif isinstance(v, datetime):
                v = v.strftime("%Y-%m-%d")
            cells.append(str(v) if v is not None else "")
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def collect(db: Database) -> dict:
    r: dict = {"generated_at": datetime.now(UTC).isoformat()}

    r["by_source"] = _agg(
        db,
        INSPECTIONS,
        [
            {
                "$group": {
                    "_id": "$source",
                    "docs": {"$sum": 1},
                    "first": {"$min": "$inspected_at"},
                    "last": {"$max": "$inspected_at"},
                    "with_bbl": {"$avg": {"$cond": [{"$ifNull": ["$bbl", False]}, 1, 0]}},
                    "with_location": {"$avg": {"$cond": [{"$ifNull": ["$location", False]}, 1, 0]}},
                    "with_nta": {"$avg": {"$cond": [{"$ifNull": ["$nta", False]}, 1, 0]}},
                    "with_business_key": {
                        "$avg": {"$cond": [{"$ifNull": ["$business_key", False]}, 1, 0]}
                    },
                    "storefront_share": {"$avg": {"$cond": ["$industry.is_storefront", 1, 0]}},
                }
            },
            {"$set": {"source": "$_id"}},
            {"$sort": {"source": 1}},
        ],
    )

    r["by_year"] = _agg(
        db,
        INSPECTIONS,
        [
            {
                "$group": {
                    "_id": "$year",
                    "inspections": {"$sum": 1},
                    "closures": {"$sum": {"$cond": ["$is_closure", 1, 0]}},
                }
            },
            {
                "$set": {
                    "year": "$_id",
                    "closure_rate": {"$divide": ["$closures", "$inspections"]},
                }
            },
            {"$sort": {"year": 1}},
        ],
    )

    r["outcomes"] = _agg(
        db,
        INSPECTIONS,
        [
            {"$group": {"_id": {"source": "$source", "outcome": "$outcome"}, "n": {"$sum": 1}}},
            {"$set": {"source": "$_id.source", "outcome": "$_id.outcome"}},
            {"$sort": {"source": 1, "n": -1}},
        ],
    )

    r["unmapped_results"] = _agg(
        db,
        INSPECTIONS,
        [
            {"$match": {"outcome": {"$in": ["unmapped", "missing"]}}},
            {
                "$group": {
                    "_id": {"source": "$source", "result_raw": "$result_raw"},
                    "n": {"$sum": 1},
                }
            },
            {"$set": {"source": "$_id.source", "result_raw": "$_id.result_raw"}},
            {"$sort": {"n": -1}},
            {"$limit": 50},
        ],
    )

    r["default_group_industries"] = _agg(
        db,
        INSPECTIONS,
        [
            {"$match": {"industry.group": {"$in": ["other", "missing"]}}},
            {
                "$group": {
                    "_id": {"source": "$source", "label": "$industry.label"},
                    "n": {"$sum": 1},
                    "is_storefront": {"$first": "$industry.is_storefront"},
                }
            },
            {"$set": {"source": "$_id.source", "label": "$_id.label"}},
            {"$sort": {"n": -1}},
            {"$limit": 80},
        ],
    )

    r["industry_groups"] = _agg(
        db,
        INSPECTIONS,
        [
            {
                "$group": {
                    "_id": {"group": "$industry.group", "source": "$source"},
                    "n": {"$sum": 1},
                }
            },
            {"$set": {"group": "$_id.group", "source": "$_id.source"}},
            {"$sort": {"group": 1, "source": 1}},
        ],
    )

    r["cardinality"] = _agg(
        db,
        INSPECTIONS,
        [
            {"$match": {"industry.is_storefront": True}},
            {
                "$facet": {
                    "storefronts": [{"$group": {"_id": "$storefront_key"}}, {"$count": "n"}],
                    "businesses": [{"$group": {"_id": "$business_key"}}, {"$count": "n"}],
                    "inspections": [{"$count": "n"}],
                }
            },
            {
                "$project": {
                    "storefronts": {"$first": "$storefronts.n"},
                    "businesses": {"$first": "$businesses.n"},
                    "inspections": {"$first": "$inspections.n"},
                }
            },
        ],
    )

    # The key risk metric: of businesses active in the archive's last year, how many are found
    # again in the live system? Uses business_id (set by `link-switch`) when it exists.
    r["cross_system_continuity"] = _agg(
        db,
        INSPECTIONS,
        [
            {"$match": {"industry.is_storefront": True, "business_key": {"$ne": None}}},
            {
                "$group": {
                    "_id": {"$ifNull": ["$business_id", "$business_key"]},
                    "archive_last": {
                        "$max": {"$cond": [{"$eq": ["$source", "archive"]}, "$inspected_at", None]}
                    },
                    "in_live": {"$max": {"$eq": ["$source", "live"]}},
                    "closed_in_archive": {
                        "$max": {"$and": [{"$eq": ["$source", "archive"]}, "$is_closure"]}
                    },
                }
            },
            {
                "$match": {
                    "archive_last": {"$gte": datetime(2022, 7, 1)},
                    "closed_in_archive": False,
                }
            },
            {
                "$group": {
                    "_id": None,
                    "open_archive_businesses_2022h2_plus": {"$sum": 1},
                    "found_in_live": {"$sum": {"$cond": ["$in_live", 1, 0]}},
                }
            },
            {
                "$set": {
                    "match_rate": {
                        "$cond": [
                            {"$gt": ["$open_archive_businesses_2022h2_plus", 0]},
                            {"$divide": ["$found_in_live", "$open_archive_businesses_2022h2_plus"]},
                            None,
                        ]
                    }
                }
            },
        ],
    )

    r["teaching_sample"] = {
        "sample_docs": db[RAW_SAMPLE].estimated_document_count(),
        "archive_docs_flagged": db[INSPECTIONS].count_documents({"in_teaching_sample": True}),
    }

    r["raw_duplicates"] = {
        "archive_rec_id": _agg(
            db,
            RAW_ARCHIVE,
            [
                {"$group": {"_id": "$rec_id", "n": {"$sum": 1}}},
                {"$match": {"n": {"$gt": 1}}},
                {"$count": "duplicated_keys"},
            ],
        ),
        "live_inspection_number": _agg(
            db,
            RAW_LIVE,
            [
                {"$group": {"_id": "$inspection_number", "n": {"$sum": 1}}},
                {"$match": {"n": {"$gt": 1}}},
                {"$count": "duplicated_keys"},
            ],
        ),
    }

    r["live_address_types"] = _agg(
        db,
        RAW_LIVE,
        [
            {"$group": {"_id": "$address_type", "n": {"$sum": 1}}},
            {"$set": {"address_type": "$_id"}},
            {"$sort": {"n": -1}},
        ],
    )
    r["live_inspection_types"] = _agg(
        db,
        RAW_LIVE,
        [
            {"$group": {"_id": "$inspection_type", "n": {"$sum": 1}}},
            {"$set": {"inspection_type": "$_id"}},
            {"$sort": {"n": -1}},
            {"$limit": 40},
        ],
    )
    return r


def render(r: dict) -> str:
    md = [f"# Data quality report\n\nGenerated {r['generated_at']}\n"]
    md.append("## Silver inspections by source\n")
    md.append(
        _table(
            r["by_source"],
            [
                "source",
                "docs",
                "first",
                "last",
                "with_bbl",
                "with_location",
                "with_nta",
                "with_business_key",
                "storefront_share",
            ],
        )
    )
    md.append("\n## Inspections and closures by year\n")
    md.append(_table(r["by_year"], ["year", "inspections", "closures", "closure_rate"]))
    md.append("\n## Outcomes by source\n")
    md.append(_table(r["outcomes"], ["source", "outcome", "n"]))
    md.append("\n## results with no crosswalk entry\n")
    md.append("Add these to `config/outcome_crosswalk.yaml`.\n\n")
    md.append(_table(r["unmapped_results"], ["source", "result_raw", "n"]))
    md.append("\n## industries in the default group\n")
    md.append(
        "Add these to `config/industry_crosswalk.yaml` (groups, renames, non_storefront).\n\n"
    )
    md.append(_table(r["default_group_industries"], ["source", "label", "n", "is_storefront"]))
    md.append("\n## Industry groups by source\n")
    md.append(_table(r["industry_groups"], ["group", "source", "n"]))
    md.append("\n## Storefront cardinality (storefront industries only)\n")
    md.append(_table(r["cardinality"], ["inspections", "storefronts", "businesses"]))
    md.append("\n## Cross-system continuity (exact business_key)\n")
    md.append(
        "Open archive businesses seen from July 2022 on, and how many the live system finds "
        "under the same key. A low rate means the key is splitting businesses across the "
        "June 2023 system switch.\n\n"
    )
    md.append(
        _table(
            r["cross_system_continuity"],
            [
                "open_archive_businesses_2022h2_plus",
                "found_in_live",
                "match_rate",
            ],
        )
    )
    md.append("\n## Sample lineage\n")
    md.append(_table([r["teaching_sample"]], ["sample_docs", "archive_docs_flagged"]))
    md.append("\n## Duplicate natural keys in raw data\n")
    md.append(
        "Archive `rec_id` repeats are expected: it is a case number shared by re-inspections. "
        "Silver keys on the raw row hash, so nothing collapses.\n\n"
    )
    dup = r["raw_duplicates"]
    md.append(
        _table(
            [
                {
                    "archive_rec_id": (dup["archive_rec_id"] or [{"duplicated_keys": 0}])[0][
                        "duplicated_keys"
                    ],
                    "live_inspection_number": (
                        dup["live_inspection_number"] or [{"duplicated_keys": 0}]
                    )[0]["duplicated_keys"],
                }
            ],
            ["archive_rec_id", "live_inspection_number"],
        )
    )
    md.append("\n## Live address types (decides the non-storefront rule)\n")
    md.append(_table(r["live_address_types"], ["address_type", "n"]))
    md.append("\n## Live inspection types\n")
    md.append(_table(r["live_inspection_types"], ["inspection_type", "n"]))
    return "\n".join(md)


def write_report(db: Database, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or REPO_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    r = collect(db)
    (out_dir / "data_quality.json").write_text(json.dumps(r, indent=2, default=str))
    path = out_dir / "data_quality.md"
    path.write_text(render(r))
    return path
