"""Core library for driving Huawei eNSP lab devices over their local console.

eNSP gives every started device a TCP console port on 127.0.0.1, starting at
2000 and increasing by one per device. That socket is the real VRP CLI, so
anything you can type by hand can be scripted.

This module has no third-party dependencies.
"""

from __future__ import annotations

import os
import re
import socket
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

__all__ = [
    "ConsoleError",
    "TopologyError",
    "Device",
    "Link",
    "Topo",
    "Console",
    "parse_topo",
    "scan_ports",
    "discover",
    "load_config_lines",
]

# Models that have no VRP command line, so a console script cannot configure them.
NON_CLI_MODELS = {"PC", "SimPC", "Laptop", "Cloud", "Hub", "MCS", "STA", "AP", "FRSW"}

DEFAULT_HOST = "127.0.0.1"
DEFAULT_FIRST_PORT = 2000
DEFAULT_LAST_PORT = 2099

# How much of the tail of the buffer to match prompts against.
_TAIL = 400

# `<Huawei>` or `[Huawei]` or `[Huawei-GigabitEthernet0/0/1]`
PROMPT_RE = re.compile(rb"[\r\n]?\s*[<\[][A-Za-z0-9_\-.]{1,64}[>\]]\s*$")
# Interactive confirmation such as `Are you sure to continue?[Y/N]`
QUESTION_RE = re.compile(rb"\[[Yy]/[Nn]\]\s*$")
# `save` on some VRP versions asks for a file name; accept the default.
FILENAME_RE = re.compile(rb"file name[^:]*:\s*$", re.IGNORECASE)
MORE_RE = re.compile(rb"-+\s*More\s*-+", re.IGNORECASE)
USERNAME_RE = re.compile(rb"(?:Username|Login)\s*:\s*$", re.IGNORECASE)
PASSWORD_RE = re.compile(rb"Password\s*:\s*$", re.IGNORECASE)

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240

# Lines in a config file that are noise rather than configuration.
_COMMENT_PREFIXES = ("#", "!", "//")


class ConsoleError(RuntimeError):
    """Raised when the device cannot be reached or a command fails."""


class TopologyError(RuntimeError):
    """Raised when a .topo file cannot be understood."""


# --------------------------------------------------------------------------
# Topology files
# --------------------------------------------------------------------------


@dataclass
class Device:
    id: str
    name: str
    model: str
    com_port: int
    cx: float = 0.0
    cy: float = 0.0

    @property
    def is_cli(self) -> bool:
        """Whether this model is expected to expose a VRP command line."""
        return self.model not in NON_CLI_MODELS

    def __str__(self) -> str:
        return f"{self.name} ({self.model}, port {self.com_port})"


@dataclass
class Link:
    src_id: str
    src_index: int
    dst_id: str
    dst_index: int
    media: str = "Copper"


@dataclass
class Topo:
    path: str
    devices: list[Device] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)

    def by_name(self, name: str) -> Device:
        for dev in self.devices:
            if dev.name == name:
                return dev
        raise TopologyError(f"device {name!r} not found in {self.path}")

    def names(self) -> list[str]:
        return [d.name for d in self.devices]


def _read_text(path: str) -> str:
    """Read a .topo file, tolerating UTF-8, UTF-8 BOM and UTF-16."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def parse_topo(path: str) -> Topo:
    """Parse an eNSP .topo file into devices and links."""
    if not os.path.isfile(path):
        raise TopologyError(f"no such file: {path}")

    try:
        root = ET.fromstring(_read_text(path))
    except ET.ParseError as exc:
        raise TopologyError(f"{path} is not valid XML: {exc}") from exc

    topo = Topo(path=os.path.abspath(path))

    for node in root.iter("dev"):
        try:
            port = int(node.get("com_port", "0"))
        except ValueError:
            port = 0
        topo.devices.append(
            Device(
                id=node.get("id", ""),
                name=node.get("name", "?"),
                model=node.get("model", "?"),
                com_port=port,
                cx=float(node.get("cx", "0") or 0),
                cy=float(node.get("cy", "0") or 0),
            )
        )

    by_id = {d.id: d for d in topo.devices}
    for line in root.iter("line"):
        src, dst = line.get("srcDeviceID"), line.get("destDeviceID")
        pair = line.find("interfacePair")
        if not (src and dst and pair is not None):
            continue
        if src not in by_id or dst not in by_id:
            continue
        try:
            topo.links.append(
                Link(
                    src_id=src,
                    src_index=int(pair.get("srcIndex", "0")),
                    dst_id=dst,
                    dst_index=int(pair.get("tarIndex", "0")),
                    media=pair.get("lineName", "Copper"),
                )
            )
        except ValueError:
            continue

    return topo


# --------------------------------------------------------------------------
# Console transport
# --------------------------------------------------------------------------


class Console:
    """A single device's VRP command line, reached over TCP."""

    def __init__(
        self,
        port: int,
        host: str = DEFAULT_HOST,
        timeout: float = 20.0,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.username = username
        self.password = password
        self._sock: socket.socket | None = None
        self._buf = b""
        self.prompt = b""
        self.name = f"{host}:{port}"

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "Console":
        return self.connect()

    def __exit__(self, *exc_info) -> None:
        self.close()

    def connect(self) -> "Console":
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=5)
        except OSError as exc:
            raise ConsoleError(f"{self.name}: cannot connect ({exc})") from exc

        self._sock.settimeout(0.2)
        self._buf = b""
        # Handshake and the first prompt are the same wait: a freshly booted
        # device may print a banner, a login prompt, or nothing but the prompt.
        self._handshake()
        self.prompt = self._prompt_from_buffer()
        self.name = self._prompt_name()
        # Long output is paginated by default; ask for a continuous stream.
        try:
            self.run("screen-length 0 temporary", timeout=5)
        except ConsoleError:
            pass
        return self

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _handshake(self) -> None:
        """Get from TCP connect to a usable shell prompt."""
        self._send_raw(b"\r\n")
        deadline = time.time() + self.timeout
        seen_login = False

        while time.time() < deadline:
            chunk = self._recv(timeout=0.5)
            if not chunk:
                continue
            tail = self._buf[-200:]

            if USERNAME_RE.search(tail) and not seen_login:
                if self.username is None:
                    raise ConsoleError(
                        f"{self.name}: device asks for a username; pass --username/--password"
                    )
                self._send_raw(self.username.encode() + b"\r\n")
                seen_login = True
                continue

            if PASSWORD_RE.search(tail):
                if self.password is None:
                    raise ConsoleError(f"{self.name}: device asks for a password")
                self._send_raw(self.password.encode() + b"\r\n")
                continue

            if b"Press ENTER" in tail or b"Press any key" in tail:
                self._send_raw(b"\r\n")
                continue

            if QUESTION_RE.search(tail):
                self._send_raw(b"Y\r\n")
                continue

            if PROMPT_RE.search(tail) and not QUESTION_RE.search(tail):
                return

        raise ConsoleError(
            f"{self.name}: no prompt after {self.timeout:.0f}s "
            f"(is the device fully booted? last output: {self._tail()!r})"
        )

    def _prompt_from_buffer(self) -> bytes:
        """Return the prompt the handshake left at the end of the buffer."""
        match = PROMPT_RE.search(self._buf[-_TAIL:])
        if match is None:
            raise ConsoleError(f"{self.name}: handshake ended without a prompt")
        return match.group(0).strip()

    # -- raw io ------------------------------------------------------------

    def _send_raw(self, data: bytes) -> None:
        if self._sock is None:
            raise ConsoleError("not connected")
        self._sock.sendall(data)

    def _recv(self, timeout: float) -> bytes:
        """Read whatever is available, stripping telnet negotiation."""
        if self._sock is None:
            raise ConsoleError("not connected")
        self._sock.settimeout(timeout)
        try:
            data = self._sock.recv(65536)
        except socket.timeout:
            return b""
        except OSError as exc:
            raise ConsoleError(f"{self.name}: connection lost ({exc})") from exc
        if not data:
            raise ConsoleError(f"{self.name}: device closed the connection")
        data = self._strip_iac(data)
        if data:
            self._buf += data
            # Keep memory bounded on very chatty commands.
            if len(self._buf) > 1_000_000:
                self._buf = self._buf[-500_000:]
        return data

    def _strip_iac(self, data: bytes) -> bytes:
        out = bytearray()
        i = 0
        while i < len(data):
            byte = data[i]
            if byte != IAC:
                out.append(byte)
                i += 1
                continue
            if i + 1 >= len(data):
                break
            cmd = data[i + 1]
            if cmd in (DO, DONT, WILL, WONT):
                opt = data[i + 2] if i + 2 < len(data) else 0
                reply = {DO: WONT, DONT: WONT, WILL: DONT, WONT: DONT}[cmd]
                self._send_raw(bytes([IAC, reply, opt]))
                i += 3
            elif cmd == SB:
                end = data.find(bytes([IAC, SE]), i)
                i = len(data) if end < 0 else end + 2
            else:
                i += 2
        return bytes(out)

    # -- reading -----------------------------------------------------------

    def _tail(self, limit: int = 400) -> str:
        return self._buf[-limit:].decode("utf-8", "replace").replace("\r", "")

    def _prompt_name(self) -> str:
        raw = self.prompt.decode("utf-8", "replace").strip("<>[] ")
        return raw or f"{self.host}:{self.port}"

    # -- commands ----------------------------------------------------------

    def run(
        self,
        command: str,
        timeout: float | None = None,
        confirm: bool = True,
    ) -> str:
        """Send one command and return its output with the echo and prompt removed.

        With `confirm`, an interactive `[Y/N]` question is answered with Y.
        """
        if self._sock is None:
            raise ConsoleError("not connected")

        self._buf = b""
        self._send_raw(command.encode("utf-8") + b"\r\n")
        deadline = time.time() + (timeout if timeout is not None else self.timeout)
        match = None

        while time.time() < deadline:
            self._recv(timeout=0.3)
            tail = self._buf[-_TAIL:]

            # A device waiting on `[Y/N]` prints no prompt, so this must be
            # checked before the prompt and pager cases.
            if QUESTION_RE.search(tail):
                if not confirm:
                    raise ConsoleError(
                        f"{self.name}: {command!r} is waiting for confirmation "
                        f"({tail.decode('utf-8', 'replace').strip()})"
                    )
                self._send_raw(b"Y\r\n")
                continue

            # A save filename prompt: pressing enter keeps the default.
            if FILENAME_RE.search(tail):
                self._send_raw(b"\r\n")
                continue

            # A returned prompt means the command finished, even if the output
            # happened to contain a `---- More ----` marker earlier.
            match = PROMPT_RE.search(tail)
            if match:
                break

            if MORE_RE.search(tail):
                self._send_raw(b" ")
                time.sleep(0.05)
                continue
        else:
            raise ConsoleError(
                f"{self.name}: no prompt after {command!r} "
                f"(last output: {self._tail()!r})"
            )

        self.prompt = match.group(0).strip()

        # The match was found in the tail slice, so translate its offset back
        # into the full buffer before cutting the output.
        offset = len(self._buf) - len(tail)
        text = self._buf[: offset + match.start()].decode("utf-8", "replace")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # Drop pager markers that were echoed back as pages were advanced.
        text = re.sub(r"[ \t]*-+\s*More\s*-+[ \t]*", "", text, flags=re.IGNORECASE)
        lines = text.split("\n")
        if lines and command.strip() in lines[0]:
            lines = lines[1:]
        return "\n".join(lines).strip("\n")

    def config(self, commands: list[str], save: bool = True) -> list[tuple[str, str]]:
        """Enter system view, apply commands, and optionally persist.

        Returns (command, output) pairs so callers can look for errors.
        """
        results: list[tuple[str, str]] = []
        self.run("system-view")
        for cmd in commands:
            cmd = cmd.strip()
            if not cmd:
                continue
            results.append((cmd, self.run(cmd)))
        self.run("return")
        if save:
            results.append(("<save>", self.save()))
        return results

    def save(self) -> str:
        """Persist the running config to flash, answering the Y/N prompt."""
        return self.run("save", timeout=90)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def _port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def scan_ports(
    host: str = DEFAULT_HOST,
    first: int = DEFAULT_FIRST_PORT,
    last: int = DEFAULT_LAST_PORT,
    timeout: float = 0.25,
) -> list[int]:
    """Return the console ports on `host` that accept a TCP connection."""
    return [p for p in range(first, last + 1) if _port_is_open(host, p, timeout)]


def discover(
    topo_path: str | None = None,
    host: str = DEFAULT_HOST,
    first: int = DEFAULT_FIRST_PORT,
    last: int = DEFAULT_LAST_PORT,
    timeout: float = 8.0,
) -> list[dict]:
    """Find running devices and their hostnames.

    With a .topo file, only its devices are probed and topology names are used
    as a fallback. Without one, the port range is scanned.
    """
    found: list[dict] = []

    if topo_path:
        topo = parse_topo(topo_path)
        candidates = [(d.com_port, d.name, d.model) for d in topo.devices if d.com_port]
    else:
        candidates = [(p, None, None) for p in scan_ports(host, first, last)]

    for port, topo_name, model in candidates:
        if not port:
            continue
        entry = {
            "port": port,
            "topo_name": topo_name,
            "model": model,
            "hostname": None,
            "port_open": False,
            "reachable": False,
        }

        # Connect first; only probe separately when that fails, so a device
        # is not asked to serve two connections just to be listed.
        try:
            with Console(port=port, host=host, timeout=timeout) as con:
                entry["hostname"] = con.name
                entry["reachable"] = True
                entry["port_open"] = True
        except ConsoleError:
            entry["port_open"] = _port_is_open(host, port)

        found.append(entry)

    return found


# --------------------------------------------------------------------------
# Config files
# --------------------------------------------------------------------------


def load_config_lines(path: str) -> list[str]:
    """Read a VRP snippet, dropping comments and blank lines."""
    lines = []
    with open(path, "r", encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            stripped = line.strip()
            if not stripped or stripped.startswith(_COMMENT_PREFIXES):
                continue
            lines.append(stripped)
    return lines


def normalize_config_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())
