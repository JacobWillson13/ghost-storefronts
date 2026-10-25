"""Bronze layer: load downloaded pages into raw collections, untouched apart from _id and _meta.

_id is a SHA-1 of the row's canonical JSON, so loading the same snapshot twice is a no-op.
After a load, rows from older snapshots are removed, so each raw collection mirrors exactly
one snapshot of the source (recorded in _meta.run_id).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pymongo import ReplaceOne
from pymongo.database import Database

from storefronts.config import sources
from storefronts.download import iter_rows, latest_run_dir

BATCH = 2000


def row_hash(row: dict) -> str:
    return hashlib.sha1(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_run(db: Database, source: str, run: Path | None = None, log=print) -> dict:
    run = run or latest_run_dir(source)
    if run is None:
        raise FileNotFoundError(f"No finished download for {source!r}. Run the download first.")
    manifest = json.loads((run / "manifest.json").read_text())
    if not manifest.get("complete"):
        raise RuntimeError(f"Download {run} is incomplete; re-run the download to finish it.")

    coll = db[sources()["sources"][source]["raw_collection"]]
    loaded_at = datetime.now(UTC)
    ops, n_rows, upserted, matched = [], 0, 0, 0

    def flush():
        nonlocal ops, upserted, matched
        if ops:
            res = coll.bulk_write(ops, ordered=False)
            upserted += res.upserted_count
            matched += res.matched_count
            ops = []

    for page, row in iter_rows(run):
        h = row_hash(row)
        doc = {
            **row,
            "_id": h,
            "_meta": {
                "source": source,
                "run_id": run.name,
                "page": page,
                "loaded_at": loaded_at,
            },
        }
        ops.append(ReplaceOne({"_id": h}, doc, upsert=True))
        n_rows += 1
        if len(ops) >= BATCH:
            flush()
            if n_rows % 100_000 < BATCH:
                log(f"{source}: {n_rows:,} rows loaded")
    flush()

    stale = coll.delete_many({"_meta.run_id": {"$ne": run.name}}).deleted_count
    in_run = coll.count_documents({"_meta.run_id": run.name})
    summary = {
        "source": source,
        "run_id": run.name,
        "rows_in_files": n_rows,
        "new_docs": upserted,
        "replaced_docs": matched,
        "stale_removed": stale,
        "collection_count": in_run,
        # identical rows inside one snapshot collapse to one document
        "exact_duplicate_rows": n_rows - in_run,
    }
    log(f"{source}: {summary}")
    return summary


def copy_sample(db: Database, log=print) -> int:
    """Copy sample_training.inspections into this database with $out, so $lookup can reach it.

    $lookup cannot join across databases, so the 2015 snapshot is copied next to the
    city data. This collection is used only for the lineage check, never for analysis, because
    every one of its rows also exists in the city archive.
    """
    cfg = sources()["sources"]["sample_2015"]
    src = db.client[cfg["source_db"]][cfg["source_collection"]]
    if src.estimated_document_count() == 0:
        raise RuntimeError(
            "sample_training.inspections is empty. Run mongorestore on sampledata.archive first."
        )
    src.aggregate(
        [
            {"$set": {"_meta": {"source": "sample_2015", "copied_at": "$$NOW"}}},
            {"$out": {"db": db.name, "coll": cfg["raw_collection"]}},
        ]
    )
    n = db[cfg["raw_collection"]].estimated_document_count()
    log(f"sample_2015: copied {n:,} docs into {db.name}.{cfg['raw_collection']}")
    return n
