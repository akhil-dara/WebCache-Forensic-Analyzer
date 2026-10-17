"""Every engine module imports cleanly, and none of them needs the GUI."""
import importlib
import pathlib

import pytest

MODULES = ["ese_parser", "recovery_engine", "forensic_engine", "struct_carver",
           "sps_decoder", "download_decoder", "url_intel", "evidence_model",
           "case_db", "geolocation", "analysis_extra", "app_settings",
           "local_clock"]


@pytest.mark.parametrize("name", MODULES)
def test_engine_module_imports(name):
    assert importlib.import_module("webcache.engine." + name) is not None


def test_engine_stays_gui_free():
    root = pathlib.Path(__file__).resolve().parent.parent / "webcache" / "engine"
    bad = [p.name for p in root.glob("*.py")
           if "PySide6" in p.read_text(encoding="utf-8")]
    assert bad == [], "engine modules must be GUI-free: %s" % bad
