"""A real browser, headless, driven over the DevTools protocol.

Nothing is installed: the Chrome or Edge this machine already has, and
websocket-client (a dev extra, already present). Not a test module."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import urllib.request

CANDIDATES = (
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

#: The one HTTP call (to 127.0.0.1) never goes through a system proxy.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def find_browser():
    override = os.environ.get("WEBCACHE_BROWSER")
    if override:
        return override if os.path.isfile(override) else None
    for path in CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


class Browser:
    def __init__(self, executable):
        import websocket
        self.profile = tempfile.mkdtemp(prefix="wc-cdp-")
        self.downloads = tempfile.mkdtemp(prefix="wc-dl-")
        self.proc = subprocess.Popen(
            [executable, "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", "--disable-extensions",
             "--remote-debugging-port=0", "--user-data-dir=" + self.profile,
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = os.path.join(self.profile, "DevToolsActivePort")
        deadline = time.monotonic() + 30
        while not (os.path.exists(port_file) and os.path.getsize(port_file)):
            if time.monotonic() > deadline or self.proc.poll() is not None:
                raise RuntimeError("the browser did not start")
            time.sleep(0.05)
        time.sleep(0.1)
        port = open(port_file, encoding="ascii").read().split()[0]
        base = "http://127.0.0.1:%s" % port
        version = json.load(_DIRECT.open(base + "/json/version", timeout=10))
        self.version = version.get("Browser", "")
        self.events = []
        self._ids = 0
        self._browser = websocket.create_connection(
            version["webSocketDebuggerUrl"], suppress_origin=True, timeout=120)
        self._send(self._browser, "Browser.setDownloadBehavior",
                   behavior="allow", downloadPath=self.downloads)
        pages = [t for t in json.load(_DIRECT.open(base + "/json", timeout=10))
                 if t.get("type") == "page"]
        self._page = websocket.create_connection(
            pages[0]["webSocketDebuggerUrl"], suppress_origin=True,
            timeout=120)
        for domain in ("Page", "Runtime", "Log", "Network"):
            self.call(domain + ".enable")

    def _send(self, sock, method, **params):
        self._ids += 1
        ident = self._ids
        sock.send(json.dumps({"id": ident, "method": method,
                              "params": params}))
        while True:
            message = json.loads(sock.recv())
            if message.get("id") == ident:
                if "error" in message:
                    raise RuntimeError("%s: %s" % (method, message["error"]))
                return message.get("result", {})
            if "method" in message:
                self.events.append(message)

    def call(self, method, **params):
        return self._send(self._page, method, **params)

    def evaluate(self, expression, await_promise=False):
        result = self.call("Runtime.evaluate", expression=expression,
                           returnByValue=True, awaitPromise=await_promise)
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = (details.get("exception", {}).get("description")
                    or details.get("text"))
            raise RuntimeError("page raised: %s" % text)
        return result.get("result", {}).get("value")

    def open(self, path, wait_ready=True, timeout=60):
        self.events = []
        self.call("Page.navigate", url=pathlib.Path(path).resolve().as_uri())
        deadline = time.monotonic() + timeout
        test = ("window.__wc_ready === true" if wait_ready
                else "document.readyState === 'complete'")
        while time.monotonic() < deadline:
            try:
                if self.evaluate(test):
                    return
            except RuntimeError:
                pass
            time.sleep(0.05)
        raise TimeoutError("the page did not become ready: %s"
                           % self.console_errors())

    # --- trusted input: the browser's own input path, never dispatchEvent --

    def click(self, x, y, count=1):
        """One real press and release at (x, y) CSS px, carrying
        clickCount `count`: a double-click is click(x, y, 1) then
        click(x, y, 2), as the browser sees a person's."""
        self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        for kind in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y,
                      button="left",
                      buttons=1 if kind == "mousePressed" else 0,
                      clickCount=count)

    _KEYS = {"Enter": (13, "\r"), "Tab": (9, ""), "Escape": (27, ""),
             "ArrowDown": (40, ""), "ArrowUp": (38, ""), " ": (32, " ")}

    def key(self, name, shift=False):
        """A real key press: keyDown (with its text, so Enter and Space
        activate a focused button as a person's would), then keyUp."""
        code, text = self._KEYS[name]
        common = dict(key=name, code="Space" if name == " " else name,
                      windowsVirtualKeyCode=code, nativeVirtualKeyCode=code,
                      modifiers=8 if shift else 0)
        down = dict(common, type="keyDown")
        if text:
            down["text"] = down["unmodifiedText"] = text
        self.call("Input.dispatchKeyEvent", **down)
        self.call("Input.dispatchKeyEvent", type="keyUp", **common)

    def center(self, selector):
        """The CSS-px centre of the first element `selector` matches."""
        return self.evaluate(
            "(function () { var r = document.querySelector(%s)"
            ".getBoundingClientRect(); return [r.left + r.width / 2,"
            " r.top + r.height / 2]; })()" % json.dumps(selector))

    def _log_entries(self):
        for event in self.events:
            if event.get("method") == "Log.entryAdded":
                yield event["params"]["entry"]

    def console_errors(self):
        out = []
        for event in self.events:
            method, params = event.get("method"), event.get("params", {})
            if method == "Runtime.exceptionThrown":
                details = params.get("exceptionDetails", {})
                out.append(details.get("exception", {}).get("description")
                           or details.get("text", ""))
            elif (method == "Runtime.consoleAPICalled"
                  and params.get("type") == "error"):
                out.append(" ".join(str(a.get("value", a.get("description")))
                                    for a in params.get("args", ())))
        out += [e.get("text", "") for e in self._log_entries()
                if e.get("level") == "error"
                and "Content Security Policy" not in e.get("text", "")]
        return out

    def csp_violations(self):
        return [e.get("text", "") for e in self._log_entries()
                if "Content Security Policy" in e.get("text", "")]

    def requests(self):
        return [e["params"]["request"]["url"] for e in self.events
                if e.get("method") == "Network.requestWillBeSent"]

    def clear_downloads(self):
        for name in os.listdir(self.downloads):
            try:
                os.remove(os.path.join(self.downloads, name))
            except FileNotFoundError:
                # Chrome removed its own file between the listing and
                # the remove: already what this wanted.
                pass
            except PermissionError:
                # Chrome keeps its own downloads.htm open while it runs;
                # only a file a test asked for matters here.
                if name != "downloads.htm":
                    raise

    def wait_download(self, name, timeout=30):
        target = os.path.join(self.downloads, name)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (os.path.exists(target)
                    and not os.path.exists(target + ".crdownload")):
                time.sleep(0.2)
                return target
            time.sleep(0.05)
        raise TimeoutError("no download named %s; have %s"
                           % (name, os.listdir(self.downloads)))

    def close(self):
        for sock in ("_page", "_browser"):
            try:
                getattr(self, sock).close()
            except Exception:                          # noqa: BLE001
                pass
        self.proc.kill()
        self.proc.wait(timeout=10)
        shutil.rmtree(self.profile, ignore_errors=True)
        shutil.rmtree(self.downloads, ignore_errors=True)
