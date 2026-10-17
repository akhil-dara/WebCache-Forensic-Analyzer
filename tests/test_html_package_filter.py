"""The page filters, sorts and searches exactly as the app does (spec:
"Filter popup", "Search all views"). Every expectation comes from the
app's own RecordFilter on the same rows."""
import datetime
import json
import random

import pytest

from webcache.shell.html_package import (PackageColumn, PackageSegment,
                                         PackageView)
from webcache.widgets.column_spec import Column, display_text
from webcache.widgets.record_filter import Condition, JoinedCondition, RecordFilter

from tests import _package_fixtures as fx

UTC = datetime.timezone.utc
COLUMNS = [Column("Id", "Id", kind="num"), Column("Name", "Name"),
           Column("When", "When (UTC)", kind="time"),
           Column("Count", "Count", kind="num"),
           Column("Flag", "Flag", kind="flag"),
           Column("Offset", "Offset", kind="offset")]
KEYS = [c.key for c in COLUMNS]
NAMES = ["alpha", "Beta", "gamma delta", "", None, "=formula",
         "\u00fcn\u00efcode", "BETA two", "item10", "item2", "Item1",
         "v1.10", "v1.9"]
COUNTS = [0, 3, 5, 8, 12, -2, None, "(not applicable)", 2.5, "", 5]
FLAGS = [True, False, "Not determinable", None]

CASES = [
    ("Name", "contains", "a", None), ("Name", "does not contain", "a", None),
    ("Name", "begins with", "b", None), ("Name", "ends with", "a", None),
    ("Name", "equals", "beta", None), ("Name", "does not equal", "alpha", None),
    ("Name", "is blank", None, None), ("Name", "is not blank", None, None),
    ("Name", "matches regex", "^g.*a$", None),
    ("Name", "matches pattern", "*a*", None),
    ("Name", "matches pattern", "b?ta*", None),
    ("Name", "does not match pattern", "*a", None),
    ("Count", "=", "5", None), ("Count", "!=", "5", None),
    ("Count", ">", "3", None), ("Count", ">=", "3", None),
    ("Count", "<", "3", None), ("Count", "<=", "3", None),
    ("Count", "between", "2", "8"), ("Count", "between", "8", "2"),
    ("Count", "is blank", None, None),
    ("When", "before", "2026-02-01", None),
    ("When", "after", "2026-02-01 12:00:00", None),
    ("When", "on", "2026-02-03", None),
    ("When", "between", "2026-01-10", "2026-02-10"),
    ("When", "in the last N days", "10", None),
    ("When", "is blank", None, None), ("When", ">", "2026-02-01", None),
    ("When", "<=", "2026-01-20T00:00:00", None),
    ("Flag", "is yes", None, None), ("Flag", "is no", None, None),
    ("Flag", "equals", "yes", None), ("Flag", "contains", "determin", None),
    ("Offset", ">", "1000", None), ("Offset", "between", "100", "500000"),
]


def _rows():
    rnd = random.Random(11)
    base = datetime.datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(48):
        when = (None if i % 9 == 4 else base + datetime.timedelta(
            hours=rnd.randint(0, 24 * 59), seconds=rnd.randint(0, 59)))
        rows.append({"Id": i, "Name": NAMES[i % len(NAMES)], "When": when,
                     "Count": COUNTS[i % len(COUNTS)],
                     "Flag": FLAGS[i % len(FLAGS)],
                     "Offset": rnd.randint(0, 1 << 20) if i % 4 else None,
                     "_kind": "table_row", "_record": None})
    return rows


@pytest.fixture
def parity_rows(browser, tmp_path):
    rows = _rows()
    seg = PackageSegment("p", "Parity",
                         [PackageColumn.from_column(c) for c in COLUMNS], rows)
    browser.open(fx.write(tmp_path, fx.snapshot(
        views=[fx.history_view([seg])])))
    return rows


def _model(browser, body):
    return browser.evaluate(
        "(function () { var m = WC.model('history', 'p'); m.clearAll(); %s;"
        " return m.visible.slice(); })()" % body)


@pytest.mark.parametrize("key,op,a,b", CASES,
                         ids=["%s %s %s %s" % c for c in CASES])
def test_every_operator_keeps_the_rows_the_app_keeps(browser, parity_rows,
                                                     key, op, a, b):
    expected = RecordFilter(parity_rows, COLUMNS)
    expected.set_condition(key, Condition(op, a, b))
    got = _model(browser, "m.setCondition(%d, WC.condition(%s, %s, %s))" % (
        KEYS.index(key), json.dumps(op), json.dumps(a), json.dumps(b)))
    assert got == [r["Id"] for r in expected.visible()]


@pytest.mark.parametrize("text", ["a", "BETA", "2026-01", "0x", "yes",
                                  "  gamma  ", "1"])
def test_the_text_box_keeps_the_rows_the_app_keeps(browser, parity_rows,
                                                   text):
    expected = RecordFilter(parity_rows, COLUMNS)
    expected.set_text(text)
    got = _model(browser, "m.setText(%s)" % json.dumps(text))
    assert got == [r["Id"] for r in expected.visible()]


@pytest.mark.parametrize("desc", [False, True])
@pytest.mark.parametrize("key", KEYS)
def test_every_sort_orders_rows_as_the_app_does(browser, parity_rows, key,
                                                desc):
    expected = RecordFilter(parity_rows, COLUMNS)
    expected.sort(key, desc)
    got = _model(browser, "m.setSort(%d, %s)" % (
        KEYS.index(key), "true" if desc else "false"))
    assert got == [r["Id"] for r in expected.visible()]


def test_a_value_set_and_the_value_list_agree_with_the_app(browser,
                                                           parity_rows):
    expected = RecordFilter(parity_rows, COLUMNS)
    expected.set_values("Name", {"alpha", "", None})
    got = _model(browser, "var ids = new Set(m.valueCounts(1).filter("
                          "function (x) { return x.label === 'alpha' ||"
                          " x.label === '(blank)'; }).map("
                          "function (x) { return x.id; })); m.setValues(1, ids)")
    assert got == [r["Id"] for r in expected.visible()]
    flag = COLUMNS[4]
    app_labels = [[display_text(v, flag) or "(blank)", n] for v, n in
                  RecordFilter(parity_rows, COLUMNS).value_counts("Flag")]
    page_labels = browser.evaluate(
        "WC.model('history', 'p').valueCounts(4).map("
        "function (x) { return [x.label, x.n]; })")
    assert page_labels == app_labels


def _popup(browser, funnel, body):
    assert browser.evaluate("document.querySelectorAll('#wc-grid th .funnel')"
                            ".length") > funnel, "that heading has no filter button"
    browser.evaluate(
        "document.querySelectorAll('#wc-grid th .funnel')[%d].click()" % funnel)
    browser.evaluate("new Promise(function (ok) { setTimeout(ok, 50); })",
                     await_promise=True)
    browser.evaluate("(function () { var p = document.querySelector('.popup');"
                     " function button(t) { return Array.from(p.querySelectorAll"
                     "('button')).filter(function (b) { return b.textContent"
                     " === t; })[0]; } %s })()" % body)


def test_the_funnel_popup_applies_a_condition_and_says_so(browser, tmp_path):
    browser.open(fx.write(tmp_path))
    browser.evaluate("WC.openSegment('history', 'history')")
    _popup(browser, 2,
           "var s = p.querySelector('select'); s.value = '>';"
           " s.dispatchEvent(new Event('change'));"
           " p.querySelector('input[aria-label=\"Operand\"]').value = '3';"
           " button('Apply').click();")
    assert browser.evaluate("document.getElementById('wc-count').textContent"
                            ).startswith("2 of 5 records")
    assert 'Visits > "3"' in browser.evaluate(
        "document.getElementById('wc-sentence').textContent")
    assert browser.evaluate("document.querySelectorAll('#wc-grid th .funnel')[2]"
                            ".classList.contains('on')")


def test_the_value_list_keeps_only_the_values_left_ticked(browser, tmp_path):
    browser.open(fx.write(tmp_path))
    browser.evaluate("WC.openSegment('history', 'history')")
    _popup(browser, 3,
           "var box = Array.from(p.querySelectorAll('.values label')).filter("
           "function (l) { return l.querySelector('span').textContent === 'No';"
           " })[0].querySelector('input'); box.click(); button('Apply').click();")
    assert browser.evaluate("document.getElementById('wc-count').textContent"
                            ).startswith("2 of 5 records")


def test_a_bad_regular_expression_is_shown_and_nothing_applied(browser,
                                                               tmp_path):
    browser.open(fx.write(tmp_path))
    browser.evaluate("WC.openSegment('history', 'history')")
    _popup(browser, 0,
           "var s = p.querySelector('select'); s.value = 'matches regex';"
           " s.dispatchEvent(new Event('change'));"
           " p.querySelector('input[aria-label=\"Operand\"]').value = '(';"
           " button('Apply').click();")
    assert browser.evaluate("document.querySelector('.popup .err').textContent")
    assert browser.evaluate("document.getElementById('wc-count').textContent"
                            ).startswith("5 records")


def test_search_all_views_counts_every_segment_and_opens_a_hit(browser,
                                                               tmp_path):
    recovered = [fx.history_row(3, carved=True), fx.history_row(30, carved=True)]
    views = [fx.history_view(),
             PackageView("recovery", "Deleted Records", "RECOVERY", "",
                         [fx.segment("records", "Recovered records",
                                     rows=recovered)])]
    browser.open(fx.write(tmp_path, fx.snapshot(views=views)))
    browser.evaluate("WC.go('search', 'page/3')")
    hits = browser.evaluate("Array.from(document.querySelectorAll('.results "
                            "button')).map(function (b) { return b.textContent; })")
    assert hits == ["History \u203a History \u2014 1 row",
                    "Deleted Records \u203a Recovered records \u2014 2 rows"]
    browser.evaluate("document.querySelector('.results button').click()")
    assert browser.evaluate("document.getElementById('wc-count').textContent"
                            ).startswith("1 of 5 records")
    assert browser.evaluate("document.getElementById('wc-filter').value") == "page/3"
    browser.evaluate("WC.go('search', 'nothing-like-this')")
    assert "No row in any view contains" in browser.evaluate(
        "document.getElementById('wc-main').textContent")


# --- parity with the app's popup (filter_popup.py / record_filter.py) --------

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
HOSTILE = ['<img src=x onerror="window.__wc_pwned=1">',
           "<b>bold</b><script>window.__wc_pwned=2</script>"]
#: Elements a value could create if it were ever parsed as markup.
MADE = "document.querySelectorAll('img, b, iframe, svg, script').length"


def _labels(browser):
    # Each value-list row: [label, count] as shown.
    return browser.evaluate(
        "Array.from(document.querySelectorAll('.popup .values label')).map("
        "function (l) { var s = l.querySelectorAll('span');"
        " return [s[0].textContent, s[1].textContent]; })")


def _model_of(browser, seg, body):
    return browser.evaluate(
        "(function () { var m = WC.model('history', %s); m.clearAll(); %s;"
        " return m.visible.slice(); })()" % (json.dumps(seg), body))


def _multi_segment():
    cols = [Column("Id", "Id", kind="num"),
            Column("Types", "Types", kind="text", multi=True),
            Column("Prov", "Reported source", kind="text", multi=True,
                   multi_source="ProvValues")]
    # One blank only: the island stores "" and None as one blank cell
    # where the app's picker would list each as "(blank)".
    joined = ["History, Cookies", "Cookies", "", "Cookies, History",
              "iedownload, History", "History"]
    prov = [["wifi, cell", "gps"], ["gps"], None, ["wifi, cell"], [], ["x"]]
    rows = []
    for i, (types, parts) in enumerate(zip(joined, prov)):
        rows.append({"Id": i, "Types": types,
                     "Prov": None if parts is None else ", ".join(parts),
                     "ProvValues": parts,
                     "_kind": "table_row", "_record": None})
    return cols, rows


def _open_multi(browser, tmp_path):
    cols, rows = _multi_segment()
    seg = PackageSegment("m", "Multi",
                         [PackageColumn.from_column(c) for c in cols], rows)
    browser.open(fx.write(tmp_path, fx.snapshot(
        views=[fx.history_view([seg])])))
    return cols, rows


def test_a_multi_value_column_offers_each_value_as_the_app_does(browser,
                                                                tmp_path):
    cols, rows = _open_multi(browser, tmp_path)
    for c in (1, 2):
        app = [[display_text(v, cols[c]) or "(blank)", n] for v, n in
               RecordFilter(rows, cols).value_counts(cols[c].key)]
        page = browser.evaluate(
            "WC.model('history', 'm').valueCounts(%d).map("
            "function (x) { return [x.label, x.n]; })" % c)
        assert page == app, cols[c].key
    for c, label in ((1, "History"), (2, "wifi, cell")):
        expected = RecordFilter(rows, cols)
        expected.set_values(cols[c].key, {label})
        got = _model_of(
            browser, "m", "var ids = new Set(m.valueCounts(%d).filter("
            "function (x) { return x.label === %s; }).map("
            "function (x) { return x.id; })); m.setValues(%d, ids)"
            % (c, json.dumps(label), c))
        assert got == [r["Id"] for r in expected.visible()], label


def test_the_multi_value_popup_lists_single_values(browser, tmp_path):
    _open_multi(browser, tmp_path)
    browser.evaluate("WC.openSegment('history', 'm')")
    _popup(browser, 1, "")
    assert [x[0] for x in _labels(browser)] == [
        "Cookies", "History", "iedownload", "(blank)"]


def _time_segment():
    cols = [Column("Id", "Id", kind="num"),
            Column("Utc", "When (UTC)", kind="time"),
            Column("Loc", "When (local)", kind="time_local")]
    utc = [datetime.datetime(2026, 2, 17, 18, 0, tzinfo=UTC),
           datetime.datetime(2026, 2, 17, 19, 0, tzinfo=UTC),
           datetime.datetime(2026, 3, 2, 1, 0, tzinfo=UTC),
           datetime.datetime(2025, 12, 31, 23, 0, tzinfo=UTC), None]
    rows = [{"Id": i, "Utc": u,
             "Loc": None if u is None else u.astimezone(IST),
             "_kind": "table_row", "_record": None}
            for i, u in enumerate(utc)]
    return cols, rows


def _open_times(browser, tmp_path):
    cols, rows = _time_segment()
    seg = PackageSegment("t", "Times",
                         [PackageColumn.from_column(c) for c in cols], rows)
    browser.open(fx.write(tmp_path, fx.snapshot(
        views=[fx.history_view([seg])])))
    browser.evaluate("WC.openSegment('history', 't')")


def _tree_rows(browser):
    return browser.evaluate(
        "Array.from(document.querySelectorAll('.popup .values label')).map("
        "function (l) { var s = l.querySelectorAll('span'); var b ="
        " l.querySelector('input'); return [s[0].textContent, s[1].textContent,"
        " b.checked ? 'on' : b.indeterminate ? 'some' : 'off']; })")


def _tree_do(browser, label, what):
    browser.evaluate(
        "Array.from(document.querySelectorAll('.popup .values label')).filter("
        "function (l) { return l.querySelector('span').textContent === %s; })[0]"
        ".querySelector(%s).click()" % (json.dumps(label), json.dumps(what)))


def test_a_time_column_is_picked_by_year_month_and_day(browser, tmp_path):
    _open_times(browser, tmp_path)
    _popup(browser, 1, "")
    assert _tree_rows(browser) == [["2025", "1", "on"], ["2026", "3", "on"],
                                   ["(blank)", "1", "on"]]
    _tree_do(browser, "2026", ".twist")
    _tree_do(browser, "2026-02", ".twist")
    assert [r[0] for r in _tree_rows(browser)] == [
        "2025", "2026", "2026-02", "2026-02-17", "2026-03", "(blank)"]
    _tree_do(browser, "2026-02-17", "input")
    rows = _tree_rows(browser)
    assert rows[1][2] == "some" and rows[3][2] == "off"
    browser.evaluate("Array.from(document.querySelectorAll('.popup button'))"
                     ".filter(function (b) { return b.textContent === 'Apply';"
                     " })[0].click()")
    assert sorted(browser.evaluate("WC.visibleRows()")) == [2, 3, 4]


def test_a_local_time_column_groups_days_on_its_own_clock(browser, tmp_path):
    _open_times(browser, tmp_path)
    _popup(browser, 2, "")
    # +05:30: 18:00 UTC is 23:30 on the 17th, 19:00 UTC is 00:30 on the
    # 18th, and 23:00 UTC on 31 Dec 2025 is 04:30 on 1 Jan 2026.
    assert [r[0] for r in _tree_rows(browser)] == ["2026", "(blank)"]
    _tree_do(browser, "2026", ".twist")
    _tree_do(browser, "2026-02", ".twist")
    _tree_do(browser, "2026-01", ".twist")
    assert [r[:2] for r in _tree_rows(browser)] == [
        ["2026", "4"], ["2026-01", "1"], ["2026-01-01", "1"],
        ["2026-02", "2"], ["2026-02-17", "1"], ["2026-02-18", "1"],
        ["2026-03", "1"], ["(blank)", "1"]]


def test_a_yes_no_column_offers_is_yes_and_is_no(browser, tmp_path):
    browser.open(fx.write(tmp_path))
    browser.evaluate("WC.openSegment('history', 'history')")
    _popup(browser, 3, "")
    options = browser.evaluate(
        "Array.from(document.querySelectorAll('.popup select option')).map("
        "function (o) { return o.textContent; })")
    assert options[:3] == ["(no condition)", "Is Yes", "Is No"]
    assert not [o for o in options if "true" in o.lower()]
    assert [x[0] for x in _labels(browser)] == ["No", "Yes"]
    _popup(browser, 3, "var s = p.querySelector('select'); s.value = 'is yes';"
                       " s.dispatchEvent(new Event('change'));"
                       " button('Apply').click();")
    assert browser.evaluate("document.getElementById('wc-count').textContent"
                            ).startswith("2 of 5 records")
    assert "InPrivate Is Yes" in browser.evaluate(
        "document.getElementById('wc-sentence').textContent")


def test_the_operand_box_shows_the_apps_placeholders(browser, tmp_path):
    from webcache.widgets.record_filter import OPERAND_PLACEHOLDERS
    browser.open(fx.write(tmp_path))
    browser.evaluate("WC.openSegment('history', 'history')")
    for funnel, kind in ((0, "url"), (1, "time"), (2, "num")):
        _popup(browser, funnel, "")
        got = browser.evaluate("document.querySelector('.popup input"
                               "[aria-label=\"Operand\"]').placeholder")
        assert got == OPERAND_PLACEHOLDERS.get(kind, "text"), kind


def test_a_values_chip_names_display_labels_and_none_reads_as_none(browser,
                                                                    tmp_path):
    browser.open(fx.write(tmp_path))
    browser.evaluate("WC.openSegment('history', 'history')")
    _popup(browser, 3,
           "var box = Array.from(p.querySelectorAll('.values label')).filter("
           "function (l) { return l.querySelector('span').textContent === 'No';"
           " })[0].querySelector('input'); box.click(); button('Apply').click();")
    sentence = browser.evaluate(
        "document.getElementById('wc-sentence').textContent")
    assert "InPrivate: Is Yes" in sentence
    assert "True" not in sentence and "IsInPrivate" not in sentence
    _popup(browser, 3, "button('Select none').click();")
    assert "No values selected" in browser.evaluate(
        "document.querySelector('.popup').textContent")
    _popup(browser, 3, "button('Select none').click(); button('Apply').click();")
    assert browser.evaluate("document.getElementById('wc-count').textContent"
                            ).startswith("0 of 5 records")
    assert "InPrivate: no values selected (matches nothing)" in browser.evaluate(
        "document.getElementById('wc-sentence').textContent")


def test_the_value_search_matches_what_each_value_shows(browser, tmp_path):
    browser.open(fx.write(tmp_path))
    browser.evaluate("WC.openSegment('history', 'history')")
    find = ("var f = p.querySelector('input[aria-label=\"Find a value\"]');"
            " f.value = %s; f.dispatchEvent(new Event('input'));")
    _popup(browser, 3, find % "'ye'")
    assert [x[0] for x in _labels(browser)] == ["Yes"]
    _popup(browser, 3, find % "'true'")
    assert _labels(browser) == []
    assert 'No values match "true".' in browser.evaluate(
        "document.querySelector('.popup').textContent")


def _search_views():
    recovered = [fx.history_row(3, carved=True),
                 fx.history_row(30, carved=True)]
    return [fx.history_view(),
            PackageView("recovery", "Deleted Records", "RECOVERY", "",
                        [fx.segment("records", "Recovered records",
                                    rows=recovered)])]


def _hits(browser):
    return browser.evaluate("Array.from(document.querySelectorAll('.results "
                            "button')).map(function (b) { return b.textContent; })")


def test_search_reads_only_evidence_fields_of_a_recovered_record(browser,
                                                                 tmp_path):
    browser.open(fx.write(tmp_path, fx.snapshot(views=_search_views())))
    # The grid's Origin detail column says "Carved (deleted/unflushed)" on
    # both recovered rows: words this tool wrote, never evidence.
    browser.evaluate("WC.go('search', 'unflushed')")
    assert "No row in any view contains" in browser.evaluate(
        "document.getElementById('wc-main').textContent")
    # Their carved Url is evidence, and the grid never shows it whole.
    browser.evaluate("WC.go('search', 'ALICE@')")
    assert _hits(browser) == [
        "Deleted Records › Recovered records — 2 rows"]


def test_search_snippets_mark_the_match_as_text(browser, tmp_path):
    browser.open(fx.write(tmp_path, fx.snapshot(views=_search_views())))
    browser.evaluate("WC.go('search', 'PAGE/3')")
    marks = browser.evaluate("Array.from(document.querySelectorAll('.results "
                             ".snip mark')).map(function (m) { return "
                             "m.textContent; })")
    assert marks and all(m == "page/3" for m in marks)
    snips = browser.evaluate("Array.from(document.querySelectorAll('.results "
                             ".snip')).map(function (s) { return "
                             "s.textContent; })")
    assert any(s.startswith("Address: ") for s in snips)
    assert any(s.startswith("Url: ") for s in snips)


def test_hostile_values_stay_text_in_the_popup_chips_and_snippets(browser,
                                                                   tmp_path):
    rows = [fx.history_row(i, CleanUrl=HOSTILE[i % 2]) for i in range(1, 5)]
    browser.open(fx.write(tmp_path, fx.snapshot(
        views=[fx.history_view([fx.segment(rows=rows)])])))
    before = browser.evaluate(MADE)
    browser.evaluate("WC.openSegment('history', 'history')")
    _popup(browser, 0, "")
    assert sorted(x[0] for x in _labels(browser)) == sorted(HOSTILE)
    _popup(browser, 0,
           "var box = Array.from(p.querySelectorAll('.values label')).filter("
           "function (l) { return l.querySelector('span').textContent === %s;"
           " })[0].querySelector('input'); box.click(); button('Apply').click();"
           % json.dumps(HOSTILE[1]))
    assert HOSTILE[0] in browser.evaluate(
        "document.getElementById('wc-sentence').textContent")
    browser.evaluate("WC.go('search', '<img')")
    assert browser.evaluate("document.querySelector('.results .snip mark')"
                            ".textContent") == "<img"
    assert browser.evaluate(MADE) - before == 0
    assert browser.evaluate("window.__wc_pwned === undefined")


def test_a_long_value_in_the_value_list_is_shown_whole(browser, tmp_path):
    """The popup's value list wraps a long value instead of
    cutting it with an ellipsis -- two URLs that differ only at the end must
    not look identical. The app's list wraps and never elides."""
    long_url = "https://example.test/" + "segment/" * 40 + "tail-end"
    rows = [fx.history_row(1, CleanUrl=long_url),
            fx.history_row(2, CleanUrl=long_url[:-3] + "xyz"),
            fx.history_row(3)]
    snap = fx.snapshot([fx.history_view([fx.segment(rows=rows)])])
    browser.open(fx.write(tmp_path, snap))
    browser.evaluate("WC.openSegment('history', 'history')")
    _popup(browser, 0, "")
    found = browser.evaluate(
        "(function () { var p = document.querySelector('.popup');"
        " return Array.from(p.querySelectorAll('.values label')).map("
        "function (l) { var s = l.querySelector('span.v');"
        " var cs = getComputedStyle(s);"
        " return {text: s.textContent, h: l.getBoundingClientRect().height,"
        " clipped: s.scrollWidth > s.clientWidth + 1,"
        " ellipsis: cs.textOverflow === 'ellipsis'}; }); })()")
    whole = [f for f in found if f["text"] in (long_url, long_url[:-3] + "xyz")]
    assert len(whole) == 2, "a long value is missing from the list"
    for f in whole:
        assert not f["clipped"] and not f["ellipsis"], f
        assert f["h"] > 22, "a long value must wrap onto more than one line"
    # Rows never overlap: each starts where the previous one ends.
    tops = browser.evaluate(
        "Array.from(document.querySelectorAll('.popup .values label')).map("
        "function (l) { var r = l.getBoundingClientRect();"
        " return [r.top, r.bottom]; })")
    tops.sort()
    for (a_top, a_bottom), (b_top, _b) in zip(tops, tops[1:]):
        assert b_top >= a_bottom - 0.5, "value rows overlap"


@pytest.mark.parametrize("label, desc", [("Sort smallest first", False),
                                         ("Sort largest first", True)])
def test_the_funnel_popup_sorts_the_column_as_the_app_does(browser, tmp_path,
                                                           label, desc):
    browser.open(fx.write(tmp_path))
    browser.evaluate("WC.openSegment('history', 'history')")
    _popup(browser, 2, "button(%s).click();" % json.dumps(label))
    m = "WC.model('history', 'history')"
    assert browser.evaluate("[%s.sortCol, %s.sortDesc]" % (m, m)) == [2, desc]
    assert browser.evaluate("document.querySelector('.popup')") is None
    visits = browser.evaluate(
        "Array.from(document.querySelectorAll('#wc-grid tbody tr')).map("
        "function (tr) { return tr.children[3] && tr.children[3].textContent; })"
        ".filter(function (t) { return t; })")
    assert visits == sorted(visits, key=int, reverse=desc)
    assert len(visits) == 5


def test_the_sort_buttons_are_worded_as_the_app_words_them(browser, tmp_path):
    from webcache.widgets.record_filter import sort_labels
    browser.open(fx.write(tmp_path))
    for kind in ("text", "url", "num", "count", "size", "offset", "bar",
                 "time", "time_local", "flag", "domain"):
        page = browser.evaluate("WC.sortLabels({kind: %s})" % json.dumps(kind))
        assert tuple(page) == sort_labels(type("C", (), {"kind": kind})())


JOINED = [
    ("Name", ("begins with", "b", None), "or", ("ends with", "a", None)),
    ("Name", ("contains", "a", None), "and", ("does not contain", "l", None)),
    ("Count", ("<", "1", None), "or", (">", "8", None)),
    ("Count", ("between", "2", "12"), "and", ("!=", "5", None)),
    ("Count", ("is blank", None, None), "or", ("=", "0", None)),
    ("When", ("in the last N days", "10", None), "or",
     ("before", "2026-01-05", None)),
    ("Flag", ("equals", "yes", None), "or", ("contains", "determin", None)),
    ("Offset", (">", "1000", None), "and", ("<", "500000", None)),
]


@pytest.mark.parametrize("key,first,join,second", JOINED,
                         ids=["%s %s %s %s" % (c[0], c[1][0], c[2], c[3][0])
                              for c in JOINED])
def test_two_joined_conditions_keep_the_rows_the_app_keeps(
        browser, parity_rows, key, first, join, second):
    expected = RecordFilter(parity_rows, COLUMNS)
    expected.set_condition(key, JoinedCondition(
        Condition(*first), join, Condition(*second)))
    got = _model(browser, "m.setCondition(%d, WC.joined(WC.condition(%s),"
                          " %s, WC.condition(%s)))" % (
        KEYS.index(key), json.dumps(list(first))[1:-1], json.dumps(join),
        json.dumps(list(second))[1:-1]))
    assert got == [r["Id"] for r in expected.visible()]
    sentence = browser.evaluate(
        "WC.model('history', 'p').describe()[0].text")
    column = COLUMNS[KEYS.index(key)]
    assert sentence == "%s %s" % (column.label, expected.condition_for(
        key).describe(column))


def test_the_funnel_popup_joins_two_conditions_and_reopens_with_both(
        browser, tmp_path):
    browser.open(fx.write(tmp_path))
    browser.evaluate("WC.openSegment('history', 'history')")

    def pick(label, value):
        return ("var s = p.querySelector('select[aria-label=\"%s\"]');"
                " s.value = %s; s.dispatchEvent(new Event('change'));"
                % (label, json.dumps(value)))
    _popup(browser, 2,
           pick("Operator", "<") +
           " p.querySelector('input[aria-label=\"Operand\"]').value = '2';" +
           pick("Join", "or") + pick("Operator 2", ">") +
           " p.querySelector('input[aria-label=\"Operand 2\"]').value = '4';"
           " button('Apply').click();")
    assert browser.evaluate("document.getElementById('wc-count').textContent"
                            ).startswith("2 of 5 records")
    assert 'Visits < "2" or > "4"' in browser.evaluate(
        "document.getElementById('wc-sentence').textContent")
    _popup(browser, 2, "")
    seeded = browser.evaluate(
        "(function () { var p = document.querySelector('.popup');"
        " function v(q) { return p.querySelector(q).value; }"
        " return [v('select[aria-label=\"Operator\"]'),"
        " v('input[aria-label=\"Operand\"]'), v('select[aria-label=\"Join\"]'),"
        " v('select[aria-label=\"Operator 2\"]'),"
        " v('input[aria-label=\"Operand 2\"]')]; })()")
    assert seeded == ["<", "2", "or", ">", "4"]
