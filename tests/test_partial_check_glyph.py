"""The tri-state "partly selected" box is not
shown by colour alone -- it carries a dash glyph, as a checked box
carries a tick."""
import os
import re

from PySide6.QtWidgets import QApplication

from webcache.shell import theme


def _rule(sheet, selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", sheet)
    return match.group(1) if match else ""


def test_the_partial_box_draws_a_dash_in_both_themes(qapp):
    app = QApplication.instance()
    for name in ("dark", "light"):
        theme.apply(app, name)
        rule = _rule(app.styleSheet(), "QTreeView::indicator:indeterminate")
        image = re.search(r"image:\s*url\(([^)]*)\)", rule)
        assert image, (name, rule)
        path = image.group(1)
        assert os.path.exists(path), path
        assert path != theme.PALETTES[name]["check_mark"]
    theme.apply(app, "dark")
