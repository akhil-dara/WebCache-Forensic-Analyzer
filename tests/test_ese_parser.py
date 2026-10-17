

# --- a refusal must say why ------------------------------------------------
#
# open() wraps whatever the ESE reader raised as
# f"Failed to open database: {e}". Some failures carry no message at all --
# an empty file is one, verified against a zero-byte copy -- and the
# examiner is then shown "Failed to open database:" with nothing after the
# colon. This application refuses blanks where an explanation belongs
# everywhere else (see provenance.ABSENCE_* and the container work); a
# refusal is exactly where that matters most, because it is the only thing
# the examiner has to act on.

def test_opening_an_empty_file_says_why(tmp_path):
    import pytest
    from webcache.engine.ese_parser import WebCacheParser

    p = tmp_path / "empty.dat"
    p.write_bytes(b"")
    with pytest.raises(RuntimeError) as excinfo:
        WebCacheParser().open(str(p))
    msg = str(excinfo.value)
    tail = msg.split(":", 1)[1].strip() if ":" in msg else ""
    assert tail, "the message is %r -- nothing after the colon" % msg
    assert "empty" in msg.lower() or "0 byte" in msg.lower(), (
        "the reason %r does not say the file is empty, which is the one "
        "fact that explains this failure" % msg)


def test_a_refusal_with_a_real_reason_keeps_it(tmp_path):
    """The fix must not paper over reasons the reader DOES give."""
    import pytest
    from webcache.engine.ese_parser import WebCacheParser

    p = tmp_path / "garbage.dat"
    p.write_bytes(b"not an ESE database at all" * 400)
    with pytest.raises(RuntimeError) as excinfo:
        WebCacheParser().open(str(p))
    assert "signature" in str(excinfo.value).lower(), str(excinfo.value)
