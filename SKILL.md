---
name: ensp-lab
description: Drive Huawei eNSP lab devices from the command line. Use when the user asks to configure, script, or verify routers and switches running in eNSP (Huawei VRP), for example "配一下 OSPF", "给 R1 灌配置", "验证 BGP 邻居", "批量下发配置到 eNSP". Covers interface/IP, static routing, OSPF, BGP, VLAN/Trunk/STP. Requires the devices to already be built and started in eNSP.
---

# eNSP lab automation

eNSP gives every started device a TCP console on `127.0.0.1`, starting at port
2000 and increasing by one per device. That socket is the real VRP command
line, so configuration can be scripted instead of typed.

## What this skill can and cannot do

**Can**: read the topology from a `.topo` file, find running devices, push
configuration, run show commands, and verify results.

**Cannot**: build the topology or start devices. That is a GUI action backed by
VirtualBox, and there is no reliable API for it. The user builds and starts the
lab in eNSP; this skill takes over from there.

## Prerequisites

Check these before doing anything else:

1. The user has built the topology in eNSP and **started all devices**.
2. You have the `.topo` file path, or the user tells you the console ports.
3. Devices finished booting. A device that is still booting accepts the TCP
   connection but never prints a prompt.

Python 3.10+ with the standard library is enough. Nothing to install.

## Workflow

Every command below uses two paths, and neither may be relative to the user's
current directory:

- `<skill>` is the directory containing this file (the one with `scripts/`,
  `examples/` and `references/` in it). Resolve it once at the start.
- `<topo>` is the user's `.topo` file. `--topo` is what lets you say `R1`
  instead of `2000`.

Resolve `<skill>` before the first command:

```bash
# The skill's own directory, not the working directory
python -c "import os,sys; print(os.path.dirname(os.path.abspath(sys.argv[1])))" <path-to-SKILL.md>
```

Then always invoke the script by its absolute path, for example:

```bash
python "C:/Users/me/.claude/skills/ensp-lab/scripts/ensp.py" ports --topo "<topo>"
```

The user's shell may be bash, PowerShell or cmd. Quote both paths, and prefer
forward slashes on Windows.

### 1. Confirm the lab is up

```bash
python "<skill>/scripts/ensp.py" ports --topo "<topo>"
```

Expect one line per device with status `running`. If everything says
`not started`, stop and tell the user to start the devices in eNSP and wait for
boot to finish. Do not guess ports.

Note the device names and models. Models `PC`, `Laptop`, `Cloud`, `Hub`, `MCS`,
`STA`, `AP`, `Client`, `Server`, `Cellphone` and `FRSW` have no VRP CLI and
cannot be configured this way. `references/device-catalog.md` lists every model
the palette offers, its interface naming, and how to set a PC's IP by editing
the `.topo` file instead of the GUI.

### 2. Look before you write

Read the current state before changing it, so you can tell the user what
actually changed and can back out:

```
python "<skill>/scripts/ensp.py" exec R1 "display current-configuration" --topo "<topo>"
```

For a lab device that is still on factory defaults this is short. If it already
has a real configuration, confirm with the user before overwriting.

### 3. Apply configuration

```
python "<skill>/scripts/ensp.py" config R1 "<skill>/examples/configs/ospf_single_area/R1.cfg" --topo "<topo>"
```

The config file is plain VRP, one command per line, `#` and `!` start comments.
The script enters `system-view`, sends each line, returns to user view, and
saves. Exit code is non-zero if VRP reported an error for any line, and the
offending lines are printed.

Repeat per device. Devices are independent, so a failure on one does not roll
back another.

### 4. Verify

```
python "<skill>/scripts/ensp.py" verify "<skill>/examples/checks/ospf_single_area.json" --topo "<topo>"
```

A check passes when every `expect` string appears in the output and no `reject`
string does. Add `--show-output` to print the raw output of failures.

Write checks that prove the feature works, not that the config was typed:
neighbour state `Full`, a route present as `OSPF` in the routing table, a ping
that returns `2 packet(s) received`. A `display current-configuration` match
only proves the text is there.

## Writing config files

Match the user's actual wiring. Interface names differ between models
(`GigabitEthernet0/0/1` on AR1220, `Ethernet0/0/1` on some switches), and
guessing produces config that applies cleanly but does not pass traffic.
`references/device-catalog.md` has the interface set per model; the `.topo`
file has the one actually installed on this device.

If you do not know the wiring, read it from the topology or ask:

```
python "<skill>/scripts/ensp.py" exec R1 "display interface brief" --topo "<topo>"
```

Use the templates in `examples/configs/` as a starting point:
`basic/` (static routing), `ospf_single_area/`, `ospf_multi_area/`, `bgp/`,
`vlan/`. They assume R1 -- R2 -- R3 over `10.0.12.0/24` and `10.0.23.0/24`
with loopbacks `10.0.1.1`, `10.0.2.2`, `10.0.3.3`.

## Failure modes worth recognising

| Symptom | Cause |
|---|---|
| `no prompt after Ns` with empty output | Device still booting, or the port belongs to a different device |
| `cannot connect` | Device not started, or eNSP is closed |
| Config applied but no connectivity | Wrong interface names, or the cable is on another port |
| `Error: Unrecognized command` | Command not supported on that model or VRP version |
| Prompt is `<Huawei>` | Device was never renamed; config may have gone to the wrong box |
| Clicks or keystrokes sent to the eNSP GUI do nothing | eNSP runs elevated; Windows UIPI drops input from a non-elevated process. Edit the `.topo` file instead |
| `no prompt after ...` while output shows `DATASYNC_CFGCHANGE` or other `Oct 25 ... DS/4/...` lines | Event logs interleaved with the command output. `config` now sends `undo terminal monitor` first; for `exec`, do it once per session |
| `eth-trunk N` → `Error: The trunk port does not exist.` | The member port joined before `interface Eth-TrunkN` existed. `config` creates it on demand now; in hand-written configs, put the `interface Eth-TrunkN` block first |
| Config looks right, works now, gone after reopening the topology | `save` only reaches the runtime flash. The user must also pick *File → Save Topology*. See below |
| `exec` prints the *previous* command's output, or nothing at all | Stale bytes still in the socket from the last command. The client now drains before each send; if you see it again, the device is answering slower than the drain window |
| A `display` command returns only its first line | The prompt was matched against output rather than the prompt line. `display current-configuration` opens with `[V200R003C00]`, which a generic `[xxx]` pattern matches. Prompts are matched against the learned hostname for exactly this reason |

When a command fails, read the actual VRP output back to the user rather than
paraphrasing it. VRP error text names the exact position of the bad token.

## Persistence: `save` is not enough

This is the one thing that costs the most work when it is missed.

`save` writes to the device's **runtime virtual flash**, which lives under
`%LOCALAPPDATA%\eNSP\VBoxServer\workspaces\<device-guid>\slot17\flash.dat`.
eNSP **deletes that directory when the topology closes**. Only *File → Save
Topology* in the eNSP GUI copies the flash images back into the `.topo` folder
as `flash.efz`, which is what survives a reopen.

So after configuring:

1. Tell the user to click **File → Save Topology** (保存拓扑) in eNSP.
2. Warn that choosing *don't save* on close discards every device config, no
   matter how many times `save` ran.
3. A device folder's `flash.efz` timestamp is the proof: if it is still the
   install date, the config was never persisted.

PC settings are the exception — they live in the `.topo` file, so they follow
the topology, not the device flash.

## Console quirks that look like bugs in this tool

These are real device behaviours. Each one used to look like a hung or empty
device, so they are worth knowing before debugging anything else.

- **A bare CR, not CR LF.** At an interactive `(y/n)` prompt VRP takes the
  answer only when the line ends in a bare `\r`. With `\r\n` the leftover LF
  is parsed as a new command and the device replies `Error: Unrecognized
  command found at '^' position.` — the save silently does not happen. The
  client sends `y\r` and nothing else.
- **The prompt is the hostname, not any bracket.** Match `<name>` / `[name]`
  against the name learned at connect time. Matching a generic `[xxx]` also
  matches `[V200R003C00]` (the config banner) and the pager's `---- More ----`.
- **`screen-length 0 temporary` does not exist on every build.** `AR1220`
  rejects it with `The type of the included user interface must be VTY.` That
  rejection is harmless and is swallowed.
- **Switches ask a second question on `save`.** After the Y/N the S-series
  prints `Please input the file name (*.cfg, *.zip) [vrpcfg.zip]:`. Answering
  that with `y` fails with `Invalid file name`. Send a bare CR to take the
  default.
- **The console logs itself out.** After a few idle minutes the session drops
  to `Configuration console exit, please press any key to log on`. Send a CR
  and carry on; it is not a broken connection.
- **A paged reply redraws the screen.** The output carries `ESC[<n>D` cursor
  moves and runs of padding spaces. Both are stripped from what `exec`
  returns.

## Safety

`config` saves to flash by default. Pass `--no-save` to change the running
config only, which is what you want when experimenting on a device that already
holds a configuration the user cares about.

Do not run `reset saved-configuration`, `undo` on interfaces the user did not
ask about, or anything that reloads a device, unless the user asked for it in
those words.
