"""Opening an exhibit keeps the window responsive.

The derived row sets the views read are computed once and cached, and the
parse and recovery workers compute them before reporting, so the GUI
thread only fills grids. A short interpreter switch interval lets the GUI
thread take the GIL back promptly while a worker computes."""
import sys

from webcache.shell import derived


class _Parser:
    def __init__(self, entries):
        self.all_entries = entries


class _Engine:
    def __init__(self):
        self.structured_records = []
        self.calls = 0
        self.tombstones = []

    def all_artifacts(self):
        self.calls += 1
        return [{"Url": "https://example.test/x", "RecoverySource": "slack"}]


def test_a_derived_set_is_computed_once():
    parser = _Parser([{"Url": "https://example.test/a",
                       "CleanUrl": "https://example.test/a"}])
    engine = _Engine()
    first = derived.carved_entries(parser, engine)
    assert derived.carved_entries(parser, engine) is first
    assert engine.calls == 1


def test_replaced_entries_are_recomputed_not_read_stale():
    parser = _Parser([])
    before = derived.domains(parser)
    parser.all_entries = [{"Url": "https://example.test/a",
                           "CleanUrl": "https://example.test/a"}]
    assert derived.domains(parser) is not before


def test_the_workers_fill_the_cache_before_they_report():
    parser = _Parser([{"Url": "https://example.test/a",
                       "CleanUrl": "https://example.test/a"}])
    engine = _Engine()
    derived.precompute_live(parser)
    derived.precompute_recovery(parser, engine)
    cached = {k for k in vars(engine)["_wc_derived"]}
    for name in ("carved_entries", "deleted_records", "domains_merged",
                 "indicators_merged", "timeline_merged"):
        assert name in cached, name
    assert {"domains_live", "indicators_live", "timeline_live"} <= set(
        vars(parser)["_wc_derived"])


def test_the_app_sets_a_short_switch_interval():
    from webcache import __main__ as entry
    old = sys.getswitchinterval()
    try:
        entry.keep_the_window_responsive()
        assert sys.getswitchinterval() <= 0.001
    finally:
        sys.setswitchinterval(old)
