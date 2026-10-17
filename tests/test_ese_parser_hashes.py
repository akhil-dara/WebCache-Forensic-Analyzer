"""WebCacheParser.open()'s known_hashes parameter.

The consent gate (consent.py) already hashes every file in evidence_scope()
before the parser is ever constructed -- EvidenceSet.hashes holds the
result. Before this fix, open() ignored that entirely and called
_hash_sources() itself, so opening a multi-gigabyte exhibit read it twice
for the exact same answer. known_hashes, when supplied, must be used
instead of recomputing -- and the values it ends up recording in
source_hashes must be BYTE-IDENTICAL to what open() would have computed on
its own: a wrong hash in a forensic tool is worse than a slow one.

No real WebCacheV01.dat exists on this machine (see test_evidence_loader.py
and test_consent.py's own docstrings for why), and dissect.esedb's EseDB()
raises immediately on anything that is not a genuine ESE database --
BEFORE open() ever reaches the hashing step -- so a bogus-bytes fixture
cannot exercise this past that point on its own. EseDB is monkeypatched
out here, along with the three _load_* methods that would otherwise need a
real database to succeed, so open() can run to completion against a small
fixture file without a real exhibit -- while every other line open()
executes (path handling, db_state, the decision log, and both the
known_hashes branch and the original _hash_sources() branch) stays real,
unmocked code.
"""
import hashlib

import pytest

from webcache.engine import ese_parser
from webcache.engine.ese_parser import WebCacheParser, evidence_scope
from webcache.provenance import EvidenceSet


class _FakeHeader:
    dbstate = 1


class _FakeDb:
    header = _FakeHeader()


@pytest.fixture
def exhibit(tmp_path, monkeypatch):
    """A small fixture 'exhibit': a .dat plus one .log sibling, exactly the
    shape evidence_scope() (and so the consent gate) expects. EseDB and the
    table/container/partition loaders are stubbed so open() can run to
    completion without a real ESE database -- see the module docstring.
    """
    db_path = tmp_path / "WebCacheV01.dat"
    db_path.write_bytes(b"pretend database bytes" * 100)
    (tmp_path / "V01.log").write_bytes(b"pretend log bytes" * 50)

    monkeypatch.setattr(ese_parser, "EseDB", lambda fh: _FakeDb())
    monkeypatch.setattr(WebCacheParser, "_load_tables", lambda self: None)
    monkeypatch.setattr(WebCacheParser, "_load_containers", lambda self: None)
    monkeypatch.setattr(WebCacheParser, "_load_partitions", lambda self: None)
    return db_path


def test_known_hashes_matches_what_open_would_have_computed_itself(exhibit):
    """The passed-in path and the computed path must agree, value for
    value -- not just both be non-empty."""
    computed = WebCacheParser()
    computed.open(str(exhibit))

    # Exactly what the consent gate produces: EvidenceSet.from_paths() over
    # evidence_scope()'s file list, entirely independent of WebCacheParser.
    evidence = EvidenceSet.from_paths(evidence_scope(str(exhibit)))

    known = WebCacheParser()
    known.open(str(exhibit), known_hashes=evidence.hashes)

    assert known.source_hashes == computed.source_hashes
    assert known.source_hashes, "both must actually contain hashes"
    assert (known.source_hashes[exhibit.name]
            == evidence.hashes[str(exhibit)]
            == hashlib.sha256(exhibit.read_bytes()).hexdigest())


def test_known_hashes_skips_recomputation_entirely(exhibit, monkeypatch):
    """The actual bug fix: passing known_hashes must skip _hash_sources()
    -- the method that re-reads every file in scope -- entirely, not just
    happen to produce the same answer."""
    def _must_not_be_called(self, db_path):
        raise AssertionError(
            "_hash_sources must not run when known_hashes is supplied")

    monkeypatch.setattr(WebCacheParser, "_hash_sources", _must_not_be_called)

    evidence = EvidenceSet.from_paths(evidence_scope(str(exhibit)))
    parser = WebCacheParser()
    parser.open(str(exhibit), known_hashes=evidence.hashes)  # must not raise
    assert (parser.source_hashes[exhibit.name]
            == evidence.hashes[str(exhibit)])


def test_default_none_preserves_the_original_recompute_behaviour(exhibit):
    """known_hashes defaults to None -- every existing caller, and every
    test written before this fix, must keep hashing exactly as before."""
    parser = WebCacheParser()
    parser.open(str(exhibit))
    expected = hashlib.sha256(exhibit.read_bytes()).hexdigest()
    assert parser.source_hashes[exhibit.name] == expected
