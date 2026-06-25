.PHONY: test eval lint check all pre-push audit

PY := .venv/bin/python

# Unit + integration tests — synthetic Ollama, tmpdir graphs. Fast + deterministic.
test:
	$(PY) -m pytest tests/ -q

# Full-pipeline eval — REAL execution on the bundled sample corpus, with evidence
# artifacts under eval/evidence/. Uses real Ollama if available; degrades to
# deterministic + spaCy otherwise. This is the release gate.
eval:
	$(PY) -m eval.eval_full_pipeline

# Lint (style + correctness)
lint:
	ruff check investigation_graph scripts tests eval

# Dependency / environment check
check:
	$(PY) -m investigation_graph.check

# Fast gate (no real-corpus run): deps + lint + unit/integration tests
all: check lint test

# Full gate before a push or a public release: fast gate + the real-execution eval
pre-push: all eval
	@echo "All checks + full-pipeline eval passed. Safe to push."

# Recurrence net: re-checks failures we've ALREADY found (disproven corruption
# claim re-asserting, grounding ceasing to quarantine, empty-graph green, the
# honest interop ledgers rotting). Floors against vacuous green; reports DEGRADED
# (exit 2, not 0) if the real model can't be reached. NOT a substitute for an
# adversarial human/agent pass — that finds NEW failure shapes (see ROADMAP).
audit:
	$(PY) scripts/audit.py
