"""Adversarial timestamp fixtures run against an isolated MongoDB test database."""

from datetime import datetime

import pytest

from storefronts.gold import build, pipeline


def test_window_and_merge_are_explicit():
    p = pipeline("visits")
    assert any("$setWindowFields" in stage for stage in p)
    assert p[-1]["$merge"]["into"] == "visit_features"
    assert pipeline("status")[-1]["$merge"]["into"] == "business_status"


@pytest.mark.integration
def test_gold_strict_history_and_rebuild(mongo_db, tmp_path):
    def row(key, day, outcome, business="A", storefront=True, name="CHAIN"):
        return {
            "_id": key,
            "business_id": business,
            "inspected_at": datetime(2025, 1, day),
            "source": "live",
            "year": 2025,
            "industry": {"is_storefront": storefront, "group": "retail"},
            "borough": "Queens",
            "business": {"name_norm": name},
            "storefront_key": f"SF:{business}",
            "nta2020": "QN0502",
            "is_closure": outcome == "closure",
            "outcome": outcome,
            "inspection_type": "Patrol",
        }

    docs = [
        row("a", 1, "violation", storefront=False),
        row("b", 2, "closure"),
        row("c", 2, "compliant"),
        row("d", 3, "closure"),
        row("e", 4, "compliant"),
        row("f", 5, "closure"),
    ]
    docs += [row(f"site{i}", 2, "compliant", f"B{i}") for i in range(10)]
    mongo_db.inspections.insert_many(docs)
    build(mongo_db, tmp_path / "audit.json")
    b = mongo_db.visit_features.find_one({"_id": "b"})
    c = mongo_db.visit_features.find_one({"_id": "c"})
    assert b["prior_visits"] == c["prior_visits"] == 1
    assert b["prior_violations"] == 1
    assert b["last_positive"] == datetime(2025, 1, 1)
    assert not b["chain_flag"]  # Tenth site observed at same timestamp is not earlier.
    d = mongo_db.visit_features.find_one({"_id": "d"})
    assert d["prior_visits"] == 3 and d["prior_oob_unresolved"] and d["chain_flag"]
    f = mongo_db.visit_features.find_one({"_id": "f"})
    assert not f["prior_oob_unresolved"]
    assert mongo_db.business_status.find_one({"_id": "A"})["oob_unresolved"]
    mongo_db.visit_features.insert_one({"_id": "stale"})
    build(mongo_db, tmp_path / "audit2.json")
    assert not mongo_db.visit_features.find_one({"_id": "stale"})
    assert mongo_db.inspections.count_documents({}) == len(docs)
