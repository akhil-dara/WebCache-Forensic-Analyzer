"""The offline report as a file. Pure Python: stdlib html.parser, no browser."""
import base64
import hashlib
import html.parser
import pathlib
import re
import shutil
import subprocess

import pytest

from tests import _package_fixtures as fx

ASSETS = (pathlib.Path(__file__).resolve().parent.parent / "webcache" /
          "shell" / "html_package_assets")

#: Never in the page's code.
BANNED = [
    r"\binnerHTML\b", r"\bouterHTML\b", r"insertAdjacentHTML",
    r"document\.write", r"\beval\s*\(", r"\bnew\s+Function\b",
    r"setTimeout\s*\(\s*['\"]", r"setInterval\s*\(\s*['\"]",
    r"setAttribute\s*\(\s*['\"](?:style|href|src|on\w+)['\"]",
    r"javascript:", r"\bfetch\s*\(", r"XMLHttpRequest", r"\bWebSocket\b",
    r"sendBeacon", r"window\.open\s*\(", r"\.src\s*=(?!=)",
    r"\blocation\s*=(?!=)", r"\blocation\.href\s*=(?!=)", r"importScripts",
    # Navigation: CSP cannot stop it (measured), so the guard must.
    r"\blocation\s*\.\s*(?:assign|replace|reload)\s*\(",
    r"\bdocument\s*\.\s*location\b", r"\bnavigation\s*\.\s*navigate\b",
    r"httpEquiv", r"http-equiv", r"(?<![\w.$])open\s*\(",
    r"\.submit\s*\(", r"\.(?:action|formAction|srcdoc)\s*=(?!=)",
    r"createElement(?:NS)?\s*\(\s*['\"](?:meta|form|iframe|frame|object|embed|"
    r"base|link|script|style|img|video|audio|source|track|input)['\"]",
    r"\.href\s*=(?!=)(?!\s*URL\.createObjectURL\()",
    # The page's own element helper: el("a"), el("iframe") ...
    # "input" stays allowed -- the page's own form controls.
    r"\bel\s*\(\s*['\"](?:a|meta|form|iframe|frame|object|embed|base|link|"
    r"script|style|img|video|audio|source|track)['\"]",
]


class _Blocks(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.blocks, self.metas, self._open = [], [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.metas.append(attrs)
        if tag in ("script", "style"):
            self._open = [tag, attrs, []]

    def handle_endtag(self, tag):
        if self._open and tag == self._open[0]:
            self.blocks.append((tag, self._open[1], "".join(self._open[2])))
            self._open = None

    def handle_data(self, data):
        if self._open:
            self._open[2].append(data)


def _parse(path):
    text = open(path, encoding="utf-8", newline="").read()
    parser = _Blocks()
    parser.feed(text)
    return text, parser


def _sha(text):
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "'sha256-%s'" % base64.b64encode(digest).decode()


def _assets():
    return sorted(ASSETS.glob("*.js"))


def test_one_style_one_data_island_one_script(tmp_path):
    _text, page = _parse(fx.write(tmp_path))
    kinds = [(tag, a.get("type"), a.get("id")) for tag, a, _ in page.blocks]
    assert kinds == [("style", None, None),
                     ("script", "application/json", "wc-data"),
                     ("script", None, None)]


def test_the_csp_is_strict_and_hashes_exactly_what_was_written(tmp_path):
    from webcache.shell.html_package import content_security_policy
    _text, page = _parse(fx.write(tmp_path))
    style, script = page.blocks[0][2], page.blocks[2][2]
    csp = [m["content"] for m in page.metas
           if m.get("http-equiv") == "Content-Security-Policy"]
    assert csp == [content_security_policy(script, style)]
    assert csp[0].startswith("default-src 'none'; script-src %s; style-src %s;"
                             % (_sha(script), _sha(style)))
    for word in ("unsafe-inline", "unsafe-eval", "http", "data:", "blob:"):
        assert word not in csp[0], word
    for directive in ("connect-src 'none'", "img-src 'none'",
                      "base-uri 'none'", "form-action 'none'",
                      "object-src 'none'", "frame-src 'none'",
                      "worker-src 'none'"):
        assert directive in csp[0], directive
    assert {"name": "referrer", "content": "no-referrer"} in page.metas


def test_the_file_holds_no_carriage_return(tmp_path):
    assert b"\r" not in open(fx.write(tmp_path), "rb").read()


def test_nothing_outside_the_island_can_fetch_or_link(tmp_path):
    text, page = _parse(fx.write(tmp_path))
    outside = text.replace(page.blocks[1][2], "")
    for needle in ("src=", "href="):
        assert needle not in outside.lower(), needle
    style = page.blocks[0][2].lower()
    for needle in ("url(", "@import"):
        assert needle not in style, needle
    # Namespace names inside the workbook writer are identifiers, never
    # fetched (and the CSP refuses every fetch); nothing else may say http.
    for found in re.findall(r"https?://[^\s\"'<>]*", outside):
        assert found.startswith("http://schemas.openxmlformats.org/"), found


def test_the_island_holds_no_angle_bracket(tmp_path):
    hostile = fx.history_row(1, CleanUrl="</script><img src=x onerror=y()>")
    path = fx.write(tmp_path, fx.snapshot(
        views=[fx.history_view([fx.segment(rows=[hostile])])]))
    _text, page = _parse(path)
    assert len(page.blocks) == 3
    assert "<" not in page.blocks[1][2]


def test_the_template_carries_no_evidence(tmp_path):
    first = open(fx.write(tmp_path, name="a.html"), encoding="utf-8").read()
    other = fx.snapshot(views=[fx.history_view([fx.segment(
        rows=[fx.history_row(9, CleanUrl="https://example.test/other")])])])
    other.meta["evidence"] = [{"path": "D:/other/WebCacheV01.dat",
                               "sha256": "cd" * 32, "bytes": 9}]
    second = open(fx.write(tmp_path, other, name="b.html"),
                  encoding="utf-8").read()

    def outside(text):
        start = text.index('id="wc-data">')
        return text[:start] + text[text.index("</script>", start):]
    assert outside(first) == outside(second)


def test_the_sidecar_states_the_files_own_sha256(tmp_path):
    path = fx.write(tmp_path)
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    with open(path + ".sha256", encoding="utf-8", newline="") as fh:
        assert fh.read() == "%s  report.html\n" % digest


def test_write_package_returns_the_page_and_its_sidecar(tmp_path):
    from webcache.shell.html_package import write_package
    path = str(tmp_path / "r.html")
    assert write_package(fx.snapshot(), path,
                         generated_utc=fx.GENERATED) == [path, path + ".sha256"]
    assert not (tmp_path / "r.html.partial").exists()


def test_the_render_refuses_a_block_that_would_break_out():
    from webcache.shell.html_package import render_page
    for kwargs in ({"data_json": "{}", "script": "x</script>", "style": ""},
                   {"data_json": "{}", "script": "", "style": "a</STYLE>"},
                   {"data_json": "<", "script": "", "style": ""},
                   {"data_json": "{}", "script": "a\r\nb", "style": ""}):
        with pytest.raises(ValueError):
            render_page(**kwargs)


def test_every_asset_is_in_the_order_and_main_is_last():
    from webcache.shell.html_package import ASSET_ORDER
    assert sorted(ASSET_ORDER) == sorted(p.name for p in _assets())
    assert ASSET_ORDER[-1] == "main.js"


@pytest.mark.parametrize("pattern", BANNED)
def test_no_asset_builds_markup_or_reaches_the_network(pattern):
    for path in _assets():
        assert not re.search(pattern, path.read_text(encoding="utf-8")), (
            "%s matches %s" % (path.name, pattern))


def test_the_one_href_assignment_is_the_download_anchor():
    hits = [p.name for p in _assets()
            for _m in re.finditer(r"\.href\s*=(?!=)",
                                  p.read_text(encoding="utf-8"))]
    assert hits in ([], ["util.js"]), hits


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="Node is not installed here")
def test_the_assembled_script_parses(tmp_path):
    from webcache.shell.html_package import page_script
    target = tmp_path / "page.js"
    target.write_text(page_script(), encoding="utf-8", newline="")
    done = subprocess.run(["node", "--check", str(target)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


CRLF, LF = bytes([13, 10]), bytes([10])


def test_a_crlf_checkout_of_the_assets_still_hashes_the_embedded_lf_text(
        tmp_path, monkeypatch):
    """core.autocrlf turns LF into CRLF in a Windows checkout; the browser
    hashes inline text after CRLF -> LF, so the writer must embed LF."""
    from webcache.shell import html_package as hp
    assert callable(hp.render_page)
    crlf = tmp_path / "assets"
    crlf.mkdir()
    for p in ASSETS.iterdir():
        if p.is_file():
            data = p.read_bytes().replace(CRLF, LF).replace(LF, CRLF)
            (crlf / p.name).write_bytes(data)
    assert CRLF in (crlf / "main.js").read_bytes()
    monkeypatch.setattr(hp, "_ASSET_DIR", crlf)
    page = hp.render_page("{}")
    assert chr(13) not in page
    parser = _Blocks()
    parser.feed(page)
    style, script = parser.blocks[0][2], parser.blocks[2][2]
    csp = [m["content"] for m in parser.metas
           if m.get("http-equiv") == "Content-Security-Policy"][0]
    assert _sha(script) in csp and _sha(style) in csp
    assert script == hp.page_script() and style == hp.page_style()


# --- navigation vectors, a browser hash check, comment breakout --

#: Where the one download anchor may live.
DOWNLOAD_ANCHOR_FILES = ("util.js",)

#: Code that makes an <a> (or navigates) is allowed only in the files above.
ANCHOR_ONLY = [r"createElement\s*\(\s*['\"]a['\"]\s*\)", r"\.click\s*\("]

NAVIGATION_VECTORS = [
    "location.assign('x')", "location.replace('x')", "location.href = 'x'",
    "window.location.assign('x')", "document.location = 'x'",
    "document.location.href = 'x'", "navigation.navigate('x')",
    "m.httpEquiv = 'refresh'", "window.open('x')", "open('x')",
    "f.submit()", "f.action = 'x'", "x.formAction = 'x'",
    "document.createElement('meta')", "document.createElement('form')",
    "document.createElement('iframe')", "document.createElement('base')",
    "document.createElement('link')", "i.srcdoc = 'x'",
    "a.href = 'https://example.test/'",
    # every asset builds elements through el(tag), so the
    # same tags made that way must be caught too.
    'el("a", null, "x")', "el('iframe')", 'el("form")', 'el("meta")',
    'el("img")', 'el("script")',
]


def _guard_hits(text, name="main.js"):
    hits = [p for p in BANNED if re.search(p, text)]
    if name not in DOWNLOAD_ANCHOR_FILES:
        hits += [p for p in ANCHOR_ONLY if re.search(p, text)]
    return hits


@pytest.mark.parametrize("code", NAVIGATION_VECTORS)
def test_the_guard_catches_every_navigation_vector(code):
    """Positive control: CSP cannot stop navigation, so the static guard
    must (measured: location.assign etc. sent live requests under this CSP)."""
    assert _guard_hits("var x; " + code + ";\n"), code


def test_the_guard_lets_the_download_anchor_through_only_in_util_js():
    anchor = ("var a = document.createElement('a'); "
              "a.href = URL.createObjectURL(b); a.click();")
    assert not _guard_hits(anchor, "util.js")
    assert _guard_hits("a.href = 'https://example.test/';", "util.js")
    assert _guard_hits("a.href = data; a.click();", "util.js")
    assert _guard_hits(anchor, "main.js")


def test_the_render_refuses_a_comment_open_with_a_script_open():
    from webcache.shell.html_package import render_page
    for script in ("var s = '<!-- <script>';", "<!--\n<SCRIPT"):
        with pytest.raises(ValueError):
            render_page(data_json="{}", script=script, style="")
    render_page(data_json="{}", script="var a = '<!--';", style="")


def _browser():
    for path in (
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if pathlib.Path(path).exists():
            return path
    return shutil.which("chrome") or shutil.which("msedge") or shutil.which(
        "chromium")


def test_a_real_browser_runs_the_hashed_script_with_no_csp_violation(
        tmp_path):
    exe = _browser()
    if exe is None:
        pytest.skip("no Chrome or Edge found on this machine")
    from webcache.shell.html_package import (
        build_island, island_json, page_script, render_page)
    script = page_script() + (
        "\ndocument.getElementById('app').textContent = "
        "'ran:' + typeof window.WC;\n")
    page = tmp_path / "probe.html"
    data = island_json(build_island(fx.snapshot(), fx.GENERATED))
    page.write_bytes(render_page(data, script=script).encode("utf-8"))
    done = subprocess.run(
        [exe, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--user-data-dir=%s" % (tmp_path / "profile"),
         "--enable-logging=stderr", "--v=0", "--dump-dom",
         page.as_uri()], capture_output=True, text=True, timeout=60)
    assert "ran:object" in done.stdout, done.stdout[-400:]
    assert "Content Security Policy" not in done.stderr
    assert "Refused to" not in done.stderr


def test_every_inline_asset_passes_the_whole_guard():
    for path in _assets():
        assert not _guard_hits(path.read_text(encoding="utf-8"), path.name), (
            path.name)


def test_the_noscript_text_describes_the_packed_island_honestly():
    """The island is packed (a string table, column-major
    storage, shared containers, null runs), so "any text editor can read
    them" overstated it. The text says the data is packed and where the
    rules for reading it are."""
    html_text = (ASSETS / "page.html").read_text("utf-8")
    noscript = html_text.split("<noscript>")[1].split("</noscript>")[0]
    assert "any text editor can read them" not in noscript
    assert "packed" in noscript and "unpackIsland" in noscript


def test_a_toast_never_covers_an_open_dialog_and_a_note_toast_goes_once_used(
        browser, tmp_path):
    """The export toast sat over the dialog's own buttons
    and, carrying "Save provenance note", never went away. Over a dialog it
    sits at the top; its extra button dismisses it once used."""
    from tests import _package_fixtures as fx
    browser.open(fx.write(tmp_path))
    browser.evaluate("WC.openRecord('history', 'history', 0)")
    browser.clear_downloads()
    browser.evaluate("WC.exportCsv('history', 'history')", await_promise=True)
    top = browser.evaluate(
        "document.getElementById('wc-toast').getBoundingClientRect().top")
    assert top < 120, top
    browser.evaluate("document.querySelector('#wc-toast button').click()")
    assert browser.evaluate("document.getElementById('wc-toast')") is None


def test_a_copy_button_never_breaks_inside_its_label():
    """It sits in cells that wrap long values anywhere; it read "Co / py"
    down a narrow window's case summary."""
    import re
    from pathlib import Path
    css = (Path(__file__).resolve().parent.parent / "webcache" / "shell"
           / "html_package_assets" / "page.css").read_text(encoding="utf-8")
    rule = re.search(r"^\.copy\s*\{([^}]*)\}", css, re.M).group(1)
    assert "white-space: nowrap" in rule
    assert "overflow-wrap: normal" in rule


def test_the_counts_table_never_splits_a_number_or_a_word():
    """Down a narrow window it read "39 / 2" and "Histo / ry": a count
    split across lines reads as two numbers. Whole words, whole numbers,
    and the table scrolls sideways instead."""
    import re
    from pathlib import Path
    assets = (Path(__file__).resolve().parent.parent / "webcache" / "shell"
              / "html_package_assets")
    css = (assets / "page.css").read_text(encoding="utf-8")
    numbers = re.search(r"^table\.counts td\.n, table\.rawcounts td\.n\s*\{([^}]*)\}",
                        css, re.M).group(1)
    assert "white-space: nowrap" in numbers
    cells = re.search(r"^table\.counts td, table\.counts th, table\.rawcounts td, "
                      r"table\.rawcounts th\s*\{([^}]*)\}", css, re.M)
    assert cells and "overflow-wrap: normal" in cells.group(1)
    assert re.search(r"^\.countswrap\s*\{[^}]*overflow-x: auto", css, re.M)
    boot = (assets / "boot.js").read_text(encoding="utf-8")
    assert 'el("div", "countswrap")' in boot
