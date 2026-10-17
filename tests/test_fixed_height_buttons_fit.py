"""A button given a fixed height still has room for its label.

The application stylesheet pads every push button vertically; a button
fixed at a smaller height than that padding plus one line of text draws
its label cut at the bottom. Each such button is trimmed in the
stylesheet, and its size hint (which includes the stylesheet's padding)
must fit the height it was given."""
from PySide6.QtWidgets import QApplication, QPushButton

from webcache.shell import theme
from webcache.shell.main_window import MainWindow

#: One line of the Windows interface font, in logical pixels.
REAL_LINE = 16


def test_every_fixed_height_button_fits_its_label(qtbot, tmp_path,
                                                   monkeypatch):
    import webcache.paths as paths
    monkeypatch.setattr(paths, "settings_path", lambda: tmp_path / "s.json")
    app = QApplication.instance()
    w = MainWindow()
    qtbot.addWidget(w)
    for key in ("history", "domains"):
        w._ensure_view_built(key)
    w.go_to("history")
    for name in ("dark", "light"):
        theme.apply(app, name)
        cut = []
        for button in w.findChildren(QPushButton):
            fixed = button.minimumHeight() == button.maximumHeight()
            if not fixed or not button.text() or button.property("compact"):
                continue
            button.ensurePolished()
            # Padding and border from the stylesheet, plus a line of the
            # real interface font: the offscreen platform's stand-in font
            # is shorter and would hide a cut label.
            chrome = button.sizeHint().height() - button.fontMetrics().height()
            needed = chrome + max(button.fontMetrics().height(), REAL_LINE)
            if needed > button.maximumHeight():
                cut.append((button.text(), needed, button.maximumHeight()))
        assert cut == [], name
