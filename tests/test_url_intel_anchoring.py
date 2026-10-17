"""The date anchor that never fires, and the provenance summarise() drops.

TWO defects in webcache/engine/url_intel.py, both live, both invisible
because the code that contains them has no failure mode -- it just
quietly does less than it says it does.

1. THE ANCHOR NEVER RUNS ON REAL EVIDENCE. scan_records() reads
   record[time_key] with time_key="AccessedTime" and keeps it only `if
   isinstance(when, datetime)`. On a live entry, ese_parser writes
   AccessedTime as filetime_to_str()'s output -- a STRING. The isinstance
   check is therefore False for every live record ever scanned, so
   record_time is always None, so _epoch_findings' single strongest
   corroboration test ("within a day of this record's own timestamp, so
   the two corroborate each other" -> HIGH) and its drift note ("+3.2
   days from this record's timestamp") have never executed against real
   evidence. Every epoch finding an examiner has seen was graded without
   the one piece of context that would have raised or explained it.

   The record carries AccessedTime_raw -- the int64 -- right beside the
   string. Reading that through filetime_to_dt is the whole fix.

2. summarise() THROWS AWAY WHICH FIELD THE INDICATOR CAME FROM.
   Finding already carries .field, .source and .record (they are declared
   __slots__ and scan_records sets all three), and summarise() keeps only
   count/decoded/confidence/reason. So a MAC address found inside a URL
   and one found inside a cached filename collapse into one
   indistinguishable row, and the Indicators view cannot say where it
   looked. url_intel.SCANNED_FIELDS covers five fields; the view shows
   none of them.

Both are pure-function defects, so both are testable with plain dicts and
no database.
"""
from datetime import datetime, timezone

from webcache.engine import url_intel

#: A query key url_intel._TIME_KEYS does NOT name. Deliberate, and it is
#: the difference between this file testing something and testing nothing:
#: a key that names a time is graded HIGH on its own name, so every
#: assertion below would pass whether the anchor fired or not.
UNNAMED_KEY = "id"

#: 2024-03-11 09:14:02 UTC, as a FILETIME and as a datetime -- the two
#: shapes ese_parser stores side by side in AccessedTime_raw and
#: AccessedTime.
ACCESSED_RAW = 133546220420000000
ACCESSED_DT = datetime(2024, 3, 11, 9, 14, 2, tzinfo=timezone.utc)


def _epoch_seconds(dt):
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def _live_shaped_record(url):
    """A live entry as ese_parser._parse_record actually produces one:
    AccessedTime is a formatted STRING, AccessedTime_raw is the int64."""
    return {
        "Url": url,
        "CleanUrl": url,
        "AccessedTime": "2024-03-11 09:14:02 UTC",
        "AccessedTime_raw": ACCESSED_RAW,
    }


# --- 1. the anchor ---------------------------------------------------------

def test_a_live_entry_anchors_its_epoch_finding_to_its_own_timestamp():
    """The whole point of the anchor: an unnamed digit run that lands
    within a day of the record's own time corroborates it, and is HIGH
    rather than LOW.

    This fails on today's code -- AccessedTime is a string, isinstance()
    rejects it, and the finding comes back LOW with the "nothing names it
    a time" reason.
    """
    stamp = _epoch_seconds(ACCESSED_DT)
    url = "https://example.test/a?%s=%d" % (UNNAMED_KEY, stamp)
    findings = url_intel.scan_records([_live_shaped_record(url)])

    epochs = [f for f in findings if f.kind == "Epoch timestamp"]
    assert epochs, "the digit run should have decoded to a plausible date"
    assert epochs[0].confidence == url_intel.HIGH, (
        "a value within a day of the record's own AccessedTime is "
        "corroborated by it; this is the anchor that has never run")
    assert "corroborate" in epochs[0].reason


def test_a_disagreeing_epoch_gets_its_drift_stated_not_averaged_away():
    """The other half of the anchor: a time that disagrees with the
    record's own time is worth an examiner's attention, and the finding
    is supposed to say by how much."""
    stamp = _epoch_seconds(
        ACCESSED_DT.replace(year=ACCESSED_DT.year - 1))
    url = "https://example.test/a?%s=%d" % (UNNAMED_KEY, stamp)
    findings = url_intel.scan_records([_live_shaped_record(url)])

    epochs = [f for f in findings if f.kind == "Epoch timestamp"]
    assert epochs
    assert "days from this record's timestamp" in epochs[0].decoded, (
        "an embedded time that disagrees with the record's own must state "
        "the drift rather than be reported as an unqualified date")


def test_a_record_with_no_usable_time_still_scans_and_claims_no_anchor():
    """No AccessedTime_raw and no parseable string means no anchor. The
    scan must still run and the finding must not claim corroboration it
    does not have."""
    stamp = _epoch_seconds(ACCESSED_DT)
    findings = url_intel.scan_records([
        {"Url": "https://example.test/a?%s=%d" % (UNNAMED_KEY, stamp), "CleanUrl": ""}])

    epochs = [f for f in findings if f.kind == "Epoch timestamp"]
    assert epochs
    assert epochs[0].confidence != url_intel.HIGH
    assert "corroborate" not in epochs[0].reason


def test_a_real_datetime_in_the_column_still_anchors():
    """A carved record's NearbyFiletime and the existing call shape both
    hand real datetimes in. Reading the _raw sibling must not break the
    path that already worked."""
    stamp = _epoch_seconds(ACCESSED_DT)
    findings = url_intel.scan_records([{
        "Url": "https://example.test/a?%s=%d" % (UNNAMED_KEY, stamp),
        "AccessedTime": ACCESSED_DT,
    }])

    epochs = [f for f in findings if f.kind == "Epoch timestamp"]
    assert epochs and epochs[0].confidence == url_intel.HIGH


def test_a_naive_datetime_is_still_read_as_utc():
    """Existing behaviour, pinned so the raw-first change cannot drop it."""
    stamp = _epoch_seconds(ACCESSED_DT)
    findings = url_intel.scan_records([{
        "Url": "https://example.test/a?%s=%d" % (UNNAMED_KEY, stamp),
        "AccessedTime": ACCESSED_DT.replace(tzinfo=None),
    }])

    epochs = [f for f in findings if f.kind == "Epoch timestamp"]
    assert epochs and epochs[0].confidence == url_intel.HIGH


# --- 2. what summarise() keeps --------------------------------------------

def test_summarise_keeps_which_field_each_value_was_found_in():
    """An examiner cannot weigh an indicator without knowing where it was
    read. A MAC address inside a URL and one inside a cached filename are
    different claims; today they are the same row.

    Two records, not one with both fields set: scan_records deliberately
    collapses identical (kind, value) pairs WITHIN one record (see its own
    docstring), so a single record can only ever name the first field the
    value was seen in. Across records is exactly the case the Indicators
    view aggregates over."""
    mac = "00-1A-2B-3C-4D-5E"
    records = [{"Url": "https://example.test/%s/a" % mac},
               {"Url": "https://other.test/b", "Filename": "log-%s.txt" % mac}]
    tally = url_intel.summarise(url_intel.scan_records(records))

    macs = tally.get("MAC address") or {}
    assert macs, "the calibrated MAC extractor should have fired"
    info = next(iter(macs.values()))
    assert "fields" in info, "summarise must keep Finding.field"
    assert isinstance(info["fields"], set)
    assert info["fields"] == {"URL", "File name"}, (
        "both scanned fields carried this value and both must be named")


def test_summarise_keeps_a_reference_to_every_originating_record():
    """The Indicators view's "Records: N" is a dead number without them.
    References, never copies -- the records are already resident."""
    stamp = _epoch_seconds(ACCESSED_DT)
    a = _live_shaped_record("https://example.test/a?%s=%d" % (UNNAMED_KEY, stamp))
    b = _live_shaped_record("https://other.test/b?%s=%d" % (UNNAMED_KEY, stamp))
    tally = url_intel.summarise(url_intel.scan_records([a, b]))

    epochs = tally.get("Epoch timestamp") or {}
    assert epochs
    info = next(iter(epochs.values()))
    assert "records" in info, "summarise must keep Finding.record"
    assert len(info["records"]) == info["count"]
    assert any(r is a for r in info["records"]), (
        "identity, not equality -- a copy would double the memory of "
        "every record an indicator touches")
    assert any(r is b for r in info["records"])
