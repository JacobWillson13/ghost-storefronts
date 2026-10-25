"""End to end against a real MongoDB: raw load -> silver -> lineage link -> indexes -> profile.

Skipped automatically when MONGO_URI is not reachable.
"""

import json

import pytest
from pymongo.errors import WriteError

from storefronts import geo, indexes, link, load_raw, profile, silver
from storefronts.db import INSPECTIONS, RAW_ARCHIVE, RAW_LIVE, RAW_SAMPLE

pytestmark = pytest.mark.integration
quiet = {"log": lambda *_: None}


def _build_all(db, data_dir):
    for s in ("archive", "live"):
        load_raw.load_run(db, s, run=data_dir / "raw" / s / "20261022", **quiet)
    return {s: silver.build_silver(db, s, **quiet) for s in ("archive", "live")}


def test_end_to_end(mongo_db, data_dir, tmp_path):
    db = mongo_db
    stats = _build_all(db, data_dir)
    ins = db[INSPECTIONS]

    def rec(rid):
        return ins.find_one({"source_record_id": rid})

    assert db[RAW_ARCHIVE].count_documents({}) == 9
    assert db[RAW_LIVE].count_documents({}) == 3
    assert stats["archive"]["rejected_bad_date"] == 1  # the 1970 placeholder
    assert stats["archive"].get("rejected_by_validator", 0) == 0
    assert stats["archive"]["collapsed_duplicate_ids"] == 0
    assert ins.count_documents({"source": "archive"}) == 8
    assert ins.count_documents({"source": "live"}) == 3

    first = rec("10021-2015-ENFO")
    closed = rec("55501-2019-ENFO")
    vape = rec("77702-2021-ENFO")

    # Name and street variants resolve to the same business at the same storefront.
    assert first["business_key"] == closed["business_key"]
    assert first["storefront_key"] == vape["storefront_key"] == "BBL:4034400001|A"
    assert first["business_key"] != vape["business_key"]  # a new tenant, not a rebrand
    assert first["industry"]["group"] == "tobacco_vape_cannabis"
    assert first["certificate_number"] == "09278806"  # leading zero kept
    assert first["location"]["coordinates"] == [-73.911525, 40.703696]
    assert closed["is_closure"] is True and first["is_closure"] is False

    # The same shop is found again across the 2023 system switch.
    live_keys = set(ins.distinct("business_key", {"source": "live"}))
    assert vape["business_key"] in live_keys
    padlock = ins.find_one({"source": "live", "is_padlock": True})
    assert padlock["industry"]["label"] == "Unlicensed Cannabis Retailer"
    assert padlock["is_closure"] is False  # padlocks are tracked separately

    # DBA name is used when the legal name is blank.
    deli = rec("INS-2025-0100")
    assert deli["business"]["name_norm"] == "FRESH MARKET DELI"

    assert rec("88803-2016-ENFO")["industry"]["is_storefront"] is False
    # rec_id is a case number: the failed inspection and the re-inspection both survive.
    assert ins.count_documents({"source_record_id": "10127-2015-ATTC"}) == 2
    addr = rec("99904-2017-ENFO")
    assert addr["storefront_key"] == "ADDR:11217|221|FLATBUSH AVE|"
    assert addr["industry"]["label"] == "Retail Laundry"
    odd = rec("22206-2018-ENFO")
    assert odd["outcome"] == "unmapped" and odd["bbl"] is None and "location" not in odd

    # Idempotent: re-loading and re-building changes nothing.
    _build_all(db, data_dir)
    assert ins.count_documents({}) == 11
    assert db[RAW_ARCHIVE].count_documents({}) == 9

    # Validator rejects documents that break the silver contract.
    with pytest.raises(WriteError):
        ins.insert_one({"_id": "archive:bad", "source": "archive", "year": "2015"})

    # Lineage: flag archive rows present in the 2015 sample, joined on (rec_id, day).
    db[RAW_SAMPLE].insert_many(
        [
            {"id": "10021-2015-ENFO", "date": "Feb 20 2015", "certificate_number": 9278806},
            {"id": "10127-2015-ATTC", "date": "Aug 14 2015", "certificate_number": 3030304},
            {"id": "NOT-IN-ARCHIVE", "date": "Jan 01 2015", "certificate_number": 1},
            {"id": "99904-2017-ENFO", "date": "Mar  3 2017", "certificate_number": 9999999},
        ]
    )
    sample_link = silver.link_teaching_sample(db, **quiet)
    assert sample_link["sample_docs_found_in_archive"] == 3  # incl. a space-padded date
    assert sample_link["archive_docs_flagged"] == 3
    assert rec("10021-2015-ENFO")["in_teaching_sample"] is True
    flagged = ins.find_one({"source_record_id": "10127-2015-ATTC", "in_teaching_sample": True})
    assert flagged["result_raw"] == "Pass"  # only the re-inspection on the sample's date
    assert ins.count_documents({}) == 11  # whenNotMatched: discard

    made = indexes.create_indexes(db, **quiet)
    assert "location_2dsphere" in made[INSPECTIONS]
    near = list(
        ins.find(
            {
                "location": {
                    "$near": {
                        "$geometry": {"type": "Point", "coordinates": [-73.9115, 40.7037]},
                        "$maxDistance": 200,
                    }
                }
            }
        )
    )
    assert len(near) == 4  # three archive rows plus one live row carry Menahan St coordinates

    # Neighborhoods: a small polygon around Menahan St, deliberately self-intersecting (bowtie)
    # in its second ring to prove geometry repair works.
    box = [
        [-73.913, 40.7025],
        [-73.910, 40.7025],
        [-73.910, 40.705],
        [-73.913, 40.705],
        [-73.913, 40.7025],
    ]
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "nta2020": "QN0502",
                    "ntaname": "Ridgewood",
                    "boroname": "Queens",
                    "ntatype": "0",
                },
                "geometry": {"type": "Polygon", "coordinates": [box]},
            },
            {
                "type": "Feature",
                "properties": {
                    "nta2020": "MN0502",
                    "ntaname": "Midtown",
                    "boroname": "Manhattan",
                    "ntatype": "0",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-73.99, 40.74],
                            [-73.98, 40.76],
                            [-73.98, 40.74],
                            [-73.99, 40.76],
                            [-73.99, 40.74],
                        ]
                    ],
                },
            },
        ],
    }
    gj = tmp_path / "nta.geojson"
    gj.write_text(json.dumps(fc))
    assert geo.load_nta(db, path=gj, **quiet) == 2
    nta = geo.assign_nta(db, **quiet)
    assert rec("10021-2015-ENFO")["nta2020"] == "QN0502"
    assert rec("10021-2015-ENFO")["nta2020_name"] == "Ridgewood"
    assert nta["archive_agreement_with_source_nta"] == 1.0

    # Cross-switch linking: no archive business here is recent enough to link, so business_id
    # falls back to business_key everywhere. Link rules are unit-tested in test_link.py.
    summary = link.link_across_switch(db, **quiet)
    assert summary["open_archive_businesses_since_2022"] == 0  # fixtures end in 2021
    assert ins.count_documents({"business_id": {"$exists": False}}) == 0
    assert rec("77702-2021-ENFO")["business_id"] == rec("77702-2021-ENFO")["business_key"]

    report = profile.write_report(db, out_dir=tmp_path)
    text = report.read_text()
    assert "Mystery Result" in text
    assert "Brand New Industry" in text
