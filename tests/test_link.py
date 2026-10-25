from datetime import datetime

from storefronts.link import block_key, find_links, name_similarity


def biz(
    key,
    name,
    unit="A",
    bbl="4034400001",
    label="Tobacco Retail Dealer",
    first=datetime(2023, 8, 1),
    last=datetime(2023, 5, 1),
):
    return {
        "_id": key,
        "storefront_key": f"BBL:{bbl}|{unit}",
        "bbl": bbl,
        "unit": unit,
        "name": name,
        "label": label,
        "first_seen": first,
        "last_seen": last,
    }


def test_name_similarity():
    assert name_similarity("ATLIXCO DELI GROCERY", "ATLIXCO DELI GROCERY") == 1.0
    assert name_similarity("ATLIXCO DELI GROCERY", "ATLIXCO DELI") >= 0.85
    assert name_similarity("CLOUD 9 SMOKE SHOP", "HAPPY NAILS") < 0.5
    assert name_similarity(None, "X") == 0.0
    # Two different delis share only generic words: never similar.
    assert name_similarity("ATLIXCO DELI GROCERY", "MI TIERRA DELI GROCERY") < 0.6
    assert name_similarity("DELI GROCERY", "DELI GROCERY CORP") == 0.0
    assert name_similarity("DELI GROCERY", "DELI GROCERY") == 1.0


def test_block_key():
    assert block_key("BBL:4034400001|A", "4034400001") == "BBL:4034400001"
    assert block_key("ADDR:11217|221|FLATBUSH AVE|", None) == "ADDR:11217|221|FLATBUSH AVE"


def test_find_links_rules():
    archive = [
        biz("a1", "ATLIXCO DELI GROCERY", unit="A"),  # name_strong to l1
        biz("a2", "ROSARIO MARTINEZ", unit="B", label="Salons And Barbershop"),  # name_unit to l2
        biz("a3", "XYZ HOLDINGS", unit="C"),  # sole_tenant to l3
        biz("a4", "EXACT MATCH", unit="D"),  # exact key, skipped
        biz("a5", "GONE STORE", unit="E"),  # no partner
    ]
    live = [
        biz("l1", "ATLIXCO DELI", unit="A1"),
        biz("l2", "ROSARIO FAMILY", unit="B", label="Salons And Barbershop"),
        biz("l3", "CORNER STORE 2023", unit="C"),
        biz("a4", "EXACT MATCH", unit="D"),
        biz("l9", "SOME NEW TENANT", unit="E", label="Electronic Store"),  # different industry
    ]
    links = {lk["archive_key"]: lk for lk in find_links(archive, live)}
    assert links["a1"]["_id"] == "l1" and links["a1"]["rule"] == "name_strong"
    assert links["a2"]["_id"] == "l2" and links["a2"]["rule"] == "name_unit"
    assert links["a3"]["_id"] == "l3" and links["a3"]["rule"] == "sole_tenant"
    assert "a4" not in links and "a5" not in links


def test_sole_tenant_requires_short_gap():
    a = [biz("a", "ZENITH TRADING", last=datetime(2021, 1, 1))]
    b = [biz("b", "PLUTO SUPPLY", first=datetime(2023, 9, 1))]
    assert find_links(a, b) == []


def test_one_to_one():
    archive = [biz("a1", "ATLIXCO DELI GROCERY"), biz("a2", "ATLIXCO DELI GROCERY 2")]
    live = [biz("l1", "ATLIXCO DELI GROCERY")]
    links = find_links(archive, live)
    assert len(links) == 1 and links[0]["archive_key"] == "a1"


def test_different_deli_same_unit_is_not_linked_by_name():
    archive = [
        biz("a", "ATLIXCO DELI GROCERY", label="Grocery-Retail"),
        biz("x", "OTHER BIZ", unit="Z"),
    ]
    live = [
        biz("b", "MI TIERRA DELI GROCERY", label="Grocery-Retail"),
        biz("y", "ANOTHER", unit="Z"),
    ]
    links = {lk["archive_key"]: lk for lk in find_links(archive, live)}
    # Only the loose sole_tenant rule can link them, and it is labelled as such.
    assert links["a"]["rule"] == "sole_tenant"
