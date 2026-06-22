"""
FollowTheMoney (FtM) crosswalk (P2.5 / interop brief G2), consumer-side.

Our ontology is ~90% a renamed FtM, so a crosswalk lets us export to the journalist
ecosystem (Aleph) and import FtM-native corpora (OpenSanctions / Open Ownership).

Built behind a thin local adapter (`to_ftm` / `from_ftm`) so the eventual kg-common
ABC hook (PUB.6) is a lift-and-shift, not a redesign — the mapping tables live here.

VERIFIED AGAINST followthemoney **4.9.2** (not the brief's from-memory table — see
DEVIATIONS for the pin). The crosswalk maps the *mappable* core; everything with no
clean FtM home is recorded in an explicit **dropped ledger**, never silently lost
and never force-fit. That dropped set IS the honest metric of a crosswalk.

Mapping decisions (against the real 4.9.2 schemata):
- Edge schemata + their entity-ref props: Ownership(owner→asset, percentage),
  Payment(payer→beneficiary, amount, currency), Employment(employee→employer),
  Directorship(director→organization), Membership(member→organization),
  Family(person→relative), UnknownLink(subject→object, role).
- `Mention` is a *thing* in 4.9.2 (not an entity↔document edge) → MENTIONED_IN is
  dropped (structural provenance, not a relation worth force-fitting).
- No FtM home (dropped by design): `claim`, `domain` entities; `CONTRADICTS`,
  `SUPPORTS` (analytical), and structural/property-shaped edges (MENTIONED_IN,
  AUTHORED→Document.author, LOCATED_AT→Address property). `transaction` entities
  are absorbed into Payment edges in FtM (structural mismatch) → dropped here.
- Loosely-associative edges → UnknownLink with the original type as `role`, so the
  link survives the crossing labelled, not invented.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from followthemoney import model

# investigative entity_type -> FtM schema (the common-case choice).
ENTITY_TO_FTM = {
    "person": "Person",
    "organization": "Company",     # Organization/PublicBody are context-specific
    "location": "Address",
    "asset": "Asset",
    "document": "Document",
    "event": "Event",
}
# FtM schema -> our entity_type (inverse; Company/Organization/PublicBody collapse).
FTM_TO_ENTITY = {
    "Person": "person", "Company": "organization", "Organization": "organization",
    "PublicBody": "organization", "LegalEntity": "organization",
    "Address": "location", "Asset": "asset", "RealEstate": "asset",
    "Security": "asset", "Vehicle": "asset", "Document": "document", "Event": "event",
}

# investigative edge_type -> (FtM edge schema, source_prop, target_prop, extra map
# {ftm_prop: our_edge_key}).
EDGE_TO_FTM = {
    "OWNS":            ("Ownership", "owner", "asset", {"percentage": "share_pct"}),
    "FUNDED_BY":       ("Payment", "payer", "beneficiary",
                        {"amount": "amount", "currency": "currency"}),
    "EMPLOYED_BY":     ("Employment", "employee", "employer", {}),
    "BOARD_MEMBER_OF": ("Directorship", "director", "organization", {}),
    "MEMBER_OF":       ("Membership", "member", "organization", {}),
    "FAMILY_OF":       ("Family", "person", "relative", {}),
}
# Loosely-associative edges -> UnknownLink, original type kept as `role`.
EDGE_TO_UNKNOWNLINK = {"ASSOCIATED_WITH", "OPERATED_BY", "REGISTERED_AGENT_OF",
                       "IMPERSONATES", "SIBLING_OF", "CO_HOSTED_WITH",
                       "OPERATES_DOMAIN"}
# Inverse of EDGE_TO_FTM, by FtM schema name.
FTM_EDGE_TO_OURS = {v[0]: (k, v[1], v[2], v[3]) for k, v in EDGE_TO_FTM.items()}


@dataclass
class CrosswalkResult:
    """FtM proxies (as dicts) + the explicit dropped ledger (the real metric)."""
    proxies: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)   # {id|edge, kind, reason}


def to_ftm(entities: list[dict], edges: list[dict]) -> CrosswalkResult:
    """Map our entities/edges to FtM proxy dicts. Unmappable items go to `dropped`
    with a reason — never silently lost, never force-fit."""
    res = CrosswalkResult()

    for e in entities:
        schema = ENTITY_TO_FTM.get(e.get("entity_type"))
        if not schema:
            res.dropped.append({"id": e["id"], "kind": "entity",
                                "reason": f"no FtM schema for type '{e.get('entity_type')}'"})
            continue
        p = model.make_entity(schema)
        p.id = e["id"]
        if e.get("label"):
            p.add("name", e["label"])
        res.proxies.append(p.to_dict())

    for ed in edges:
        et = ed.get("edge_type")
        if et in EDGE_TO_FTM:
            schema, sp, tp, extra = EDGE_TO_FTM[et]
            p = model.make_entity(schema)
            p.id = ed.get("id") or f"{et}:{ed['source_id']}:{ed['target_id']}"
            p.add(sp, ed["source_id"])
            p.add(tp, ed["target_id"])
            for ftm_prop, our_key in extra.items():
                if ed.get(our_key) not in (None, "", 0, 0.0):
                    p.add(ftm_prop, str(ed[our_key]))
            res.proxies.append(p.to_dict())
        elif et in EDGE_TO_UNKNOWNLINK:
            p = model.make_entity("UnknownLink")
            p.id = ed.get("id") or f"{et}:{ed['source_id']}:{ed['target_id']}"
            p.add("subject", ed["source_id"])
            p.add("object", ed["target_id"])
            p.add("role", et)
            res.proxies.append(p.to_dict())
        else:
            res.dropped.append({"edge": f"{ed['source_id']}-{et}->{ed['target_id']}",
                                "kind": "edge",
                                "reason": f"no FtM edge schema for '{et}'"})
    return res


def from_ftm(proxies: list[dict]) -> dict:
    """Map FtM proxy dicts back to our entities/edges, preserving per-proxy
    provenance (the FtM `sourceUrl`/`publisher`, NOT flattened to one source).
    Returns ``{"entities","edges","dropped"}``."""
    entities, edges, dropped = [], [], []
    for d in proxies:
        p = model.get_proxy(d)
        sname = p.schema.name
        # Per-statement provenance preserved: keep the proxy's own source pointer.
        prov = (p.first("sourceUrl") or p.first("publisher")
                or (p.context.get("dataset") if hasattr(p, "context") else None) or "")
        if p.schema.edge and sname in FTM_EDGE_TO_OURS:
            our_type, sp, tp, extra = FTM_EDGE_TO_OURS[sname]
            edge = {"source_id": p.first(sp), "target_id": p.first(tp),
                    "edge_type": our_type, "provenance": prov or "ftm_import",
                    "extraction_source": "ftm_import"}
            for ftm_prop, our_key in extra.items():
                if p.first(ftm_prop) is not None:
                    edge[our_key] = p.first(ftm_prop)
            edges.append(edge)
        elif sname == "UnknownLink":
            edges.append({"source_id": p.first("subject"), "target_id": p.first("object"),
                          "edge_type": p.first("role") or "ASSOCIATED_WITH",
                          "provenance": prov or "ftm_import",
                          "extraction_source": "ftm_import"})
        elif sname in FTM_TO_ENTITY:
            entities.append({"id": p.id, "entity_type": FTM_TO_ENTITY[sname],
                             "label": p.caption, "source_url": prov,
                             "provenance": prov or "ftm_import",
                             "extraction_source": "ftm_import"})
        else:
            dropped.append({"id": p.id, "schema": sname,
                            "reason": "FtM schema has no investigative-ontology home"})
    return {"entities": entities, "edges": edges, "dropped": dropped}


# The crosswalk's documented boundary — the types with no FtM home (loss ledger).
NO_FTM_HOME = {
    "entities": ["claim", "domain", "transaction"],
    "edges": ["CONTRADICTS", "SUPPORTS", "MENTIONED_IN", "AUTHORED", "LOCATED_AT",
              "ABOUT", "SUPERSEDES", "CITES", "REGULATES", "ALIAS_OF",
              "GROUPED_UNDER", "ATTENDED", "PAID_TO", "CONTRACTED_WITH"],
}
FTM_VERSION_VERIFIED = "4.9.2"
