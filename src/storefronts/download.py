"""Download DCWP inspections from the NYC Open Data (Socrata) API.

Each run writes gzipped NDJSON pages to data/raw/<source>/<YYYYMMDD>/ plus a manifest.
Re-running on the same day resumes from the last finished page; a new day starts a fresh
snapshot, so the live dataset's edits never get mixed with an older pull.
"""

from __future__ import annotations

import gzip
import json
import time
from datetime import date
from pathlib import Path

import httpx

from storefronts.config import settings, sources

RETRY_STATUS = {429, 500, 502, 503, 504}


def run_dir(source: str, data_dir: Path | None = None, run_id: str | None = None) -> Path:
    base = (data_dir or settings().data_dir) / "raw" / source
    return base / (run_id or date.today().strftime("%Y%m%d"))


def latest_run_dir(source: str, data_dir: Path | None = None) -> Path | None:
    base = (data_dir or settings().data_dir) / "raw" / source
    runs = sorted(p for p in base.glob("*") if (p / "manifest.json").exists())
    return runs[-1] if runs else None


def _get_with_retry(client: httpx.Client, url: str, params: dict, attempts: int = 6) -> list:
    for i in range(attempts):
        try:
            resp = client.get(url, params=params)
            if resp.status_code in RETRY_STATUS:
                raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
            resp.raise_for_status()
            return resp.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and (
                exc.response.status_code not in RETRY_STATUS
            ):
                raise
            if i == attempts - 1:
                raise
            time.sleep(min(2**i, 30))
    raise RuntimeError("unreachable")


def download_source(
    source: str,
    *,
    since: str | None = None,
    page_size: int | None = None,
    max_pages: int | None = None,
    data_dir: Path | None = None,
    run_id: str | None = None,
    http: httpx.Client | None = None,
    log=print,
) -> dict:
    cfg = sources()
    src = cfg["sources"][source]
    page_size = page_size or cfg["page_size"]
    url = f"{cfg['socrata_base']}/{src['dataset_id']}.json"

    out = run_dir(source, data_dir, run_id)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.exists()
        else {
            "source": source,
            "dataset_id": src["dataset_id"],
            "url": url,
            "since": since,
            "page_size": page_size,
            "pages": {},
            "complete": False,
        }
    )
    if manifest["complete"]:
        log(f"{source}: run {out.name} already complete ({manifest['rows']:,} rows)")
        return manifest

    params_base = {"$limit": page_size, "$order": ":id"}
    if since:
        params_base["$where"] = f"{src['date_field']} >= '{since}T00:00:00'"

    headers = {}
    token = settings().socrata_app_token
    if token:
        headers["X-App-Token"] = token

    own_client = http is None
    http = http or httpx.Client(timeout=120, headers=headers)
    try:
        page = len(manifest["pages"])
        while max_pages is None or page < max_pages:
            rows = _get_with_retry(http, url, {**params_base, "$offset": page * page_size})
            path = out / f"page_{page:05d}.ndjson.gz"
            tmp = path.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, separators=(",", ":")) + "\n")
            tmp.rename(path)
            manifest["pages"][str(page)] = len(rows)
            manifest_path.write_text(json.dumps(manifest, indent=2))
            total = sum(manifest["pages"].values())
            log(f"{source}: page {page} -> {len(rows):,} rows (total {total:,})")
            page += 1
            if len(rows) < page_size:
                manifest["complete"] = True
                break
    finally:
        if own_client:
            http.close()

    manifest["rows"] = sum(manifest["pages"].values())
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def download_boundaries(data_dir: Path | None = None, http: httpx.Client | None = None) -> Path:
    url = sources()["boundaries"]["nta2020"]["url"]
    out = (data_dir or settings().data_dir) / "boundaries" / "nta2020.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    own = http is None
    http = http or httpx.Client(timeout=300, follow_redirects=True)
    try:
        resp = http.get(url)
        resp.raise_for_status()
        out.write_bytes(resp.content)
    finally:
        if own:
            http.close()
    return out


def iter_rows(run: Path):
    """Yield (page_number, row) from a finished run directory, in page order."""
    for path in sorted(run.glob("page_*.ndjson.gz")):
        page = int(path.stem.split("_")[1].split(".")[0])
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield page, json.loads(line)
