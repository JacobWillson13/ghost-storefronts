"""Index definitions. Each one is justified by a query it serves; see docs in the README."""

from __future__ import annotations

from pymongo import ASCENDING, GEOSPHERE, IndexModel
from pymongo.database import Database

from storefronts.db import INSPECTIONS, RAW_ARCHIVE, RAW_LIVE

INDEXES: dict[str, list[IndexModel]] = {
    INSPECTIONS: [
        # Business histories: $setWindowFields partitions by business, sorts by date.
        IndexModel(
            [("business_key", ASCENDING), ("inspected_at", ASCENDING)], name="business_history"
        ),
        # Storefront successions: what came before and after at the same lot and unit.
        IndexModel(
            [("storefront_key", ASCENDING), ("inspected_at", ASCENDING)], name="storefront_history"
        ),
        # Time-window filters, the most common predicate in the EDA.
        IndexModel([("inspected_at", ASCENDING)], name="inspected_at"),
        # Industry trends by year, e.g. the tobacco/vape/cannabis section.
        IndexModel(
            [("industry.group", ASCENDING), ("year", ASCENDING)], name="industry_group_year"
        ),
        IndexModel([("nta", ASCENDING), ("year", ASCENDING)], name="nta_year"),
        IndexModel([("outcome", ASCENDING), ("year", ASCENDING)], name="outcome_year"),
        # $geoNear questions. 2dsphere indexes skip docs without `location`.
        IndexModel([("location", GEOSPHERE)], name="location_2dsphere"),
        # Lineage join against the 2015 sample.
        IndexModel(
            [("source_record_id", ASCENDING), ("inspected_at", ASCENDING)],
            name="source_record_id_date",
        ),
        # Cross-system matching (archive to live) on lot plus normalized name.
        IndexModel([("bbl", ASCENDING), ("business.name_norm", ASCENDING)], name="bbl_name"),
    ],
    RAW_ARCHIVE: [IndexModel([("rec_id", ASCENDING)], name="rec_id")],
    RAW_LIVE: [IndexModel([("inspection_number", ASCENDING)], name="inspection_number")],
}


def create_indexes(db: Database, log=print) -> dict[str, list[str]]:
    made = {}
    for coll, models in INDEXES.items():
        made[coll] = db[coll].create_indexes(models)
        log(f"{coll}: {', '.join(made[coll])}")
    return made
