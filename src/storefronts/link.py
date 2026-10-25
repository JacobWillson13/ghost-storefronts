"""Link businesses across the June 2023 record-system switch.

The exact business_key (storefront + normalized name) finds about 77% of open archive businesses
again in the live system. The rest split because the two systems record units, legal names or
lots differently. Without a fix, every split business looks like a closure plus a new tenant
right at the switch, which would fake a turnover spike exactly where the study looks.

Method (deterministic, every link carries the rule that made it):
  1. Candidates: archive businesses still open and seen since 2022, and live businesses first
     seen by the end of 2024, with no exact-key match.
  2. Block on lot (BBL), or on zip + building + street when there is no lot.
  3. Score each pair in a block and accept, best score first, one-to-one:
       name_strong   name similarity >= 0.85
       name_unit     name similarity >= 0.60 and same unit
       sole_tenant   the only unmatched business on each side at the same storefront, same
                     industry, first live visit within 365 days of the last archive visit
  4. Write `business_links` and set `business_id` on every inspection: the archive key for linked
     live businesses, otherwise the business's own key.
`sole_tenant` is the loosest rule; the analysis reports results with and without it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher

from pymongo import UpdateMany
from pymongo.database import Database

from storefronts.db import INSPECTIONS

LINKS = "business_links"
ARCHIVE_SINCE = datetime(2022, 1, 1)
LIVE_UNTIL = datetime(2025, 1, 1)


# Words that say what a shop is, not which shop it is. Extended at run time with any token that
# appears in many names (see generic_tokens), so "DELI GROCERY" never links two different delis.
BASE_GENERIC = frozenset(
    [
        "DELI",
        "GROCERY",
        "GROCERIES",
        "FOOD",
        "FOODS",
        "MARKET",
        "MINI",
        "MART",
        "SUPERMARKET",
        "CONVENIENCE",
        "STORE",
        "STORES",
        "SHOP",
        "SMOKE",
        "VAPE",
        "TOBACCO",
        "CIGAR",
        "NEWS",
        "CANDY",
        "CARD",
        "CARDS",
        "NYC",
        "NY",
        "NEW",
        "YORK",
        "BROOKLYN",
        "BRONX",
        "QUEENS",
        "MANHATTAN",
        "STATEN",
        "ISLAND",
        "CENTER",
        "CENTRE",
        "ENTERPRISES",
        "ENTERPRISE",
        "GROUP",
        "TRADING",
        "SERVICES",
        "SERVICE",
        "NAILS",
        "NAIL",
        "SALON",
        "BEAUTY",
        "BARBER",
        "BARBERSHOP",
        "HAIR",
        "LAUNDROMAT",
        "LAUNDRY",
        "CLEANERS",
        "WIRELESS",
        "CELLULAR",
        "PHONE",
        "PHONES",
        "ELECTRONICS",
        "1",
        "2",
        "3",
        "OF",
        "THE",
        "A",
    ]  # noqa: SIM905
)


def generic_tokens(names, min_share: float = 0.002, min_count: int = 25) -> frozenset[str]:
    df: dict[str, int] = defaultdict(int)
    n = 0
    for name in names:
        if not name:
            continue
        n += 1
        for t in set(name.split()):
            df[t] += 1
    common = {t for t, c in df.items() if c >= min_count and c / max(n, 1) >= min_share}
    return BASE_GENERIC | common


def name_similarity(a: str | None, b: str | None, generic: frozenset[str] = BASE_GENERIC) -> float:
    """Similarity on the distinctive words of two names, ignoring generic ones.

    If either name is all generic words ("DELI GROCERY"), only a near-identical full name counts.
    """
    if not a or not b:
        return 0.0
    da = [t for t in a.split() if t not in generic]
    db_ = [t for t in b.split() if t not in generic]
    if not da or not db_:
        r = SequenceMatcher(None, a, b).ratio()
        return r if r >= 0.95 else 0.0
    sa, sb = " ".join(da), " ".join(db_)
    ratio = SequenceMatcher(None, sa, sb).ratio()
    ta, tb = set(da), set(db_)
    jacc = len(ta & tb) / len(ta | tb)
    contained = 0.9 if (ta <= tb or tb <= ta) else 0.0
    return max(ratio, jacc, contained)


_ADDR_BLOCK = re.compile(r"^ADDR:([^|]*)\|([^|]*)\|([^|]*)\|")


def block_key(storefront_key: str, bbl: str | None) -> str | None:
    if bbl:
        return f"BBL:{bbl}"
    m = _ADDR_BLOCK.match(storefront_key or "")
    return f"ADDR:{m.group(1)}|{m.group(2)}|{m.group(3)}" if m else None


def _summaries(db: Database, source: str, match: dict) -> list[dict]:
    return list(
        db[INSPECTIONS].aggregate(
            [
                {
                    "$match": {
                        "source": source,
                        "industry.is_storefront": True,
                        "business_key": {"$ne": None},
                    }
                },
                {
                    "$group": {
                        "_id": "$business_key",
                        "storefront_key": {"$first": "$storefront_key"},
                        "bbl": {"$first": "$bbl"},
                        "unit": {"$first": "$address.unit_norm"},
                        "name": {"$first": "$business.name_norm"},
                        "label": {"$last": "$industry.label"},
                        "first_seen": {"$min": "$inspected_at"},
                        "last_seen": {"$max": "$inspected_at"},
                        "closed": {"$max": "$is_closure"},
                    }
                },
                {"$match": match},
            ],
            allowDiskUse=True,
        )
    )


def find_links(archive: list[dict], live: list[dict]) -> list[dict]:
    live_keys = {b["_id"] for b in live}
    a_open = [a for a in archive if a["_id"] not in live_keys]
    exact = {a["_id"] for a in archive if a["_id"] in live_keys}
    l_open = [b for b in live if b["_id"] not in exact]

    blocks_a, blocks_l = defaultdict(list), defaultdict(list)
    for a in a_open:
        k = block_key(a["storefront_key"], a.get("bbl"))
        if k:
            blocks_a[k].append(a)
    for b in l_open:
        k = block_key(b["storefront_key"], b.get("bbl"))
        if k:
            blocks_l[k].append(b)

    generic = generic_tokens([x["name"] for x in archive + live])
    candidates = []
    for k, alist in blocks_a.items():
        blist = blocks_l.get(k)
        if not blist:
            continue
        for a in alist:
            for b in blist:
                sim = name_similarity(a["name"], b["name"], generic)
                same_unit = (a.get("unit") or "") == (b.get("unit") or "")
                if sim >= 0.85:
                    rule, rank = "name_strong", 3 + sim
                elif sim >= 0.60 and same_unit:
                    rule, rank = "name_unit", 2 + sim
                else:
                    sole = (
                        a["storefront_key"] == b["storefront_key"]
                        and sum(x["storefront_key"] == a["storefront_key"] for x in alist) == 1
                        and sum(y["storefront_key"] == b["storefront_key"] for y in blist) == 1
                        and a.get("label") == b.get("label")
                        and 0 <= (b["first_seen"] - a["last_seen"]).days <= 365
                    )
                    if not sole:
                        continue
                    rule, rank = "sole_tenant", 1 + sim
                candidates.append((rank, a, b, rule, sim))

    candidates.sort(key=lambda c: -c[0])
    used_a, used_b, links = set(), set(), []
    for _, a, b, rule, sim in candidates:
        if a["_id"] in used_a or b["_id"] in used_b:
            continue
        used_a.add(a["_id"])
        used_b.add(b["_id"])
        links.append(
            {
                "_id": b["_id"],  # live key -> archive key
                "archive_key": a["_id"],
                "rule": rule,
                "name_similarity": round(sim, 3),
                "archive_name": a["name"],
                "live_name": b["name"],
                "gap_days": (b["first_seen"] - a["last_seen"]).days,
            }
        )
    return links


def link_across_switch(db: Database, log=print) -> dict:
    archive = _summaries(db, "archive", {"last_seen": {"$gte": ARCHIVE_SINCE}, "closed": False})
    live = _summaries(db, "live", {"first_seen": {"$lt": LIVE_UNTIL}})
    links = find_links(archive, live)

    db[LINKS].delete_many({})
    if links:
        db[LINKS].insert_many(links)

    ins = db[INSPECTIONS]
    ins.update_many({}, [{"$set": {"business_id": "$business_key"}}])
    if links:
        ins.bulk_write(
            [
                UpdateMany(
                    {"source": "live", "business_key": lk["_id"]},
                    {"$set": {"business_id": lk["archive_key"]}},
                )
                for lk in links
            ],
            ordered=False,
        )
    ins.create_index([("business_id", 1), ("inspected_at", 1)], name="business_id_history")

    live_keys = {b["_id"] for b in live}
    exact = sum(1 for a in archive if a["_id"] in live_keys)
    by_rule = defaultdict(int)
    for lk in links:
        by_rule[lk["rule"]] += 1
    n = len(archive)
    summary = {
        "open_archive_businesses_since_2022": n,
        "exact_key_match": exact,
        **{f"linked_{k}": v for k, v in sorted(by_rule.items())},
        "match_rate_exact": round(exact / n, 4) if n else None,
        "match_rate_with_links": round((exact + len(links)) / n, 4) if n else None,
        "match_rate_without_sole_tenant": (
            round((exact + len(links) - by_rule["sole_tenant"]) / n, 4) if n else None
        ),
    }
    log(f"cross-switch links: {summary}")
    return summary
