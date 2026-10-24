#!/usr/bin/env python3
"""Command line front end for driving Huawei eNSP devices.

    python ensp.py ports                      # list running devices
    python ensp.py exec R1 "display version"  # run one command
    python ensp.py config R1 cfg.txt          # apply a config snippet
    python ensp.py verify plan.json           # run a set of checks
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ensp_lib as el

class UsageError(RuntimeError):
    """A bad argument, as opposed to a problem talking to a device."""


# VRP prints these when it rejects a command. Used to fail fast instead of
# silently leaving a half-configured device.
ERROR_MARKERS = (
    "Error:",
    "Wrong parameter",
    "Unrecognized command",
    "Incomplete command",
    "Too many parameters",
    "Ambiguous command",
    "Error.",
)


def _add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=el.DEFAULT_HOST, help="eNSP host (default 127.0.0.1)")
    parser.add_argument("--topo", help="path to a .topo file, used to map names to ports")
    parser.add_argument("--timeout", type=float, default=20.0, help="per-command timeout in seconds")
    parser.add_argument("--username", help="console username, if the device asks for one")
    parser.add_argument("--password", help="console password, if the device asks for one")


def _resolve_port(args, target: str | None) -> int:
    """Turn a device name or a port number into a console port."""
    if target is None:
        raise UsageError("a device name or port is required")

    if target.isdigit():
        return int(target)

    if not args.topo:
        raise UsageError(
            f"{target!r} is a device name, so --topo is required "
            "(or pass a port number instead)"
        )

    topo = el.parse_topo(args.topo)
    device = topo.by_name(target)
    if not device.com_port:
        raise UsageError(f"{device.name} has no console port recorded in the topo file")
    return device.com_port


def _connect(args, target: str | None) -> el.Console:
    port = _resolve_port(args, target)
    return el.Console(
        port=port,
        host=args.host,
        timeout=args.timeout,
        username=args.username,
        password=args.password,
    ).connect()


def _check_output(command: str, output: str) -> str | None:
    for marker in ERROR_MARKERS:
        if marker in output:
            return f"{command!r} -> {output.strip()}"
    return None


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def cmd_ports(args) -> int:
    rows = el.discover(
        topo_path=args.topo,
        host=args.host,
        first=args.first,
        last=args.last,
        timeout=args.timeout,
    )

    if not rows:
        print("No device consoles found. Start the devices in eNSP first.")
        return 1

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    width = max(len(str(r["hostname"] or r["topo_name"] or "")) for r in rows) + 2
    print(f"{'PORT':<6} {'NAME':<{width}} {'MODEL':<12} STATUS")
    running = 0
    for row in rows:
        name = row["hostname"] or row["topo_name"] or "-"
        if row["reachable"]:
            status = "running"
            running += 1
        elif row["port_open"]:
            status = "port open, no CLI yet"
        else:
            status = "not started"
        print(f"{row['port']:<6} {name:<{width}} {row['model'] or '-':<12} {status}")

    if not running:
        print("\nNo device answered on its console. Start the devices in eNSP "
              "and wait for them to finish booting.", file=sys.stderr)
    return 0 if running else 1


def cmd_exec(args) -> int:
    with _connect(args, args.target) as con:
        output = con.run(args.command, timeout=args.timeout)
    print(output)
    if args.ignore_errors:
        return 0
    return 1 if _check_output(args.command, output) else 0


def cmd_config(args) -> int:
    lines = el.load_config_lines(args.file)
    if not lines:
        raise UsageError(f"{args.file} has no commands")

    with _connect(args, args.target) as con:
        print(f"# {con.name} ({args.host}:{con.port}) - {len(lines)} commands")
        results = con.config(lines, save=not args.no_save)

    failures = []
    for command, output in results:
        if command == "<save>":
            continue
        problem = _check_output(command, output)
        if problem:
            failures.append(problem)

    if failures:
        print(f"\n{len(failures)} command(s) reported an error:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print(f"applied {len(lines)} commands" + ("" if args.no_save else ", saved"))
    return 0


def cmd_verify(args) -> int:
    """Run checks described in a JSON plan.

    {
      "checks": [
        {"device": "R1", "command": "display ip routing-table",
         "expect": ["10.0.2.0/24"], "reject": ["Error"]}
      ]
    }
    """
    with open(args.plan, "r", encoding="utf-8-sig") as fh:
        plan = json.load(fh)

    checks = plan.get("checks", [])
    if not checks:
        raise UsageError("plan has no checks")

    passed = failed = 0
    for check in checks:
        target = check.get("device")
        command = check["command"]
        try:
            with _connect(args, str(target)) as con:
                output = con.run(command, timeout=args.timeout)
        except el.ConsoleError as exc:
            print(f"FAIL {target}: {exc}")
            failed += 1
            continue

        problems = []
        for needle in check.get("expect", []):
            if needle not in output:
                problems.append(f"missing {needle!r}")
        for needle in check.get("reject", []):
            if needle in output:
                problems.append(f"unexpected {needle!r}")

        label = check.get("name") or command
        if problems:
            failed += 1
            print(f"FAIL {target}: {label} - {'; '.join(problems)}")
            if args.show_output:
                print(_indent(output))
        else:
            passed += 1
            print(f"ok   {target}: {label}")

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ensp.py",
        description="Drive Huawei eNSP lab devices over their local console ports.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ports = sub.add_parser("ports", help="list running devices")
    _add_connection_args(p_ports)
    p_ports.add_argument("--first", type=int, default=el.DEFAULT_FIRST_PORT)
    p_ports.add_argument("--last", type=int, default=el.DEFAULT_LAST_PORT)
    p_ports.add_argument("--json", action="store_true", help="machine readable output")
    p_ports.set_defaults(func=cmd_ports)

    p_exec = sub.add_parser("exec", help="run one command on a device")
    _add_connection_args(p_exec)
    p_exec.add_argument("target", help="device name (needs --topo) or console port")
    p_exec.add_argument("command")
    p_exec.add_argument("--ignore-errors", action="store_true")
    p_exec.set_defaults(func=cmd_exec)

    p_config = sub.add_parser("config", help="apply a config snippet")
    _add_connection_args(p_config)
    p_config.add_argument("target")
    p_config.add_argument("file", help="text file of VRP commands, # for comments")
    p_config.add_argument("--no-save", action="store_true", help="do not write to flash")
    p_config.set_defaults(func=cmd_config)

    p_verify = sub.add_parser("verify", help="run checks from a JSON plan")
    _add_connection_args(p_verify)
    p_verify.add_argument("plan")
    p_verify.add_argument("--show-output", action="store_true")
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (el.ConsoleError, el.TopologyError, UsageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
