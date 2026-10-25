"""Command line entry point: `uv run storefronts --help`."""

from __future__ import annotations

import json

import typer

from storefronts import download as dl
from storefronts import geo, indexes, link, load_raw, profile, silver
from storefronts.config import settings
from storefronts.db import INSPECTIONS, get_db

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)

SOURCES = ["archive", "live"]


def _pick(source: str) -> list[str]:
    if source == "all":
        return SOURCES
    if source not in SOURCES:
        raise typer.BadParameter(f"source must be one of {SOURCES + ['all']}")
    return [source]


@app.command()
def ping() -> None:
    """Check the MongoDB connection."""
    db = get_db()
    info = db.client.server_info()
    typer.echo(f"MongoDB {info['version']} at {settings().mongo_uri} (db: {db.name})")


@app.command()
def download(
    source: str = typer.Argument("all", help="archive, live, or all"),
    max_pages: int = typer.Option(None, help="Stop after N pages (for a quick test pull)."),
) -> None:
    """Pull inspections from NYC Open Data into data/raw/<source>/<date>/."""
    for s in _pick(source):
        since = settings().archive_since if s == "archive" else None
        m = dl.download_source(s, since=since, max_pages=max_pages)
        typer.echo(
            f"{s}: {m.get('rows', sum(m['pages'].values())):,} rows, complete={m['complete']}"
        )


@app.command()
def boundaries() -> None:
    """Download 2020 NTA neighborhood boundaries (GeoJSON) for neighborhood maps."""
    typer.echo(f"wrote {dl.download_boundaries()}")


@app.command("load-raw")
def load_raw_cmd(source: str = typer.Argument("all", help="archive, live, or all")) -> None:
    """Load the latest finished download into raw_archive / raw_live."""
    db = get_db()
    for s in _pick(source):
        load_raw.load_run(db, s)


@app.command("copy-sample")
def copy_sample() -> None:
    """Copy sample_training.inspections (restored with mongorestore) into this database."""
    load_raw.copy_sample(get_db())


@app.command("build-silver")
def build_silver(source: str = typer.Argument("all", help="archive, live, or all")) -> None:
    """Transform raw collections into the validated `inspections` collection."""
    db = get_db()
    for s in _pick(source):
        silver.build_silver(db, s)


@app.command("link-sample")
def link_sample() -> None:
    """Flag archive inspections that appear in the 2015 sample ($merge join)."""
    silver.link_teaching_sample(get_db())


@app.command("create-indexes")
def create_indexes() -> None:
    """Create all secondary indexes."""
    indexes.create_indexes(get_db())


@app.command("load-nta")
def load_nta() -> None:
    """Load 2020 NTA polygons (from `boundaries`) into the nta2020 collection."""
    geo.load_nta(get_db())


@app.command("assign-nta")
def assign_nta() -> None:
    """Tag every inspection with its 2020 NTA by point in polygon. Re-run after build-silver."""
    geo.assign_nta(get_db())


@app.command("link-switch")
def link_switch() -> None:
    """Link businesses across the 2023 system switch (sets business_id). Re-run after silver."""
    link.link_across_switch(get_db())


@app.command("profile")
def profile_cmd() -> None:
    """Write reports/data_quality.md."""
    typer.echo(f"wrote {profile.write_report(get_db())}")


@app.command()
def status() -> None:
    """Document counts for every collection in the project database."""
    db = get_db()
    counts = {
        name: db[name].estimated_document_count() for name in sorted(db.list_collection_names())
    }
    typer.echo(json.dumps(counts, indent=2))
    if INSPECTIONS in counts:
        sample = db[INSPECTIONS].find_one({}, {"_id": 1, "business_key": 1, "outcome": 1})
        typer.echo(f"sample silver doc: {sample}")


@app.command("gold")
def gold_cmd() -> None:
    """Rebuild only gold collections from silver and run the leakage audit."""
    from storefronts.gold import build

    typer.echo(json.dumps(build(), indent=2, default=str))


@app.command("exports")
def exports_cmd() -> None:
    """Export dashboard CSVs after the executed notebooks."""
    from storefronts.exports import export

    typer.echo(json.dumps(export(), indent=2))


if __name__ == "__main__":
    app()
