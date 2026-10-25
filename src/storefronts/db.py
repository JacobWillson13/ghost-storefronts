"""MongoDB connection helpers."""

from __future__ import annotations

from pymongo import MongoClient
from pymongo.database import Database

from storefronts.config import settings

# Collection names, in one place so pipelines and notebooks agree.
RAW_ARCHIVE = "raw_archive"
RAW_LIVE = "raw_live"
RAW_SAMPLE = "raw_sample_2015"
INSPECTIONS = "inspections"  # silver: one unified, validated schema
CROSSWALK = "status_crosswalk"


def client(uri: str | None = None) -> MongoClient:
    return MongoClient(uri or settings().mongo_uri, appname="ghost-storefronts")


def get_db(name: str | None = None, uri: str | None = None) -> Database:
    return client(uri)[name or settings().mongo_db]
