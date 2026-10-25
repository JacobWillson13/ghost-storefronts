from datetime import datetime

import pytest

from storefronts import normalize as nz
from storefronts.config import crosswalks


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ATLIXCO DELI GROCERY INC.", "ATLIXCO DELI GROCERY"),
        ("Atlixco Deli Grocery, Inc", "ATLIXCO DELI GROCERY"),
        ("Joe's Deli L.L.C.", "JOES DELI"),
        ("JOE’S DELI LLC", "JOES DELI"),
        ("Smith & Sons Corp Inc", "SMITH SONS"),
        ("Atlixco Deli & Grocery, Inc", "ATLIXCO DELI GROCERY"),
        ("SMITH AND SONS", "SMITH SONS"),
        ("THE CORNER LAUNDROMAT", "CORNER LAUNDROMAT"),
        ("ABC HOLDINGS CORP DBA CLOUD 9", "ABC HOLDINGS"),
        ("INC", "INC"),  # never strip a name down to nothing
        ("", None),
        (None, None),
    ],
)
def test_normalize_name(raw, expected):
    assert nz.normalize_name(raw) == expected


@pytest.mark.parametrize(
    "unit_type, unit, expected",
    [
        ("STE", "A", "A"),
        ("SUITE", "a", "A"),
        (None, "Store #3", "3"),
        (None, None, ""),
        ("FL", "1ST", "1ST"),
    ],
)
def test_normalize_unit(unit_type, unit, expected):
    assert nz.normalize_unit(unit_type, unit) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("4034400001", "4034400001"),
        ("4034400001.0", "4034400001"),
        ("2000000000", None),
        ("6034400001", None),
        ("123", None),
        (None, None),
    ],
)
def test_normalize_bbl(raw, expected):
    assert nz.normalize_bbl(raw) == expected


def test_street_and_building():
    assert nz.normalize_street("Menahan Street") == nz.normalize_street("MENAHAN ST")
    assert nz.normalize_street("West 34th Avenue") == "W 34TH AVE"
    assert nz.normalize_building("0221") == "221"


def test_borough_falls_back_to_bbl():
    assert nz.normalize_borough("QUEENS") == "Queens"
    assert nz.normalize_borough(None, "3012340001") == "Brooklyn"
    assert nz.normalize_borough("nowhere") is None


def test_keys():
    sf = nz.storefront_key("4034400001", "A", "11385", "1712", "MENAHAN ST")
    assert sf == "BBL:4034400001|A"
    assert nz.storefront_key(None, "", "11217", "221", "FLATBUSH AVE") == (
        "ADDR:11217|221|FLATBUSH AVE|"
    )
    assert nz.storefront_key(None, "", None, "221", "FLATBUSH AVE") is None
    assert nz.business_key(sf, "ATLIXCO DELI GROCERY") == "BBL:4034400001|A|ATLIXCO DELI GROCERY"
    assert nz.business_key(sf, None) is None


def test_dates():
    assert nz.parse_socrata_ts("2015-02-20T13:50:00.000") == datetime(2015, 2, 20, 13, 50)
    assert nz.parse_socrata_ts("garbage") is None
    assert nz.parse_sample_date("Feb 20 2015") == datetime(2015, 2, 20)


def test_geo_point():
    assert nz.geo_point("40.703696", "-73.911525") == {
        "type": "Point",
        "coordinates": [-73.911525, 40.703696],
    }
    assert nz.geo_point("0", "0") is None
    assert nz.geo_point(None, None) is None
    # the sample `zips` collection's sign-flipped longitudes would land in Central Asia
    assert nz.geo_point("40.7", "73.9") is None


def test_industry_classification():
    xw = crosswalks()
    tob = nz.classify_industry("Cigarette Retail Dealer - 127", xw)
    assert tob["label"] == "Tobacco Retail Dealer"
    assert tob["code"] == "127"
    assert tob["group"] == "tobacco_vape_cannabis"
    assert tob["is_storefront"] is True
    assert nz.classify_industry("Pedicab Business - 130", xw)["is_storefront"] is False
    assert nz.classify_industry("Laundry - 064", xw)["label"] == "Retail Laundry"
    assert nz.classify_industry("Brand New Industry - 999", xw)["group"] == "other"
    assert nz.classify_industry(None, xw)["group"] == "missing"


def test_outcome_crosswalk():
    xw = crosswalks()
    assert xw.outcome("Out of Business") == "out_of_business"
    assert xw.outcome("out of business ") == "out_of_business"
    assert xw.outcome("Business Padlocked") == "padlocked"
    assert xw.outcome("No Evidence of Activity") == "no_activity"
    assert xw.outcome("Mystery Result") == "unmapped"
    assert xw.outcome(None) == "missing"


def test_non_string_inputs_do_not_crash():
    assert nz.normalize_street(42) == "42"
    assert nz.normalize_name(7) == "7"
    assert nz.split_industry(808) == ("808", None)


def test_crosswalk_additions_from_real_data():
    xw = crosswalks()
    assert xw.outcome("EWAR - ECB Warning Issued") == "warning"
    assert xw.outcome("Unidentified Vendor/Business") == "unable"
    fire = nz.classify_industry("Secondhand Dealer - Firearm - 006A", xw)
    assert (fire["label"], fire["code"], fire["group"]) == (
        "Secondhand Dealer - Firearm",
        "006A",
        "secondhand_pawn",
    )
    assert nz.classify_industry("Laundries - 064", xw)["label"] == "Retail Laundry"
    assert nz.classify_industry("Air Condtioning Law", xw)["group"] == "product_rule_checks"
    assert nz.classify_industry("Tow Truck Driver", xw)["is_storefront"] is False
