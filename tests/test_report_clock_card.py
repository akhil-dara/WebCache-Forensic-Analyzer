"""The offline report states the clock offsets the Integrity screen does.

The Clock card -- every UTC offset the SPS local/UTC pairs show, with
records and dates and whether it was adopted -- was missing from the
HTML report, so a colleague reading it could not see which zone the
machine kept, or that a second offset appeared."""
from pathlib import Path

from webcache.shell import package_snapshot

INFO = {"clock_offsets": [
    {"offset": "UTC+02:00", "records": 40, "first": "2026-01-02",
     "last": "2026-02-16", "adopted": True, "source": "live"},
    {"offset": "UTC+00:00", "records": 1, "first": "2026-01-05",
     "last": "2026-01-05", "adopted": False, "source": "live"}]}


def test_the_reports_integrity_section_carries_each_observed_offset():
    clock = package_snapshot.integrity_section(INFO)["clock"]
    labels = [row[0] for row in clock]
    assert labels == ["UTC+02:00", "UTC+00:00"]
    assert "40 records, 2026-01-02 to 2026-02-16" in clock[0][1]
    assert "not adopted" in clock[1][1]


def test_the_apps_display_format_is_not_reported_as_a_fact():
    """"Times shown as" is this examiner's View setting, not evidence."""
    clock = package_snapshot.integrity_section(INFO)["clock"]
    assert not any(row[0] == "Times shown as" for row in clock)


def test_no_offset_observed_is_stated_not_left_out():
    clock = package_snapshot.integrity_section({})["clock"]
    assert clock and "no offset was observed" in clock[0][1]


def test_the_page_renders_the_clock_card():
    boot = (Path(package_snapshot.__file__).parent / "html_package_assets"
            / "boot.js").read_text(encoding="utf-8")
    assert 'el("h2", null, "Clock")' in boot
    assert "kvTable(integrity.clock)" in boot
