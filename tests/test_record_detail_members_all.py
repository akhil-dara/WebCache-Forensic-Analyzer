"""The record dialog of an aggregate (a domain, a period) lists its first
records at once and every other one on request, in place."""
from webcache.shell import detail_fields as df
from webcache.shell.record_detail import RecordDetailDialog
from tests.test_detail_fields import domain_row


def test_activating_show_all_lists_every_member(qtbot):
    members = [{"CleanUrl": "https://example.test/%d" % i} for i in range(700)]
    d = RecordDetailDialog(domain_row(_members=members, Records=700), None)
    qtbot.addWidget(d)
    fields = df.flatten(d.groups)
    more = next(i for i, f in enumerate(fields)
                if f.key == "aggregate:member_overflow")
    d.activate_field(more)
    openable = [f for f in df.flatten(d.groups) if f.target is not None]
    assert len(openable) == 700
