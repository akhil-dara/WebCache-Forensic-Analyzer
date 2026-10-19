"""Every spelling of a file: URL lands on the right volume.

A network share written with four or five slashes (file:////server/share)
decoded to a path with one leading backslash and no volume, so a filter
on Drive for network shares missed it; file://localhost/C:/ named a
share called "localhost" instead of the local C: drive."""
import pytest

from webcache.engine import url_intel as u


@pytest.mark.parametrize("url,path,volume", [
    ("file:///C:/Users/x/a.pdf", r"C:\Users\x\a.pdf", "C:"),
    ("file:///E:/report.docx", r"E:\report.docx", "E:"),
    ("file://fileserver/share/a.pdf", r"\\fileserver\share\a.pdf",
     r"\\fileserver\share"),
    ("file:////fileserver/share/a.pdf", r"\\fileserver\share\a.pdf",
     r"\\fileserver\share"),
    ("file://///fileserver/share/a.pdf", r"\\fileserver\share\a.pdf",
     r"\\fileserver\share"),
    ("file:///%5C%5Cfs01/share/a.pdf", r"\\fs01\share\a.pdf",
     r"\\fs01\share"),
    ("file://localhost/C:/x.txt", r"C:\x.txt", "C:"),
    ("file://LOCALHOST/D:/y.txt", r"D:\y.txt", "D:"),
])
def test_a_file_url_decodes_to_its_path_and_volume(url, path, volume):
    decoded = u.windows_path_from_file_url(url)
    assert decoded == path
    assert u.path_volume(decoded) == volume
