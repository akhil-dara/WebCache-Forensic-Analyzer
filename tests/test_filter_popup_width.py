"""The value picker is as wide as its values need, within a cap: a column of
long addresses no longer wraps each one onto three lines in a narrow box,
and a Yes/No column stays compact."""
from webcache.widgets.column_spec import Column
from webcache.widgets.filter_popup import FilterPopup
from webcache.widgets.record_model import RecordTableModel

LONG = Column("Url", "Address", 300, kind="url")
SHORT = Column("Flag", "InPrivate", 80, kind="flag")


def _popup(qtbot, column, values):
    model = RecordTableModel([column], [{column.key: v} for v in values])
    popup = FilterPopup(model, column)
    qtbot.addWidget(popup)
    popup.show()
    qtbot.waitExposed(popup)
    return popup


def test_long_values_widen_the_picker_and_short_ones_do_not(qtbot):
    long_values = ["https://example.test/a/very/long/path/%d/segment/that/"
                   "keeps/going/for/a/while/page.html" % i for i in range(30)]
    wide = _popup(qtbot, LONG, long_values)
    narrow = _popup(qtbot, SHORT, [True, False] * 15)
    assert wide.width() > narrow.width() + 100, (wide.width(), narrow.width())


def test_the_picker_never_grows_past_its_cap(qtbot):
    huge = ["x" * 2000 + str(i) for i in range(5)]
    popup = _popup(qtbot, LONG, huge)
    assert popup.width() <= FilterPopup.MAX_WIDTH
