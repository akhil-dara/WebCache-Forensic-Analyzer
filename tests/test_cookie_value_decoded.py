"""A percent-encoded cookie value is shown decoded beside the stored one
(raw beside derived): "%7B%22id%22%3A1%7D" reads as {"id":1}. A value with
nothing to decode gets no extra row."""
from types import SimpleNamespace

from webcache.shell import detail_fields as df
from webcache.shell.evidence_loader import cookie_rows_from_parser


def _rows(*values):
    entries = [{"Domain": "example.test", "Name": "c%d" % i, "Value": v,
                "Path": "/", "Expires_raw": None, "LastModified_raw": None}
               for i, v in enumerate(values)]
    return cookie_rows_from_parser(SimpleNamespace(cookie_entries=entries))


def _fields(row):
    return {f.label: f for g in df.fields_for(row) for f in g.fields}


def test_an_encoded_value_is_shown_decoded_beside_the_stored_one():
    row = _rows("%7B%22id%22%3A1%7D")[0]
    fields = _fields(row)
    assert fields["Cookie value"].display_value == "%7B%22id%22%3A1%7D"
    decoded = fields["Cookie value (percent-decoded)"]
    assert decoded.display_value == '{"id":1}'
    short, _tip = df.basis_badge(decoded.field)
    assert short == "DER"


def test_a_value_with_nothing_to_decode_gets_no_extra_row():
    row = _rows("19F0BB6638AA")[0]
    assert "Cookie value (percent-decoded)" not in _fields(row)
