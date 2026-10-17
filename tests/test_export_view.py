"""Export & Report: every declared format gets a card, and a card that
cannot run says so on screen instead of vanishing.

The rule this file exists to hold: set_available(False, reason) NEVER
hides and NEVER removes. A format that disappears from the page when it
cannot run teaches an examiner the tool does not have it; a greyed card
carrying its own sentence teaches them why it cannot run right now.
"""
import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from webcache.shell import export_formats as F
from webcache.views.export import ExportView, FormatCard


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app):
    v = ExportView()
    yield v
    v.deleteLater()


# --- every catalogue entry is on the page -------------------------------

def test_every_catalogue_entry_has_a_card(view):
    assert set(view.cards) == {f.key for f in F.CATALOGUE}


def test_a_card_knows_its_own_format(view):
    assert view.cards["csv"].fmt.key == "csv"


def test_the_bundle_card_is_separate_from_the_format_grid(view):
    assert view.bundle_card is not None
    assert view.bundle_button.text().startswith("Export bundle")


def test_every_group_label_is_on_the_page(view):
    labels = {lbl.text() for lbl in view.group_labels.values()}
    assert F.G_COURT in labels
    assert F.G_GENERAL in labels
    assert F.G_POSITION in labels


# --- disabled means visible, greyed and explained -----------------------

def test_a_disabled_card_is_still_in_the_layout(view):
    view.set_availability(F.availability(F.capabilities(None, [], None, None)))
    card = view.cards["pdf"]
    assert card.parent() is not None
    assert view.grid_for(card.fmt.group).indexOf(card) >= 0, (
        "a card that cannot run must keep its position, not leave a hole")


def test_a_disabled_card_shows_the_reason_verbatim(view):
    reason = F.UNAVAILABLE_REASON["location_fixes"]
    view.set_availability({"loc_kml": (False, reason)})
    card = view.cards["loc_kml"]
    assert card.reason_label.isVisibleTo(view)
    assert card.reason_label.text() == reason


def test_a_disabled_cards_button_is_disabled_and_tooltipped(view):
    reason = F.UNAVAILABLE_REASON["entries"]
    view.set_availability({"csv": (False, reason)})
    card = view.cards["csv"]
    assert not card.button.isEnabled()
    assert card.button.toolTip() == reason


def test_making_a_card_available_again_reverses_every_part(view):
    view.set_availability({"csv": (False, F.UNAVAILABLE_REASON["entries"])})
    view.set_availability({"csv": (True, "")})
    card = view.cards["csv"]
    assert card.button.isEnabled()
    assert card.button.toolTip() == ""
    assert not card.reason_label.isVisibleTo(view)
    assert card.available is True


def test_the_position_cards_read_unavailable_on_a_fully_loaded_exhibit(view):
    caps = F.capabilities(object(), [{"Url": "u"}], {"total_entries": 1}, None)
    view.set_availability(F.availability(caps))
    assert view.cards["loc_csv"].available is False
    assert view.cards["csv"].available is True


# --- asking for an export -----------------------------------------------

def test_clicking_a_card_emits_its_own_key(view, app):
    view.set_availability({"csv": (True, "")})
    seen = []
    view.exportRequested.connect(seen.append)
    view.cards["csv"].button.click()
    assert seen == ["csv"]


def test_the_bundle_button_asks_for_the_bundle(view):
    view.set_availability({"bundle": (True, "")})
    seen = []
    view.exportRequested.connect(seen.append)
    view.bundle_button.click()
    assert seen == ["bundle"]


# --- failure lands on the card, and stays -------------------------------

def test_a_failure_message_stays_on_the_card_that_caused_it(view):
    """[4] report_failed used to hand the message to set_available(False,
    message) -- the channel reserved for "this FORMAT cannot run on this
    exhibit", painted in reason_label. A write failure is a fact about
    THIS ATTEMPT, not about the format, so it must stay on screen (a
    message that vanishes is a message that did not happen) through its
    OWN channel -- never reason_label, which set_available still owns
    exclusively."""
    view.set_availability({"csv": (True, "")})
    view.report_failed("csv", "Disk full while writing row 4,102.")
    card = view.cards["csv"]
    assert card.error_label.text() == "Disk full while writing row 4,102."
    assert card.error_label.isVisibleTo(view)
    assert card.reason_label.text() == "", (
        "a write failure must never borrow the unavailability channel")


def test_a_failed_export_does_not_permanently_disable_its_card(view):
    """[4] Verified against a real MainWindow: a PermissionError (the
    destination locked by Excel, a read-only volume) permanently removed
    that format for the rest of the session, because report_failed's
    message became the card's own UNAVAILABILITY reason -- which disables
    the button and nothing ever re-enables it. A transient failure is not
    the same fact as "this format does not apply here"; the button must
    stay usable so the examiner can simply try again."""
    view.set_availability({"csv": (True, "")})
    view.report_failed("csv", "Permission denied.")
    card = view.cards["csv"]
    assert card.available is True
    assert card.button.isEnabled()


def test_a_new_export_attempt_clears_the_previous_failure(view):
    """The stale error must not linger forever once the examiner tries
    again -- set_busy(True, ...) is what _start_export calls at the top
    of every attempt, format card or bundle alike."""
    view.set_availability({"csv": (True, "")})
    view.report_failed("csv", "Permission denied.")
    card = view.cards["csv"]
    view.set_busy("csv", True, "Writing…")
    assert card.error_label.text() == ""
    assert not card.error_label.isVisibleTo(view)


def test_a_failed_bundle_does_not_permanently_disable_its_card(view):
    """The bundle's card is a plain Card behind _BundleCardAdapter, kept
    to the identical set_available/set_busy/report_failed surface as
    every FormatCard -- the same defect, the same fix, one code path."""
    view.set_availability({"bundle": (True, "")})
    view.report_failed("bundle", "Permission denied.")
    card = view.cards["bundle"]
    assert card.available is True
    assert card.button.isEnabled()


def test_a_failure_also_lands_in_the_result_strip(view):
    view.report_failed("csv", "Disk full.")
    assert "Disk full." in view.result_line.text()


# --- busy ---------------------------------------------------------------

def test_a_busy_card_disables_its_button_and_says_what_it_is_doing(view):
    view.set_availability({"xlsx": (True, "")})
    view.set_busy("xlsx", True, "Writing workbook…")
    card = view.cards["xlsx"]
    assert not card.button.isEnabled()
    assert "Writing workbook" in card.busy_label.text()
    view.set_busy("xlsx", False)
    assert card.button.isEnabled()


def test_busy_does_not_re_enable_a_card_that_was_unavailable(view):
    view.set_availability({"pdf": (False, F.UNAVAILABLE_REASON["reportlab"])})
    view.set_busy("pdf", True, "…")
    view.set_busy("pdf", False)
    assert not view.cards["pdf"].button.isEnabled()


# --- coverage, metadata, result -----------------------------------------

def test_the_coverage_line_is_built_once_and_used_twice(view):
    view.set_coverage({"records": 3915, "cookies": 42, "hsts": 7, "certs": 3,
                       "leaks": 1, "recovered": None})
    assert "3,915 records" in view.coverage_text
    assert "deleted records not yet recovered" in view.coverage_text, (
        "a 0 there would be a claim nobody has checked")
    assert view.coverage_text in view.bundle_coverage_label.text()


def test_the_coverage_line_states_a_real_recovered_count_after_a_scan(view):
    view.set_coverage({"records": 10, "cookies": 0, "hsts": 0, "certs": 0,
                       "leaks": 0, "recovered": 222})
    assert "222 recovered" in view.coverage_text


def test_the_coverage_line_names_what_it_counts(view):
    """"0 leaks" named nothing an examiner could look up, and "certs" and
    "HSTS" were not what the Cookies & HSTS tabs call the same things."""
    view.set_coverage({"records": 10, "cookies": 1, "hsts": 2, "certs": 3,
                       "leaks": 4, "recovered": 5})
    text = view.coverage_text
    assert "2 HSTS pins" in text and "3 certificates" in text, text
    assert "4 leak files" in text, text
    assert "1 cookie ·" in text, text
    view.set_coverage({"records": 1, "cookies": 0, "hsts": 1, "certs": 1,
                       "leaks": 1, "recovered": 1})
    assert view.coverage_text.startswith(
        "1 record · 0 cookies · 1 HSTS pin · 1 certificate · 1 leak file"), (
        view.coverage_text)
    tip = view.bundle_coverage_label.toolTip()
    assert "could not delete" in tip and "locked" in tip, tip


def test_case_metadata_is_disabled_until_an_exhibit_is_open(view):
    view.set_case_enabled(False, "Open a database first.")
    assert not view.examiner_field.isEnabled()
    assert not view.notes_field.isEnabled()
    assert "Open a database first." in view.case_note_label.text()


def test_filling_the_case_fields_never_re_emits_them(view):
    view.set_case_enabled(True)
    seen = []
    view.caseMetaChanged.connect(lambda k, v: seen.append((k, v)))
    view.set_case_meta({"examiner": "A", "case_number": "1",
                        "evidence_id": "E", "notes": "n"})
    assert seen == [], "set_case_meta must block signals while filling"
    assert view.examiner_field.text() == "A"
    assert view.notes_field.toPlainText() == "n"


def test_typing_reaches_the_signal_through_a_gui_thread_timer(view, app):
    view.set_case_enabled(True)
    seen = []
    view.caseMetaChanged.connect(lambda k, v: seen.append((k, v)))
    view.examiner_field.setText("Examiner Name")
    view.flush_case_meta()          # what the 400ms QTimer would fire
    assert ("examiner", "Examiner Name") in seen


def test_the_result_strip_is_empty_until_something_is_written(view):
    assert view.result_line.text() == ""
    assert not view.copy_path_button.isEnabled()


def test_reporting_a_write_arms_copy_path(view):
    view.report_written([r"C:\out\webcache_history.csv",
                        r"C:\out\webcache_history.csv.provenance.txt"],
                        "Exported 1,204 rows")
    assert "webcache_history.csv" in view.result_line.text()
    assert view.copy_path_button.isEnabled()


def test_copy_path_asks_for_the_first_path_written(view):
    seen = []
    view.copyPathRequested.connect(seen.append)
    view.report_written([r"C:\out\a.csv", r"C:\out\a.csv.provenance.txt"],
                        "done")
    view.copy_path_button.click()
    assert seen == [r"C:\out\a.csv"]


def test_there_is_no_open_folder_button_anywhere(view):
    """Standing rule: Copy, never Open. An export path names a location on
    the examiner's own machine."""
    for btn in view.findChildren(QPushButton):
        assert "open folder" not in btn.text().lower()
        assert "reveal" not in btn.text().lower()


# --- the footnote -------------------------------------------------------

def test_the_footnote_interpolates_the_field_count_rather_than_hardcoding(view):
    view.set_field_count(F.CANONICAL_FIELD_COUNT)
    text = view.footnote_label.text()
    assert str(F.CANONICAL_FIELD_COUNT) in text
    assert "69" not in text or F.CANONICAL_FIELD_COUNT == 69, (
        "a hardcoded field count goes wrong when the schema grows")
    assert "RFC 3339" in text and "LOCAL" in text


# --- the page must scroll -----------------------------------------------

def test_the_page_scrolls_because_nine_cards_do_not_fit_900px(view):
    from PySide6.QtWidgets import QScrollArea
    assert view.findChild(QScrollArea) is not None


def test_refresh_theme_reaches_every_card(view):
    view.refresh_theme()        # must not raise
    assert isinstance(view.cards["csv"], FormatCard)


def test_every_case_field_hints_what_belongs_in_it(view):
    from webcache.views.export import CASE_FIELDS
    for attr, label, _key in CASE_FIELDS:
        hint = getattr(view, attr).placeholderText()
        assert hint and hint != label, attr
