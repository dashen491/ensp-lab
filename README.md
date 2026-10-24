# ensp-lab

Script Huawei eNSP lab devices from the command line, and as a Claude Code skill.

eNSP opens a TCP console for every started device on `127.0.0.1`, from port
2000 upward. That socket is the device's real VRP command line, so configuration
can be pushed and verified by a script instead of typed into the GUI.

No dependencies. Python 3.8+ standard library only.

## What it does not do

It does not build topologies or start devices. Those are GUI actions backed by
VirtualBox, with no usable API. Build and start the lab in eNSP, then use this.

## Install

```bash
git clone <this repo> ensp-lab
cd ensp-lab
python -m unittest discover -s tests    # no eNSP needed
```

As a Claude Code skill, copy or symlink the repository into your skills
directory:

```bash
# Windows
xcopy /E /I ensp-lab %USERPROFILE%\.claude\skills\ensp-lab
# macOS / Linux
ln -s "$PWD/ensp-lab" ~/.claude/skills/ensp-lab
```

Then ask Claude things like "配一下 OSPF" or "验证 BGP 邻居状态".

## Usage

Every command that takes a device name also needs `--topo`, so that `R1`
resolves to the right console port.

```bash
# 1. Is the lab up?
python scripts/ensp.py ports --topo lab.topo

# 2. What is on the device now?
python scripts/ensp.py exec R1 "display current-configuration" --topo lab.topo

# 3. Apply a config file (plain VRP, # and ! are comments)
python scripts/ensp.py config R1 examples/configs/ospf_single_area/R1.cfg --topo lab.topo

# 4. Verify
python scripts/ensp.py verify examples/checks/ospf_single_area.json --topo lab.topo
```

```
$ python scripts/ensp.py ports --topo lab.topo
PORT   NAME MODEL        STATUS
2000   R1   AR1220       running
2001   R2   AR1220       running
2002   R3   AR1220       not started
```

```
$ python scripts/ensp.py verify examples/checks/ospf_single_area.json --topo lab.topo
ok   R1: OSPF neighbour R2 is Full
ok   R2: OSPF has two neighbours
ok   R3: learned R1 loopback as OSPF
ok   R1: learned R3 loopback as OSPF
ok   R1: ping R3 loopback
ok   R1: LSDB holds router LSAs

6 passed, 0 failed
```

Without a topology file, pass the console port directly:

```bash
python scripts/ensp.py exec 2000 "display version"
python scripts/ensp.py ports --first 2000 --last 2010
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | A command or check failed |
| 2 | Could not connect, or the topology file could not be read |

Non-zero exits make the commands usable in a loop or a CI-style check.

## Config files

Plain VRP, one command per line. Blank lines, `#` and `!` are ignored. The
script wraps the whole file in `system-view` … `return` and saves afterwards.

```text
# R1
sysname R1

interface LoopBack0
 ip address 10.0.1.1 255.255.255.0

interface GigabitEthernet0/0/1
 ip address 10.0.12.1 255.255.255.0

ospf 1 router-id 10.0.1.1
 area 0.0.0.0
  network 10.0.1.0 0.0.0.255
  network 10.0.12.0 0.0.0.255
```

Use `--no-save` to change the running config only, leaving flash untouched.

## Check files

A check passes when every `expect` string appears in the command output and no
`reject` string does.

```json
{
  "checks": [
    {
      "device": "R1",
      "name": "learned R3 loopback as OSPF",
      "command": "display ip routing-table",
      "expect": ["10.0.3.0/24", "OSPF"],
      "reject": ["Error"]
    },
    {
      "device": "R1",
      "name": "ping R3 loopback",
      "command": "ping -c 2 10.0.3.3",
      "expect": ["2 packet(s) received"]
    }
  ]
}
```

Checks should prove behaviour — neighbour state, route source, a working ping —
rather than that a line of text was written into the config.

## Layout

```
SKILL.md                     Claude Code skill instructions
scripts/ensp_lib.py          console transport, topo parsing, discovery
scripts/ensp.py              CLI: ports / exec / config / verify
examples/configs/            static routing, OSPF (single/multi area), BGP, VLAN,
                             campus_vrrp_lacp (dual-core with VRRP + LACP + STP)
examples/checks/             matching verification plans
references/device-catalog.md every eNSP model, its interfaces, and PC config
references/topo-format.md    the .topo XML format
references/vrp-cookbook.md   short working VRP snippets
tests/                       unit tests plus a fake VRP device
tests/fake_device.py         run a fake device on a fixed port for manual testing
```

## How it works

`ensp_lib.Console` is a small telnet client: it connects, answers the
`Press ENTER` banner, handles login prompts if the device has them, detects the
VRP prompt, and turns off pagination. Reading is driven by prompt detection, so
a command returns as soon as the device is done rather than after a fixed sleep.
`---- More ----` is advanced automatically, and `[Y/N]` confirmations are
answered.

Topology parsing reads the `.topo` XML directly to map device names to console
ports, so you never have to look up which port belongs to which router.

## Tests

The suite runs without eNSP on Linux, macOS and Windows (Python 3.9+), and CI
runs it on all three.

## Testing without eNSP

The test suite includes a fake VRP device that speaks the same protocol, which
covers prompt detection, the pager, save confirmation, and error reporting:

```bash
python -m unittest discover -s tests -v
```

To exercise the CLI by hand against it:

```bash
python tests/fake_device.py 2000 R1        # terminal 1
python scripts/ensp.py exec 2000 "display version"   # terminal 2
```

## Gotchas that cost real debugging time

These are covered by tests now, but they are worth knowing before you meet them
on a live lab.

**`save` does not survive closing the topology.** VRP's `save` writes to the
runtime virtual flash under `%LOCALAPPDATA%\eNSP\VBoxServer\workspaces\<guid>\`,
which eNSP deletes on close. Only *File → Save Topology* copies the flash images
back into the `.topo` folder. If a lab "loses" its config after reopening, this
is why.

**PC settings live in the `.topo` file, not on the device.** A `PC` has no
console. Its address is the `-simpc_ip` / `-simpc_mask` / `-simpc_gateway`
attributes of its `<dev>` element. Edit them with the topology closed, or eNSP
overwrites the file from memory.

**Event logs break prompt detection.** VRP prints `DATASYNC_CFGCHANGE` and link
up/down messages asynchronously, straight into the middle of command output.
`config` sends `undo terminal monitor` first; for a long `exec` session, do the
same.

**Eth-Trunk members need the trunk to exist.** `eth-trunk 1` on a port fails
with `The trunk port does not exist` unless `interface Eth-Trunk1` came first.
`config` creates it on demand and retries, so snippet order no longer matters.

**Interface prompts contain slashes.** The prompt inside an interface view is
`[L1-GigabitEthernet0/0/1]`, so the prompt regex has to accept `/`.

**The eNSP GUI cannot be driven by synthetic input.** eNSP runs elevated, and
Windows UIPI silently discards mouse and keyboard events sent from a
non-elevated process. Nothing errors; clicks simply do nothing. Change the
`.topo` file instead.

## Limitations

- Device names come from the `.topo` file. A device renamed with `sysname`
  shows its new name in `ports`, which is usually what you want, but the topo
  name is what `--topo` resolves. Localised labels such as `三层交换机L2` resolve
  from the short name too, as long as the match is unambiguous.
- Devices with no VRP CLI (`PC`, `Laptop`, `Cloud`, `Hub`, `MCS`, `STA`, `AP`,
  `Client`, `Server`, `Cellphone`, `FRSW`) cannot be configured.
  `references/device-catalog.md` lists every model eNSP offers.
- One console session per device at a time. Do not run two commands against the
  same device in parallel.
- eNSP console ports are assigned in device creation order, so the port is
  stable for a given topology but changes if devices are added or deleted.

## License

MIT
