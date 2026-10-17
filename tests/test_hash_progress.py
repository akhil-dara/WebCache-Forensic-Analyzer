"""While the Open dialog hashes, it says how far
it has got in bytes, beside the disabled Open button; and the centre card,
which appears only once hashing has finished, says it is reading the
database -- not hashing it."""
from webcache.shell.first_run import FirstRunView
from webcache.shell.open_evidence import OpenEvidenceDialog


def test_the_opening_card_says_reading_not_hashing(qtbot):
    view = FirstRunView()
    qtbot.addWidget(view)
    view.set_opening("WebCacheV01.dat")
    assert view.body.text().startswith("Reading the database")
    assert "Hashing" not in view.body.text()


def test_the_dialog_reports_bytes_hashed(qtbot, tmp_path):
    evidence = tmp_path / "WebCacheV01.dat"
    evidence.write_bytes(b"\x00" * (3 * (1 << 20) + 17))
    dialog = OpenEvidenceDialog(str(evidence))
    qtbot.addWidget(dialog)
    seen = []
    real = dialog._progress_label.setText
    dialog._progress_label.setText = lambda t: (seen.append(t), real(t))
    with qtbot.waitSignal(dialog.hashingFinished, timeout=10_000):
        dialog.ok_button.click()
    assert any("MB of" in t and t.startswith("Hashing") for t in seen), seen
