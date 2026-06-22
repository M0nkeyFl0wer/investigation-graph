"""Tests for the FollowTheMoney crosswalk (P2.5 / interop brief G2).

Pins the crosswalk behavior against the real followthemoney model: mappable types
round-trip, money/percentage survive, associative edges become UnknownLink, and the
known-unmappable set lands in the dropped ledger (never silently lost).
"""
from followthemoney import model

from investigation_graph.interop import from_ftm, to_ftm

ENTS = [
    {"id": "p1", "entity_type": "person", "label": "Jane Roe"},
    {"id": "o1", "entity_type": "organization", "label": "Acme Corp"},
    {"id": "x1", "entity_type": "claim", "label": "nope"},
]
EDGES = [
    {"source_id": "p1", "target_id": "o1", "edge_type": "OWNS", "share_pct": 55.0},
    {"source_id": "p1", "target_id": "o1", "edge_type": "ASSOCIATED_WITH"},
    {"source_id": "p1", "target_id": "o1", "edge_type": "CONTRADICTS"},
]


def test_mappable_entities_become_valid_ftm_proxies():
    res = to_ftm(ENTS, [])
    schemas = {p["id"]: p["schema"] for p in res.proxies}
    assert schemas["p1"] == "Person"
    assert schemas["o1"] == "Company"
    # Each proxy validates against the real ftm model.
    for d in res.proxies:
        model.get_proxy(d)  # raises if the proxy is malformed


def test_unmappable_entity_is_dropped_not_silent():
    res = to_ftm(ENTS, [])
    dropped = {d["id"] for d in res.dropped}
    assert "x1" in dropped
    assert all(p["id"] != "x1" for p in res.proxies)  # not force-fit into FtM


def test_ownership_percentage_survives_round_trip():
    res = to_ftm([ENTS[0], ENTS[1]], [EDGES[0]])
    back = from_ftm(res.proxies)
    owns = next(e for e in back["edges"] if e["edge_type"] == "OWNS")
    assert owns["source_id"] == "p1" and owns["target_id"] == "o1"
    assert str(owns["share_pct"]) == "55.0"


def test_associative_edge_becomes_unknownlink_with_role():
    res = to_ftm([ENTS[0], ENTS[1]], [EDGES[1]])
    ul = next(p for p in res.proxies if p["schema"] == "UnknownLink")
    assert ul["properties"]["role"] == ["ASSOCIATED_WITH"]
    back = from_ftm(res.proxies)
    assert back["edges"][0]["edge_type"] == "ASSOCIATED_WITH"  # role preserved back


def test_analytical_edge_has_no_ftm_home():
    res = to_ftm([ENTS[0], ENTS[1]], [EDGES[2]])  # CONTRADICTS
    assert any("CONTRADICTS" in d.get("edge", "") for d in res.dropped)
    assert not any(p["schema"] not in ("Person", "Company") for p in res.proxies)


def test_from_ftm_preserves_provenance_not_flattened():
    # A proxy carrying its own sourceUrl must keep it (not collapse to one source).
    p = model.make_entity("Person")
    p.id = "imp1"
    p.add("name", "Imported Person")
    p.add("sourceUrl", "https://opensanctions.org/entities/imp1")
    back = from_ftm([p.to_dict()])
    ent = back["entities"][0]
    assert ent["source_url"] == "https://opensanctions.org/entities/imp1"
    assert ent["extraction_source"] == "ftm_import"
