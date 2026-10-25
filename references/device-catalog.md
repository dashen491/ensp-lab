# eNSP device catalog

Every model eNSP can place on the canvas, what its console looks like, and how
its interfaces are named. Read this instead of guessing a model name or an
interface prefix.

This is original documentation, written from observing the device palette and
from the interface blocks that appear in topologies built with eNSP 1.3.x. No
file shipped inside the eNSP installer is reproduced here. The model set is
stable across 1.3.x installs; only the installed plugins vary.

## Routers — category `AR`

| Model | Interfaces | Console |
|---|---|---|
| `AR201` | 8× `Ethernet` (+1 uplink) | yes |
| `AR1220` | 2× `GE`, 8× `Ethernet`, 2× `Serial` | yes |
| `AR2220` | 3× `GE` (+ combo) | yes |
| `AR2240` | 3× `GE` combo | yes |
| `AR3260` | 4× `GE` + `Serial` | yes |
| `Router` | 2× `Ethernet`, 4× `GE`, 4× `Serial` | yes |

`Router` is the generic entry at the bottom of the palette. It is a plain AR
image with a mixed port set — it is **not** an AR1220, and its interface list
differs, so read it from the `.topo` file rather than assuming.

Interface names in VRP are `GigabitEthernet0/0/N`, `Ethernet0/0/N`,
`Serial0/0/N`, abbreviated `G0/0/N`, `E0/0/N`, `S0/0/N`.

## Switches — category `LSW`

| Model | Interfaces | Console |
|---|---|---|
| `S5700` | 24× `GE` | yes |
| `S3700` | 22× `Ethernet`, 2× `GE` | yes |
| `CE6800` | `GE` (data-center switch) | yes |

On switches the VRP names are `GigabitEthernet0/0/N` and `Ethernet0/0/N`, same
as routers. S5700 is the usual choice for VLAN/STP/LACP labs; S3700 is the
older 100 Mbit box and shows up in HCNA-era examples.

## Firewalls — category `FW`

| Model | Notes |
|---|---|
| `USG5500` | runs as a VirtualBox VM, needs the firewall plugin |
| `USG6000V` | runs as a VirtualBox VM, needs the firewall plugin |

Both expose a console, but their CLI is USG (not plain VRP) and the plugin has
to be installed. The first boot of a USG6000V takes several minutes.

## Wireless — category `WLAN`

Access controllers: `AC6005`, `AC6605` (8× `GE`).
Access points: `AP2010`, `AP2030`, `AP2050`, `AP3030`, `AP4030`, `AP4050`,
`AP5010`, `AP5030`, `AP6010`, `AP6050`, `AP6510`, `AP6610`, `AP7030`, `AP7050`,
`AP8030`, `AP8130`, `AP9131`, `AD9430`, `R250D`.

ACs have a console. APs do not — they are configured through the AC, so a
console script cannot touch them.

## End devices — category `CLIENT`

| Model | Console | How it is configured |
|---|---|---|
| `PC` | **no** | GUI dialog, or the `-simpc_*` args in `.topo` |
| `MCS` | no | GUI dialog |
| `Client` | no | GUI dialog |
| `Server` | no | GUI dialog |
| `STA` | no | GUI dialog |
| `Cellphone` | no | GUI dialog |

## Other — category `Other Devices` / custom

`Cloud`, `FRSW` (frame-relay switch), `HUB`, `CE12800` — no VRP console.
`Cloud` bridges the lab to a host NIC; it is a bridge, not a device.

## Consoles

Only devices with a VRP CLI get one. eNSP listens on `127.0.0.1`, starting at
**2000** and incrementing per started device, in the order the devices were
created. A device that is not started has no listener at all, so a connection
refused means "not started", not "wrong port".

`com_port` in the `.topo` file records the assigned port. Devices with
`com_port="0"` have no console.

## Configuring a PC without the GUI

A `PC` device carries its whole network config in the `settings` attribute of
its `<dev>` element:

```
<dev id="E0BA61B6-..." name="PC1" model="PC"
     settings=" -simpc_ip 192.168.100.101  -simpc_mask 255.255.255.0
                -simpc_gateway 192.168.100.254  -simpc_mac 54-89-98-F5-21-18
                -simpc_dhcp_state 0 ... " />
```

Editable keys: `-simpc_ip`, `-simpc_mask`, `-simpc_gateway`, `-simpc_dns1`,
`-simpc_dns2`, `-simpc_mac`, `-simpc_dhcp_state`, `-simpc_ipv6`,
`-simpc_prefix`, `-simpc_gatewayv6`, `-simpc_hostname`.

Two traps:

1. **eNSP must not have the topology open when you write.** It holds the file in
   memory and rewrites it on save, so the edit is lost. Have the user close the
   topology *without saving*, then reopen it.
2. **The PC must be started** for its IP to matter, and the GUI dialog only
   reflects what the file says at load time.

Do not try to drive the PC dialog with synthetic mouse/keyboard input. eNSP runs
elevated, and Windows UIPI silently discards input sent from a non-elevated
process — clicks land nowhere and no error is raised.
