"""Add a trailing backslash to pathVBox in eNSP's config files.

eNSP builds its VBoxManage path as `"%sVBoxManage"` with no separator, so the
configured directory must end with a backslash. The value written by the
installer does not, which makes the Options dialog report a bad VBox path even
though VirtualBox is installed correctly.

Byte-level editing only: the file holds GBK-encoded paths and must not be
re-encoded.
"""

import sys

PATHS = [
    r"C:\Users\23163\AppData\Local\eNSP\cfg\config_sys.ini",
    r"D:\ensp\eNSP\cfg\config_sys.ini",
]

OLD = b"path=D:\\ensp\\VirtualBox"
NEW = b"path=D:\\ensp\\VirtualBox\\"


def patch(path: str) -> str:
    raw = open(path, "rb").read()

    # Only touch the pathVBox section, in case another key shares the value.
    marker = b"[pathVBox]"
    start = raw.find(marker)
    if start < 0:
        return f"no [pathVBox] section in {path}"

    end = raw.find(b"[", start + len(marker))
    section = raw[start:] if end < 0 else raw[start:end]

    if NEW in section:
        return f"already patched: {path}"
    if OLD not in section:
        return f"value not found: {path}"

    patched_section = section.replace(OLD, NEW, 1)
    out = raw[:start] + patched_section + (raw[end:] if end >= 0 else b"")
    open(path, "wb").write(out)
    return f"patched: {path}"


for p in PATHS:
    print(patch(p))
