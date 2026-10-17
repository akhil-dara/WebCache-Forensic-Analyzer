"""The JSON island."""
import json

from webcache import provenance
from webcache.engine import forensic_engine
from webcache.shell import export_formats
from webcache.shell.record_kinds import K_COOKIE, K_PERIOD

from tests import _package_fixtures as fx


def _island(snap=None):
    from webcache.shell.html_package import build_island
    return build_island(snap or fx.snapshot(), fx.GENERATED)


def test_a_record_shown_in_two_segments_is_stored_once():
    from webcache.shell.html_package import PackageView
    shared = fx.history_row(1)
    twin = dict(shared)                      # another view's row, same record
    views = [fx.history_view([fx.segment(rows=[shared])]),
             PackageView("timeline", "Timeline", "ANALYSIS", "",
                         [fx.segment("day_utc", "By day", rows=[twin])])]
    island = _island(fx.snapshot(views=views))
    a = island["views"][0]["segments"][0]["rec"][0]
    b = island["views"][1]["segments"][0]["rec"][0]
    assert a == b and len(island["records"]) == 1


def test_canonical_cells_are_stored_per_record_in_schema_order():
    island = _island()
    assert [f[0] for f in island["fields"]] == forensic_engine.ENTRY_FIELD_KEYS
    record = island["records"][0]
    assert len(record["c"]) == 80
    index = forensic_engine.ENTRY_FIELD_KEYS.index("EntryId")
    assert record["c"][index] == 1


def test_a_cookie_row_stores_its_own_fields_not_the_entry_schema():
    cookie = {"Name": "sid", "Domain": "example.test", "Value": "v"}
    row = {"Name": "sid", "Domain": "example.test",
           "Origin": provenance.LIVE_ORIGIN, "_kind": K_COOKIE,
           "_record": cookie}
    from webcache.shell.html_package import PackageColumn
    cols = [PackageColumn("Name", "Name"), PackageColumn("Domain", "Domain")]
    island = _island(fx.snapshot(views=[fx.history_view(
        [fx.segment("cookies", "Cookies", rows=[row], columns=cols)])]))
    record = island["records"][0]
    assert "c" not in record and record["own"]["Value"] == "v"
    canon = island["views"][0]["segments"][0]["export"]["canon"]
    assert [None, "Value", "Value"] in canon


def test_the_export_layout_is_the_apps_own():
    island = _island()
    seg = island["views"][0]["segments"][0]
    rows = fx.segment().rows
    headers, flags, appended, canon = export_formats.view_layout(
        rows, fx.history_columns())
    assert seg["export"]["headers"] == headers
    assert seg["export"]["ts"] == flags
    assert seg["n"] == len(fx.history_columns())
    assert all(len(r) == seg["n"] + len(appended) for r in seg["rows"])
    first = seg["export"]["canon"][0]
    assert first[0] == forensic_engine.ENTRY_FIELD_KEYS.index(canon[0][0])
    assert seg["export"]["view_column_count"] == seg["n"] + len(appended)


def test_a_carved_row_carries_its_provenance_strip_and_carved_cells():
    island = _island(fx.snapshot(views=[fx.history_view(
        [fx.segment(rows=[fx.history_row(4, carved=True)])])]))
    record = island["records"][0]
    head = island["heads"][island["views"][0]["segments"][0]["hd"][0]]
    strip = dict(map(tuple, head["p"]))
    assert strip["Carved from"] == "WebCacheV01.dat"
    assert strip["Offset"] == "0x%08X" % (0x3B0523 + 4)
    seg = island["views"][0]["segments"][0]
    assert seg["origins"][seg["org"][0]] == provenance.CARVED_ORIGIN
    method = forensic_engine.ENTRY_FIELD_KEYS.index("Method")
    assert record["c"][method] == "unallocated"


def test_aggregate_members_are_references_with_member_cells():
    from webcache.shell.html_package import PackageColumn
    members = [fx.entry(1), fx.entry(2, RecoverySource="log")]
    row = {"Period": "2026-02-17", "Records": 2, "_kind": K_PERIOD,
           "_members": members}
    member_cols = [PackageColumn("CleanUrl", "Address", kind="url"),
                   PackageColumn("Origin", "Source record", kind="flag")]
    snap = fx.snapshot(views=[fx.history_view([fx.segment(
        "day_utc", "By day", rows=[row],
        columns=[PackageColumn("Period", "Period"),
                 PackageColumn("Records", "Records", kind="num")])])],
        member_columns=member_cols)
    island = _island(snap)
    seg = island["views"][0]["segments"][0]
    assert seg["rec"] == [-1]
    refs = seg["mem"][0]
    assert len(refs) == 2
    assert [island["records"][i]["m"][1] for i in refs] == [
        provenance.LIVE_ORIGIN, provenance.CARVED_ORIGIN]
    assert island["member_cols"][0]["l"] == "Address"


def test_default_sort_becomes_a_column_index():
    island = _island(fx.snapshot(views=[fx.history_view(
        [fx.segment(default_sort=("AccessedUtc", True))])]))
    assert island["views"][0]["segments"][0]["sort"] == [1, True]


def test_a_factory_segment_is_resolved_with_its_note_and_subtitle():
    from webcache.shell.html_package import PackageSegment
    rows = [fx.history_row(i) for i in range(1, 4)]
    seg = PackageSegment("day_utc", "By day (UTC)", fx.history_columns(),
                         factory=lambda: (None, rows, "3 dated"),
                         subtitle=lambda n: "%d periods" % n, clock="utc")
    island = _island(fx.snapshot(views=[fx.history_view([seg])]))
    out = island["views"][0]["segments"][0]
    assert len(out["rows"]) == 3 and out["note"] == "3 dated"
    assert out["subtitle"] == "3 periods" and out["clock"] == "utc"


def test_the_island_json_holds_no_markup_and_round_trips():
    from webcache.shell.html_package import island_json
    hostile = fx.history_row(1, CleanUrl="</script><script>x()</script>&amp;\u2028")
    island = _island(fx.snapshot(views=[fx.history_view(
        [fx.segment(rows=[hostile])])]))
    text = island_json(island)
    for ch in ("<", ">", "&", "\u2028", "\u2029"):
        assert ch not in text
    back = json.loads(text)
    assert back["views"][0]["segments"][0]["rows"][0][0] == (
        "</script><script>x()</script>&amp;\u2028")
    assert back["views"][0]["segments"][0]["rows"][0][1].startswith("\x01")


def test_a_lone_surrogate_is_replaced_but_a_tag_survives():
    from webcache.shell.html_package import island_json
    island = {"a": "\ud800x", "b": "\x012026-01-01 00:00:00",
              "c": "a\x7fb"}
    back = json.loads(island_json(island))
    # The engine's own substitution (forensic_engine._safe_text), so the
    # island says what every other export says for the same bytes.
    assert back["a"] == forensic_engine._safe_text("\ud800x")
    assert "\ud800" not in back["a"]
    assert back["b"] == "\x012026-01-01 00:00:00"
    # DEL is the one _safe_text character json.dumps leaves raw; its
    # visible escape must survive as text, not become a broken JSON escape.
    assert back["c"] == forensic_engine._safe_text("a\x7fb")


def test_factory_segments_that_free_their_rows_never_merge_records():
    # A factory builds its rows inside resolve() and they are freed once
    # the segment is built; CPython then hands the next segment's fresh
    # records the same ids. Distinct records must stay distinct.
    from webcache.shell.html_package import PackageSegment

    def factory(k):
        return lambda: (None, [fx.history_row(10 * k + j) for j in range(3)],
                        "")

    segs = [PackageSegment("day_%d" % k, "Day %d" % k, fx.history_columns(),
                           factory=factory(k)) for k in range(4)]
    island = _island(fx.snapshot(views=[fx.history_view(segs)]))
    assert len(island["records"]) == 12
    entry_id = forensic_engine.ENTRY_FIELD_KEYS.index("EntryId")
    seen = []
    for k, seg in enumerate(island["views"][0]["segments"]):
        assert [island["records"][i]["c"][entry_id] for i in seg["rec"]] == [
            10 * k + j for j in range(3)]
        seen.extend(seg["rec"])
    assert sorted(seen) == list(range(12))


def test_a_record_reached_through_two_rows_states_each_rows_own_facts():
    # The record dialog's header (identity, origin, twin, provenance strip)
    # is what the app's dialog says for the row clicked. Two rows over one
    # record that say different things must not inherit the first row's.
    from webcache.shell import detail_fields
    from webcache.shell.html_package import PackageView
    first = fx.history_row(1)
    second = dict(first, ContainerName="Content")
    assert (detail_fields.origin_line(first)
            != detail_fields.origin_line(second))
    views = [fx.history_view([fx.segment(rows=[first])]),
             PackageView("timeline", "Timeline", "ANALYSIS", "",
                         [fx.segment("day_utc", "By day", rows=[second])])]
    island = _island(fx.snapshot(views=views))
    for view, row in zip(island["views"], (first, second)):
        record = island["heads"][view["segments"][0]["hd"][0]]
        assert record["o"] == detail_fields.origin_line(row)
        assert record["i"] == detail_fields.identity_of(row)
        assert record["t"] == detail_fields.twin_line(row)
        assert record["p"] == [list(p) for p
                               in detail_fields.provenance_facts(row)]


def test_two_row_builders_over_one_record_share_its_cells_once():
    # The canonical cells belong to the record and are stored ONCE; what
    # the dialog says for a row (identity, origin, twin, provenance strip)
    # belongs to the row. History's row and Timeline's member row over
    # the same carved record say different things and share one record.
    from webcache.shell import detail_fields, timeline_loader
    from webcache.shell.html_package import (PackageColumn, PackageView,
                                             encode_cell)
    first = fx.history_row(1, carved=True)
    second = timeline_loader.member_record_rows([first["_record"]])[0]
    assert second["_record"] is first["_record"]

    def head(row):
        return {"i": detail_fields.identity_of(row),
                "o": detail_fields.origin_line(row),
                "t": detail_fields.twin_line(row),
                "p": [list(p) for p in detail_fields.provenance_facts(row)],
                "k": "carved"}

    assert head(first) != head(second)
    tl_columns = [PackageColumn("CleanUrl", "Address", kind="url"),
                  PackageColumn("KeyTimeUtc", "Key time (UTC)", kind="time"),
                  PackageColumn("ContainerName", "Container")]
    views = [fx.history_view([fx.segment(rows=[first])]),
             PackageView("timeline", "Timeline", "ANALYSIS", "",
                         [fx.segment("day_utc", "By day", rows=[second],
                                     columns=tl_columns)])]
    island = json.loads(json.dumps(_island(fx.snapshot(views=views))))
    assert len(island["records"]) == 1
    for view, row, columns in zip(island["views"], (first, second),
                                  (fx.history_columns(), tl_columns)):
        seg = view["segments"][0]
        assert seg["rec"] == [0]
        assert island["heads"][seg["hd"][0]] == head(row)
        record = island["records"][0]
        rebuilt = seg["rows"][0] + [
            record["c"][i] if i is not None else record["own"].get(name)
            for i, name, _h in seg["export"]["canon"]]
        _h, flags, appended, canon = export_formats.view_layout([row],
                                                                columns)
        assert rebuilt == [encode_cell(v, f) for v, f in zip(
            export_formats._view_cells(row, columns, appended, canon),
            flags)]


# --- absence words are asked once per row shape ----------------------

def _absence_corpus():
    """Rows of every shape the dialog words differently: live, carved
    (structured and string), a deleted-record stub, an MSHist record on a
    local clock, stated absence tokens, None, "", blank text, lists, dicts
    and bytes -- and the awkward generated set from tests/fixtures."""
    from webcache.shell.record_kinds import (K_CARVED_STRING, K_COOKIE,
                                             K_TOMBSTONE)
    from tests.fixtures import make_rows
    rows = [fx.history_row(i, carved=bool(i % 2)) for i in range(1, 9)]
    rows += [fx.history_row(20, Title=None), fx.history_row(21, Title=""),
             fx.history_row(22, Title="   "),
             fx.history_row(23, IsInPrivate=provenance.ABSENCE_NOT_DETERMINABLE),
             fx.history_row(24, carved=True, Encoding=""),
             fx.history_row(25, carved=True, _kind=K_CARVED_STRING,
                            IsInPrivate=provenance.ABSENCE_NOT_DETERMINABLE),
             fx.history_row(26, carved=True, _kind=K_TOMBSTONE, Key="UrlHash 7"),
             fx.history_row(27, Tags=["a", "", None], Extra={"x": "", "y": 1}),
             fx.history_row(28, Blob=b"", Other=b"\x00\x01", Count=0),
             fx.history_row(29, carved=True, UrlHealth="damaged"),
             fx.history_row(30, _kind=K_COOKIE)]
    mshist = fx.history_row(31)
    mshist["_record"].update(MSHistFrom="2026-02-17", ModifiedTime_raw=0,
                             SecureDirectory="")
    other = fx.history_row(32)
    other["_record"].update(MSHistFrom="2026-02-17",
                            ModifiedTime_raw=133500000000000000,
                            ModifiedTime=None, AccessedTime_raw=0)
    rows += [mshist, other]
    for i, row in enumerate(make_rows(60)):
        row = dict(row, _record=dict(row), _kind="history")
        if i % 3 == 0:
            row["_record"]["CreationTime_raw"] = 0 if i % 2 else None
        rows.append(row)
    return rows


def _other_text(value):
    return value + "-other" if isinstance(value, str) else value + 1


def test_a_rows_absence_words_never_depend_on_the_text_of_a_present_value():
    # The memo's premise, held against the dialog itself: change the text
    # of any present value (or any nonzero number) and neither the words
    # the dialog says nor the shape key changes.
    from webcache.shell.html_package import absence_signature, absence_words
    checked = 0
    for row in _absence_corpus():
        words, key = absence_words(row), absence_signature(row)
        for target in (row, row.get("_record") or {}):
            for name, value in list(target.items()):
                if name.startswith("_") or type(value) not in (str, int):
                    continue
                if (not value or provenance.is_absence(value)
                        or (isinstance(value, str) and not value.strip())):
                    continue
                changed = dict(row)
                if target is not row:
                    changed["_record"] = dict(target)
                    changed["_record"][name] = _other_text(value)
                else:
                    changed[name] = _other_text(value)
                if name != "UrlHealth":     # kept whole in the key
                    assert absence_signature(changed) == key, name
                assert absence_words(changed) == words, name
                checked += 1
    assert checked > 500, checked


def test_rows_of_one_shape_get_the_same_absence_words_and_shapes_differ():
    from webcache.shell.html_package import absence_signature, absence_words
    first = {}
    for row in _absence_corpus():
        key = absence_signature(row)
        assert key is not None
        first.setdefault(key, absence_words(row))
        assert absence_words(row) == first[key]
    # Positive control: the corpus does reach different words.
    assert len({json.dumps(w, sort_keys=True) for w in first.values()}) >= 5


def test_the_memoised_island_equals_one_built_without_the_memo(monkeypatch):
    from webcache.shell import html_package
    rows = _absence_corpus()
    snap = fx.snapshot(views=[fx.history_view([fx.segment(rows=rows)])])
    memoised = html_package.build_island(snap, fx.GENERATED)
    monkeypatch.setattr(html_package, "absence_signature", lambda row: None)
    direct = html_package.build_island(snap, fx.GENERATED)
    assert memoised == direct
    assert sum(1 for r in direct["records"] if r.get("a")) >= 10


def test_canonical_cells_short_paths_match_the_general_encoding():
    # Every value type through canonical_cells equals _cell + encode_cell
    # on canonical_record_row's own value (the long way round).
    import datetime
    from webcache.shell.html_package import canonical_cells, encode_cell
    record = fx.entry(1, Url="a\x00b\ud800", CleanUrl="https://example.test/é",
                      AccessCount=2 ** 60, FileSize=-3, Flags=True,
                      SyncCount=1.5, CacheFolder=b"\x01\xff",
                      KeyTimestampUTC="2026-02-17 16:50:09.123",
                      ExpiryTime=datetime.datetime(2026, 2, 17, 1, 2, 3),
                      FileExtension="", Type="  ", Server="tab\there")
    for carved in (False, True):
        full = forensic_engine.canonical_record_row(
            record, carved=True if carved else None)
        stamps = forensic_engine.TIMESTAMP_EXPORT_KEYS
        expected = []
        for key in forensic_engine.ENTRY_FIELD_KEYS:
            raw = full.get(key)
            if raw is None:
                expected.append(None)
                continue
            value = forensic_engine._safe_text(raw) if isinstance(raw, str) else raw
            if isinstance(value, str):
                expected.append(None if not value else
                                forensic_engine.excel_datetime(value)
                                if key in stamps else value)
            else:
                expected.append(encode_cell(forensic_engine._cell(value),
                                            key in stamps))
        assert canonical_cells(record, carved) == expected


# --- the island is written compactly -----------

def _stored_island_text(path):
    text = open(path, encoding="utf-8").read()
    start = text.index('id="wc-data">') + len('id="wc-data">')
    return text[start:text.index("</script>", start)]


def test_a_value_repeated_across_rows_and_records_is_written_once(tmp_path):
    # A sample exhibit wrote 21.4 MB against a 12 MB budget: the same words (a
    # container type, an origin sentence, a cached file's folder, the
    # absence words) written out once per cell. Once is enough.
    repeated = "https://example.test/" + "repeated-segment/" * 6
    rows = [fx.history_row(i, CleanUrl=repeated) for i in range(1, 41)]
    for row in rows:
        row["_record"]["CacheFolder"] = repeated + "folder"
    stored = _stored_island_text(fx.write(tmp_path, fx.snapshot(
        views=[fx.history_view([fx.segment(rows=rows)])])))
    assert stored.count(repeated.replace("/", "\\/")) + stored.count(
        repeated) <= 2, stored.count(repeated)


def test_packing_round_trips_every_island_shape_exactly():
    from webcache.shell.html_package import (build_island, island_json,
                                             pack_island, unpack_island)
    from tests.test_html_package_boot import _read_back_snapshot
    from tests.test_html_package_security import _hostile_snapshot
    rows = _absence_corpus()
    for snap in (fx.snapshot(), _read_back_snapshot(), _hostile_snapshot(),
                 fx.snapshot(views=[fx.history_view([fx.segment(rows=rows),
                                                     fx.segment("none", "None",
                                                                rows=[])])])):
        island = build_island(snap, fx.GENERATED)
        stored = json.loads(island_json(pack_island(island)))
        assert stored["pack"] == 1 and stored["schema"] == island["schema"]
        assert unpack_island(stored) == json.loads(island_json(island))


def test_packing_keeps_text_that_looks_like_its_own_markers():
    from webcache.shell.html_package import pack_island, unpack_island
    tricky = ["~", "~~", "~0", "~*0", "~-5", "~~-5", "~zz", "x~", "", None, 7]
    island = {"schema": "s", "fields": [], "records": [], "heads": [],
              "member_cols": [], "views": [], "meta": {"~k": tricky * 3},
              "ev": [tricky, tricky]}
    assert unpack_island(json.loads(json.dumps(pack_island(island)))) == island


def test_view_cells_short_paths_match_encode_cell():
    import datetime
    from webcache.shell.html_package import PackageColumn, encode_cell, view_cells
    values = ["", "  ", "plain", "tab\there", "a\x00b", "\ud800x", "é",
              "2026-02-17 16:50:09.123", "2026-02-17T16:50:09Z", 0, -7,
              2 ** 60, True, False, 1.5, float("nan"), b"\x01\xff", None,
              datetime.datetime(2026, 2, 17, 1, 2, 3,
                                tzinfo=datetime.timezone.utc),
              datetime.date(2026, 2, 17)]
    columns = [PackageColumn("v%d" % i, kind=kind)
               for i in range(len(values)) for kind in ("text", "time")]
    row = {"v%d" % i: v for i, v in enumerate(values)}
    flags = [c.kind == "time" for c in columns]
    from webcache.shell import export_formats
    raw = export_formats._view_cells(row, columns, [], [], None, None)
    assert view_cells(row, columns, [], flags) == [
        encode_cell(v, f) for v, f in zip(raw, flags)]


def test_a_control_character_outside_a_cell_reads_as_its_visible_escape():
    """json.dumps writes every control character as a JSON
    escape, so island_json's substitution never saw one, and a NUL in a
    label, a summary value or an evidence path reached the page raw while
    the same NUL in a cell read \x00. Every non-cell string goes through
    _safe_text, as every other writer's does; cells keep their tags."""
    import json as _json
    from tests import _package_fixtures as fx2
    from webcache.shell.html_package import build_island, island_json
    seg = fx2.segment(label="Hist\x00ory")
    snap = fx2.snapshot(views=[fx2.history_view([seg])],
                        summary=[("File", "Web\x00Cache.dat")],
                        scope=[("Sco\x00pe", "What the\x00 cache stored.")],
                        integrity={"hashes": [["Web\x00Cache.dat", "Database",
                                               "ab" * 32]],
                                   "source": [], "log": []})
    snap.meta["evidence"][0]["path"] = "C:/case/Web\x00CacheV01.dat"
    island = _json.loads(island_json(build_island(snap, "2026-10-05T00:00:00Z")))
    assert island["views"][0]["segments"][0]["label"] == "Hist\\x00ory"
    assert island["summary"][0][1] == "Web\\x00Cache.dat"
    assert island["meta"]["evidence"][0]["path"] == "C:/case/Web\\x00CacheV01.dat"
    assert island["scope"][0] == ["Sco\\x00pe", "What the\\x00 cache stored."]
    assert island["integrity"]["hashes"][0][0] == "Web\\x00Cache.dat"
    # Cells keep their tags: the first History row is still decodable.
    assert island["views"][0]["segments"][0]["rows"]


def test_a_place_s_members_show_the_record_each_fix_was_read_from():
    """A place's members are position FIXES -- shaped rows carrying the
    engine record behind them as _record. Handed to the member table as if
    they were records, every cell came out blank (seen on a real machine:
    68 members, When/Record type/Visits all empty)."""
    from webcache.shell.html_package import PackageColumn
    from webcache.shell.record_kinds import K_HISTORY, K_PLACE
    entries = [fx.entry(1), fx.entry(2)]
    fixes = [{"Coords": "1.0, 2.0", "_kind": K_HISTORY, "_record": e,
              "Origin": provenance.LIVE_ORIGIN} for e in entries]
    row = {"Coords": "1.000, 2.000", "Fixes": 2, "_kind": K_PLACE,
           "_record": None, "_members": fixes}
    member_cols = [PackageColumn("CleanUrl", "Address", kind="url")]
    snap = fx.snapshot(views=[fx.history_view([fx.segment(
        "places", "Places", rows=[row],
        columns=[PackageColumn("Coords", "Coords"),
                 PackageColumn("Fixes", "Fixes", kind="num")])])],
        member_columns=member_cols)
    island = _island(snap)
    seg = island["views"][0]["segments"][0]
    cells = [island["records"][i]["m"][0] for i in seg["mem"][0]]
    assert cells == [e["CleanUrl"] for e in entries], cells
    assert seg["mn"] == ["position fix", "position fixes"]
