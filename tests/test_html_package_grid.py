"""Views in the page."""
import datetime

from webcache import provenance
from webcache.shell.html_package import (PackageColumn, PackageSegment,
                                         PackageView)
from webcache.shell.record_kinds import K_DOMAIN
from webcache.widgets.column_spec import Column, display_text, searchable_text

from tests import _package_fixtures as fx

UTC = datetime.timezone.utc
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
KINDS = ["text", "url", "num", "count", "size", "offset", "time",
         "time_local", "flag", "bar", "domain"]
VALUES = [None, "", "plain", "a\nb", 0, 7, -12345, 2 ** 53 + 5, -(2 ** 60),
          1234.5, 0.4523, 1.0, 1e-07, True, False, "Not determinable",
          datetime.datetime(2026, 2, 17, 16, 50, 9, 123456, tzinfo=UTC),
          datetime.datetime(2026, 2, 17, 16, 50, 9),
          datetime.datetime(2024, 3, 1, 5, 30, tzinfo=IST)]
ROWS = "#wc-grid tbody tr:not(.spacer)"


def _open(browser, tmp_path, snap):
    browser.open(fx.write(tmp_path, snap))
    browser.evaluate("WC.setWrap(true)")


def _rows_text(browser, column):
    # Data cells are <td>; the leading origin label is the row's <th>.
    return browser.evaluate(
        "Array.from(document.querySelectorAll('%s'))"
        ".map(function (tr) { return tr.querySelectorAll('td')[%d]"
        ".textContent; })" % (ROWS, column))


def _origins(browser):
    return browser.evaluate(
        "Array.from(document.querySelectorAll('%s')).map(function (tr) {"
        " var th = tr.querySelector('th.origin');"
        " return th ? th.textContent : null; })" % ROWS)


def _settle(browser):
    browser.evaluate("new Promise(function (ok) { requestAnimationFrame("
                     "function () { requestAnimationFrame(ok); }); })",
                     await_promise=True)


def test_every_cell_shows_and_searches_what_the_app_grid_does(
        browser, tmp_path):
    columns = [Column("k_" + kind, kind, kind=kind) for kind in KINDS]
    rows = []
    for value in VALUES:
        row = {"k_" + kind: value for kind in KINDS}
        row.update({"_kind": "table_row", "_record": None})
        rows.append(row)
    seg = PackageSegment("m", "Matrix",
                         [PackageColumn.from_column(c) for c in columns], rows)
    browser.open(fx.write(tmp_path, fx.snapshot(views=[fx.history_view([seg])])))
    got = browser.evaluate(
        "(function () { var s = WC.data().views[0].segments[0];"
        " return s.rows.map(function (r) { return s.cols.map("
        "function (c, i) { return [WC.displayText(r[i], c),"
        " WC.searchText(r[i], c)]; }); }); })()")
    for r, row in enumerate(rows):
        for c, col in enumerate(columns):
            value = row[col.key]
            if (isinstance(value, datetime.datetime)
                    and col.kind not in ("time", "time_local")):
                # Not pinned: outside a timestamp column the island stores
                # the export's text for a datetime (the timestamp-column
                # rule), which is not what the app's grid shows.
                continue
            assert got[r][c] == [display_text(value, col),
                                 searchable_text(value, col)], (value, col.kind)


def test_the_dom_holds_only_the_rows_in_view(browser, tmp_path):
    rows = [fx.history_row(i) for i in range(1, 5001)]
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view(
        [fx.segment(rows=rows)])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    _settle(browser)
    in_view = (
        "(function () { var w = document.getElementById('wc-grid');"
        " var box = w.getBoundingClientRect(), drawn = 0, seen = 0;"
        " Array.from(document.querySelectorAll('%s')).forEach(function (tr) {"
        "  drawn++; var r = tr.getBoundingClientRect();"
        "  if (r.bottom > box.top && r.top < box.bottom) seen++; });"
        " return [drawn, seen]; })()" % ROWS)
    drawn, seen = browser.evaluate(in_view)
    assert 0 < seen and drawn <= seen + 2 * 20
    browser.evaluate("(function () { var w = document.getElementById('wc-grid');"
                     " w.scrollTop = w.scrollHeight; })()")
    _settle(browser)
    _settle(browser)
    assert "https://example.test/page/5000" in _rows_text(browser, 0)
    drawn, seen = browser.evaluate(in_view)
    assert 0 < seen and drawn <= seen + 2 * 20


def test_a_long_value_is_capped_with_a_marker_that_opens_it_whole(
        browser, tmp_path):
    long_value = "\n".join("line %d" % i for i in range(20))
    rows = [fx.history_row(1, CleanUrl=long_value)]
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view(
        [fx.segment(rows=rows)])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    _settle(browser)
    assert browser.evaluate(
        "document.querySelector('#wc-grid .more').textContent") == (
        "▾ +15 more lines")
    browser.evaluate("document.querySelector('#wc-grid .more').click()")
    assert browser.evaluate(
        "document.querySelector('.dialog pre.whole').textContent") == long_value
    browser.evaluate("document.querySelector('.dialog .dfoot button:last-child')"
                     ".click()")


def test_every_row_starts_with_its_origin_in_words(browser, tmp_path):
    records = PackageSegment(
        "history", "History", fx.history_columns(),
        [fx.history_row(1), fx.history_row(2, carved=True)])
    live, carved = fx.entry(1), fx.entry(2, RecoverySource="log")
    cols = [PackageColumn("Domain", "Domain"),
            PackageColumn("Records", "Records", kind="num")]

    def agg(name, members):
        return {"Domain": name, "Records": len(members), "_kind": K_DOMAIN,
                "_members": members}
    domains = PackageSegment("domains", "Domains", cols, [
        agg("a.example.test", [live]), agg("b.example.test", [live, carved]),
        agg("c.example.test", [carved]),
        {"Domain": "d.example.test", "Records": 0, "_kind": "table_row",
         "_record": None}])
    _open(browser, tmp_path, fx.snapshot(views=[
        fx.history_view([records]),
        PackageView("domains", "Domains", "ANALYSIS", "", [domains])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    _settle(browser)
    assert browser.evaluate(
        "document.querySelector('#wc-grid thead th').textContent") == "Origin"
    assert _origins(browser) == ["Live", "Carved"]
    tint = ("Array.from(document.querySelectorAll('%s')).map(function (tr) {"
            " return [tr.classList.contains('carved'),"
            " getComputedStyle(tr.querySelector('td')).backgroundColor]; })"
            % ROWS)
    (live_carved, live_bg), (carved_flag, carved_bg) = browser.evaluate(tint)
    assert not live_carved and carved_flag and live_bg != carved_bg
    browser.evaluate("WC.openSegment('domains', 'domains')")
    _settle(browser)
    assert _origins(browser) == ["Live", provenance.AGGREGATE_MIXED,
                                 provenance.AGGREGATE_RECOVERED,
                                 provenance.NOT_A_RECORD]
    assert [c for c, _bg in browser.evaluate(tint)] == [
        False, False, True, False]


def test_a_heading_click_sorts_with_a_mark_and_badges_explain_themselves(
        browser, tmp_path):
    cols = fx.history_columns()
    cols[0].badge, cols[0].badge_tooltip = "OBS", "OBS (Observed) - read directly"
    rows = [fx.history_row(i) for i in (3, 1, 2)]
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view(
        [fx.segment(rows=rows, columns=cols)])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    assert browser.evaluate("document.querySelector('#wc-grid th .badge').title"
                            ) == "OBS (Observed) - read directly"
    browser.evaluate("document.querySelectorAll('#wc-grid th .hlabel')[2].click()")
    _settle(browser)
    assert _rows_text(browser, 2) == ["1", "2", "3"]
    assert browser.evaluate(
        "document.querySelector('#wc-grid th .sortmark').textContent") == "▲"
    browser.evaluate("document.querySelectorAll('#wc-grid th .hlabel')[2].click()")
    _settle(browser)
    assert _rows_text(browser, 2) == ["3", "2", "1"]
    assert browser.evaluate(
        "document.querySelector('#wc-grid th .sortmark').textContent") == "▼"


def test_a_filter_reuses_the_sort_instead_of_sorting_again(browser, tmp_path):
    rows = [fx.history_row(i) for i in range(1, 41)]
    seg = fx.segment(rows=rows, default_sort=("VisitCount", True))
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view([seg])]))
    browser.evaluate(
        "(function () { var real = Array.prototype.sort; window.__sorts = 0;"
        " Array.prototype.sort = function () { window.__sorts++;"
        " return real.apply(this, arguments); }; })()")
    browser.evaluate("WC.openSegment('history', 'history')")
    model = "WC.model('history', 'history')"
    browser.evaluate("window.__sorts = 0")
    for text in ("page/1", "page/2", ""):
        browser.evaluate("%s.setText(%r)" % (model, text))
    assert browser.evaluate("window.__sorts") == 0
    assert browser.evaluate("%s.visible.length" % model) == 40
    assert browser.evaluate("%s.visible.slice(0, 3)" % model) == [39, 38, 37]
    browser.evaluate("%s.setText('page/3')" % model)
    assert browser.evaluate("%s.visible.map(function (r) { return r + 1; })"
                            % model) == [39, 38, 37, 36, 35, 34, 33, 32, 31,
                                         30, 3]
    browser.evaluate("%s.setSort(2, false)" % model)
    assert browser.evaluate("window.__sorts") > 0
    assert browser.evaluate("%s.visible.map(function (r) { return r + 1; })"
                            % model) == [3, 30, 31, 32, 33, 34, 35, 36, 37,
                                         38, 39]


def test_the_selected_row_stands_out_and_no_heading_is_clipped(
        browser, tmp_path):
    cols = fx.history_columns()
    cols.append(PackageColumn("Long", "Characteristically Unabbreviated",
                              kind="text", width=20))
    rows = [fx.history_row(i, Long="x") for i in range(1, 6)]
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view(
        [fx.segment(rows=rows, columns=cols)])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    _settle(browser)
    clipped = browser.evaluate(
        "Array.from(document.querySelectorAll('#wc-grid thead th')).filter("
        "function (th) { var box = th.getBoundingClientRect();"
        " return th.scrollWidth > th.clientWidth ||"
        " Array.from(th.querySelectorAll('.hlabel, .badge, .sortmark'))"
        ".some(function (n) { var r = n.getBoundingClientRect();"
        " return r.right > box.right + 0.5 || r.left < box.left - 0.5; }); })"
        ".map(function (th) { return th.textContent; })")
    assert clipped == []
    browser.evaluate("document.querySelectorAll('%s')[1]"
                     ".querySelector('td').click()" % ROWS)
    look = browser.evaluate(
        "Array.from(document.querySelectorAll('%s')).slice(0, 3).map("
        "function (tr) { var s = getComputedStyle(tr.querySelector('td'));"
        " var o = getComputedStyle(tr.querySelector('th.origin'));"
        " return [tr.classList.contains('sel'), s.backgroundColor,"
        " o.boxShadow]; })" % ROWS)
    assert [s for s, _bg, _bar in look] == [False, True, False]
    assert look[1][1] != look[0][1] and look[1][1] != look[2][1]
    assert look[1][2] != "none" and look[0][2] == "none"


def test_the_count_line_chips_and_filter_box_narrow_the_rows(browser, tmp_path):
    quick = [{"label": "InPrivate only", "key": "IsInPrivate",
              "values": ["Yes"], "cond": None, "sentence": None},
             {"label": "One row per visit",
              "skipped": "Not reproduced in the offline report."}]
    seg = fx.segment(note="5 live, 0 recovered", quick=quick)
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view([seg])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    count = "document.getElementById('wc-count').textContent"
    assert browser.evaluate(count) == "5 records — 5 live, 0 recovered"
    chips = browser.evaluate(
        "Array.from(document.querySelectorAll('button.chip')).map("
        "function (b) { return [b.textContent, b.disabled]; })")
    assert chips == [["InPrivate only", False],
                     ["One row per visit (not reproduced)", True]]
    browser.evaluate("document.querySelector('button.chip').click()")
    assert browser.evaluate(count).startswith("2 of 5 records")
    browser.evaluate("(function () { var b = document.getElementById('wc-filter');"
                     " b.value = 'page/4'; b.dispatchEvent(new Event('input')); })()")
    assert browser.evaluate(count).startswith("1 of 5 records")
    assert "InPrivate only" in browser.evaluate(
        "document.getElementById('wc-sentence').textContent")


def test_a_chip_on_a_field_the_grid_does_not_show_still_filters(
        browser, tmp_path):
    # History's "Local files only" and "Has search terms" read row fields
    # that are not columns; the report reproduces every value/condition chip.
    quick = [{"label": "Local files only", "key": "IsLocalFile",
              "values": ["Yes"], "cond": None, "sentence": None},
             {"label": "Has search terms", "key": "SearchTerms",
              "values": None, "cond": ["is not blank", None, None],
              "sentence": None}]
    rows = [fx.history_row(i, IsLocalFile=i <= 2,
                           SearchTerms="alice" if i == 5 else None)
            for i in range(1, 6)]
    seg = fx.segment(rows=rows, quick=quick)
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view([seg])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    count = "document.getElementById('wc-count').textContent"
    chips = "document.querySelectorAll('button.chip')"
    assert browser.evaluate(
        "Array.from(%s).map(function (b) { return b.disabled; })" % chips
    ) == [False, False]
    browser.evaluate("%s[0].click()" % chips)
    assert browser.evaluate(count).startswith("2 of 5 records")
    browser.evaluate("%s[0].click()" % chips)
    browser.evaluate("%s[1].click()" % chips)
    assert browser.evaluate(count).startswith("1 of 5 records")
    assert _rows_text(browser, 0) == ["https://example.test/page/5"]


def test_the_default_sort_applies_and_enter_opens_the_selected_row(
        browser, tmp_path):
    seg = fx.segment(default_sort=("AccessedUtc", True))
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view([seg])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    _settle(browser)
    assert _rows_text(browser, 1)[0] == "2026-02-17 16:50:05"
    assert browser.evaluate(
        "document.querySelector('#wc-grid th .sortmark').textContent") == "▼"
    browser.evaluate(
        "(function () { var w = document.getElementById('wc-grid'); w.focus();"
        " w.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true}));"
        " w.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); })()")
    assert browser.evaluate("document.querySelectorAll('.modal').length") == 1
    browser.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
    assert browser.evaluate("document.querySelectorAll('.modal').length") == 0


def test_timeline_switches_between_its_utc_and_local_grains(browser, tmp_path):
    cols = [PackageColumn("Period", "Period"),
            PackageColumn("Records", "Records", kind="num")]

    def seg(key, label, clock, period):
        return PackageSegment(key, label, cols, rows=[
            {"Period": period, "Records": 1, "_kind": "table_row",
             "_record": None}], clock=clock, noun="periods")
    view = PackageView("timeline", "Timeline", "ANALYSIS", "", [
        seg("day_utc", "By day (UTC)", "utc", "2026-02-17"),
        seg("day_local", "By day (UTC+05:30)", "local", "2026-02-18")],
        initial="day_utc")
    _open(browser, tmp_path, fx.snapshot(views=[view]))
    browser.evaluate("WC.go('view:timeline')")
    _settle(browser)
    assert _rows_text(browser, 0) == ["2026-02-17"]
    labels = browser.evaluate(
        "Array.from(document.querySelectorAll('.vhead .bar button')).map("
        "function (b) { return b.textContent; })")
    assert "UTC" in labels and "Local (UTC+05:30)" in labels
    browser.evaluate(
        "Array.from(document.querySelectorAll('.vhead .bar button')).filter("
        "function (b) { return b.textContent === 'Local (UTC+05:30)'; })[0].click()")
    _settle(browser)
    assert _rows_text(browser, 0) == ["2026-02-18"]


def test_chips_in_one_group_are_exclusive_like_the_apps_method_buttons(
        browser, tmp_path):
    """Deleted Records' method chips are one exclusive
    group in the app (a QButtonGroup); ticking a second replaces the first."""
    quick = [{"label": "Structured", "key": "Kind", "values": ["s"],
              "cond": None, "sentence": None, "group": "method"},
             {"label": "Stubs", "key": "Kind", "values": ["t"],
              "cond": None, "sentence": None, "group": "method"},
             {"label": "High confidence only", "key": "Confidence",
              "values": ["high"], "cond": None, "sentence": None}]
    rows = [fx.history_row(i, Kind="s" if i <= 3 else "t",
                           Confidence="high" if i % 2 else "low")
            for i in range(1, 6)]
    seg = fx.segment(rows=rows, quick=quick)
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view([seg])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    count = "document.getElementById('wc-count').textContent"
    chips = "document.querySelectorAll('button.chip')"
    browser.evaluate("%s[0].click()" % chips)
    assert browser.evaluate(count).startswith("3 of 5 records")
    browser.evaluate("%s[1].click()" % chips)
    assert browser.evaluate(count).startswith("2 of 5 records")
    assert browser.evaluate(
        "Array.from(%s).map(function (b) { return b.classList.contains('on'); })"
        % chips) == [False, True, False]
    browser.evaluate("%s[2].click()" % chips)
    assert browser.evaluate(count).startswith("1 of 5 records")


def test_identical_and_empty_columns_fold_away_and_are_named(browser, tmp_path):
    """As the app's "Hide identical columns" (on by
    default), a column holding one value in every row on screen, or nothing
    at all, is hidden and named under the count; untick it and they return.
    The export still writes them, and its note says they were hidden."""
    rows = [fx.history_row(i, IsInPrivate=False, Origin=None)
            for i in range(1, 6)]
    seg = fx.segment(rows=rows)
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view([seg])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    heads = ("Array.from(document.querySelectorAll('#wc-grid thead th'))"
             ".map(function (t) { return t.textContent; }).join('|')")
    shown = browser.evaluate(heads)
    assert "InPrivate" not in shown and "Origin detail" not in shown
    assert "Address" in shown and "Visits" in shown
    line = browser.evaluate("document.getElementById('wc-identical').textContent")
    assert line.startswith("2 columns hidden: 1 identical, 1 empty in every row")
    assert "InPrivate: No" in line and "empty in every row: Origin detail" in line
    browser.evaluate("document.getElementById('wc-hide-identical').click()")
    shown = browser.evaluate(heads)
    assert "InPrivate" in shown and "Origin detail" in shown
    assert browser.evaluate(
        "document.getElementById('wc-identical').textContent").startswith(
            "Identical in all 5: ")


def test_a_column_with_a_filter_on_it_is_never_folded_away(browser, tmp_path):
    """The page's rule matches the app's: filtering a column down to one
    value must not hide it, or its filter could be neither seen nor cleared."""
    _open(browser, tmp_path, fx.snapshot())
    browser.evaluate("WC.openSegment('history', 'history')")
    browser.evaluate(
        "(function () { var b = Array.from(document.querySelectorAll('#wc-grid th'))"
        ".filter(function (t) { return t.textContent.indexOf('InPrivate') === 0; })[0]"
        ".querySelector('.funnel'); b.click(); })()")
    browser.evaluate("new Promise(function (ok) { setTimeout(ok, 50); })",
                     await_promise=True)
    browser.evaluate(
        "(function () { var p = document.querySelector('.popup');"
        " var no = Array.from(p.querySelectorAll('.values label')).filter("
        "function (l) { return l.querySelector('span').textContent === 'No'; })[0];"
        " no.querySelector('input').click();"
        " Array.from(p.querySelectorAll('button')).filter(function (b) {"
        " return b.textContent === 'Apply'; })[0].click(); })()")
    heads = browser.evaluate(
        "Array.from(document.querySelectorAll('#wc-grid thead th'))"
        ".map(function (t) { return t.textContent; }).join('|')")
    assert "InPrivate" in heads
    # Identical now (every row left is Yes) but shown: named as such, and
    # not counted among the hidden columns.
    line = browser.evaluate("document.getElementById('wc-identical').textContent")
    assert "InPrivate: Yes (filtered, shown)" in line, line
    assert line.startswith("1 column hidden: 1 identical — in all 2: "), line


def test_a_list_view_opens_on_its_first_table_that_holds_rows(browser,
                                                              tmp_path):
    """Raw tables opened on an empty table. A list picker
    with nothing chosen opens the first segment that holds rows."""
    from webcache.shell.html_package import PackageView
    empty = fx.segment(key="t:empty", label="Empty table", rows=[])
    full = fx.segment(key="t:full", label="Full table")
    view = PackageView("raw", "Raw tables", "DATABASE", "Raw ESE tables.",
                       [empty, full], picker="list")
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view(), view]))
    browser.evaluate("WC.go('view:raw')")
    assert browser.evaluate("document.getElementById('wc-count').textContent"
                            ).startswith("5 ")


def test_a_segment_cap_limits_its_wrapped_rows(browser, tmp_path):
    """A segment's own cap (Location: 3) is honoured."""
    long_text = "word " * 400
    # Distinct per row, or "Hide identical columns" would fold the column.
    rows = [fx.history_row(i, CleanUrl=long_text + str(i)) for i in range(1, 4)]
    heights = {}
    for cap in (None, 2):
        seg = fx.segment(rows=rows, cap=cap)
        _open(browser, tmp_path, fx.snapshot(views=[fx.history_view([seg])]))
        browser.evaluate("WC.setWrap(true)")
        browser.evaluate("WC.openSegment('history', 'history')")
        _settle(browser)
        heights[cap] = browser.evaluate(
            "document.querySelector('#wc-grid tbody tr[data-pos=\"0\"]')"
            ".getBoundingClientRect().height")
    assert heights[2] < heights[None]


def test_opening_a_view_with_search_text_drops_the_old_selection(browser,
                                                                tmp_path):
    """A search drill set new text but kept the previous
    row selected -- a selection pointing at a different row after the
    filter changed what is shown."""
    _open(browser, tmp_path, fx.snapshot())
    browser.evaluate("WC.openSegment('history', 'history')")
    browser.evaluate("document.querySelectorAll('#wc-grid tbody tr[data-pos]')[2]"
                     ".dispatchEvent(new MouseEvent('click', {bubbles: true}))")
    assert browser.evaluate("document.querySelectorAll('#wc-grid tr.sel').length") == 1
    browser.evaluate("WC.openSegment('history', 'history', 'page/1')")
    assert browser.evaluate("document.querySelectorAll('#wc-grid tr.sel').length") == 0


def test_the_members_table_keeps_its_header_in_view(browser, tmp_path):
    """A long members table scrolls under a sticky header."""
    _open(browser, tmp_path, fx.snapshot())
    assert browser.evaluate(
        "(function () { var t = document.createElement('table');"
        " t.className = 'members'; var th = document.createElement('th');"
        " t.appendChild(th); document.body.appendChild(t);"
        " var p = getComputedStyle(th).position; t.remove(); return p; })()"
    ) == "sticky"


def test_the_clock_choice_has_its_own_labelled_bar(browser, tmp_path):
    """UTC / Local sat among the grain buttons. The clock
    is its own bar, labelled "Clock:", ahead of the grains."""
    from webcache.shell.html_package import PackageView
    segs = [fx.segment(key="day_utc", label="By day", clock="utc"),
            fx.segment(key="hour_utc", label="By hour", clock="utc"),
            fx.segment(key="day_local", label="By day", clock="local"),
            fx.segment(key="hour_local", label="By hour", clock="local")]
    view = PackageView("timeline", "Timeline", "ANALYSIS", "Periods.", segs)
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view(), view]))
    browser.evaluate("WC.go('view:timeline')")
    clock = browser.evaluate(
        "(function () { var c = document.querySelector('.vhead .bar.clock');"
        " return c ? c.textContent : null; })()")
    assert clock is not None and clock.startswith("Clock:")
    assert "UTC" in clock and "By day" not in clock


def test_hiding_copies_says_how_many_are_hidden_and_that_they_still_count(
        browser, tmp_path):
    """The app's count line says "N duplicate copies hidden
    (left out of Export view; kept in the full case exports)" when the chip is on; the page says it too."""
    from webcache.shell.html_package import PackageColumn
    from webcache.widgets.column_spec import Column
    cols = fx.history_columns() + [PackageColumn.from_column(
        Column("Copies", "Copies", 120, kind="text", field="Copies"))]
    quick = [{"label": "Hide duplicate copies", "key": "Copies", "values": None,
              "cond": ["does not contain", "copy ", None],
              "sentence": "duplicate carved copies hidden"}]
    rows = [fx.history_row(1, Copies="1 of 3"), fx.history_row(2, Copies="copy 2 of 3"),
            fx.history_row(3, Copies="copy 3 of 3"), fx.history_row(4, Copies="")]
    seg = fx.segment(rows=rows, columns=cols, quick=quick)
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view([seg])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    browser.evaluate("document.querySelector('button.chip').click()")
    text = browser.evaluate("document.getElementById('wc-count').textContent")
    assert text.startswith("2 of 4 records")
    assert "2 duplicate copies hidden (left out of Export view; kept in the full case exports)" in text


def test_one_row_per_visit_works_in_the_report(browser, tmp_path):
    """It was offered as "(not reproduced)": on a real machine 169 File
    Access rows were MSHist copies of a visit whose History record was
    listed, and the report could not fold them. An MSHist row is hidden
    only while its History twin is on screen, as in the app."""
    from webcache.shell.package_snapshot import quick_spec
    from webcache.views.record_chips import one_row_per_visit_chip
    rows = [fx.history_row(i) for i in range(1, 4)]
    twin = fx.history_row(1)
    twin["_record"] = dict(twin["_record"], EntryId=51,
                           ContainerName="MSHist012024063020240701",
                           MSHistFrom="2024-06-30", VisitTwin=[("History", 1)])
    lone = fx.history_row(9)
    lone["_record"] = dict(lone["_record"], EntryId=59,
                           ContainerName="MSHist012024063020240701",
                           MSHistFrom="2024-06-30", VisitTwin=[("History", 99)])
    seg = fx.segment(rows=rows + [twin, lone],
                     quick=[quick_spec(one_row_per_visit_chip())])
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view([seg])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    count = "document.getElementById('wc-count').textContent"
    chip = browser.evaluate(
        "[document.querySelector('button.chip').textContent,"
        " document.querySelector('button.chip').disabled]")
    assert chip == ["One row per visit", False], chip
    browser.evaluate("document.querySelector('button.chip').click()")
    assert browser.evaluate(count).startswith("4 of 5 records"), (
        browser.evaluate(count))
    # The app's own sentence beside the count: hidden, not dropped.
    assert ("1 MSHist row hidden — each is the same visit as a History "
            "row shown (left out of Export view; kept in the full case exports)") in browser.evaluate(count)


def test_a_counted_chip_names_its_count_as_the_app_does(browser, tmp_path):
    """The app's chips say "Has search terms · 0" before the click; a
    colleague reading the report asks the same question of it. Counted
    over the whole segment, with the chip's own test."""
    quick = [{"label": "Local files only", "key": "IsLocalFile",
              "values": ["Yes"], "cond": None, "sentence": None,
              "counted": True},
             {"label": "Has search terms", "key": "SearchTerms",
              "values": None, "cond": ["is not blank", None, None],
              "sentence": None, "counted": True},
             {"label": "Hide duplicate copies", "key": "Copies",
              "values": None, "cond": ["does not contain", "copy ", None],
              "sentence": None, "counted": False}]
    rows = [fx.history_row(i, IsLocalFile=i <= 2, SearchTerms=None)
            for i in range(1, 6)]
    seg = fx.segment(rows=rows, quick=quick)
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view([seg])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    chips = browser.evaluate(
        "Array.from(document.querySelectorAll('button.chip')).map("
        "function (b) { return [b.textContent, b.title]; })")
    assert [c[0] for c in chips] == ["Local files only · 2",
                                     "Has search terms · 0",
                                     "Hide duplicate copies"]
    assert "2 of 5" in chips[0][1]


def test_the_snapshot_says_which_chips_count(qtbot):
    from webcache.shell.package_snapshot import quick_spec
    from webcache.views.record_chips import hide_copies_chip
    from webcache.views.history import HistoryView
    assert quick_spec(hide_copies_chip())["counted"] is False
    v = HistoryView()
    qtbot.addWidget(v)
    spec = next(s for s in v._quick_filters if s.attr == "chip_search_terms")
    assert quick_spec(spec)["counted"] is True


def test_a_share_column_is_drawn_as_the_app_draws_it(browser, tmp_path):
    """Timeline's "Relative volume" is a 0..1 share the app paints as a
    bar. The report printed the fraction ("0.0653", "1.0"), a number no
    reader was told how to read. Drawn, with the percentage on hover and
    for a screen reader; the value itself stays in search and exports."""
    cols = [PackageColumn("Period", "Period"),
            PackageColumn("Share", "Relative volume", kind="bar")]
    seg = PackageSegment("day_utc", "By day (UTC)", cols, [
        {"Period": "2026-01-01", "Share": 1.0, "_kind": "table_row",
         "_record": None},
        {"Period": "2026-01-02", "Share": 0.25, "_kind": "table_row",
         "_record": None}])
    _open(browser, tmp_path, fx.snapshot(views=[
        PackageView("timeline", "Timeline", "ANALYSIS", "", [seg])]))
    browser.evaluate("WC.openSegment('timeline', 'day_utc')")
    _settle(browser)
    bars = browser.evaluate(
        "Array.from(document.querySelectorAll('#wc-grid .share > i')).map("
        "function (b) { return [b.style.width, b.parentNode.title,"
        " b.parentNode.getAttribute('aria-label'),"
        " b.parentNode.parentNode.textContent]; })")
    # bar_delegate.ShareBarDelegate: square-root width, linear words.
    assert [b[0] for b in bars] == ["100%", "50%"]
    assert bars[1][1] == bars[1][2]
    assert bars[1][1].startswith("25.0% of the busiest day in this view.")
    assert "square-root" in bars[1][1]
    assert bars[1][3] == "", "the fraction is not printed beside the bar"
    # The peak is the busiest row ON SCREEN, as the app rescales it.
    browser.evaluate("(function () { var b = document.getElementById('wc-filter');"
                     " b.value = '2026-01-02'; b.dispatchEvent(new Event('input')); })()")
    _settle(browser)
    assert browser.evaluate(
        "document.querySelector('#wc-grid .share > i').style.width") == "100%"


def test_a_chip_at_zero_carries_the_apps_scope_note(browser, tmp_path):
    """The app's "Has search terms" at zero states what the zero covers;
    the report's chip says the same."""
    note = "A scope sentence for this zero."
    quick = [{"label": "Has search terms", "key": "SearchTerms",
              "values": None, "cond": ["is not blank", None, None],
              "sentence": None, "counted": True, "none_note": note}]
    rows = [fx.history_row(i, SearchTerms=None) for i in range(1, 4)]
    seg = fx.segment(rows=rows, quick=quick)
    _open(browser, tmp_path, fx.snapshot(views=[fx.history_view([seg])]))
    browser.evaluate("WC.openSegment('history', 'history')")
    title = browser.evaluate("document.querySelector('button.chip').title")
    assert note in title


def test_the_snapshot_carries_a_chips_scope_note(qtbot):
    from webcache.shell.package_snapshot import quick_spec
    from webcache.views.history import HistoryView
    v = HistoryView()
    qtbot.addWidget(v)
    spec = next(s for s in v._quick_filters if s.attr == "chip_search_terms")
    assert "Chromium-based Edge" in quick_spec(spec)["none_note"]
