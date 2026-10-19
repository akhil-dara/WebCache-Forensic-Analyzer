"""A recovered record's container, from evidence the record or its page
holds, with how it was found stated beside it.

Measured on a real exhibit: every reconstructed record from a container
Windows had since dropped showed "Not determinable" although its own URL
carried the dated-history prefix that names the container; and every
string carved from a database page showed no container although the
page's header names the B-tree that owns it. Validated there first:
every reconstructed record on a live container's page carried that
container's id (no mismatch), and every dropped tree's records named
exactly one container.
"""
from webcache.engine import recovery_engine
from webcache.engine.ese_parser import normalise_record

META = [{"ContainerId": 6, "Name": "History"},
        {"ContainerId": 12, "Name": "MSHist012026020220260209"}]
TYPES = {6: "History", 12: "History"}


def test_a_dropped_dated_history_container_is_named_by_the_records_prefix():
    rec = {"ContainerId": 999,
           "Url": ":2025010120250108: user@https://site.test/page"}
    normalise_record(rec, META, TYPES)
    assert rec["ContainerType"] == "History"
    assert rec["ContainerName"] == "MSHist012025010120250108"
    assert "no longer listed" in rec["ContainerFrom"]


def test_without_the_prefix_a_dropped_container_stays_unknown():
    rec = {"ContainerId": 999, "Url": "https://site.test/page"}
    normalise_record(rec, META, TYPES)
    assert rec["ContainerType"] == ""
    assert not rec.get("ContainerFrom")


def test_a_listed_container_needs_no_explanation():
    rec = {"ContainerId": 6, "Url": "Visited: user@https://site.test/"}
    normalise_record(rec, META, TYPES)
    assert rec["ContainerType"] == "History"
    assert not rec.get("ContainerFrom")


def test_a_carved_string_takes_the_container_its_page_belongs_to():
    objid = {10: 44, 20: 368, 21: 368, 30: 37, 40: 50, 41: 50, 42: 50}
    carved = [{"Page": 10}, {"Page": 20}, {"Page": 30}, {"Page": 40}]
    structured = [{"Page": 21, "ContainerId": 359},
                  {"Page": 41, "ContainerId": 7},
                  {"Page": 42, "ContainerId": 8}]
    recovery_engine.attribute_page_owners(
        carved, structured, objid.get, live_owner={44: 6})
    on_live, on_dropped, on_unknown, on_split = carved
    assert on_live["ContainerId"] == 6
    assert "Container_6" in on_live["ContainerFrom"]
    assert on_dropped["ContainerId"] == 359
    assert "no longer listed" in on_dropped["ContainerFrom"]
    assert "ContainerId" not in on_unknown
    # Records on one tree naming two containers settle nothing.
    assert "ContainerId" not in on_split


def test_a_carve_that_already_has_a_container_is_left_alone():
    carved = [{"Page": 10, "ContainerId": 3}]
    recovery_engine.attribute_page_owners(
        carved, [], {10: 44}.get, live_owner={44: 6})
    assert carved[0]["ContainerId"] == 3
    assert "ContainerFrom" not in carved[0]


def test_an_inferred_container_is_badged_inferred_not_observed():
    from webcache.shell import detail_fields as df
    rec = {"ContainerId": 5, "ContainerName": "Content",
           "ContainerType": "Content",
           "ContainerFrom": "Inferred from the database page ..."}
    for key in ("ContainerId", "ContainerName", "ContainerType"):
        short, tip = df.basis_badge(key, carved=True, record=rec)
        assert short == "INF", key
        assert "Inferred from the database page" in tip
    # A row whose engine record carries the note is read the same way.
    short, _tip = df.basis_badge("ContainerId", carved=True,
                                 record={"_record": rec})
    assert short == "INF"
    # A record that stored its container keeps OBS.
    short, _tip = df.basis_badge("ContainerId", carved=True,
                                 record={"ContainerId": 5})
    assert short == "OBS"


def test_every_export_carries_how_the_container_was_found():
    """The exports render from one schema; an inferred container would
    otherwise read there as a stored one."""
    from webcache.engine import forensic_engine as fe
    keys = [k for k, _h, _g in fe.ENTRY_FIELDS]
    assert keys.index("ContainerFrom") == keys.index("ContainerType") + 1
    header = dict((k, h) for k, h, _g in fe.ENTRY_FIELDS)["ContainerFrom"]
    assert header == "ContainerIdentifiedBy"
    row = fe.build_entry_row({"ContainerId": 5, "ContainerFrom": "Inferred x"})
    assert row["ContainerFrom"] == "Inferred x"


class _Unreadable:
    page_size = 32768

    def tables(self):
        raise OSError("damaged catalog")

    def page(self, n):
        raise OSError("damaged page")


def test_a_database_it_cannot_read_leaves_the_carves_as_they_are():
    """Attribution is an addition; a damaged database must never cost the
    recovery itself."""
    eng = recovery_engine.RecoveryEngine()
    eng.page_artifacts = [{"Page": 10, "Url": "https://a.test/"}]
    eng.structured_records = [{"Page": 11, "ContainerId": 6}]
    eng.attribute_carved_pages(_Unreadable())
    assert eng.page_artifacts == [{"Page": 10, "Url": "https://a.test/"}]
    assert any("container" in line.lower() for line in eng.decision_log)


def test_the_decision_log_states_how_many_were_attributed():
    class _Page:
        def __init__(self, oid):
            self.header = type("H", (), {"objidFDP": oid})()

    class _Table:
        name, root_page = "Container_6", 1

    class _Db:
        page_size = 32768

        def tables(self):
            return [_Table()]

        def page(self, n):
            return _Page({1: 44, 10: 44, 20: 99}[n])

    eng = recovery_engine.RecoveryEngine()
    eng.page_artifacts = [{"Page": 10}, {"Page": 20}]
    eng.structured_records = []
    eng.attribute_carved_pages(_Db())
    assert eng.page_artifacts[0]["ContainerId"] == 6
    assert "ContainerId" not in eng.page_artifacts[1]
    assert "1 of 2 string(s)" in eng.decision_log[-1]
