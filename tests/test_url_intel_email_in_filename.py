"""An address used as a file name -- "<user>@example.com.pdf" -- is the
address, not a domain "example.com.pdf". The extension is trimmed and the
reason says so, so the trim is visible to the examiner."""
from webcache.engine.url_intel import scan_text


def _emails(text):
    return [f for f in scan_text(text) if f.kind == "Email address"]


def test_a_file_extension_is_not_part_of_the_domain():
    [f] = _emails("file:///C:/Users/x/Downloads/jdoe@example.test.pdf")
    assert f.value == "jdoe@example.test"
    assert f.decoded == "domain example.test"
    assert ".pdf" in f.reason and "file name" in f.reason


def test_a_plain_address_is_unchanged():
    [f] = _emails("https://mail.example.test/?to=jdoe@example.test")
    assert f.value == "jdoe@example.test"
    assert "file name" not in f.reason


def test_an_extension_with_no_domain_left_is_not_trimmed():
    # "@host.pdf" would leave "host" -- not a dotted domain; keep it whole.
    [f] = _emails("file:///C:/x/jdoe@host.pdf")
    assert f.value == "jdoe@host.pdf"
