"""Adversarial robustness tests for tabular ingestion (P2.4).

The fixture evals are correct-by-construction; these probe the messy-data failure
modes the kg-ingestion skill warns about — embedded delimiters in free-text cells
(the #1 tabular desync), and cross-row name-variant resolution (the case that
motivates the structured-linkage tier, PUB.5).
"""
from investigation_graph.ontology import Ontology
from investigation_graph.pipeline import ground_and_resolve
from investigation_graph.processors.tabular import MappingSpec, ingest_table

ONT = Ontology()
SPEC_YAML = (
    "entities:\n"
    "  - {column: owner, type: person}\n"
    "  - {column: asset, type: organization}\n"
    "edges:\n"
    "  - {source: owner, type: OWNS, target: asset}\n"
)


def _spec(tmp_path):
    p = tmp_path / "s.map.yaml"
    p.write_text(SPEC_YAML)
    return MappingSpec.from_yaml(p, ONT)


def test_embedded_commas_and_quotes_do_not_desync(tmp_path):
    # A quoted cell containing a comma + an escaped quote must parse as ONE value,
    # not split the row (the delimited-free-text desync the skill flags).
    csv = tmp_path / "t.csv"
    csv.write_text(
        'owner,asset\n'
        '"Smith, John & Co.",Brightpath Advisors\n'
        '"O\'\'Brien ""Holdings""",Harbor City RDA\n'
    )
    out = ingest_table(csv, _spec(tmp_path), ontology=ONT)
    labels = {e["label"] for e in out["entities"]}
    assert "Smith, John & Co." in labels          # comma preserved, not split
    assert any("Brien" in line for line in labels) # quotes handled
    assert len(out["edges"]) == 2                  # two clean OWNS edges, no desync


def test_name_variants_are_NOT_merged_by_exact_fuzzy_alone(tmp_path):
    # HONEST limitation: exact + fuzzy resolution (no embeddings here) does NOT merge
    # "Brightpath Advisors" vs "Brightpath Advisors LLC" — token_sort_ratio < 0.92.
    # This is exactly why a structured-linkage tier (Splink, PUB.5) is on the roadmap;
    # the test documents the current behavior so a future fix has a baseline.
    csv = tmp_path / "v.csv"
    csv.write_text(
        "owner,asset\n"
        "Jane Roe,Brightpath Advisors\n"
        "Jane Roe,Brightpath Advisors LLC\n"
    )
    out = ingest_table(csv, _spec(tmp_path), ontology=ONT)
    chunks = [{"id": c["id"], "text": c["text"]} for c in out["chunks"]]
    built, _ = ground_and_resolve(chunks, out["entities"], out["edges"])
    org_labels = sorted(e["label"] for e in built["entities"]
                        if e["entity_type"] == "organization")
    # Documented current behavior: the two surface forms stay SEPARATE (2 orgs).
    assert org_labels == ["Brightpath Advisors", "Brightpath Advisors LLC"]
