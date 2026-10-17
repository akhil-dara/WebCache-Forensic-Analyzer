"""Cookies, HSTS entries and cached TLS certificates.

Three record sets behind one segmented switcher: they come from the same
auxiliary ESE tables (CookieEntryEx_*, HstsEntryEx_*, BlobEntry_*), and an
examiner working on one usually wants the others close by.

For HSTS, the Significance and HostAttribution columns state, per entry,
how far it establishes a visit to the host, in the engine's own wording
(engine/analysis_extra.hsts_visit_evidence).
"""
from ..engine.analysis_extra import (HSTS_ATTRIBUTION_HOST_ONLY,
                                     HSTS_ATTRIBUTION_SUBDOMAINS,
                                     HSTS_SIGNIFICANCE_CORROBORATED,
                                     HSTS_SIGNIFICANCE_UNCORROBORATED)
from ..widgets.column_spec import Column
from .records_view import RecordSet, RecordsView

#: Domain's field is "RDomain": the cell shows the readable domain, and the
#: badge names the stored (reversed) column it is derived from.
COOKIE_COLUMNS = [
    Column("Domain", "Domain", 220, kind="url", field="RDomain"),
    Column("Name", "Cookie name", 200, kind="text", field="CookieName"),
    Column("Value", "Value", None, kind="text", field="CookieValue"),
    Column("Path", "Path", 90, kind="text"),
    Column("Expires", "Expires (UTC)", 160, kind="time", field="Expires"),
    Column("LastModified", "Last modified (UTC)", 160, kind="time",
          field="LastModified"),
    # Bit 0x1 of the cookie's Flags, decoded by ese_parser. No field and
    # so no basis badge: the bit's meaning is an observed pattern, not a
    # documented or cited one.
    Column("IsSecure", "Secure", 80, kind="flag", field=None),
]

#: Corroborated carries hsts_visit_evidence's "yes"/"NO" strings as
#: written (see evidence_loader.hsts_rows_from_parser).
HSTS_COLUMNS = [
    Column("Domain", "Domain", 260, kind="url"),
    # The tool's statements about an entry are the same for every entry of
    # a kind, so they are given once in the header tooltips; the per-row
    # columns are optional and every export writes them.
    Column("Corroborated", "Other records?", 120, kind="flag",
          field="Corroborated",
          note=("What this shows, when the host appears in other records: "
                + HSTS_SIGNIFICANCE_CORROBORATED + "\n\n"
                "What this shows, when it does not: "
                + HSTS_SIGNIFICANCE_UNCORROBORATED)),
    Column("Significance", "What this shows", 420, kind="text",
          field="Significance", optional=True),
    Column("HostAttribution", "How far it pins the host", 300, kind="text",
          field="HostAttribution", optional=True),
    Column("LastTimeUsed", "Pin last used (UTC)", 165, kind="time",
          field="LastTimeUsed"),
    Column("Expires", "Expires", 130, kind="time", field="Expires"),
    Column("IncludeSubdomains", "Subdomains", 90, kind="flag",
          field="IncludeSubdomains",
          note=("How far the pin reaches the host, when it covers "
                "subdomains: " + HSTS_ATTRIBUTION_SUBDOMAINS + "\n\n"
                "When it does not: " + HSTS_ATTRIBUTION_HOST_ONLY)),
]

CERT_COLUMNS = [
    Column("HostPort", "Host : port", 300, kind="url", field="HostPort"),
    Column("IsCertificate", "Certificate", 90, kind="flag",
          field="IsCertificate"),
    Column("Thumbprint", "SHA-1 thumbprint", None, kind="text",
          field="Thumbprint"),
    Column("BlobSize", "Blob bytes", 90, kind="num", field="BlobSize"),
    Column("ModifiedTime", "Stored (UTC)", 165, kind="time"),
]


def _cookies_subtitle(count):
    return ("%s cookie%s. Domain, name, value and both timestamps are "
           "decoded from the CookieEntryEx table."
           % (format(count, ","), "" if count == 1 else "s"))


def _hsts_subtitle(count):
    return ("%s HSTS pin%s. Corroboration is checked against every other "
           "record this exhibit holds, not this table alone."
           % (format(count, ","), "" if count == 1 else "s"))


def _certs_subtitle(count):
    return ("%s certificate-store record%s, decoded from the BlobEntry "
           "table." % (format(count, ","), "" if count == 1 else "s"))


class CookiesView(RecordsView):
    def __init__(self, parent=None):
        super().__init__(
            record_sets=[
                RecordSet(
                    "cookies", "Cookies", COOKIE_COLUMNS,
                    subtitle=_cookies_subtitle, count_noun="cookies",
                    empty_text=("No Cookies in this exhibit — the "
                                "CookieEntryEx table held no live entries "
                                "when the database was parsed."),
                    default_sort=("LastModified", True),
                    caveat=("A cookie shows a site stored state in this "
                            "profile, not that a page was read.")),
                RecordSet(
                    "hsts", "HSTS Pins", HSTS_COLUMNS,
                    subtitle=_hsts_subtitle, count_noun="HSTS pins",
                    empty_text=("No HSTS pins in this exhibit — the "
                                "HstsEntryEx table held no live entries "
                                "when the database was parsed."),
                    caveat=("An HSTS pin proves a TLS connection, not that "
                            "a page was viewed.")),
                RecordSet(
                    "certs", "Certificates", CERT_COLUMNS,
                    subtitle=_certs_subtitle, count_noun="certificates",
                    empty_text=("No certificates in this exhibit — the "
                                "BlobEntry table held no live entries "
                                "when the database was parsed."),
                    caveat=("A cached certificate proves a TLS connection "
                            "was made, not that a page was read.")),
            ],
            header_icon="lock", header_title="Cookies & HSTS",
            parent=parent)
