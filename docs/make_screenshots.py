"""Regenerate the README's screenshots from a MADE-UP exhibit.

Nothing here comes from real evidence: every URL, user, file and time is
invented below (fictional .test / .example hosts, a user called jdoe), fed
through the real parser and the real window. Run from the repository root
on Windows, with the Segoe UI font:

    python -m docs.make_screenshots

Writes docs/screenshots/*.png. Never touches the user's settings or case
files: both are pointed at a temporary folder first.
"""
import datetime
import hashlib
import pathlib
import random
import sys
import tempfile

from webcache import paths

_SCRATCH = pathlib.Path(tempfile.mkdtemp(prefix="wc-shots-"))
paths.settings_path = lambda: _SCRATCH / "settings.json"
paths.cases_dir = lambda: _SCRATCH / "cases"
paths.default_cases_dir = lambda: _SCRATCH / "cases"
(_SCRATCH / "cases").mkdir()

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / "screenshots"
UTC = datetime.timezone.utc
USER = "jdoe"
ZONE = 2 * 3600                     # the made-up machine's clock: UTC+2
START = datetime.datetime(2025, 3, 3, 7, 40, tzinfo=UTC)

SITES = [
    ("https://mail.contoso.test/inbox", "Inbox - Contoso Mail"),
    ("https://mail.contoso.test/message/88412", "Re: Q3 forecast - Contoso Mail"),
    ("https://portal.fabrikam.test/hr/payroll", "Payroll - Fabrikam HR"),
    ("https://portal.fabrikam.test/vpn/download", "VPN client - Fabrikam"),
    ("https://search.example.org/search?q=how+to+clear+browser+history", "how to clear browser history - Search"),
    ("https://search.example.org/search?q=usb+file+transfer+log", "usb file transfer log - Search"),
    ("https://search.example.org/search?q=delete+recent+files+windows", "delete recent files windows - Search"),
    ("https://news.example.com/world/2025/03/markets-open-higher", "Markets open higher - Example News"),
    ("https://docs.example.net/guides/sharing-large-files", "Sharing large files - Docs"),
    ("https://cloud.example.com/share/7f3c9a/project-files", "project-files - Example Cloud"),
    ("https://cloud.example.com/upload?folder=7f3c9a", "Upload - Example Cloud"),
    ("https://login.example.org/oauth2/authorize?client_id=4411&redirect_uri=https://cloud.example.com/", "Sign in"),
    ("https://intranet.fabrikam.test/projects/apollo/specs", "Apollo specs - Intranet"),
    ("https://maps.example.com/place/Harbour+Street+12", "Harbour Street 12 - Maps"),
    ("https://shop.example.net/orders/55120", "Order 55120 - Example Shop"),
]
FILES = [
    "file:///C:/Users/jdoe/Documents/Q3-forecast-final.xlsx",
    "file:///C:/Users/jdoe/Documents/Apollo/specs-v4.pdf",
    "file:///E:/transfer/project-files.zip",
    "file:///C:/Users/jdoe/Desktop/notes.txt",
]


def sps_blob(local_filetime, visits, title):
    """An [MS-PROPSTORE] set as the browser writes one: the local-clock
    last visit (id 24), the visit count (id 6) and the page title."""
    import struct
    import uuid

    def prop(pid, vt, payload):
        body = struct.pack("<I", pid) + b"\x00" + struct.pack("<HH", vt, 0) + payload
        return struct.pack("<I", 4 + len(body)) + body
    text = (title + "\x00").encode("utf-16-le")
    props = (prop(24, 0x0040, struct.pack("<Q", local_filetime))
             + prop(6, 0x0003, struct.pack("<i", visits))
             + (prop(2, 0x001F, struct.pack("<I", len(text) // 2) + text)
                if title else b""))
    body = b"1SPS" + uuid.UUID(int=7).bytes_le + props + struct.pack("<I", 0)
    return struct.pack("<I", 4 + len(body)) + body + struct.pack("<I", 0)


def build_exhibit():
    """A real WebCacheParser over a made-up database (the way the suite
    builds one: tests/test_mshist_local_clock.py)."""
    from tests.test_mshist_local_clock import _Db, _Record, ft
    from webcache.engine.ese_parser import WebCacheParser

    rnd = random.Random(2025)

    def container(cid, name):
        return _Record({"ContainerId": cid, "Name": name, "Directory": "",
                        "PartitionId": "", "Flags": 0, "Size": 0,
                        "Limit": 0, "LastScavengeTime": 0,
                        "LastAccessTime": 0, "EntryMaxAge": 0,
                        "SecureDirectories": None})

    visits = []
    t = START
    for i in range(150):
        t += datetime.timedelta(minutes=rnd.choice([3, 7, 12, 25, 41, 95, 180, 600]))
        url, title = (rnd.choice(SITES) if rnd.random() > 0.12
                      else (rnd.choice(FILES), ""))
        visits.append((t, url, title, rnd.choice([1, 1, 2, 3, 5, 8, 13])))

    history, daily = [], {}
    for i, (when, url, title, count) in enumerate(visits):
        local = when.replace(tzinfo=None) + datetime.timedelta(seconds=ZONE)
        history.append(_Record({
            "EntryId": 100 + i, "Url": "Visited: %s@%s" % (USER, url),
            "ModifiedTime": ft(when), "AccessedTime": ft(when),
            "ExpiryTime": 0, "AccessCount": count,
            "ResponseHeaders": sps_blob(ft(local), count, title),
            "Flags": 0}))
        day = local.date()
        name = "MSHist01%s%s" % (day.strftime("%Y%m%d"),
                                 (day + datetime.timedelta(days=1)).strftime("%Y%m%d"))
        daily.setdefault(name, []).append(_Record({
            "EntryId": 5000 + i,
            "Url": ":%s%s: %s@%s" % (name[8:16], name[16:24], USER, url),
            "ModifiedTime": ft(local), "AccessedTime": ft(when),
            "AccessCount": count, "Flags": 0}))

    content = []
    for i, (when, url, _title, _c) in enumerate(visits[::3]):
        if not url.startswith("http"):
            continue
        headers = ("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                   "Server: example-edge\r\nCache-Control: private, max-age=0\r\n"
                   "X-Request-Id: %08x\r\n\r\n" % rnd.getrandbits(32)).encode()
        content.append(_Record({
            "EntryId": 9000 + i, "Url": url, "ModifiedTime": ft(when),
            "AccessedTime": ft(when), "ExpiryTime": ft(when + datetime.timedelta(days=7)),
            "AccessCount": 1, "ResponseHeaders": headers, "Flags": 0,
            "Filename": "page%03d[1].htm" % i, "FileSize": rnd.randrange(8_000, 240_000)}))

    cookies = [_Record({"EntryId": 12000 + i,
                        "Url": "Cookie:%s@%s/" % (USER, host),
                        "ModifiedTime": ft(START + datetime.timedelta(hours=i * 5)),
                        "AccessedTime": ft(START + datetime.timedelta(hours=i * 5)),
                        "ExpiryTime": ft(START + datetime.timedelta(days=365)),
                        "Flags": 0, "AccessCount": 1})
               for i, host in enumerate(["mail.contoso.test", "cloud.example.com",
                                         "search.example.org", "portal.fabrikam.test",
                                         "shop.example.net"])]

    tables = {"Containers": [container(1, "History"), container(2, "Content"),
                             container(3, "Cookies")]}
    tables["Container_1"] = history
    tables["Container_2"] = content
    tables["Container_3"] = cookies
    for n, (name, rows) in enumerate(sorted(daily.items()), start=10):
        tables["Containers"].append(container(n, name))
        tables["Container_%d" % n] = rows

    parser = WebCacheParser()
    parser.db = _Db(tables)
    parser.table_names = list(tables)
    parser._load_containers()
    parser.parse_all_entries()
    # What a real open records about the file itself, made up to match.
    parser.db_state = 2
    facts = parser.get_database_info
    parser.get_database_info = lambda: {**facts(), "file_size": 26_214_400}
    return parser, visits


def build_recovery(visits):
    from webcache.engine.recovery_engine import RecoveryEngine
    from tests.test_mshist_local_clock import ft
    engine = RecoveryEngine()
    when = visits[40][0]
    engine.structured_records = [{
        "Url": "Visited: %s@%s" % (USER, url), "CleanUrl": url,
        "ContainerType": "History", "ContainerId": 1, "EntryId": 900 + i,
        "SPS_PageTitle": title, "ModifiedTime_raw": ft(when - datetime.timedelta(hours=i)),
        "AccessedTime_raw": 0, "CreationTime_raw": 0, "SPS_LastVisitLocal_raw": None,
        "SPS_VisitCount": 1, "AccessCount": 1, "Flags": 0,
        "Source": "WebCacheV01.dat", "Offset": 0x3B0000 + i * 0x400, "Page": 236 + i,
        "RecoverySource": "Structured record reconstruction", "Confidence": "high"}
        for i, (url, title) in enumerate([
            ("https://cloud.example.com/share/7f3c9a/project-files/delete", "Delete files - Example Cloud"),
            ("https://search.example.org/search?q=wipe+free+space", "wipe free space - Search"),
            ("file:///E:/transfer/apollo-designs.zip", ""),
        ])]
    engine.page_artifacts = [{
        "Url": "Visited: %s@https://paste.example.net/raw/q81kz" % USER,
        "CleanUrl": "https://paste.example.net/raw/q81kz", "ContainerType": "",
        "NearbyFiletime": when,
        "NearbyFiletime_raw": ft(when),
        "Source": "WebCacheV01.dat", "Offset": 0x41A2C0, "Page": 262,
        "RecoverySource": "Unallocated page", "Confidence": "medium"}]
    engine.log_artifacts = [{
        "Url": "Visited: %s@https://search.example.org/search?q=anti+forensics" % USER,
        "CleanUrl": "https://search.example.org/search?q=anti+forensics",
        "ContainerType": "", "NearbyFiletime": when, "NearbyFiletime_raw": ft(when),
        "Source": "V01.log", "Offset": 0x1F40, "Page": None,
        "RecoverySource": "Transaction log", "Confidence": "medium"}]
    engine.tombstones = [{"Table": "Container_1", "ContainerId": 1,
                          "ContainerType": "History", "Source": "WebCacheV01.dat",
                          "Offset": 0x3C2000, "Page": 240,
                          "KeyColumns": ("EntryId",), "KeyValues": (131,)}]
    return engine


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Segoe UI"))
    from webcache.provenance import EvidenceSet
    from webcache.shell import theme
    from webcache.shell.evidence_loader import history_rows_from_parser
    from webcache.shell.main_window import MainWindow
    from webcache.widgets.record_filter import Condition, JoinedCondition

    OUT.mkdir(exist_ok=True)
    theme.apply(app, "dark")

    def pump(n=40):
        for _ in range(n):
            app.processEvents()

    def shot(widget, name):
        pump()
        widget.grab().save(str(OUT / ("%s.png" % name)))
        print("wrote", name)

    parser, visits = build_exhibit()
    path = r"D:\Demo\jdoe-laptop\WebCacheV01.dat"
    parser.db_path = path
    digest = hashlib.sha256(b"made-up demo exhibit").hexdigest()
    # Keyed by file name, as the parser keys the hashes it computes.
    parser.source_hashes = {"WebCacheV01.dat": digest}
    win = MainWindow()
    win.showNormal()
    win.resize(1600, 900)
    pump()
    win._on_evidence_loaded(
        {"rows": history_rows_from_parser(parser), "parser": parser},
        EvidenceSet([path], {path: 26_214_400}, {path: digest}))
    pump(80)
    win._on_recovery_loaded(build_recovery(visits))
    pump(80)

    win.go_to("dashboard")
    shot(win, "01-dashboard")
    win.go_to("history")
    history = win._ensure_view_built("history")
    # One row per visit: the daily-copy twins folded, as an analyst reads it.
    history.chip_one_row_per_visit.click()
    shot(win, "02-history")
    history.chip_one_row_per_visit.click()

    model = history.table.model()
    keys = [c.key for c in model.columns]
    section = keys.index("CleanUrl")
    history.table._open_filter_popup(section)
    popup = history.table._filter_popup
    popup.operator_box.setCurrentText("contains")
    popup.operand_a.setText("search")
    popup.join_box.setCurrentText("Or")
    popup.operator_box_2.setCurrentText("contains")
    popup.operand_a_2.setText("cloud")
    popup.move(win.mapToGlobal(win.rect().center()) - popup.rect().center())
    shot(popup, "03-filter-popup")
    popup._ok()
    shot(win, "04-history-filtered")
    history.clear_all_filters()

    rows = list(model.filter.visible())
    titled = next(r for r in rows if (r.get("_record") or {}).get("SPS_PageTitle"))
    dialog = win._show_record_detail(titled)
    shot(dialog, "05-record-detail")
    dialog.close()

    for key, name in (("timeline", "06-timeline"), ("domains", "07-domains"),
                      ("recovery", "08-deleted-records")):
        win.go_to(key)
        shot(win, name)
    win.go_to("export")
    export = win._ensure_view_built("export")
    from webcache.views.export import CASE_FIELDS
    for (attr, _label, _key), text in zip(
            CASE_FIELDS[:3], ("A. Examiner", "2025-0147", "EXH-03 (jdoe-laptop)")):
        getattr(export, attr).setText(text)
    export.notes_field.setPlainText(
        "Read-only copy acquired from the made-up demo image; "
        "recovery run with defaults.")
    shot(win, "09-export")

    # The date calendar: every day's record count, shaded by it.
    win.go_to("timeline")
    timeline = win._ensure_view_built("timeline")
    cal = timeline.date_calendar
    busiest = max(cal.calendar.counted_days(), key=cal.calendar.count_for)
    timeline.date_box.setText(busiest.toString("yyyy-MM-dd"))
    cal.open_calendar()
    shot(cal.calendar, "11-calendar")
    cal._menu.close()

    win._toggle_theme()
    win.go_to("history")
    shot(win, "10-history-light")
    win._toggle_theme()
    win.close()


if __name__ == "__main__":
    main()
