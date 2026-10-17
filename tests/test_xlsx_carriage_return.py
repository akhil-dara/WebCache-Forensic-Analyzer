"""A carriage return in evidence survives the app's workbooks.

openpyxl writes a value's \\r as the character reference &#13; only when
lxml is installed. The packaged build excludes lxml (packaging/webcache.spec),
so the program examiners run wrote a raw \\r -- and every XML reader, Excel
included, reads a raw \\r back as \\n. "line one\\r\\nline two\\r" became
"line one\\n\\nline two\\n". Found by the release runner, which has no lxml;
this machine's lxml hid it. The writers are run here in a subprocess with
OPENPYXL_LXML=False -- openpyxl reads that switch once, at import -- so the
test exercises the path the shipped program takes, whatever is installed."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("openpyxl")

VALUE = "line one\r\nline two\rline three\n"

_SCRIPT = r"""
import json, sys
import openpyxl
from webcache.engine import forensic_engine
value, out = sys.argv[1], sys.argv[2]
simple = out + "-simple.xlsx"
forensic_engine.write_simple_xlsx(simple, "S", ["Address"], [[value]])
full = out + "-full.xlsx"
entries = [{"Url": value, "CleanUrl": value, "ContainerType": "History",
            "ContainerName": "History", "AccessedTime_raw": 133843382090000000,
            "AccessCount": 1, "EntryId": 1, "ContainerId": 3}]
engine = forensic_engine.ForensicEngine()
engine.load_entries(entries)
engine.export_xlsx(entries, full, True, {"examiner": "E"}, {}, {}, None, None,
                   None, engine.get_statistics())
found = {"simple": openpyxl.load_workbook(simple)["S"]["A2"].value,
         "full": [c.value for ws in openpyxl.load_workbook(full).worksheets
                  for row in ws.iter_rows() for c in row
                  if isinstance(c.value, str) and "line one" in c.value]}
print(json.dumps(found))
"""


@pytest.mark.parametrize("lxml", ["False", "True"])
def test_a_carriage_return_is_read_back_as_written(tmp_path, lxml):
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": ".", "OPENPYXL_LXML": lxml}
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, VALUE, str(tmp_path / "wb")],
        capture_output=True, text=True, timeout=120, cwd=root, env=env)
    assert result.returncode == 0, result.stderr[-3000:]
    found = json.loads(result.stdout.strip().splitlines()[-1])
    assert found["simple"] == VALUE
    assert found["full"] and all(v == VALUE for v in found["full"]), found["full"]
