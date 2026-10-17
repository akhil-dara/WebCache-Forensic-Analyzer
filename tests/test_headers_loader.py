"""The HTTP Headers row set: which records carry headers, and what the
raw blob says that the decoded dict cannot.

Two facts this file exists to pin:

THE SPS EXCLUSION. ese_parser decodes a response-headers blob by its
observed CLASS, not by its container: a blob that classifies "sps" is a
property store and produces no header dict at all. On a History-heavy
exhibit that is most of the database, so this view legitimately shows a
handful of rows against a status bar reading hundreds -- and the
predicate that causes it has to be provable, not folklore.

WIRE ORDER, AND THE DUPLICATES THE DICT ATE. decode_content_headers
returns a plain dict, so a repeated Set-Cookie is collapsed to its last
occurrence and header order is thrown away by anything that sorts the
keys. header_pairs() re-splits the RAW blob, so both survive -- and
PairCount is what makes "Export header pairs (N)" a number the written
file can be held to.
"""
import datetime

import pytest

from webcache import provenance
from webcache.engine import ese_parser
from webcache.shell import headers_loader as H
from webcache.shell.record_kinds import K_CARVED_STRUCT

#: A real-looking FILETIME: 2024-03-11 09:14:02 UTC.
FT = 133546220420000000

#: Two Set-Cookie lines with the SAME name -- the collapse the decoded
#: dict performs and this module's whole reason for reading the raw blob.
RESP_BLOB = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n"
    b"Server: nginx/1.25.3\r\n"
    b"Set-Cookie: a=1; Path=/\r\n"
    b"Set-Cookie: b=2; Path=/\r\n"
    b"X-Forwarded-For: 203.0.113.7\r\n"
    b"\r\n")

REQ_BLOB = (b"Accept: */*\r\n"
            b"Accept-Language: en-GB\r\n"
            b"\r\n")


def _entry(**overrides):
    """A live Content-container record carrying both header sides."""
    entry = {
        "ContainerType": "Content",
        "ContainerId": 5,
        "ContainerName": "Content",
        "EntryId": 41,
        "Url": "https://example.test/page",
        "CleanUrl": "https://example.test/page",
        "ModifiedTime_raw": FT,
        "ResponseHeaders_raw": RESP_BLOB,
        "RequestHeaders_raw": REQ_BLOB,
        "ResponseHeaders": ese_parser.decode_content_headers(RESP_BLOB),
        "RequestHeaders": ese_parser.decode_content_headers(REQ_BLOB),
        "BlobClass": "http",
    }
    entry.update(overrides)
    return entry


def _sps_entry():
    """A History record whose ResponseHeaders blob is a property store.

    ese_parser gives it SPS_* fields and NO ResponseHeaders dict at all --
    the exact shape the exclusion below is about.
    """
    return {
        "ContainerType": "History",
        "ContainerId": 3,
        "EntryId": 9,
        "CleanUrl": "https://example.test/visited",
        "ModifiedTime_raw": FT,
        "ResponseHeaders_raw": b"\x01\x00\x00\x00propstore",
        "BlobClass": "sps",
        "SPS_VisitCount": 4,
    }


class _StubParser:
    def __init__(self, entries):
        self.all_entries = list(entries)


class _StubEngine:
    def __init__(self, records):
        self.structured_records = list(records)


# --- the predicate --------------------------------------------------------

def test_a_record_with_a_response_header_dict_carries_headers():
    assert H.carries_headers(_entry()) is True


def test_a_record_with_only_request_headers_carries_headers():
    """"ResponseHeaders OR RequestHeaders" -- a cached request whose
    response blob never decoded is still a header record."""
    entry = _entry()
    entry.pop("ResponseHeaders")
    assert H.carries_headers(entry) is True


def test_an_sps_record_does_not_carry_headers():
    """THE EXCLUSION, stated as a test rather than as a docstring: a
    property store is not a header set, and a History record whose blob
    classifies "sps" gets no header dict from the parser at all."""
    assert H.carries_headers(_sps_entry()) is False


def test_an_empty_header_dict_does_not_carry_headers():
    """An empty dict is not "headers were stored and were empty" -- it is
    a decode that produced nothing. Counting it would put a row on screen
    with nothing in it."""
    assert H.carries_headers(_entry(ResponseHeaders={},
                                    RequestHeaders={})) is False


def test_the_sps_record_is_absent_from_the_row_set():
    rows = H.header_rows_from_parser(_StubParser([_entry(), _sps_entry()]))
    assert len(rows) == 1
    assert rows[0]["EntryId"] == 41


# --- wire order and the collapsed duplicates ------------------------------

def test_header_pairs_preserve_wire_order():
    pairs = H.header_pairs(_entry(), "response")
    names = [name for _o, name, _v, _r in pairs]
    assert names == [H.STATUS_LINE_LABEL, "Content-Type", "Server",
                     "Set-Cookie", "Set-Cookie", "X-Forwarded-For"]


def test_header_pairs_ordinals_are_one_based_and_contiguous():
    """Ordinal is what preserves wire order in a file whoever opens it
    will sort by something else."""
    pairs = H.header_pairs(_entry(), "response")
    assert [o for o, _n, _v, _r in pairs] == list(range(1, len(pairs) + 1))


def test_both_repeated_headers_survive_the_dict_that_collapsed_them():
    """The decoded dict keeps one Set-Cookie; the raw blob has two, and
    both values are here."""
    decoded = _entry()["ResponseHeaders"]
    assert decoded["Set-Cookie"] == "b=2; Path=/"
    values = [v for _o, n, v, _r in H.header_pairs(_entry(), "response")
              if n == "Set-Cookie"]
    assert values == ["a=1; Path=/", "b=2; Path=/"]


def test_a_repeated_name_is_flagged_and_a_unique_one_is_not():
    flags = {name: repeats
             for _o, name, _v, repeats in H.header_pairs(_entry(), "response")}
    assert flags["Set-Cookie"] is True
    assert flags["Server"] is False


def test_the_status_line_is_renamed_not_left_as_the_synthetic_key():
    """_status_line is this tool's own plumbing. A report carrying an
    underscore-prefixed key is the tool showing its wiring."""
    names = [n for _o, n, _v, _r in H.header_pairs(_entry(), "response")]
    assert "_status_line" not in names
    assert names[0] == H.STATUS_LINE_LABEL


def test_request_pairs_come_from_the_request_blob_only():
    names = [n for _o, n, _v, _r in H.header_pairs(_entry(), "request")]
    assert names == ["Accept", "Accept-Language"]


def test_header_pairs_of_a_record_with_no_blob_is_empty():
    assert H.header_pairs({}, "response") == []


# --- the row ---------------------------------------------------------------

def test_row_key_count_stays_inside_its_size_bucket():
    """21 keys, the same ceiling every other record row in this package
    keeps -- see tests/test_row_is_a_record.py for the measured buckets.
    The 22nd key would cross a dict size boundary and belongs on _record.
    """
    import sys
    row = H.header_rows_from_parser(_StubParser([_entry()]))[0]
    assert len(row) <= 21, sorted(row)
    baseline = {("k%03d" % i): i for i in range(21)}
    assert sys.getsizeof(row) == sys.getsizeof(baseline)


def test_the_row_points_at_the_engine_record_rather_than_copying_it():
    entry = _entry()
    row = H.header_rows_from_parser(_StubParser([entry]))[0]
    assert row["_record"] is entry
    assert row["_record"]["ResponseHeaders_raw"] is RESP_BLOB


def test_the_row_counts_distinct_names_not_lines():
    """RespCount is what the decoded field list holds, so it excludes the
    synthetic status line and counts a repeated name once."""
    row = H.header_rows_from_parser(_StubParser([_entry()]))[0]
    assert row["RespCount"] == 4      # Content-Type, Server, Set-Cookie, XFF
    assert row["ReqCount"] == 2


def test_resp_count_agrees_with_the_engines_own_decoded_dict():
    """The two parses must not drift: RespCount is read off the raw blob,
    and the decoded dict is what the detail dialog renders."""
    entry = _entry()
    row = H.header_rows_from_parser(_StubParser([entry]))[0]
    decoded = dict(entry["ResponseHeaders"])
    decoded.pop("_status_line", None)
    assert row["RespCount"] == len(decoded)


def test_duplicate_count_is_the_number_of_lines_the_dict_dropped():
    row = H.header_rows_from_parser(_StubParser([_entry()]))[0]
    assert row["DuplicateCount"] == 1


def test_pair_count_equals_the_pairs_the_export_would_write():
    """The button label is a promise the written file has to keep. This is
    the arithmetic that makes it one."""
    rows = H.header_rows_from_parser(_StubParser([_entry()]))
    assert rows[0]["PairCount"] == len(H.pairs_for(rows[0]))
    assert H.total_pairs(rows) == 8   # 6 response lines + 2 request lines


def test_status_is_the_code_and_the_class_is_derived_from_it():
    row = H.header_rows_from_parser(_StubParser([_entry()]))[0]
    assert row["Status"] == "200"
    assert row["StatusClass"] == "2xx"


def test_a_response_with_no_status_line_says_empty_not_a_dash():
    """This codebase already has a vocabulary for absence. A second
    spelling of the same fact is a second thing every consumer has to
    learn -- see tests/test_absence_vocabulary.py."""
    blob = b"Content-Type: text/plain\r\n\r\n"
    entry = _entry(ResponseHeaders_raw=blob,
                   ResponseHeaders=ese_parser.decode_content_headers(blob))
    row = H.header_rows_from_parser(_StubParser([entry]))[0]
    assert row["Status"] == provenance.ABSENCE_EMPTY
    assert row["Status"] != "—"


def test_content_type_and_server_reach_their_own_columns():
    row = H.header_rows_from_parser(_StubParser([_entry()]))[0]
    assert row["ContentType"] == "text/html; charset=utf-8"
    assert row["Server"] == "nginx/1.25.3"


def test_a_client_ip_header_is_named_in_words_not_only_in_colour():
    """Colour alone is not a finding -- the earlier version highlighted
    these five names in amber and said nothing. This is the column that
    can be sorted, filtered and exported."""
    row = H.header_rows_from_parser(_StubParser([_entry()]))[0]
    assert "X-Forwarded-For" in row["ClientIpHeaders"]


def test_a_record_with_no_client_ip_header_leaves_the_column_blank():
    """Blank, not a token: the quick-filter chip is Condition("is not
    blank"), and an absence token there would match it."""
    blob = b"HTTP/1.1 204 No Content\r\nServer: x\r\n\r\n"
    entry = _entry(ResponseHeaders_raw=blob,
                   ResponseHeaders=ese_parser.decode_content_headers(blob),
                   RequestHeaders_raw=None, RequestHeaders={})
    row = H.header_rows_from_parser(_StubParser([entry]))[0]
    assert row["ClientIpHeaders"] == ""


def test_the_stored_instant_names_the_column_it_came_from():
    row = H.header_rows_from_parser(_StubParser([_entry()]))[0]
    assert isinstance(row["ModifiedTime"], datetime.datetime)
    assert row["ModifiedTimeBasis"]


def test_a_live_row_is_stamped_live_with_no_source():
    row = H.header_rows_from_parser(_StubParser([_entry()]))[0]
    assert row["Origin"] == "Live record"
    assert row["Source"] == ""


# --- carved ----------------------------------------------------------------

def test_a_carved_header_row_is_stamped_carved_and_names_its_source():
    """Origin is shown on these rows, so a carved header record and a
    live one are never visually identical in this view."""
    carved = _entry(Source="transaction log", RecoverySource="log")
    rows = H.carved_header_rows(_StubEngine([carved, _sps_entry()]))
    assert len(rows) == 1
    assert rows[0]["Origin"] == provenance.CARVED_ORIGIN
    assert rows[0]["Source"] == "transaction log"
    assert rows[0]["_kind"] is K_CARVED_STRUCT


def test_carved_rows_carry_the_identical_keys_a_live_row_does():
    """The two lists are concatenated with no reconciling pass, so a key
    one half carries and the other does not is how a merged set starts
    behaving differently depending on which half a row came from."""
    live = H.header_rows_from_parser(_StubParser([_entry()]))[0]
    carved = H.carved_header_rows(_StubEngine([_entry(Source="page slack")]))[0]
    assert set(live) == set(carved)


# --- the transient export shape -------------------------------------------

def test_pair_export_rows_carry_every_pair_and_stay_off_the_view_row():
    """_pairs is what export_formats.write_header_pairs_csv reads, and it
    is built at export time rather than stored on every row: a pair list
    per record is a decode the raw blob already holds, and the 22nd key
    would cross the row's size bucket."""
    rows = H.header_rows_from_parser(_StubParser([_entry()]))
    assert "_pairs" not in rows[0]
    out = H.pair_export_rows(rows)
    assert len(out) == 1
    assert len(out[0]["_pairs"]) == rows[0]["PairCount"]
    directions = {p[0] for p in out[0]["_pairs"]}
    assert directions == {"response", "request"}


def test_pair_export_rows_keep_the_origin_the_view_row_carried():
    carved = H.carved_header_rows(_StubEngine([_entry(Source="page slack")]))
    out = H.pair_export_rows(carved)
    assert out[0]["Origin"] == provenance.CARVED_ORIGIN
    assert out[0]["_kind"] is K_CARVED_STRUCT


@pytest.mark.parametrize("side", ["response", "request"])
def test_pairs_for_labels_each_side_by_name_not_by_position(side):
    """The distinction exists only in which key the dict came out of, so
    the file has to carry it explicitly."""
    rows = H.header_rows_from_parser(_StubParser([_entry()]))
    assert any(p[0] == side for p in H.pairs_for(rows[0]))


# --- defects the on-screen run exposed ------------------------------------

def test_the_duplicate_sentence_counts_the_lines_that_were_overwritten():
    """"N lines share a name with another" is not what N is.

    On the real exhibit one record had a header name appearing FOUR
    times: four lines share a name, and three were overwritten. N is the
    second number -- the lines the decoded field list no longer holds --
    so the sentence has to say that, not the first.
    """
    note = H.duplicates_note(3)
    assert "3" in note
    assert "overwritten by a later line with the same name" in note
    assert "share a name with another" not in note


def test_the_duplicate_sentence_still_says_where_every_value_is():
    note = H.duplicates_note(2)
    assert "pair export carries all of them" in note
    assert "keeps only the last of each" in note


def test_the_sentence_agrees_with_the_count_the_row_carries():
    """One repeated name appearing four times: three lines dropped."""
    from webcache.engine import ese_parser
    blob = (b"HTTP/1.1 200 OK\r\n"
            b"x-forward: a\r\nx-forward: b\r\nx-forward: c\r\n"
            b"x-forward: d\r\n\r\n")
    entry = _entry(ResponseHeaders_raw=blob,
                   ResponseHeaders=ese_parser.decode_content_headers(blob),
                   RequestHeaders_raw=None, RequestHeaders={})
    row = H.header_rows_from_parser(_StubParser([entry]))[0]
    assert row["DuplicateCount"] == 3
    assert len(H.header_pairs(entry, "response")) == 5
