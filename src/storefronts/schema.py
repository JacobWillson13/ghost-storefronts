"""$jsonSchema validator for the silver `inspections` collection."""

from __future__ import annotations

OUTCOMES = [
    "out_of_business",
    "padlocked",
    "no_activity",
    "closed_at_visit",
    "violation",
    "warning",
    "compliant",
    "unable",
    "administrative",
    "unmapped",
    "missing",
]

STR_OR_NULL = {"bsonType": ["string", "null"]}

INSPECTIONS_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "title": "Unified DCWP inspection (silver)",
        "required": [
            "_id",
            "source",
            "schema_version",
            "inspected_at",
            "year",
            "result_raw",
            "outcome",
            "is_closure",
            "business",
            "industry",
            "address",
            "in_teaching_sample",
            "silver_build_id",
        ],
        "properties": {
            "_id": {"bsonType": "string", "pattern": "^(archive|live):"},
            "source": {"enum": ["archive", "live"]},
            "schema_version": {"bsonType": "int", "minimum": 1, "maximum": 2},
            "source_record_id": STR_OR_NULL,
            "raw_id": {"bsonType": "string"},
            "certificate_number": STR_OR_NULL,
            "inspection_number": STR_OR_NULL,
            "business_unique_id": STR_OR_NULL,
            "license_number": STR_OR_NULL,
            "inspected_at": {"bsonType": "date"},
            "year": {"bsonType": "int", "minimum": 1990, "maximum": 2100},
            "inspection_type": STR_OR_NULL,
            "result_raw": {"bsonType": "string"},
            "outcome": {"enum": OUTCOMES},
            "is_closure": {"bsonType": "bool"},
            "is_padlock": {"bsonType": "bool"},
            "business": {
                "bsonType": "object",
                "required": ["name_norm"],
                "properties": {
                    "name_raw": STR_OR_NULL,
                    "dba_raw": STR_OR_NULL,
                    "name_norm": STR_OR_NULL,
                },
            },
            "industry": {
                "bsonType": "object",
                "required": ["label", "group", "is_storefront"],
                "properties": {
                    "raw": STR_OR_NULL,
                    "label": STR_OR_NULL,
                    "code": STR_OR_NULL,
                    "group": {"bsonType": "string"},
                    "is_storefront": {"bsonType": "bool"},
                },
            },
            "address": {"bsonType": "object"},
            "borough": {
                "enum": ["Manhattan", "Bronx", "Brooklyn", "Queens", "Staten Island", None]
            },
            "nta": STR_OR_NULL,
            "bbl": {"bsonType": ["string", "null"], "pattern": "^[1-5][0-9]{9}$"},
            "location": {
                "bsonType": "object",
                "required": ["type", "coordinates"],
                "properties": {
                    "type": {"enum": ["Point"]},
                    "coordinates": {"bsonType": "array", "minItems": 2, "maxItems": 2},
                },
            },
            "storefront_key": STR_OR_NULL,
            "business_key": STR_OR_NULL,
            "in_teaching_sample": {"bsonType": "bool"},
            "silver_build_id": {"bsonType": "string"},
        },
    }
}
