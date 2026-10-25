"""Tests that do not need eNSP: topology parsing and console interaction.

The console tests run against a fake VRP device on a loopback socket, which
covers the parts most likely to break in practice: prompt detection, the
`---- More ----` pager, the save confirmation, and error reporting.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import re
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import ensp_lib as el


TOPO_XML = """<?xml version="1.0" encoding="UNICODE" ?>
<topo>
    <devices>
        <dev id="A" name="R1" model="AR1220" settings="" com_port="2000" bootmode="0" cx="341.0" cy="125.0" />
        <dev id="B" name="R2" model="AR2220" settings="" com_port="2001" bootmode="0" cx="120.0" cy="446.0" />
        <dev id="C" name="PC1" model="PC" settings="" com_port="0" bootmode="0" cx="10.0" cy="10.0" />
    </devices>
    <lines>
        <line srcDeviceID="A" destDeviceID="B">
            <interfacePair lineName="Copper" srcIndex="0" tarIndex="1" />
        </line>
    </lines>
    <shapes />
    <txttips />
</topo>
"""


class FakeVRP:
    """A tiny stand-in for a Huawei device, good enough to exercise the client."""

    def __init__(self, hostname="R1"):
        self.hostname = hostname
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.saved = False
        self.received: list[str] = []
        # Eth-Trunks that exist on this fake device, so `eth-trunk N` on a
        # member port can be rejected the way VRP rejects it.
        self.eth_trunks: set[int] = set()
        # Set when the last reply ended on an interactive question, so the next
        # line is an answer rather than a new command.
        self._pending = False
        self._more_pending = False
        self._pager: list[int] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass

    def _prompt(self, view="user"):
        name = self.hostname if view == "user" else f"{self.hostname}"
        return f"<{name}>" if view == "user" else f"[{name}]"

    def _serve(self):
        # A device stays available for later connections, so accept in a loop
        # rather than handling a single client and exiting.
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(conn,), daemon=True).start()

    def _session(self, conn):
        try:
            self._run_session(conn)
        except OSError:
            # The client hung up mid-command; normal at test teardown.
            return

    def _run_session(self, conn):
        with conn:
            view = "user"
            conn.sendall(b"\r\nPress ENTER to get started.\r\n")
            conn.sendall(self._prompt(view).encode())
            buf = b""
            while not self._stop.is_set():
                try:
                    data = conn.recv(4096)
                except OSError:
                    return
                if not data:
                    return
                buf += data
                # A pager advance is a bare space, with no line terminator.
                while self._more_pending and b" " in buf:
                    buf = buf.replace(b" ", b"", 1)
                    self.received.append(" ")
                    page = self._next_page()
                    if not self._more_pending:
                        page += self._prompt(view)
                    conn.sendall(page.encode())
                if not buf:
                    continue
                # Accept a bare CR or LF, the way a real console line does.
                while b"\r" in buf or b"\n" in buf:
                    split_at = min(
                        (buf.index(sep) for sep in (b"\r", b"\n") if sep in buf),
                        default=None,
                    )
                    if split_at is None:
                        break
                    line, rest = buf[:split_at], buf[split_at + 1 :]
                    terminated_by_lf = buf[split_at] == 0x0A
                    buf = rest.lstrip(b"\r\n")
                    cmd = line.decode("utf-8", "replace").strip()
                    self.received.append(cmd)
                    # Real VRP takes a bare CR at a `(y/n)` prompt. A CR LF
                    # leaves the LF to be parsed as a fresh command, which
                    # produces this error instead of saving.
                    if self._pending and terminated_by_lf:
                        self._pending = False
                        conn.sendall(
                            (cmd + "\r\n     ^\r\nError: Unrecognized command found "
                             "at '^' position.\r\n" + self._prompt(view)).encode()
                        )
                        continue
                    view, reply = self._handle(cmd, view)
                    if self._pending or self._more_pending:
                        # Waiting on an answer or a pager key: no prompt yet.
                        conn.sendall((cmd + "\r\n" + reply).encode())
                        self._pending = False
                    else:
                        conn.sendall((cmd + "\r\n" + reply + self._prompt(view)).encode())

    def _handle(self, cmd, view):
        """Return (view, reply). Replies ending on a question set _pending."""
        self._pending = False

        if cmd == "":
            return view, ""
        if cmd == "system-view":
            return "system", ""
        if cmd == "return":
            return "user", ""
        if cmd == "save":
            self._pending = True
            return view, (
                "  The current configuration will be written to the device.\r\n"
                "  Are you sure to continue?[Y/N]"
            )
        if cmd in ("Y", "y"):
            self.saved = True
            return view, "  Now saving the current configuration...\r\n  Save the configuration successfully."
        if cmd == "screen-length 0 temporary":
            return view, ""
        if cmd == "display long":
            # Page one screen at a time, as a real device does.
            self._pager = list(range(200))
            return view, self._next_page()
        if cmd == "display version":
            return view, "Huawei Versatile Routing Platform Software\r\nVRP (R) software, Version 5.110"
        if cmd == "display current-configuration":
            # The version banner opens with `[V200R003C00]`, which a generic
            # prompt pattern mistakes for the prompt.
            return view, (
                "[V200R003C00]\r\n#\r\n sysname R1\r\n#\r\n"
                "interface GigabitEthernet0/0/1\r\n ip address 10.0.0.1 255.255.255.0\r\n#\r\nreturn"
            )
        if cmd == "sysname R2":
            self.hostname = "R2"
            return view, ""
        if cmd == "bad-command":
            return view, "Error: Unrecognized command found at '^' position."
        if cmd == "undo terminal monitor":
            return view, "Info: Current terminal monitor is off."
        trunk_if = re.match(r"^interface Eth-Trunk(\d+)$", cmd)
        if trunk_if:
            self.eth_trunks.add(int(trunk_if.group(1)))
            return view, ""
        member = re.match(r"^eth-trunk (\d+)$", cmd)
        if member:
            if int(member.group(1)) not in self.eth_trunks:
                return view, "Error: The trunk port does not exist."
            return view, ""
        if cmd == "confirm-me":
            self._pending = True
            return view, "Really do it?[Y/N]"
        return view, f"  echo: {cmd}"

    def _next_page(self, size=24):
        chunk, self._pager = self._pager[:size], self._pager[size:]
        text = "".join(f"line {i}\r\n" for i in chunk)
        self._more_pending = bool(self._pager)
        if self._pager:
            return text + "  ---- More ----"
        return text


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class TopologyTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        handle = tempfile.NamedTemporaryFile("w", suffix=".topo", delete=False, encoding="utf-8")
        handle.write(TOPO_XML)
        handle.close()
        self.path = handle.name

    def tearDown(self):
        os.unlink(self.path)

    def test_parses_devices(self):
        topo = el.parse_topo(self.path)
        self.assertEqual(topo.names(), ["R1", "R2", "PC1"])
        self.assertEqual(topo.by_name("R1").com_port, 2000)
        self.assertEqual(topo.by_name("R2").model, "AR2220")

    def test_parses_links(self):
        topo = el.parse_topo(self.path)
        self.assertEqual(len(topo.links), 1)
        self.assertEqual(topo.links[0].src_index, 0)
        self.assertEqual(topo.links[0].dst_index, 1)

    def test_marks_non_cli_models(self):
        topo = el.parse_topo(self.path)
        self.assertFalse(topo.by_name("PC1").is_cli)
        self.assertTrue(topo.by_name("R1").is_cli)

    def test_unknown_device(self):
        with self.assertRaises(el.TopologyError):
            el.parse_topo(self.path).by_name("R9")

    def test_missing_file(self):
        with self.assertRaises(el.TopologyError):
            el.parse_topo("does-not-exist.topo")

    def test_example_topology_from_ensp(self):
        """The real eNSP example files must parse, when present."""
        examples = os.environ.get("ENSP_EXAMPLES")
        if not examples or not os.path.isdir(examples):
            self.skipTest("ENSP_EXAMPLES not set")
        for root, _dirs, files in os.walk(examples):
            for name in files:
                if name.endswith(".topo"):
                    topo = el.parse_topo(os.path.join(root, name))
                    self.assertGreater(len(topo.devices), 0, name)


class ConsoleTests(unittest.TestCase):
    def test_connect_and_prompt(self):
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                self.assertEqual(con.name, "R1")

    def test_runs_command_and_strips_echo(self):
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                out = con.run("display version")
        self.assertIn("Versatile Routing Platform", out)
        self.assertNotIn("display version", out)
        self.assertNotIn("<R1>", out)

    def test_pager_is_advanced(self):
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=10) as con:
                out = con.run("display long")
        self.assertIn("line 199", out)
        self.assertNotIn("More", out)

    def test_version_banner_is_not_a_prompt(self):
        """`[V200R003C00]` opens every `display current-configuration`.

        Treating it as the prompt truncates the output to nothing, which is
        what made every config dump look like an empty device.
        """
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                out = con.run("display current-configuration")
        self.assertIn("V200R003C00", out)
        self.assertIn("ip address 10.0.0.1", out)
        self.assertIn("return", out)

    def test_sysname_change_is_followed(self):
        """After `sysname R2` the prompt is `<R2>`; matching must follow it."""
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                con.run("system-view")
                con.run("sysname R2")
                self.assertEqual(con.name, "R2")
                con.run("return")
                out = con.run("display version")
        self.assertIn("Versatile Routing Platform", out)

    def test_save_answer_uses_bare_cr(self):
        """A CR LF at the `(y/n)` prompt is rejected by real VRP."""
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                out = con.save()
        self.assertTrue(fake.saved)
        self.assertNotIn("Unrecognized command", out)

    def test_config_enters_system_view_and_saves(self):
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                results = con.config(["sysname R1", "interface GigabitEthernet0/0/1"])
        self.assertTrue(fake.saved)
        self.assertIn("system-view", fake.received)
        self.assertIn("sysname R1", fake.received)
        self.assertIn("<save>", [cmd for cmd, _ in results])

    def test_config_without_save(self):
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                con.config(["sysname R1"], save=False)
        self.assertFalse(fake.saved)

    def test_error_output_is_returned_verbatim(self):
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                out = con.run("bad-command")
        self.assertIn("Unrecognized command", out)

    def test_confirmation_is_answered(self):
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                con.run("confirm-me")
        # Lower case: real VRP takes `y` at a `(y/n)` prompt and rejects `Y`.
        self.assertIn("y", fake.received)

    def test_config_quietens_terminal_monitor(self):
        """Event logs interleaved with output look like a hung device."""
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                con.config(["sysname R1"], save=False)
        self.assertIn("undo terminal monitor", fake.received)

    def test_eth_trunk_member_creates_missing_trunk(self):
        """`eth-trunk 1` fails unless Eth-Trunk1 exists, whatever the order."""
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                results = con.config(
                    ["interface GigabitEthernet0/0/3", "eth-trunk 1"], save=False
                )
        outputs = dict(results)
        self.assertNotIn("does not exist", outputs["eth-trunk 1"])
        self.assertIn("interface Eth-Trunk1", fake.received)

    def test_eth_trunk_existing_is_not_recreated(self):
        with FakeVRP("R1") as fake:
            with el.Console(fake.port, timeout=5) as con:
                con.config(["interface Eth-Trunk1", "mode lacp-static"], save=False)
                fake.received.clear()
                con.config(["interface GigabitEthernet0/0/3", "eth-trunk 1"], save=False)
        self.assertNotIn("interface Eth-Trunk1", fake.received)

    def test_missing_device_raises(self):
        with self.assertRaises(el.ConsoleError):
            el.Console(free_port(), timeout=2).connect()

    def test_scan_ports_finds_listener(self):
        with FakeVRP("R1") as fake:
            found = el.scan_ports(first=fake.port, last=fake.port)
        self.assertEqual(found, [fake.port])


class CliTests(unittest.TestCase):
    """Exercise scripts/ensp.py end to end against a fake device."""

    @classmethod
    def setUpClass(cls):
        import importlib.util

        path = os.path.join(os.path.dirname(__file__), "..", "scripts", "ensp.py")
        spec = importlib.util.spec_from_file_location("ensp_cli", path)
        cls.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)

    def main(self, argv):
        """Run the CLI with its output swallowed, so the test log stays readable."""
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return self.cli.main(argv)

    def test_config_exit_zero_on_success(self):
        with FakeVRP("R1") as fake:
            code = self.main([
                "config", str(fake.port), _write_cfg("sysname R1\n"),
            ])
        self.assertEqual(code, 0)
        self.assertTrue(fake.saved)

    def test_config_no_save(self):
        with FakeVRP("R1") as fake:
            code = self.main([
                "config", str(fake.port), _write_cfg("sysname R1\n"), "--no-save",
            ])
        self.assertEqual(code, 0)
        self.assertFalse(fake.saved)

    def test_config_fails_on_rejected_command(self):
        with FakeVRP("R1") as fake:
            code = self.main([
                "config", str(fake.port), _write_cfg("bad-command\n"),
            ])
        self.assertEqual(code, 1)

    def test_exec_returns_output(self):
        with FakeVRP("R1") as fake:
            code = self.main(["exec", str(fake.port), "display version"])
        self.assertEqual(code, 0)

    def test_exec_fails_on_error_output(self):
        with FakeVRP("R1") as fake:
            code = self.main(["exec", str(fake.port), "bad-command"])
        self.assertEqual(code, 1)

    def test_exec_ignore_errors(self):
        with FakeVRP("R1") as fake:
            code = self.main([
                "exec", str(fake.port), "bad-command", "--ignore-errors",
            ])
        self.assertEqual(code, 0)

    def test_unreachable_device_exits_two(self):
        code = self.main(["exec", str(free_port()), "display version", "--timeout", "1"])
        self.assertEqual(code, 2)

    def test_verify_passes_and_fails(self):
        import json
        import tempfile

        with FakeVRP("R1") as fake:
            plan = {"checks": [
                {"device": str(fake.port), "command": "display version",
                 "expect": ["Versatile Routing Platform"]},
                {"device": str(fake.port), "command": "display version",
                 "expect": ["nonexistent-string"]},
            ]}
            handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                                 encoding="utf-8")
            json.dump(plan, handle)
            handle.close()
            try:
                code = self.main(["verify", handle.name])
            finally:
                os.unlink(handle.name)
        self.assertEqual(code, 1)

    def test_topo_name_requires_topo_flag(self):
        code = self.main(["exec", "R1", "display version"])
        self.assertEqual(code, 2)

    def test_unknown_topo_device_exits_two(self):
        import tempfile

        handle = tempfile.NamedTemporaryFile("w", suffix=".topo", delete=False,
                                             encoding="utf-8")
        handle.write(TOPO_XML)
        handle.close()
        try:
            code = self.main(["exec", "R9", "display version", "--topo", handle.name])
        finally:
            os.unlink(handle.name)
        self.assertEqual(code, 2)


def _write_cfg(text: str) -> str:
    import tempfile

    handle = tempfile.NamedTemporaryFile("w", suffix=".cfg", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return handle.name


class ConfigFileTests(unittest.TestCase):
    def test_comments_and_blanks_are_dropped(self):
        import tempfile

        handle = tempfile.NamedTemporaryFile("w", suffix=".cfg", delete=False, encoding="utf-8")
        handle.write("# a comment\n\n! another\nsysname R1\n  interface GE0/0/1  \n")
        handle.close()
        try:
            lines = el.load_config_lines(handle.name)
        finally:
            os.unlink(handle.name)
        self.assertEqual(lines, ["sysname R1", "interface GE0/0/1"])


if __name__ == "__main__":
    unittest.main()
