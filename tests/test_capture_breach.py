"""DeHashed breach-capture tests — offline, no network, no real key.

We monkeypatch the single HTTP call (`dehashed_search`) to return canned, fake
(non-real) responses and assert the negative-evidence discipline holds:

  (a) a positive hit records a manifest artifact with kind=osint_breach;
  (b) a 0-result response STILL records an artifact — the documented absence of a
      breach footprint is itself captured evidence, not a dropped lookup.

No DeHashed endpoint is contacted and no key is read; the env requirement is only
enforced in `main()`, which we don't call here.
"""
import scripts.capture_breach as cb
from investigation_graph.capture import EvidenceManifest

# Canned, FAKE bodies — invented selectors/data, never a real breach record.
_FAKE_HIT = b'{"entries":[{"email":"fake@example.test","note":"FAKE"}],"total":1}'
_FAKE_EMPTY = b'{"entries":[],"total":0}'


def test_positive_hit_records_breach_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "dehashed_search", lambda key, query, **kw: (200, _FAKE_HIT))
    m = EvidenceManifest(tmp_path / "evidence")
    summary = cb.capture_selector(m, "unused-fake-key", "email:fake@example.test")

    assert summary["n_results"] == 1
    rows = m.load()
    assert len(rows) == 1
    assert rows[0].kind == "osint_breach"
    assert rows[0].capture_method == "dehashed-api-v2"
    assert "SENSITIVE-PRIVATE" in rows[0].notes


def test_zero_results_still_records_negative_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "dehashed_search", lambda key, query, **kw: (200, _FAKE_EMPTY))
    m = EvidenceManifest(tmp_path / "evidence")
    summary = cb.capture_selector(m, "unused-fake-key", "username:nobody-fake")

    assert summary["n_results"] == 0
    rows = m.load()
    assert len(rows) == 1  # negative evidence IS recorded
    assert rows[0].kind == "osint_breach"
    assert "negative evidence" in rows[0].notes  # explicitly flagged as such
