"""Sub-project D: the examiner's chosen export set. Removed: two
third-party-layout files (kape_csv, timesketch) and the position-fixes PDF.
Kept: xlsx, csv, both SQLite files, json, the signed PDF report, the
position-fix KML, CSV, JSON and XLSX, and the offline HTML report.
Removed means gone everywhere: the catalogue, the bundle, the runner and
the engine writers behind them."""
from webcache.engine import forensic_engine
from webcache.shell import export_formats, export_runner

REMOVED = ("kape_csv", "timesketch", "loc_pdf")
REMOVED_WRITERS = ("export_kape_csv", "export_timesketch_jsonl",
                   "export_location_pdf")


def test_the_removed_formats_are_not_offered():
    keys = {f.key for f in export_formats.CATALOGUE}
    assert not keys & set(REMOVED)
    for kept in ("csv", "xlsx", "sqlite", "sqlite_raw", "json", "pdf",
                 "html", "loc_kml", "loc_csv", "loc_json", "loc_xlsx"):
        assert kept in keys, kept


def test_the_bundle_writes_none_of_them_and_numbers_its_files_in_order():
    keys = [k for k, _label, _name in export_formats.BUNDLE_MEMBERS]
    assert not set(keys) & set(REMOVED)
    names = [name for _k, _l, name in export_formats.BUNDLE_MEMBERS]
    assert [n[:2] for n in names] == ["%02d" % i
                                      for i in range(1, len(names) + 1)]


def test_no_writer_for_them_remains():
    import inspect
    source = inspect.getsource(export_runner)
    for key in REMOVED:
        assert '"%s"' % key not in source, key
    for name in REMOVED_WRITERS:
        assert not hasattr(forensic_engine.ForensicEngine, name), name
