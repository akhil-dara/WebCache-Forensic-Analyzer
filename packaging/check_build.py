"""Inspect a built tree: report its size, and fail if it contains a
browser engine.

Size is reported, not gated; the only failure is structural.
"""
import pathlib
import sys

FORBIDDEN = "Qt6WebEngineCore.dll"


def walk(root):
    total, biggest = 0, []
    for p in root.rglob("*"):
        if p.is_file():
            size = p.stat().st_size
            total += size
            biggest.append((size, p.relative_to(root)))
    biggest.sort(reverse=True)
    return total, biggest[:15]


def main(argv):
    root = pathlib.Path(argv[1] if len(argv) > 1 else "dist/WebCacheAnalyzer")
    if not root.is_dir():
        print("no build at %s" % root)
        return 2
    total, biggest = walk(root)
    mb = total / (1024 * 1024)
    print("## Build size: %.1f MB unpacked" % mb)
    print()
    print("| file | MB |")
    print("|---|---|")
    for size, rel in biggest:
        print("| `%s` | %.2f |" % (rel, size / (1024 * 1024)))

    offenders = [str(p.relative_to(root)) for p in root.rglob(FORBIDDEN)]
    if offenders:
        print()
        print("FAIL: %s is in the build (%s)." % (FORBIDDEN, offenders))
        print("A browser engine is not part of this application; it "
              "depends on PySide6-Essentials, which does not ship one.")
        return 1
    print()
    print("OK: no %s in the tree." % FORBIDDEN)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
