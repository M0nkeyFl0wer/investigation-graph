"""Evidence-manifest tests — the chain-of-custody spine.

All deterministic and network-free: we hash real temp files and assert the
manifest records correct, independently-verifiable provenance. The Playwright /
ffmpeg engines are not exercised here (they need a browser / system binary and
the network); this covers the integrity + provenance logic every capture relies on.
"""
from investigation_graph.capture import EvidenceManifest, sha256_file
from investigation_graph.capture.manifest import Artifact


def _write(parent, name, data=b"hello evidence"):
    parent.mkdir(parents=True, exist_ok=True)
    p = parent / name
    p.write_bytes(data)
    return p


def test_record_file_hash_matches_independent_rehash(tmp_path):
    root = tmp_path / "evidence"
    m = EvidenceManifest(root)
    f = _write(root / "artifacts", "a.txt")  # under the evidence root
    art = m.record_file(f, artifact_id="a", kind="note",
                        capture_method="unit", tool_version="t")
    # The manifest hash must equal an independent re-hash of the same bytes.
    assert art.sha256 == sha256_file(f)
    assert art.bytes == len(b"hello evidence")
    assert art.collector  # always attributed
    assert art.captured_at_utc.endswith("+00:00")  # tz-aware UTC


def test_paths_are_stored_relative_to_evidence_root(tmp_path):
    root = tmp_path / "evidence"
    m = EvidenceManifest(root)
    (root / "artifacts" / "web").mkdir(parents=True)
    f = root / "artifacts" / "web" / "page.png"
    f.write_bytes(b"png")
    art = m.record_file(f, artifact_id="p", kind="screenshot",
                        capture_method="unit", tool_version="t")
    # Portable: no absolute machine path baked into the manifest.
    assert art.local_path == "artifacts/web/page.png"


def test_manifest_is_append_only_and_reloads(tmp_path):
    root = tmp_path / "evidence"
    m = EvidenceManifest(root)
    f1 = _write(root, "x.txt", b"one")
    f2 = _write(root, "y.txt", b"two")
    m.record_file(f1, artifact_id="x", kind="note", capture_method="u", tool_version="t")
    m.record_file(f2, artifact_id="y", kind="note", capture_method="u", tool_version="t")
    rows = m.load()
    assert [a.artifact_id for a in rows] == ["x", "y"]  # order preserved
    assert m.ids() == {"x", "y"}


def test_load_tolerates_unknown_future_fields(tmp_path):
    """A manifest written by a newer schema must still load (forward-compatible)."""
    root = tmp_path / "evidence"
    m = EvidenceManifest(root)
    m.path.write_text(
        '{"artifact_id":"z","capture_group":"z","kind":"note","local_path":"z.txt",'
        '"sha256":"deadbeef","bytes":3,"captured_at_utc":"2026-06-20T00:00:00+00:00",'
        '"collector":"x@y","capture_method":"u","tool_version":"t",'
        '"some_future_field":"ignore-me"}\n',
        encoding="utf-8",
    )
    rows = m.load()
    assert len(rows) == 1
    assert isinstance(rows[0], Artifact)
    assert rows[0].artifact_id == "z"
