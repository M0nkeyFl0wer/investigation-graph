"""Quick system check — verifies all dependencies are available."""
# ruff: noqa: F401


def run():
    from . import config
    checks = []

    # Core dependencies
    try:
        import real_ladybug
        checks.append(f"  LadybugDB: {real_ladybug.__version__}")
    except ImportError:
        checks.append("  LadybugDB: NOT INSTALLED (pip install real_ladybug)")

    try:
        import pyarrow
        checks.append(f"  PyArrow: {pyarrow.__version__}")
    except ImportError:
        checks.append("  PyArrow: NOT INSTALLED (pip install pyarrow)")

    try:
        import spacy
        checks.append(f"  spaCy: {spacy.__version__}")
        try:
            spacy.load("en_core_web_sm")
            checks.append("  spaCy model: en_core_web_sm OK")
        except OSError:
            checks.append("  spaCy model: MISSING (python -m spacy download en_core_web_sm)")
    except ImportError:
        checks.append("  spaCy: NOT INSTALLED")

    try:
        import networkx
        checks.append(f"  NetworkX: {networkx.__version__}")
    except ImportError:
        checks.append("  NetworkX: NOT INSTALLED (pip install networkx)")

    try:
        import ripser
        checks.append("  Ripser: OK")
    except ImportError:
        checks.append("  Ripser: not installed (optional, pip install ripser)")

    # DuckDB — the base of the hybrid (chunks + embeddings + FTS). Required.
    try:
        import duckdb
        checks.append(f"  DuckDB: {duckdb.__version__}")
    except ImportError:
        checks.append("  DuckDB: NOT INSTALLED (pip install duckdb)")

    # kg-common — the shared substrate (GraphWriter, Ontology, ER, grounding).
    try:
        import kg_common
        ver = getattr(kg_common, "__version__", "OK")
        checks.append(f"  kg-common: {ver}")
    except ImportError:
        checks.append("  kg-common: NOT INSTALLED "
                      '(pip install -e "../kg-common[ladybug,ollama,dedup,measure]")')

    # Embedding model
    try:
        import ollama
        models = ollama.list()
        model_names = [m.model for m in models.models] if hasattr(models, "models") else []
        checks.append(f"\n  Ollama: OK ({len(model_names)} models)")

        # Check configured embedding model
        emb_model = config.EMBEDDING_MODEL
        if any(emb_model in m for m in model_names):
            checks.append(f"  Embedding model ({emb_model}, {config.EMBEDDING_DIM}d): OK")
        else:
            checks.append(f"  Embedding model: MISSING ({emb_model})")
            checks.append(f"    Run: ollama pull {emb_model}")
    except Exception:
        checks.append("  Ollama: NOT RUNNING (install from ollama.com, then: ollama serve)")

    print("open-newsroom-graph system check")
    print("=" * 40)
    for c in checks:
        print(c)
    print()

    from .ontology import Ontology
    try:
        ont = Ontology()
        print(f"Ontology: {ont}")
        if "NOT" in "\n".join(checks):
            print("  Some dependencies missing — see above.")
        else:
            print("  All checks passed.")
    except FileNotFoundError:
        print("  ONTOLOGY.md not found — run from the repo root directory.")


if __name__ == "__main__":
    run()
