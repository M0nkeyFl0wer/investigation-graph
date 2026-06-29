"""GATE-ER-MULTIFIELD — entity resolution must use the OTHER FIELDS, not just the name.

The R1 resolver is name-only (normalize + legal-suffix). The independent verifier
found its open gap: cross-source SPELLING variants ("J.P. Morgan" / "JP Morgan" /
"JPMorgan") fragment, because no safe name-only rule merges them without also merging
"Acme 1"/"Acme 10". The fix is multi-field matching: registry records carry address,
registration number, jurisdiction — and THOSE break the tie.

This gate is a TWO-SIDED trap that a name-only resolver fails in BOTH directions:
  * UNDER-MERGE (recall): three spellings of the same company with the SAME reg-id and
    address must MERGE — a name-only resolver can't (different normalized names).
  * OVER-MERGE (precision, the libel direction): two genuinely DIFFERENT companies that
    share a name ("Acme Holdings" in Delaware vs in London — different reg-id and
    jurisdiction) must STAY SEPARATE — a name-only resolver WRONGLY fuses them
    (identical normalized name). Fusing two distinct entities is the libel failure, so
    this floor is the one that matters most.
Plus legal-suffix variants (with a shared field) still merge.

A multi-field resolver (Splink, behind the PUB.5 seam) passes both because it weighs
reg-id / address / jurisdiction, not just the string. Run:
    .venv/bin/python -m eval.eval_er_multifield        (exit 0 = all floors met)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from investigation_graph.pipeline import ground_and_resolve  # noqa: E402

SRC = "https://registry.example.gov/feed"


def gen_corpus():
    """Entities carry MULTI-FIELD props (address, reg_id, jurisdiction). chunks
    ground each by its label. Returns (chunks, entities, gold)."""
    entities, chunks = [], []

    def ent(eid, label, reg_id, address, jurisdiction):
        entities.append({
            "id": eid, "label": label, "entity_type": "organization",
            "source_url": SRC, "provenance": f"{SRC}#{eid}", "extraction_source": "structured",
            # multi-field signals the resolver must use:
            "reg_id": reg_id, "address": address, "jurisdiction": jurisdiction,
        })
        chunks.append({"id": f"c_{eid}", "text": f"{label} (reg {reg_id}) of {address}, {jurisdiction}."})

    # 1. Cross-source SPELLING variants of ONE company — same reg-id + address.
    #    Name-only CANNOT merge these (the open gap). Multi-field must.
    ent("jpm1", "J.P. Morgan", "US-0000001", "270 Park Avenue, New York", "US")
    ent("jpm2", "JP Morgan", "US-0000001", "270 Park Avenue, New York", "US")
    ent("jpm3", "JPMorgan Chase", "US-0000001", "270 Park Avenue, New York", "US")

    # 2. SAME NAME, DIFFERENT companies — different reg-id + jurisdiction.
    #    Name-only WRONGLY merges these (the libel over-merge). Multi-field must keep apart.
    ent("acme_us", "Acme Holdings", "US-9001", "1209 Orange St, Wilmington DE", "US")
    ent("acme_gb", "Acme Holdings", "GB-7700", "1 Mark Lane, London", "GB")

    # 3. Legal-suffix variant of one company, shared reg-id — must merge.
    ent("gx1", "Globex", "US-5555", "500 Howard St, San Francisco", "US")
    ent("gx2", "Globex LLC", "US-5555", "500 Howard St, San Francisco", "US")

    # 4. A clearly distinct singleton.
    ent("initech", "Initech Systems", "US-7777", "88 Congress Ave, Austin", "US")

    # 5. BLANK reg_id, same name, DIFFERENT address — the libel over-merge a verifier
    #    found: '' must NOT match '' (a reg_id-less feed is common). Two "Summit
    #    Capital" at different addresses are distinct until something says otherwise;
    #    merging them on name alone (because reg_id is blank) is the libel failure.
    ent("summit1", "Summit Capital", "", "11 Wall Street, New York", "US")
    ent("summit2", "Summit Capital", "", "9000 Sunset Blvd, Los Angeles", "US")

    # 6. reg_id COLLISION with contradicting name AND address — a shared reg-id string
    #    (data-entry error / coincidence) must NOT be treated as conclusive when the
    #    name and address both strongly disagree. Reg-id alone is not identity.
    ent("galaxy", "Galaxy Mining Corp", "US-4242", "1 Ore Road, Reno", "US")
    ent("tulip", "Tulip Bakery Ltd", "US-4242", "4 Flour Lane, Portland", "US")

    # 7. reg-id COLLISION with COINCIDENTALLY similar addresses in DIFFERENT cities.
    #    A fuzzy address-similarity veto (difflib > 0.85) bypasses this; the only safe
    #    handling is exact-normalized comparison (different city = different address)
    #    -> route to review -> stay apart. (The verifier's veto-bypass break.)
    ent("spring1", "Springfield Mills", "US-9999", "100 Main Street, Springfield", "US")
    ent("spring2", "Springvale Foods", "US-9999", "100 Main Street, Springvale", "US")

    # 8. BLANK reg-id via a unicode zero-width space, and via a punctuation-only
    #    sentinel — both must NORMALIZE to 'no reg-id' and never act as a merge key.
    #    Distinct names + different addresses, so they must stay apart.
    ent("zwsp1", "Helix Bio", "​", "5 Genome Way, Cambridge", "US")
    ent("zwsp2", "Vortex Labs", "​", "9 Fusion Rd, Berkeley", "US")
    ent("punct1", "Delta Corp", "---", "12 First St, Denver", "US")
    ent("punct2", "Sigma Inc", "---", "34 Second Ave, Phoenix", "US")

    # 9. reg-id COLLISION with MISSING address + contradicting names — nothing
    #    corroborates the shared reg-id, so it must route to review, not auto-merge.
    ent("noaddr1", "Apex Mining Corp", "US-8888", "", "US")
    ent("noaddr2", "Zenith Foods Ltd", "US-8888", "", "US")

    gold = {
        "merge_groups": [{"jpm1", "jpm2", "jpm3"}, {"gx1", "gx2"}],   # each -> 1 survivor
        "must_not_merge": [
            {"acme_us", "acme_gb"},        # same name, different reg-id + jurisdiction
            {"summit1", "summit2"},        # same name, BLANK reg-id, different address
            {"galaxy", "tulip"},           # reg-id collision, contradicting name + address
            {"spring1", "spring2"},        # reg-id collision, coincidentally-similar diff-city address
            {"zwsp1", "zwsp2"},            # same zero-width-space reg-id sentinel — must not match
            {"punct1", "punct2"},          # same punctuation-only reg-id sentinel — must not match
            {"noaddr1", "noaddr2"},        # reg-id collision, missing address, contradicting names
        ],
        # 1 jpmorgan + 1 globex + 1 initech + (2 acme + 2 summit + 2 galaxy + 2 spring
        # + 2 zwsp + 2 punct + 2 noaddr distinct)
        "expected_unique": 17,
    }
    return chunks, entities, gold


def main() -> int:
    chunks, entities, gold = gen_corpus()
    build_records, report = ground_and_resolve(chunks, entities, [])
    surviving = {e["id"] for e in build_records["entities"]}

    fails: list[str] = []

    # recall: each cross-source / suffix group must collapse to exactly one survivor
    for grp in gold["merge_groups"]:
        kept = grp & surviving
        if len(kept) != 1:
            fails.append(f"under-merge: {sorted(grp)} left {len(kept)} survivors (must be 1) "
                         "— name-only can't merge cross-source spellings; use reg-id/address")

    # precision (the libel floor): same-name-different-company must stay separate
    for pair in gold["must_not_merge"]:
        kept = pair & surviving
        if len(kept) != len(pair):
            fails.append(f"OVER-MERGE (libel): {sorted(pair)} collapsed to {len(kept)} "
                         "— distinct companies with the same name fused; keep them apart by reg-id/jurisdiction")

    # overall: the resolved entity count must equal the true number of real entities
    if len(surviving) != gold["expected_unique"]:
        fails.append(f"entities_out={len(surviving)} != expected {gold['expected_unique']}")

    print("\nGATE-ER-MULTIFIELD — resolution must use reg-id / address / jurisdiction, not just the name")
    print(f"  entities_in={len(entities)} entities_out={len(surviving)} "
          f"(expected {gold['expected_unique']})")
    if fails:
        print("  RESULT: \033[31mFAIL\033[0m — floors not met:")
        for f in fails:
            print(f"    ✗ {f}")
        print("  (expected to fail on the name-only resolver — this gate IS the multi-field target.)")
        return 1
    print("  RESULT: \033[32mPASS\033[0m — cross-source spellings merged, same-name-different-company kept apart.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
