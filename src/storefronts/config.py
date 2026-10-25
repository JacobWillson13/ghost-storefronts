"""Settings and config-file loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    mongo_uri: str = field(
        default_factory=lambda: os.getenv(
            "MONGO_URI", "mongodb://localhost:27018/?directConnection=true"
        )
    )
    mongo_db: str = field(default_factory=lambda: os.getenv("MONGO_DB", "storefronts"))
    socrata_app_token: str | None = field(
        default_factory=lambda: os.getenv("SOCRATA_APP_TOKEN") or None
    )
    data_dir: Path = field(
        default_factory=lambda: (REPO_ROOT / os.getenv("DATA_DIR", "data")).resolve()
    )
    archive_since: str = field(default_factory=lambda: os.getenv("ARCHIVE_SINCE", "2010-01-01"))


def settings() -> Settings:
    return Settings()


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name) as fh:
        return yaml.safe_load(fh)


@lru_cache
def sources() -> dict:
    return _load_yaml("sources.yaml")


@dataclass(frozen=True)
class Crosswalks:
    outcome_by_raw: dict[str, str]
    industry_renames: dict[str, str]
    industry_group: dict[str, str]
    default_group: str
    non_storefront: frozenset[str]

    def outcome(self, raw: str | None) -> str:
        if not raw:
            return "missing"
        return self.outcome_by_raw.get(raw.strip().casefold(), "unmapped")


@lru_cache
def crosswalks() -> Crosswalks:
    outcomes = _load_yaml("outcome_crosswalk.yaml")
    industries = _load_yaml("industry_crosswalk.yaml")
    outcome_by_raw = {raw.strip().casefold(): cls for cls, raws in outcomes.items() for raw in raws}
    industry_group = {
        label.casefold(): group
        for group, labels in industries["groups"].items()
        for label in labels
    }
    return Crosswalks(
        outcome_by_raw=outcome_by_raw,
        industry_renames={k.casefold(): v for k, v in industries.get("renames", {}).items()},
        industry_group=industry_group,
        default_group=industries.get("default_group", "other"),
        non_storefront=frozenset(x.casefold() for x in industries.get("non_storefront", [])),
    )
