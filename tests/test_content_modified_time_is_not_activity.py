"""A cached file's ModifiedTime is the server's date, not activity here.

Found working "over what period was this profile active": the activity
span began ten years before the database was created. Every record
behind that was a Content (cache) record keyed on its ModifiedTime, and
on the exhibit every live Content record with one dated it a day or
more before the cache entry itself was created -- it cannot be when
anything happened on this machine. For a History record ModifiedTime is
the visit; for any other known container the key instant is when the
cache entry was last used, else when it was written."""
from webcache.engine import forensic_engine as fe

OLD = 130818000000000000           # 2015-07-13
USED = 134155000000000000          # 2026-02-15
MADE = 134150000000000000          # 2026-02-09


def test_a_cached_files_key_time_is_when_it_was_used_here():
    raw, basis = fe.key_timestamp({"ContainerType": "Content",
                                   "ModifiedTime_raw": OLD,
                                   "AccessedTime_raw": USED,
                                   "CreationTime_raw": MADE})
    assert raw == USED
    assert basis.startswith("AccessedTime")


def test_without_a_use_time_it_is_when_it_was_cached():
    raw, basis = fe.key_timestamp({"ContainerType": "Content",
                                   "ModifiedTime_raw": OLD,
                                   "CreationTime_raw": MADE})
    assert raw == MADE
    assert basis.startswith("CreationTime")


def test_a_history_records_key_time_is_still_its_visit():
    raw, basis = fe.key_timestamp({"ContainerType": "History",
                                   "ModifiedTime_raw": USED,
                                   "AccessedTime_raw": MADE})
    assert raw == USED
    assert basis.startswith("ModifiedTime")


def test_an_unknown_container_keeps_its_modified_time():
    """Nothing says what its ModifiedTime means, so it is not reinterpreted."""
    raw, _basis = fe.key_timestamp({"ModifiedTime_raw": OLD,
                                    "AccessedTime_raw": USED})
    assert raw == OLD


def test_the_display_names_the_same_instant():
    text, basis = fe.key_timestamp_display({
        "ContainerType": "Content", "ModifiedTime_raw": OLD,
        "ModifiedTime": "2015-07-13 06:49:22", "AccessedTime_raw": USED,
        "AccessedTime": "2026-02-15 10:00:00"})
    assert text.startswith("2026-02-15")
    assert basis.startswith("AccessedTime")
