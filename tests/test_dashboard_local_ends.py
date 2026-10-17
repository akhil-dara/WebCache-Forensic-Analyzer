"""The case summary's local activity range reads
each end on that record's own clock -- a History record's own observed
offset, as the Timeline cuts its day -- not the principal zone. On a DST
exhibit the summer end is an hour away from the winter zone."""
from webcache.engine import local_clock
from webcache.shell import dashboard_data
from tests.test_mshist_local_clock import SUMMER, WINTER, build_dst_parser


def test_a_summer_end_reads_its_own_offset_not_the_winter_zone():
    parser = build_dst_parser(winter=4, summer=3)
    assert parser.derived_tz_offset_seconds == WINTER
    rows = dict(dashboard_data.case_summary(parser))
    label, local = next((k, v) for k, v in rows.items()
                        if k.startswith("Activity (local"))
    latest = max((e for e in parser.all_entries
                  if not local_clock.is_mshist_record(e)),
                 key=lambda e: e["ModifiedTime_raw"])
    end = local_clock.local_naive(latest).strftime("%Y-%m-%d %H:%M:%S")
    assert local.endswith("%s (%s)" % (end, local_clock.zone_label(SUMMER))), \
        local
