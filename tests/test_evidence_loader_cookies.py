"""cookie_rows_from_parser / hsts_rows_from_parser / cert_rows_from_parser:
the three row sets CookiesView's segments expect, each tested against a
stub parser -- the same testable-without-a-real-database contract
history_rows_from_parser already follows (test_evidence_loader.py's own
docstring explains why: there is no real WebCacheV01.dat on this machine
for CI to parse).

Kept in its own file rather than appended to test_evidence_loader.py so
this task's diff stays additive to a file it did not need to touch.
"""
import datetime

from webcache.shell.evidence_loader import (cert_rows_from_parser,
                                             cookie_rows_from_parser,
                                             hsts_rows_from_parser)

# --- Cookies -----------------------------------------------------------


class _StubCookieParser:
    """Just enough of WebCacheParser's surface for cookie_rows_from_parser
    -- a list of dicts shaped the way _parse_cookie_table() actually
    produces them (see ese_parser.py)."""

    def __init__(self, cookie_entries):
        self.cookie_entries = cookie_entries


def _cookie_entry(**overrides):
    base = {
        "Domain": "example.com", "RDomain": "com.example",
        "Name": "sessionid", "Value": "abc123", "Path": "/",
        "Expires_raw": 133535904000000000,
        "LastModified_raw": 133535904000000000,
    }
    base.update(overrides)
    return base


def test_cookie_rows_carry_every_key_the_cookies_segment_reads():
    rows = cookie_rows_from_parser(_StubCookieParser([_cookie_entry()]))
    row = rows[0]
    for key in ("Domain", "Name", "Value", "Path", "Expires", "LastModified"):
        assert key in row, "CookiesView's cookies segment reads %r" % key


def test_cookie_domain_is_the_human_readable_unreversed_form():
    """cookie_entries carries both Domain (unreversed, human-readable) and
    RDomain (raw, reversed, as stored) -- the column shows Domain; RDomain
    is only the provenance badge (see COOKIE_COLUMNS' field=)."""
    rows = cookie_rows_from_parser(_StubCookieParser(
        [_cookie_entry(Domain="login.example.com", RDomain="com.example.login")]))
    assert rows[0]["Domain"] == "login.example.com"


def test_cookie_name_and_value_are_carried_through_unchanged():
    rows = cookie_rows_from_parser(_StubCookieParser(
        [_cookie_entry(Name="prefs", Value="dark-mode=1")]))
    assert rows[0]["Name"] == "prefs"
    assert rows[0]["Value"] == "dark-mode=1"


def test_cookie_expires_is_a_real_datetime_not_a_preformatted_string():
    """CookiesView's Expires column is kind='time'; record_filter.py's time
    operators compare actual datetime objects -- the same reasoning
    test_accessed_utc_is_a_real_datetime_not_a_preformatted_string pins for
    History in test_evidence_loader.py."""
    rows = cookie_rows_from_parser(_StubCookieParser([_cookie_entry()]))
    assert isinstance(rows[0]["Expires"], datetime.datetime)
    assert isinstance(rows[0]["LastModified"], datetime.datetime)


def test_cookie_with_no_expiry_raw_is_none_not_a_crash():
    rows = cookie_rows_from_parser(_StubCookieParser(
        [_cookie_entry(Expires_raw=0, LastModified_raw=None)]))
    assert rows[0]["Expires"] is None
    assert rows[0]["LastModified"] is None


# --- HSTS ----------------------------------------------------------------


class _StubHstsParser:
    def __init__(self, hsts_entries, all_entries=None):
        self.hsts_entries = hsts_entries
        self.all_entries = all_entries or []


def _hsts_entry(**overrides):
    base = {
        "Domain": "example.com", "IncludeSubdomains": False,
        "Expires": "2026-01-01 00:00:00 UTC", "LastTimeUsed": "",
        "LastTimeUsed_raw": 0,
    }
    base.update(overrides)
    return base


def test_hsts_rows_carry_every_key_the_hsts_segment_reads():
    rows = hsts_rows_from_parser(_StubHstsParser([_hsts_entry()]))
    row = rows[0]
    for key in ("Domain", "Corroborated", "Significance", "HostAttribution",
               "LastTimeUsed", "Expires", "IncludeSubdomains"):
        assert key in row, "CookiesView's HSTS segment reads %r" % key


def test_hsts_last_time_used_is_a_real_datetime_when_the_pin_was_used():
    rows = hsts_rows_from_parser(_StubHstsParser(
        [_hsts_entry(LastTimeUsed_raw=133535904000000000)]))
    assert isinstance(rows[0]["LastTimeUsed"], datetime.datetime)


def test_hsts_last_time_used_is_none_when_the_pin_was_never_used():
    """LastTimeUsed_raw is 0 for a pin ese_parser's own NEVER-sentinel check
    already turned into 'never used' -- filetime_to_dt(0) already returns
    None, so this is a plain pass-through, not a special case added here."""
    rows = hsts_rows_from_parser(_StubHstsParser([_hsts_entry(LastTimeUsed_raw=0)]))
    assert rows[0]["LastTimeUsed"] is None


def test_hsts_expires_is_passed_through_as_the_engine_supplied_it():
    """No raw FILETIME survives for Expires in hsts_entries (see
    ese_parser.py's _parse_hsts_table) -- only the engine's own
    pre-formatted string, or the literal 'never' for its NEVER sentinel.
    Reconstructing a datetime here would mean inventing a value the engine
    never actually gave this function -- the same discipline
    container_rows_from_parser's LastAccess/LastScavenge follow below."""
    rows = hsts_rows_from_parser(_StubHstsParser([_hsts_entry(Expires="never")]))
    assert rows[0]["Expires"] == "never"


def test_hsts_corroborated_reflects_whether_the_host_appears_elsewhere():
    stub = _StubHstsParser(
        [_hsts_entry(Domain="example.com")],
        all_entries=[{"CleanUrl": "https://example.com/a"}])
    rows = hsts_rows_from_parser(stub)
    assert rows[0]["Corroborated"] is True


def test_hsts_uncorroborated_pin_is_a_false_flag():
    """analysis_extra.hsts_visit_evidence returns 'NO' for an
    uncorroborated pin (kept for the exports); the row carries False, so
    the grid says No in the one form every flag uses."""
    stub = _StubHstsParser([_hsts_entry(Domain="nowhere.example")], all_entries=[])
    rows = hsts_rows_from_parser(stub)
    assert rows[0]["Corroborated"] is False


# --- Certificates ----------------------------------------------------------


class _StubCertParser:
    def __init__(self, cert_entries):
        self.cert_entries = cert_entries


def _cert_entry(**overrides):
    base = {
        "HostPort": "example.com:443", "IsCertificate": True,
        "Thumbprint": "aa11bb22", "BlobSize": 512,
        "ModifiedTime_raw": 133535904000000000,
    }
    base.update(overrides)
    return base


def test_cert_rows_carry_every_key_the_certificates_segment_reads():
    rows = cert_rows_from_parser(_StubCertParser([_cert_entry()]))
    row = rows[0]
    for key in ("HostPort", "IsCertificate", "Thumbprint", "BlobSize", "ModifiedTime"):
        assert key in row, "CookiesView's Certificates segment reads %r" % key


def test_cert_modified_time_is_a_real_datetime():
    rows = cert_rows_from_parser(_StubCertParser([_cert_entry()]))
    assert isinstance(rows[0]["ModifiedTime"], datetime.datetime)


def test_cert_is_certificate_stays_a_real_bool_not_a_string():
    rows = cert_rows_from_parser(_StubCertParser([_cert_entry(IsCertificate=False)]))
    assert rows[0]["IsCertificate"] is False
