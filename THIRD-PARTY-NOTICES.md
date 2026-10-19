# Third-party notices

WebCache Forensic Analyzer is built on the following libraries. Each is
distributed under its own licence, and each library's licence and
copyright files travel with the packaged application.

| Library | Used for | Author | Licence |
|---|---|---|---|
| [dissect.esedb](https://github.com/fox-it/dissect.esedb) | Reading the ESE database: pages, B-trees, catalog and records, including databases in a dirty-shutdown state | Dissect Team, Fox-IT (part of NCC Group) | Apache-2.0 |
| [dissect.cstruct](https://github.com/fox-it/dissect.cstruct) | Binary structure definitions used by dissect.esedb | Dissect Team, Fox-IT (part of NCC Group) | Apache-2.0 |
| [dissect.util](https://github.com/fox-it/dissect.util) | Helpers used by dissect.esedb | Dissect Team, Fox-IT (part of NCC Group) | Apache-2.0 |
| [Qt for Python (PySide6, shiboken6)](https://pyside.org) | The desktop interface | The Qt Company and the Qt for Python Team | LGPL-3.0 |
| [openpyxl](https://openpyxl.readthedocs.io) and et_xmlfile | Excel workbook export | openpyxl authors | MIT |
| [ReportLab](https://www.reportlab.com) | PDF report export | ReportLab Inc. | BSD |
| [Pillow](https://python-pillow.org) | Image support used by ReportLab | Jeffrey A. Clark and contributors | MIT-CMU |
| [charset-normalizer](https://github.com/jawah/charset_normalizer) | Text-encoding detection used by ReportLab | Ahmed R. Tahri | MIT |

Dissect is released as open source by Fox-IT (https://www.fox-it.com),
part of NCC Group Plc (https://www.nccgroup.com), and is available at
https://github.com/fox-it/dissect.esedb under the Apache License 2.0
(https://www.apache.org/licenses/LICENSE-2.0).

Qt for Python is used under the GNU Lesser General Public License v3.0
(https://www.gnu.org/licenses/lgpl-3.0.html). Its text, and the GNU General
Public License v3.0 it extends, are in [licenses/](licenses). The packaged
application loads the Qt and PySide6 libraries as separate files, which
can be replaced.
