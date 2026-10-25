"""Add a trailing backslash to pathVBox in eNSP's config files.

eNSP builds its VBoxManage path as `"%sVBoxManage"` with no separator, so the
configured directory must end with a backslash. The value written by the
installer does not, which makes the Options dialog report a bad VBox path even
though VirtualBox is installed correctly.

Byte-level editing only: the file holds GBK-encoded paths and must not be
re-encoded.

    python tools/fix_vbox_path.py                 # auto-detect the config file
    python tools/fix_vbox_path.py <config_sys.ini>  # or name one explicitly
"""

from __future__ import annotations

import os
import sys

MARKER = b"[pathVBox]"


def candidate_paths() -> list[str]:
    """The places eNSP writes config_sys.ini, most likely first."""
    found = []

    local = os.environ.get("LOCALAPPDATA")
    if local:
        found.append(os.path.join(local, "eNSP", "cfg", "config_sys.ini"))

    # A portable install keeps the config next to the executable.
    for drive in ("C:", "D:", "E:"):
        found.append(os.path.join(drive + os.sep, "eNSP", "eNSP", "cfg", "config_sys.ini"))
        found.append(os.path.join(drive + os.sep, "ensp", "eNSP", "cfg", "config_sys.ini"))

    return found


def patch(path: str) -> str:
    raw = open(path, "rb").read()

    # Only touch the pathVBox section, in case another key shares the value.
    start = raw.find(MARKER)
    if start < 0:
        return f"no [pathVBox] section in {path}"

    end = raw.find(b"[", start + len(MARKER))
    section = raw[start:] if end < 0 else raw[start:end]

    # The current value, whatever drive or folder it points at.
    key = b"path="
    key_at = section.find(key)
    if key_at < 0:
        return f"no path= key in [pathVBox] of {path}"

    value_start = key_at + len(key)
    value_end = section.find(b"\n", value_start)
    if value_end < 0:
        value_end = len(section)

    value = section[value_start:value_end].rstrip(b"\r")
    if value.endswith(b"\\"):
        return f"already patched: {path}"

    # Keep whatever line ending the file already uses.
    eol = b"\r" if section[value_start:value_end].endswith(b"\r") else b""
    patched_section = section[:value_start] + value + b"\\" + eol + section[value_end:]
    out = raw[:start] + patched_section + (raw[end:] if end >= 0 else b"")
    open(path, "wb").write(out)
    return f"patched: {path}"


def main(argv: list[str]) -> int:
    paths = argv[1:] or candidate_paths()
    if not paths:
        print("no candidate config_sys.ini found; pass the path explicitly")
        return 2

    seen = 0
    for path in paths:
        if not os.path.isfile(path):
            continue
        seen += 1
        print(patch(path))

    if not seen:
        print("config_sys.ini not found in any of:")
        for path in paths:
            print(f"  {path}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
