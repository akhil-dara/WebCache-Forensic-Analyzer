"""Evidence text is never rendered as markup.

A QLabel's default text format is Qt.AutoText: a text Qt.mightBeRichText
judges to be markup (one that starts with a tag, for example) is RENDERED
as rich text. Evidence is attacker-influenced -- a page title or URL can
be anything -- so a stored value like "<b>bold</b>" showed as bold, and
one like '<img src="x">' showed as nothing at all. Every label in the
application is PlainText, except the few that build escaped markup on
purpose and say so with an explicit Qt.RichText.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from webcache.provenance import EvidenceSet
from webcache.shell.open_evidence import OpenEvidenceDialog
from webcache.shell.main_window import MainWindow
from webcache.shell.record_detail import RecordDetailDialog
from webcache.widgets.wrapping_text import WrappingText

from tests.fixtures import make_rows
from tests.test_detail_fields import history_row

_EVIDENCE_PATH = r"C:\case\WebCacheV01.dat"
_MARKUP_TITLE = '<b>bold</b><img src="x">'
_MARKUP_URL = "<b>https://example.test/</b>"


@pytest.fixture(autouse=True)
def _settings_go_somewhere_disposable(tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")


def _auto_text_labels(root):
    """Every label that would guess its own format from its text."""
    bad = []
    for label in root.findChildren(QLabel):
        if label.textFormat() == Qt.AutoText and label.text():
            bad.append("%s/%s: %r" % (type(label.parent()).__name__,
                                      type(label).__name__,
                                      label.text()[:40]))
    return bad


def _carrying(dlg, needle):
    """Every widget in the dialog showing `needle`: QLabels, plus the
    identity line, which is a WrappingText (a QTextEdit), not a QLabel
    -- it never renders markup at all (setPlainText only),
    but it is still a value carrier this test must account for."""
    found = [l for l in dlg.findChildren(QLabel) if needle in l.text()]
    identity = getattr(dlg, "identity_label", None)
    if isinstance(identity, WrappingText) and needle in identity.full_text():
        found.append(identity)
    return found


def _renders_literally(label):
    """PlainText, and wide enough to be showing the characters: rendered
    as rich text, '<img src="x">' has no visible width at all."""
    if label.textFormat() != Qt.PlainText:
        return False
    literal = label.text()
    return (label.sizeHint().width()
            >= label.fontMetrics().horizontalAdvance(literal) - 4)


@pytest.fixture
def dialog(qtbot):
    made = []

    def _build(row):
        parent = QWidget()
        made.append(parent)
        parent.resize(1500, 900)
        parent.show()
        dlg = RecordDetailDialog(row, parent)
        made.append(dlg)
        dlg.resize(1279, 724)
        dlg.show()
        qtbot.waitExposed(dlg)
        return dlg

    yield _build
    for widget in reversed(made):
        try:
            widget.close()
        except RuntimeError:
            pass


def test_a_markup_title_renders_literally_in_the_record_dialog(dialog):
    row = history_row(Title=_MARKUP_TITLE, CleanUrl=_MARKUP_URL)
    row["_record"] = dict(row["_record"], SPS_PageTitle=_MARKUP_TITLE,
                          CleanUrl=_MARKUP_URL)
    dlg = dialog(row)
    carrying = _carrying(dlg, "<b>") + _carrying(dlg, "<img")
    assert carrying, "no label in the dialog shows the synthetic value"
    rendered_as_markup = [l.text()[:40] for l in carrying
                          if l.textFormat() != Qt.PlainText]
    assert not rendered_as_markup, (
        "evidence rendered as markup: %r" % rendered_as_markup)
    assert _renders_literally(dlg.identity_label) or \
        "<" not in dlg.identity_label.text()


def test_a_bare_img_tag_is_shown_not_swallowed(dialog):
    row = history_row(Title='<img src="x">', CleanUrl='<img src="x">')
    row["_record"] = dict(row["_record"], SPS_PageTitle='<img src="x">',
                          CleanUrl='<img src="x">')
    dlg = dialog(row)
    carrying = _carrying(dlg, "<img")
    assert carrying
    assert all(_renders_literally(l) for l in carrying), [
        (l.text()[:30], l.textFormat().name, l.sizeHint().width())
        for l in carrying]


def test_no_label_in_the_main_window_guesses_its_format(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    w._on_evidence_loaded(
        {"rows": make_rows(20), "parser": None},
        EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                    {_EVIDENCE_PATH: "a" * 64}))
    for key in w.nav_keys:
        w.go_to(key)
    assert _auto_text_labels(w) == []


def test_no_label_in_the_record_dialog_guesses_its_format(dialog):
    assert _auto_text_labels(dialog(history_row())) == []


def test_no_label_in_the_consent_dialog_guesses_its_format(qtbot, tmp_path):
    # It shows evidence file paths; Windows forbids "<" in a name, but an
    # image mounted from another filesystem does not.
    evidence = tmp_path / "WebCacheV01.dat"
    evidence.write_bytes(b"not a real ese db")
    d = OpenEvidenceDialog(str(evidence))
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    assert _auto_text_labels(d) == []
