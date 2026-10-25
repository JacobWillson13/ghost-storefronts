from __future__ import annotations

import gzip
import json
import os
import uuid
from pathlib import Path

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

# Rows shaped exactly like the Socrata JSON API returns them (all values are strings).
# The first archive row is the real record 10021-2015-ENFO; the rest are constructed to hit
# specific rules: name variants, a new tenant at the same storefront, a vehicle license,
# an address-only record, a placeholder date, and an unknown result.
ARCHIVE_ROWS = [
    {
        "rec_id": "10021-2015-ENFO",
        "cert_nbr": "09278806",
        "biz_name": "ATLIXCO DELI GROCERY INC.",
        "insp_dt": "2015-02-20T13:50:00.000",
        "insp_rslt": "No Violation Issued",
        "industry": "Cigarette Retail Dealer - 127",
        "boro": "Queens",
        "bldg_nbr": "1712",
        "street": "MENAHAN ST",
        "unit_typ": "STE",
        "unit": "A",
        "city": "RIDGEWOOD",
        "state": "NY",
        "zip": "11385",
        "latitude": "40.703696",
        "longitude": "-73.911525",
        "community_board": "405",
        "council_district": "34",
        "bin": "4082153",
        "bbl": "4034400001",
        "ct2020": "547",
        "nta2020": "QN0502",
    },
    {
        "rec_id": "55501-2019-ENFO",
        "cert_nbr": "01234567",
        "biz_name": "Atlixco Deli & Grocery, Inc",
        "insp_dt": "2019-06-11T10:05:00.000",
        "insp_rslt": "Out of Business",
        "industry": "Grocery-Retail - 808",
        "boro": "Queens",
        "bldg_nbr": "1712",
        "street": "MENAHAN STREET",
        "unit_typ": "SUITE",
        "unit": "A",
        "city": "RIDGEWOOD",
        "state": "NY",
        "zip": "11385",
        "latitude": "40.703696",
        "longitude": "-73.911525",
        "bbl": "4034400001",
        "nta2020": "QN0502",
    },
    {
        "rec_id": "77702-2021-ENFO",
        "cert_nbr": "07777777",
        "biz_name": "CLOUD 9 SMOKE SHOP CORP",
        "insp_dt": "2021-09-01T15:00:00.000",
        "insp_rslt": "Violation Issued",
        "industry": "Electronic Cigarette Dealer",
        "boro": "QUEENS",
        "bldg_nbr": "1712",
        "street": "MENAHAN ST",
        "unit_typ": "STE",
        "unit": "A",
        "zip": "11385",
        "latitude": "40.703696",
        "longitude": "-73.911525",
        "bbl": "4034400001",
        "nta2020": "QN0502",
    },
    {
        "rec_id": "88803-2016-ENFO",
        "cert_nbr": "08888888",
        "biz_name": "BIKE TAXI NYC LLC",
        "insp_dt": "2016-05-05T12:00:00.000",
        "insp_rslt": "Pass",
        "industry": "Pedicab Business - 130",
        "boro": "Manhattan",
    },
    {
        "rec_id": "99904-2017-ENFO",
        "cert_nbr": "09999999",
        "biz_name": "THE CORNER LAUNDROMAT",
        "insp_dt": "2017-03-03T09:00:00.000",
        "insp_rslt": "Warning",
        "industry": "Laundry - 064",
        "boro": "Brooklyn",
        "bldg_nbr": "0221",
        "street": "Flatbush Avenue",
        "zip": "11217",
    },
    {
        "rec_id": "11105-1970-ENFO",
        "cert_nbr": "01111111",
        "biz_name": "PLACEHOLDER",
        "insp_dt": "1970-04-19T00:00:00.000",
        "insp_rslt": "Pass",
        "industry": "Grocery-Retail - 808",
        "boro": "Bronx",
    },
    {
        "rec_id": "22206-2018-ENFO",
        "cert_nbr": "02222222",
        "biz_name": "ODD RESULT LLC",
        "insp_dt": "2018-08-08T08:00:00.000",
        "insp_rslt": "Mystery Result",
        "industry": "Brand New Industry - 999",
        "boro": "Bronx",
        "bbl": "2000000000",
        "latitude": "0",
        "longitude": "0",
    },
]

# rec_id is a case number: one tow-truck case, failed then re-inspected and passed.
ARCHIVE_ROWS += [
    {
        "rec_id": "10127-2015-ATTC",
        "cert_nbr": "03030303",
        "biz_name": "LA ISLA TOWING INC",
        "insp_dt": "2015-07-24T10:00:00.000",
        "insp_rslt": "Fail",
        "industry": "Tow Truck Company - 124",
        "boro": "Bronx",
    },
    {
        "rec_id": "10127-2015-ATTC",
        "cert_nbr": "03030304",
        "biz_name": "LA ISLA TOWING INC",
        "insp_dt": "2015-08-14T10:00:00.000",
        "insp_rslt": "Pass",
        "industry": "Tow Truck Company - 124",
        "boro": "Bronx",
    },
]

LIVE_ROWS = [
    {
        "certificate_of_inspection": "PL-000123",
        "inspection_number": "INS-2024-0001",
        "date_of_occurrence": "2024-03-02T00:00:00.000",
        "business_unique_id": "BA-1",
        "business_name": "Cloud 9 Smoke Shop Corp.",
        "dba_trade_name": "CLOUD NINE",
        "business_category": "Unlicensed Cannabis Retailer",
        "inspection_type": "Tobacco - Adult Inspection",
        "inspection_status": "Violation Issued",
        "address_type": "Address",
        "building_no": "1712",
        "street_1": "MENAHAN ST",
        "unit_type": "STE",
        "apt_suite": "A",
        "city": "RIDGEWOOD",
        "state": "NY",
        "zip_code": "11385",
        "borough": "Queens",
        "bbl": "4034400001",
        "nta": "QN0502",
        "latitude": "40.703696",
        "longitude": "-73.911525",
    },
    {
        "certificate_of_inspection": "PL-000124",
        "inspection_number": "INS-2024-0002",
        "date_of_occurrence": "2024-07-10T00:00:00.000",
        "business_unique_id": "BA-1",
        "business_name": "CLOUD 9 SMOKE SHOP CORP",
        "business_category": "Unlicensed Cannabis Retailer",
        "inspection_type": "Sealing Order Follow-up",
        "inspection_status": "Business Padlocked",
        "building_no": "1712",
        "street_1": "MENAHAN ST",
        "unit_type": "STE",
        "apt_suite": "A",
        "zip_code": "11385",
        "borough": "Queens",
        "bbl": "4034400001",
        "nta": "QN0502",
    },
    {
        "certificate_of_inspection": "PL-000200",
        "inspection_number": "INS-2025-0100",
        "date_of_occurrence": "2025-01-15T00:00:00.000",
        "business_unique_id": "BA-2",
        "business_name": "",
        "dba_trade_name": "Fresh Market Deli",
        "business_category": "Grocery-Retail - 808",
        "inspection_type": "Patrol",
        "inspection_status": "No Violation Issued",
        "building_no": "50",
        "street_1": "W 34 ST",
        "zip_code": "10001",
        "borough": "Manhattan",
        "bbl": "1008350001",
        "nta": "MN0502",
        "latitude": "40.749",
        "longitude": "-73.987",
    },
]


def write_run(data_dir: Path, source: str, rows: list[dict], run_id: str = "20261022") -> Path:
    run = data_dir / "raw" / source / run_id
    run.mkdir(parents=True, exist_ok=True)
    with gzip.open(run / "page_00000.ndjson.gz", "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    (run / "manifest.json").write_text(
        json.dumps(
            {"source": source, "pages": {"0": len(rows)}, "complete": True, "rows": len(rows)}
        )
    )
    return run


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    write_run(tmp_path, "archive", ARCHIVE_ROWS)
    write_run(tmp_path, "live", LIVE_ROWS)
    return tmp_path


@pytest.fixture
def mongo_db():
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27018/?directConnection=true")
    client = MongoClient(uri, serverSelectionTimeoutMS=1500)
    try:
        client.admin.command("ping")
    except PyMongoError:
        pytest.skip(f"MongoDB not reachable at {uri}")
    name = f"storefronts_test_{uuid.uuid4().hex[:8]}"
    yield client[name]
    client.drop_database(name)
    client.close()
