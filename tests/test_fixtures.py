import datetime
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from tests.fixtures import FIXTURE_COLUMNS, make_rows

# Expected digest of make_rows(50). Verified identical on Python 3.13 and 3.14.
# This pins the fixture shape and generation logic. It must change only when the
# fixture shape is deliberately changed (e.g. adding a new column, changing the
# seed or row distribution). A silent change here means every performance budget
# has drifted, and nothing will fail to warn us.
FIXTURE_DIGEST = "6f3eada03d476147a95c09a2d3f41dbbcd65e9980caf83f2eee672c6d00c011b"


def test_row_count_and_same_process_determinism():
    """Cheap sanity check: two calls within the same process must agree."""
    a = make_rows(500)
    b = make_rows(500)
    assert len(a) == 500
    assert a == b, "same-process calls must be deterministic"


def test_cross_process_determinism():
    """Expensive: verify fixture determinism across separate Python interpreters.

    This test matters because performance budget comparisons run in separate
    pytest invocations, potentially on different machines (CI matrix for 3.13/3.14).
    The test uses subprocess to spawn fresh interpreters and compares a stable
    digest of the generated rows.
    """
    # Derive the webcache-qt directory: this test lives in webcache-qt/tests/
    webcache_qt_dir = Path(__file__).resolve().parent.parent

    # Snippet to run in subprocess: import fixtures, generate, hash, and print digest
    snippet = (
        "from tests.fixtures import make_rows;"
        "import hashlib;"
        "rows = make_rows(50);"
        "digest = hashlib.sha256(repr(rows).encode()).hexdigest();"
        "print(digest)"
    )

    # Run the snippet twice in separate interpreters
    digests = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            # Run from webcache-qt directory so pythonpath = ["."] applies
            cwd=webcache_qt_dir,
            # Inherit environment and set PYTHONPATH so subprocess can import tests.fixtures
            env={**os.environ, "PYTHONPATH": "."},
            check=True
        )
        digest = result.stdout.strip()
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), \
            f"subprocess produced invalid digest: {digest}"
        digests.append(digest)

    # Both runs must produce the same digest
    assert digests[0] == digests[1], \
        f"cross-process determinism failed: {digests[0]} != {digests[1]}"

    # Pinned digest for this fixture shape and seed
    assert digests[0] == FIXTURE_DIGEST, \
        f"fixture shape changed: expected {FIXTURE_DIGEST}, got {digests[0]}"


def test_every_column_kind_is_represented():
    kinds = {c.kind for c in FIXTURE_COLUMNS}
    for needed in ("text", "url", "num", "time", "time_local", "flag"):
        assert needed in kinds, "fixtures must exercise %s" % needed


def test_rows_carry_both_origins():
    rows = make_rows(500)
    origins = {r["Origin"] for r in rows}
    assert "Live record" in origins
    assert any(o.startswith("Carved") for o in origins)


def test_carved_rows_carry_their_source_file_and_offset():
    """"if we recover, we should give source which file we got it"."""
    carved = [r for r in make_rows(500) if r["Origin"].startswith("Carved")]
    assert carved
    for r in carved:
        assert r["Source"], "a carved record with no source file is unusable"
        assert isinstance(r["Offset"], int)
        assert r["Confidence"] in ("high", "medium", "low")


def test_time_columns_hold_real_datetimes_not_strings():
    """The sort-correctness test depends on these being datetime objects."""
    rows = make_rows(50)
    stamped = [r for r in rows if r["AccessedUtc"] is not None]
    assert stamped
    assert all(isinstance(r["AccessedUtc"], datetime.datetime) for r in stamped)


def test_some_values_are_blank_so_blank_handling_is_exercised():
    rows = make_rows(500)
    assert any(r["Title"] == "" for r in rows)
    assert any(r["AccessedUtc"] is None for r in rows)
