"""Pure normalization functions. No database access, so they are cheap to unit test.

These decide what counts as "the same business" and "the same storefront", so every rule
here shows up directly in the survival numbers. Keep them simple and deterministic.
"""

from __future__ import annotations

import re
from datetime import datetime

from storefronts.config import Crosswalks

# ---------------------------------------------------------------- business names

_LEGAL_SUFFIXES = {
    "INC",
    "INCORPORATED",
    "LLC",
    "CORP",
    "CORPORATION",
    "CO",
    "LTD",
    "LIMITED",
    "LP",
    "LLP",
    "PC",
    "PLLC",
}
_SPACED_LLC = re.compile(r"\bL\s+L\s+C\b")
_DBA = re.compile(r"\s+(?:D\s*B\s*A|D/B/A)\s+.*$")
_NON_ALNUM = re.compile(r"[^A-Z0-9 ]+")
_SPACES = re.compile(r"\s+")


def normalize_name(raw: str | None) -> str | None:
    """Uppercase, drop punctuation and legal suffixes. "Joe's Deli, Inc." -> "JOES DELI"."""
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).upper()
    s = _DBA.sub("", s)  # keep the legal name; DBA text varies more between records
    # "&" and "AND" are dropped so "DELI & GROCERY" and "DELI GROCERY" match.
    s = s.replace("&", " ").replace("'", "").replace("’", "")
    s = _NON_ALNUM.sub(" ", s)
    s = _SPACED_LLC.sub("LLC", s)
    tokens = _SPACES.sub(" ", s).strip().split(" ")
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    if len(tokens) > 1 and tokens[0] == "THE":
        tokens.pop(0)
    out = " ".join(t for t in tokens if t and t != "AND")
    return out or None


# ---------------------------------------------------------------- units and addresses

_UNIT_WORDS = {
    "STE",
    "SUITE",
    "UNIT",
    "APT",
    "STORE",
    "STOR",
    "SHOP",
    "RM",
    "ROOM",
    "SPACE",
    "SPC",
    "FL",
    "FLR",
    "FLOOR",
    "NO",
    "NUM",
}


def normalize_unit(unit_type: str | None, unit: str | None) -> str:
    """ "STE" + "A" -> "A"; "STORE #3" -> "3"; nothing -> "" (whole building frontage)."""
    s = f"{unit_type or ''} {unit or ''}".upper()
    s = _NON_ALNUM.sub(" ", s)
    tokens = [t for t in s.split() if t not in _UNIT_WORDS]
    return "".join(tokens)


_STREET_WORDS = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "AV": "AVE",
    "BOULEVARD": "BLVD",
    "ROAD": "RD",
    "PLACE": "PL",
    "PARKWAY": "PKWY",
    "DRIVE": "DR",
    "LANE": "LN",
    "COURT": "CT",
    "TERRACE": "TER",
    "HIGHWAY": "HWY",
    "EAST": "E",
    "WEST": "W",
    "NORTH": "N",
    "SOUTH": "S",
    "SAINT": "ST",
}


def normalize_street(raw: str | None) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    s = _NON_ALNUM.sub(" ", str(raw).upper())
    tokens = [_STREET_WORDS.get(t, t) for t in s.split()]
    return " ".join(tokens) or None


def normalize_building(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = _NON_ALNUM.sub("", str(raw).upper())
    return s.lstrip("0") or None


def normalize_zip(raw) -> str | None:
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw).split(".")[0])
    return digits[:5].zfill(5) if digits else None


def normalize_bbl(raw) -> str | None:
    """10-digit borough-block-lot string, or None if missing or malformed."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = re.sub(r"\D", "", s)
    if len(s) != 10 or s[0] not in "12345" or s[1:6] == "00000":
        return None
    return s


_BOROUGHS = {
    "manhattan": "Manhattan",
    "new york": "Manhattan",
    "mn": "Manhattan",
    "1": "Manhattan",
    "bronx": "Bronx",
    "the bronx": "Bronx",
    "bx": "Bronx",
    "2": "Bronx",
    "brooklyn": "Brooklyn",
    "kings": "Brooklyn",
    "bk": "Brooklyn",
    "3": "Brooklyn",
    "queens": "Queens",
    "qn": "Queens",
    "4": "Queens",
    "staten island": "Staten Island",
    "richmond": "Staten Island",
    "si": "Staten Island",
    "5": "Staten Island",
}


def normalize_borough(raw: str | None, bbl: str | None = None) -> str | None:
    if raw and raw.strip().casefold() in _BOROUGHS:
        return _BOROUGHS[raw.strip().casefold()]
    if bbl:
        return _BOROUGHS[bbl[0]]
    return None


def storefront_key(
    bbl: str | None,
    unit_norm: str,
    zip5: str | None,
    building: str | None,
    street: str | None,
) -> str | None:
    """Physical storefront identity: property lot plus unit, else a normalized address."""
    if bbl:
        return f"BBL:{bbl}|{unit_norm}"
    if zip5 and building and street:
        return f"ADDR:{zip5}|{building}|{street}|{unit_norm}"
    return None


def business_key(storefront: str | None, name_norm: str | None) -> str | None:
    """A business is a normalized name at a storefront. Same name elsewhere = different key."""
    if not storefront or not name_norm:
        return None
    return f"{storefront}|{name_norm}"


# ---------------------------------------------------------------- dates and geo


def parse_socrata_ts(raw: str | None) -> datetime | None:
    """Socrata floating timestamps like "2015-02-20T13:50:00.000" (NYC local time, no offset)."""
    if not raw:
        return None
    s = raw.strip().replace("Z", "")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def parse_sample_date(raw: str | None) -> datetime | None:
    """The 2015 sample stores dates as text like "Feb 20 2015"."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%b %d %Y")
    except ValueError:
        return None


# Generous NYC bounding box; anything outside is treated as a bad geocode.
_LAT = (40.45, 40.95)
_LNG = (-74.30, -73.65)


def geo_point(lat, lng) -> dict | None:
    try:
        la, lo = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if _LAT[0] <= la <= _LAT[1] and _LNG[0] <= lo <= _LNG[1]:
        return {"type": "Point", "coordinates": [round(lo, 6), round(la, 6)]}
    return None


# ---------------------------------------------------------------- industries

_CODE_SUFFIX = re.compile(r"^(.*?)\s*-\s*(\d{3}[A-Z]?)\s*$")  # "006A" occurs too


def split_industry(raw: str | None) -> tuple[str | None, str | None]:
    """ "Cigarette Retail Dealer - 127" -> ("Cigarette Retail Dealer", "127")."""
    if raw is None or not str(raw).strip():
        return None, None
    raw = str(raw)
    m = _CODE_SUFFIX.match(raw.strip())
    if m:
        return m.group(1).strip(), m.group(2)
    return raw.strip(), None


def classify_industry(raw: str | None, xw: Crosswalks) -> dict:
    label, code = split_industry(raw)
    if label is None:
        return {
            "raw": raw,
            "label": None,
            "code": None,
            "group": "missing",
            "is_storefront": False,
        }
    canonical = xw.industry_renames.get(label.casefold(), label)
    key = canonical.casefold()
    return {
        "raw": raw,
        "label": canonical,
        "code": code,
        "group": xw.industry_group.get(key, xw.default_group),
        "is_storefront": key not in xw.non_storefront,
    }
