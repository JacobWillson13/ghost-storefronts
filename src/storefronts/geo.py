"""Neighborhoods: load 2020 NTA polygons and tag every inspection by point in polygon.

Why: the archive carries 2020 NTA codes (e.g. QN0502) but the live system carries 2010 codes
(e.g. MN17), so the two cannot be compared or mapped together. Assigning NTA 2020 from each
inspection's coordinates gives one consistent neighborhood field, `nta2020`.

Method: one `$geoWithin` updateMany per polygon (262 of them), served by the 2dsphere index on
`inspections.location`. Polygons are repaired with shapely first, because MongoDB rejects
self-intersecting rings.
"""

from __future__ import annotations

import json
from pathlib import Path

from pymongo import GEOSPHERE, UpdateMany
from pymongo.database import Database
from shapely.geometry import mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.validation import make_valid

from storefronts.config import settings
from storefronts.db import INSPECTIONS

NTA = "nta2020"


def _prop(props: dict, *names: str):
    lower = {k.lower(): v for k, v in props.items()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def _clean_geometry(geom: dict) -> dict:
    g = make_valid(shape(geom))
    polys = [p for p in getattr(g, "geoms", [g]) if p.geom_type in ("Polygon", "MultiPolygon")]
    g = unary_union(polys)
    g = orient(g) if g.geom_type == "Polygon" else type(g)([orient(p) for p in g.geoms])
    return mapping(g)


def load_nta(db: Database, path: Path | None = None, log=print) -> int:
    path = path or settings().data_dir / "boundaries" / "nta2020.geojson"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run `make boundaries` first.")
    fc = json.loads(path.read_text())
    docs = []
    for f in fc["features"]:
        p = f.get("properties") or {}
        code = _prop(p, "nta2020", "ntacode", "nta_code")
        if not code or not f.get("geometry"):
            continue
        docs.append(
            {
                "_id": code,
                "name": _prop(p, "ntaname", "nta_name"),
                "borough": _prop(p, "boroname", "borough"),
                "nta_type": _prop(p, "ntatype"),  # 0 = residential; others are parks, airports...
                "cdta2020": _prop(p, "cdta2020"),
                "geometry": _clean_geometry(f["geometry"]),
            }
        )
    coll = db[NTA]
    coll.delete_many({})
    coll.insert_many(docs)
    coll.create_index([("geometry", GEOSPHERE)], name="geometry_2dsphere")
    log(f"{NTA}: loaded {len(docs)} neighborhoods")
    return len(docs)


def assign_nta(db: Database, log=print) -> dict:
    ins = db[INSPECTIONS]
    ins.create_index([("location", GEOSPHERE)], name="location_2dsphere")
    ins.update_many({}, {"$unset": {"nta2020": "", "nta2020_name": ""}})
    ops = [
        UpdateMany(
            {"location": {"$geoWithin": {"$geometry": n["geometry"]}}},
            {"$set": {"nta2020": n["_id"], "nta2020_name": n["name"]}},
        )
        for n in db[NTA].find({}, {"geometry": 1, "name": 1})
    ]
    if not ops:
        raise RuntimeError("No NTA polygons loaded. Run `storefronts load-nta` first.")
    res = ins.bulk_write(ops, ordered=False)
    with_loc = ins.count_documents({"location": {"$exists": True}})
    assigned = ins.count_documents({"nta2020": {"$exists": True}})
    # How often the agency's own NTA field agrees, for the archive where both are 2020 codes.
    archive_with_both = ins.count_documents(
        {"source": "archive", "nta": {"$ne": None}, "nta2020": {"$exists": True}}
    )
    agree = next(
        ins.aggregate(
            [
                {
                    "$match": {
                        "source": "archive",
                        "nta": {"$ne": None},
                        "nta2020": {"$exists": True},
                    }
                },
                {"$match": {"$expr": {"$eq": ["$nta", "$nta2020"]}}},
                {"$count": "n"},
            ]
        ),
        {"n": 0},
    )["n"]
    summary = {
        "polygons": len(ops),
        "docs_updated": res.modified_count,
        "with_location": with_loc,
        "assigned": assigned,
        "assigned_share": round(assigned / with_loc, 4) if with_loc else None,
        "archive_agreement_with_source_nta": (
            round(agree / archive_with_both, 4) if archive_with_both else None
        ),
    }
    log(f"nta tagging: {summary}")
    return summary
