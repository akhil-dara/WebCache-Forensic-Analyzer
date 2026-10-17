"""No string from the evidence reaches the HTML report as markup.

The report this file used to test (ForensicEngine.export_html_report) was
replaced by the offline package on 2026-10-01; the same HOSTILE set and the
same LIVE detector now run against that file.
This half is the FILE: outside the JSON island nothing carries evidence,
and the island carries no "<". tests/test_html_package_security.py is the
half that runs it in a browser."""
import re

import pytest

from webcache.engine.forensic_engine import ForensicEngine

from tests import _package_fixtures as fx

HOSTILE = ["<script>x()</script>", "\"><img src=x onerror=y()>",
           "'><svg onload=z()>", "javascript:alert(1)", "&lt;script&gt;",
           "\u202egnp.exe", "a\x00b"]

# See the history of this file for the reasoning behind the anchored
# handler alternative: it fires on "<div onmouseover=...>" but not on the
# entity-escaped, inert "&lt;div onmouseover=...&gt;".
LIVE = re.compile(
    r"<\s*(script|img|svg)\b"
    r"|<[a-zA-Z][^>]*\son\w+\s*="
    r"|href\s*=\s*['\"]?\s*javascript:", re.I)


def _page(tmp_path, value):
    row = fx.history_row(1, CleanUrl="https://example.invalid/" + value)
    snap = fx.snapshot(views=[fx.history_view([fx.segment(rows=[row])])],
                       summary=[("File", value)])
    snap.meta["evidence"] = [{"path": value, "sha256": value, "bytes": 1}]
    return open(fx.write(tmp_path, snap), encoding="utf-8").read()


def _split(page):
    start = page.index('id="wc-data">') + len('id="wc-data">')
    end = page.index("</script>", start)
    return page[start:end], page[:start] + page[end:]


@pytest.mark.parametrize("value", HOSTILE)
def test_no_hostile_string_is_live_markup(tmp_path, value):
    """Outside the island the file is byte-identical to a report built
    from harmless values (the page's own two script elements and its style
    are the only markup there is), and the island can neither close its
    element nor carry a tag."""
    island, outside = _split(_page(tmp_path, value))
    _clean_island, clean_outside = _split(_page(tmp_path, "plain"))
    assert outside == clean_outside
    assert "<" not in island
    assert not LIVE.search(island)


def test_the_detector_catches_live_markup():
    """Positive control: a clean result must mean clean, not blind."""
    assert LIVE.search("<td><img src=x onerror=y()></td>")
    assert LIVE.search("<div onmouseover=x()>")
    assert LIVE.search("<body onload=x()>")
    assert not LIVE.search("&lt;div onmouseover=x()&gt;")
    assert not LIVE.search('<td class="url">x</td>')


def test_no_url_is_made_clickable(tmp_path):
    assert "<a " not in _page(tmp_path, "plain").lower()


def test_the_escape_helper_escapes_the_apostrophe():
    """_html_escape outlived the old report: the location PDF uses it."""
    assert "'" not in ForensicEngine._html_escape("it's")
