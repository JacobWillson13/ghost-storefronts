"""Silver layer: map the two record systems onto one validated `inspections` schema.

archive (Accela, schema_version 1)  insp_rslt, industry, biz_name, cert_nbr, rec_id ...
live    (current, schema_version 2) inspection_status, business_category, business_name ...

Row-level cleaning (names, units, dates) runs in Python because MongoDB aggregation has no
regex replace; everything downstream of silver is aggregation pipelines.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime

from pymongo import ReplaceOne
from pymongo.database import Database
from pymongo.errors import BulkWriteError, CollectionInvalid

from storefronts import normalize as nz
from storefronts.config import Crosswalks, crosswalks, sources
from storefronts.db import CROSSWALK, INSPECTIONS, RAW_SAMPLE
from storefronts.schema import INSPECTIONS_SCHEMA

BATCH = 5000


def _s(v) -> str | None:
    """Socrata sends everything as strings; treat blanks as missing."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _build(
    *,
    xw: Crosswalks,
    source: str,
    schema_version: int,
    _id: str,
    raw_id: str,
    source_record_id,
    inspected_at: datetime,
    name_raw,
    dba_raw,
    industry_raw,
    inspection_type,
    result_raw,
    building,
    street,
    street2,
    unit_type,
    unit,
    city,
    state,
    zip_raw,
    borough_raw,
    bbl_raw,
    bin_raw,
    nta,
    council_district,
    community_district,
    lat,
    lng,
    ids: dict,
    build_id: str,
) -> dict:
    bbl = nz.normalize_bbl(bbl_raw)
    unit_norm = nz.normalize_unit(unit_type, unit)
    zip5 = nz.normalize_zip(zip_raw)
    bldg = nz.normalize_building(building)
    street_norm = nz.normalize_street(street)
    name_norm = nz.normalize_name(name_raw) or nz.normalize_name(dba_raw)
    sf_key = nz.storefront_key(bbl, unit_norm, zip5, bldg, street_norm)
    outcome = xw.outcome(result_raw)

    doc = {
        "_id": _id,
        "source": source,
        "schema_version": schema_version,
        "source_record_id": _s(source_record_id),
        "raw_id": raw_id,
        **{k: _s(v) for k, v in ids.items()},
        "inspected_at": inspected_at,
        "year": inspected_at.year,
        "inspection_type": _s(inspection_type),
        "result_raw": _s(result_raw) or "",
        "outcome": outcome,
        "is_closure": outcome == "out_of_business",
        "is_padlock": outcome == "padlocked",
        "business": {"name_raw": _s(name_raw), "dba_raw": _s(dba_raw), "name_norm": name_norm},
        "industry": nz.classify_industry(_s(industry_raw), xw),
        "address": {
            "building": _s(building),
            "street": _s(street),
            "street2": _s(street2),
            "unit_type": _s(unit_type),
            "unit": _s(unit),
            "unit_norm": unit_norm,
            "street_norm": street_norm,
            "city": _s(city),
            "state": _s(state),
            "zip": zip5,
        },
        "borough": nz.normalize_borough(_s(borough_raw), bbl),
        "nta": _s(nta),
        "bbl": bbl,
        "bin": _s(bin_raw),
        "council_district": _s(council_district),
        "community_district": _s(community_district),
        "storefront_key": sf_key,
        "business_key": nz.business_key(sf_key, name_norm),
        "in_teaching_sample": False,
        "silver_build_id": build_id,
    }
    point = nz.geo_point(lat, lng)
    if point:
        doc["location"] = point
    return doc


def _plausible(ts: datetime | None) -> datetime | None:
    """Drop placeholder dates (the archive has a few from 1970) and future dates."""
    if ts is None or ts.year < 1990 or ts.year > datetime.now().year + 1:
        return None
    return ts


def from_archive(raw: dict, xw: Crosswalks, build_id: str) -> dict | None:
    ts = _plausible(nz.parse_socrata_ts(raw.get("insp_dt")))
    if ts is None:
        return None
    rec_id = _s(raw.get("rec_id"))
    return _build(
        xw=xw,
        source="archive",
        schema_version=1,
        # Not rec_id: it is a case number and repeats across re-inspections of one case.
        _id=f"archive:{raw['_id']}",
        raw_id=raw["_id"],
        source_record_id=rec_id,
        inspected_at=ts,
        name_raw=raw.get("biz_name"),
        dba_raw=None,
        industry_raw=raw.get("industry"),
        inspection_type=None,  # the archive has no inspection type field
        result_raw=raw.get("insp_rslt"),
        building=raw.get("bldg_nbr"),
        street=raw.get("street"),
        street2=raw.get("street2"),
        unit_type=raw.get("unit_typ"),
        unit=raw.get("unit"),
        city=raw.get("city"),
        state=raw.get("state"),
        zip_raw=raw.get("zip"),
        borough_raw=raw.get("boro"),
        bbl_raw=raw.get("bbl"),
        bin_raw=raw.get("bin"),
        nta=raw.get("nta2020"),
        council_district=raw.get("council_district"),
        community_district=raw.get("community_board"),
        lat=raw.get("latitude"),
        lng=raw.get("longitude"),
        ids={
            # kept as text: the 2015 sample stored this as a number and lost leading zeros
            "certificate_number": raw.get("cert_nbr"),
            "inspection_number": None,
            "business_unique_id": None,
            "license_number": None,
        },
        build_id=build_id,
    )


def from_live(raw: dict, xw: Crosswalks, build_id: str) -> dict | None:
    ts = _plausible(nz.parse_socrata_ts(raw.get("date_of_occurrence")))
    if ts is None:
        return None
    return _build(
        xw=xw,
        source="live",
        schema_version=2,
        _id=f"live:{raw['_id']}",
        raw_id=raw["_id"],
        source_record_id=raw.get("inspection_number"),
        inspected_at=ts,
        name_raw=raw.get("business_name"),
        dba_raw=raw.get("dba_trade_name"),
        industry_raw=raw.get("business_category"),
        inspection_type=raw.get("inspection_type"),
        result_raw=raw.get("inspection_status"),
        building=raw.get("building_no"),
        street=raw.get("street_1"),
        street2=raw.get("street_2"),
        unit_type=raw.get("unit_type"),
        unit=raw.get("apt_suite"),
        city=raw.get("city"),
        state=raw.get("state"),
        zip_raw=raw.get("zip_code"),
        borough_raw=raw.get("borough"),
        bbl_raw=raw.get("bbl"),
        bin_raw=raw.get("bin"),
        nta=raw.get("nta"),
        council_district=raw.get("city_council_district"),
        community_district=raw.get("community_district"),
        lat=raw.get("latitude"),
        lng=raw.get("longitude"),
        ids={
            "certificate_number": raw.get("certificate_of_inspection"),
            "inspection_number": raw.get("inspection_number"),
            "business_unique_id": raw.get("business_unique_id"),
            "license_number": raw.get("dcwp_license_number"),
        },
        build_id=build_id,
    )


TRANSFORMS = {"archive": from_archive, "live": from_live}


def ensure_inspections(db: Database) -> None:
    """Create the silver collection with its validator, or update the validator in place."""
    try:
        db.create_collection(
            INSPECTIONS,
            validator=INSPECTIONS_SCHEMA,
            validationLevel="strict",
            validationAction="error",
        )
    except CollectionInvalid:
        db.command(
            "collMod",
            INSPECTIONS,
            validator=INSPECTIONS_SCHEMA,
            validationLevel="strict",
            validationAction="error",
        )


def write_crosswalk_collection(db: Database) -> int:
    """Store the outcome crosswalk in MongoDB too, so pipelines can $lookup it."""
    xw = crosswalks()
    docs = [{"_id": raw, "outcome": cls} for raw, cls in xw.outcome_by_raw.items()]
    db[CROSSWALK].delete_many({})
    if docs:
        db[CROSSWALK].insert_many(docs)
    return len(docs)


def build_silver(db: Database, source: str, log=print) -> dict:
    ensure_inspections(db)
    write_crosswalk_collection(db)
    xw = crosswalks()
    transform = TRANSFORMS[source]
    raw = db[sources()["sources"][source]["raw_collection"]]
    out = db[INSPECTIONS]
    build_id = f"{source}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"

    stats = Counter()
    errors: list[str] = []
    ops: list[ReplaceOne] = []

    def flush():
        nonlocal ops
        if not ops:
            return
        try:
            out.bulk_write(ops, ordered=False)
        except BulkWriteError as exc:
            # Validation failures are counted and sampled instead of killing a 1M-row build.
            for err in exc.details.get("writeErrors", []):
                stats["rejected_by_validator"] += 1
                if len(errors) < 5:
                    errors.append(
                        f"{err['op'].get('_id')}: {str(err.get('errInfo') or err['errmsg'])[:300]}"
                    )
        ops = []

    for row in raw.find({}, batch_size=BATCH):
        stats["raw_rows"] += 1
        doc = transform(row, xw, build_id)
        if doc is None:
            stats["rejected_bad_date"] += 1
            continue
        stats[f"outcome:{doc['outcome']}"] += 1
        ops.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
        if len(ops) >= BATCH:
            flush()
            if stats["raw_rows"] % 100_000 < BATCH:
                log(f"{source}: {stats['raw_rows']:,} rows transformed")
    flush()

    removed = out.delete_many(
        {"source": source, "silver_build_id": {"$ne": build_id}}
    ).deleted_count
    stats["stale_removed"] = removed
    stats["silver_docs"] = out.count_documents({"source": source})
    # Should be 0: _id comes from the raw row hash, so only identical rows could collapse.
    stats["collapsed_duplicate_ids"] = (
        stats["raw_rows"]
        - stats["rejected_bad_date"]
        - stats["rejected_by_validator"]
        - stats["silver_docs"]
    )
    summary = {"source": source, "build_id": build_id, **dict(sorted(stats.items()))}
    if errors:
        summary["validator_error_samples"] = errors
    log(f"{source}: {summary}")
    return summary


def link_teaching_sample(db: Database, log=print) -> dict:
    """Flag archive inspections that appear in MongoDB's 2015 sample.

    The sample's `id` equals the archive's `rec_id`, but rec_id is a case number shared by
    re-inspections, so the join is on (rec_id, calendar day). The sample stores dates as text
    ("Feb 20 2015"), parsed in the pipeline with $dateFromString.
    """
    db[INSPECTIONS].create_index(
        [("source_record_id", 1), ("inspected_at", 1)], name="source_record_id_date"
    )
    db[INSPECTIONS].update_many(
        {"in_teaching_sample": True}, {"$set": {"in_teaching_sample": False}}
    )
    match_stages = [
        {
            "$set": {
                "rid": {"$toString": "$id"},
                "day": {
                    "$dateFromString": {
                        # single-digit days are space-padded: "Sep  8 2015"
                        "dateString": {
                            "$replaceAll": {"input": "$date", "find": "  ", "replacement": " "}
                        },
                        "format": "%b %d %Y",
                        "onError": None,
                    }
                },
            }
        },
        {
            "$lookup": {
                "from": INSPECTIONS,
                "let": {"rid": "$rid", "day": "$day"},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$source_record_id", "$$rid"]}}},
                    {
                        "$match": {
                            "$expr": {
                                "$eq": [
                                    {"$dateTrunc": {"date": "$inspected_at", "unit": "day"}},
                                    "$$day",
                                ]
                            }
                        }
                    },
                    {"$project": {"_id": 1}},
                ],
                "as": "hits",
            }
        },
    ]
    db[RAW_SAMPLE].aggregate(
        [
            *match_stages,
            {"$unwind": "$hits"},
            {"$project": {"_id": "$hits._id", "in_teaching_sample": {"$literal": True}}},
            {
                "$merge": {
                    "into": INSPECTIONS,
                    "on": "_id",
                    "whenMatched": "merge",
                    "whenNotMatched": "discard",
                }
            },
        ]
    )
    sample_rows_matched = next(
        db[RAW_SAMPLE].aggregate(
            [*match_stages, {"$match": {"hits.0": {"$exists": True}}}, {"$count": "n"}]
        ),
        {"n": 0},
    )["n"]
    sample_n = db[RAW_SAMPLE].estimated_document_count()
    summary = {
        "sample_docs": sample_n,
        "sample_docs_found_in_archive": sample_rows_matched,
        "archive_docs_flagged": db[INSPECTIONS].count_documents({"in_teaching_sample": True}),
        "match_rate": round(sample_rows_matched / sample_n, 4) if sample_n else None,
    }
    log(f"2015 sample link: {summary}")
    return summary
