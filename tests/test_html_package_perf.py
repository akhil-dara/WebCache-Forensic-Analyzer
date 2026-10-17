"""The offline report's budgets, on synthetic data only. Never loosened: a
failure here is a performance defect to fix, not a number to raise. The
Python-side write budget is stated for the examiner's workstation and
stretched only on a machine that measures itself slower
(test_perf.machine_factor) -- the release runner wrote the package in
10.47 s with the code unchanged."""
import time

import pytest

from tests import _package_fixtures as fx

BIG = 50_000
#: Deleted Records on the largest sample exhibit, the largest segment
#: measured.
XLSX_ROWS = 2_742


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    from webcache.shell.html_package import write_package
    rows = [fx.history_row(i) for i in range(1, BIG + 1)]
    path = str(tmp_path_factory.mktemp("perf") / "big.html")
    started = time.perf_counter()
    write_package(fx.snapshot(views=[fx.history_view([fx.segment(rows=rows)])]),
                  path, generated_utc=fx.GENERATED)
    return path, time.perf_counter() - started


def _ms(browser, body):
    return browser.evaluate(
        "(function () { var m = WC.model('history', 'history');"
        " var t = performance.now(); %s; return performance.now() - t; })()"
        % body)


def test_a_50k_row_package_is_written_within_10_s(big):
    from tests.test_perf import machine_factor
    budget = 10.0 * machine_factor()
    assert big[1] <= budget, "%.2f s against %.2f s" % (big[1], budget)


def test_a_50k_row_segment_filters_within_300_ms_and_sorts_within_500_ms(
        browser, big):
    browser.open(big[0])
    filtered = _ms(browser, "m.setText('page/4999')")
    assert filtered <= 300, filtered
    ordered = _ms(browser, "m.setText(''); m.setSort(1, true)")
    assert ordered <= 500, ordered


def test_a_50k_row_segment_draws_only_the_rows_in_view(browser, big):
    browser.open(big[0])
    browser.evaluate("WC.openSegment('history', 'history')")
    assert browser.evaluate("document.querySelectorAll('#wc-grid tbody "
                            "tr:not(.spacer)').length") <= 120


def test_the_largest_sample_segment_exports_to_xlsx_within_5_s(browser,
                                                             tmp_path):
    rows = [fx.history_row(i, carved=bool(i % 2))
            for i in range(1, XLSX_ROWS + 1)]
    browser.clear_downloads()
    browser.open(fx.write(tmp_path, fx.snapshot(
        views=[fx.history_view([fx.segment(rows=rows)])])))
    took = browser.evaluate(
        "(function () { var t = performance.now(); return WC.exportXlsx("
        "'history', 'history', false).then(function () {"
        " return performance.now() - t; }); })()", await_promise=True)
    assert took <= 5000, took
    assert browser.wait_download("webcache_history.xlsx")
