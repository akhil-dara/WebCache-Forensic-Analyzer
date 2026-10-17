"""integrity_loader: shaping WebCacheParser.get_database_info() into what
IntegrityView's three cards actually render, tested against plain dicts the
same way every other *_loader module in this package is (see
test_evidence_loader_containers.py's own docstring for why: there is no
real WebCacheV01.dat on this machine for CI to parse).

hash_rows() is the one genuinely new piece of shaping: source_hashes is a
bare filename -> hex dict, and the ROLE matters more than the hash itself -- which file is the transaction log is
what determines what a recovery scan actually had to work with. Every case
below is a real ese_parser.evidence_scope() filename shape: the database
file itself, V01.log (current), a rolled V01xxxxx.log, V01.chk, and the
.jrs/.jfm reserved-log siblings that get hashed for completeness but are
never parsed by the recovery carve (see recovery_engine.py's own
_iter_log_paths, which only ever globs *.log/.chk).
"""
from webcache.engine.evidence_model import SCOPE_STATEMENTS
from webcache.shell.integrity_loader import (decision_log_rows, hash_rows,
                                             source_integrity_rows)

_SOURCE_HANDLING_TEXT = next(
    text for heading, text in SCOPE_STATEMENTS if heading == "Source handling")


def _info(**overrides):
    base = {
        "path": r"C:\case\WebCacheV01.dat",
        "db_state_text": "Dirty shutdown",
        "derived_tz": "UTC+05:30",
        "parse_stats": {"parsed": 610, "skipped": 0, "errors": 0},
        "source_hashes": {"WebCacheV01.dat": "a" * 64},
        "decision_log": ["Opened read-only: WebCacheV01.dat (DIRTY shutdown)"],
    }
    base.update(overrides)
    return base


# --- hash_rows: role determination --------------------------------------

def test_the_database_file_itself_is_labelled_as_the_exhibit():
    rows = hash_rows(_info())
    assert rows[0]["File"] == "WebCacheV01.dat"
    assert "exhibit itself" in rows[0]["Role"].lower()
    assert rows[0]["SHA256"] == "a" * 64


def test_the_current_transaction_log_is_distinguished_from_a_rolled_one():
    rows = hash_rows(_info(source_hashes={
        "WebCacheV01.dat": "a" * 64,
        "V01.log": "b" * 64,
        "V0100023.log": "c" * 64,
    }))
    by_file = {r["File"]: r["Role"] for r in rows}
    assert "current" in by_file["V01.log"].lower()
    assert "rolled" in by_file["V0100023.log"].lower()
    # Both are transaction logs -- and both say so, not just "current"/
    # "rolled" with no shared word tying them to the same category.
    assert "transaction log" in by_file["V01.log"].lower()
    assert "transaction log" in by_file["V0100023.log"].lower()


def test_the_checkpoint_file_is_labelled_distinctly_from_a_transaction_log():
    rows = hash_rows(_info(source_hashes={
        "WebCacheV01.dat": "a" * 64, "V01.chk": "d" * 64}))
    role = next(r["Role"] for r in rows if r["File"] == "V01.chk")
    assert "checkpoint" in role.lower()
    assert "transaction log" not in role.lower()


def test_reserved_log_files_say_they_are_not_parsed_by_the_recovery_carve():
    rows = hash_rows(_info(source_hashes={
        "WebCacheV01.dat": "a" * 64,
        "V0100023.jrs": "e" * 64,
        "V01.jfm": "f" * 64,
    }))
    by_file = {r["File"]: r["Role"] for r in rows}
    for fn in ("V0100023.jrs", "V01.jfm"):
        assert "not parsed" in by_file[fn].lower()


def test_the_database_file_sorts_first_then_alphabetically():
    rows = hash_rows(_info(source_hashes={
        "V01.log": "b" * 64,
        "V01.chk": "d" * 64,
        "WebCacheV01.dat": "a" * 64,
    }))
    assert [r["File"] for r in rows] == ["WebCacheV01.dat", "V01.chk", "V01.log"]


def test_a_single_file_exhibit_yields_exactly_one_row():
    """The common real-evidence case: no sibling transaction logs survived
    next to the .dat at all, so evidence_scope() -- and therefore
    source_hashes -- holds only the database file itself."""
    rows = hash_rows(_info())
    assert len(rows) == 1


# --- source_integrity_rows: the Source Integrity card ---------------------

def test_source_integrity_rows_cover_every_field_the_brief_names_in_order():
    rows = source_integrity_rows(_info())
    labels = [r["label"] for r in rows]
    assert labels == ["Database state", "Read-only guarantee",
                      "Derived machine TZ", "Records (URL-cache entries)",
                      "Rows parsed, all tables",
                      "Tables skipped", "Record errors"]


def _by_label(info):
    return {r["label"]: r for r in source_integrity_rows(info)}


def test_database_state_is_the_parsers_own_text():
    rows = _by_label(_info(db_state_text="Clean shutdown"))
    assert rows["Database state"]["value"] == "Clean shutdown"


def test_derived_tz_reads_honestly_when_it_could_not_be_derived():
    """derived_tz is "" when parse_all_entries() had fewer than 5 SPS/
    ModifiedTime pairs to derive a delta from (see ese_parser.py) -- an
    empty string on screen would read as a blank field, not as "this
    could not be computed"."""
    rows = _by_label(_info(derived_tz=""))
    assert rows["Derived machine TZ"]["value"] != ""


def test_records_parsed_tables_skipped_and_record_errors_come_from_parse_stats():
    rows = _by_label(_info(parse_stats={"parsed": 993, "skipped": 2, "errors": 7}))
    # "Records parsed" became "Rows parsed, all tables"; the records
    # figure is the parser's own total_entries.
    assert "993" in rows["Rows parsed, all tables"]["value"]
    assert "2" in rows["Tables skipped"]["value"]
    assert "7" in rows["Record errors"]["value"]


def test_the_read_only_guarantee_is_true_of_this_ports_open_path():
    """WebCacheParser.open() (ese_parser.py) does exactly
    `self.db_file = open(db_path, "rb")` then hands that file object to
    EseDB -- no write-mode open anywhere on the evidence path, and no
    esentutl/soft-recovery call anywhere in the engine. What is shown must
    state that fact, in a phrasing this test can hold the code to: it must
    name the actual read mode ('rb') AND state that no soft recovery ran
    -- not a vaguer paraphrase of either half."""
    rows = _by_label(_info())
    guarantee = rows["Read-only guarantee"]["value"]
    assert "'rb'" in guarantee or '"rb"' in guarantee
    assert "soft recovery" in guarantee.lower() or "esentutl" in guarantee.lower()


def test_the_read_only_guarantee_links_to_the_canonical_scope_statement():
    """This project already has ONE vetted, court-facing statement of this
    exact fact -- evidence_model.SCOPE_STATEMENTS' "Source handling" entry,
    which every export already carries verbatim. The Integrity view must
    not invent a second, differently-worded claim with no link back to it
    -- the row's own tooltip carries the full canonical text, so the two
    can never quietly drift apart."""
    rows = _by_label(_info())
    assert rows["Read-only guarantee"]["tooltip"] == _SOURCE_HANDLING_TEXT


def test_every_row_carries_a_tooltip_key_even_when_blank():
    """A caller that reads row["tooltip"] unconditionally (the view does)
    must never KeyError on a row this function did not bother to annotate."""
    for row in source_integrity_rows(_info()):
        assert "tooltip" in row


# --- decision_log_rows: skipped tables and record errors stay visible -----

def test_decision_log_rows_preserve_every_line_in_order():
    log = ["line one", "line two", "line three"]
    rows = decision_log_rows(_info(decision_log=log))
    assert [r["text"] for r in rows] == log


def test_a_skipped_table_line_is_flagged():
    rows = decision_log_rows(_info(decision_log=[
        "Opened read-only: WebCacheV01.dat (DIRTY shutdown)",
        "Container_9 (Foo): registered in Containers but table absent",
        "SomeTable: SKIPPED — permission denied",
    ]))
    flagged = [r["flagged"] for r in rows]
    assert flagged == [False, True, True]


def test_a_record_error_line_is_flagged():
    rows = decision_log_rows(_info(decision_log=[
        "Container_2 (History): 3/50 records failed to parse",
    ]))
    assert rows[0]["flagged"] is True


def test_an_empty_decision_log_yields_no_rows():
    assert decision_log_rows(_info(decision_log=[])) == []
