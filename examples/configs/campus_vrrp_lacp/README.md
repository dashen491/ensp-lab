# Dual-core campus with VRRP, LACP and STP

Five devices: two routers (`R1`, `R2`), a Layer-2 access switch (`L1`) and two
Layer-3 core switches (`L2`, `L3`) acting as a VRRP pair.

```
   PC1 192.168.100.101/24 ─┐
                           L1 ──G0/0/1── L2 ──G0/0/2── R1 G0/0/2 (192.168.101.2)
   PC2 192.168.200.101/24 ─┘   │          │  └─G0/0/5── R2 G0/0/0 (201.1.1.2)
                               └─G0/0/2────┤
                      L2 G0/0/3,4 ══ L3 G0/0/3,4  (Eth-Trunk1, LACP)
                               L3 ──G0/0/2── R1 G0/0/1 (192.168.102.2)
```

| Device | Role |
|---|---|
| `L1` | Access. GE0/0/24 = vlan100 to PC1, GE0/0/23 = vlan200 to PC2, two trunks up |
| `L2` | Core. STP primary root, VRRP master (priority 120), OSPF ABR |
| `L3` | Core. STP secondary root, VRRP backup, OSPF |
| `R1` | Area 0, loopback 1.1.1.1 |
| `R2` | Area 1, loopback 4.4.4.4 |

## Addressing

| | vlanif100 | vlanif200 | other |
|---|---|---|---|
| `L2` | 192.168.100.200/24 | 192.168.200.200/24 | vlanif101 192.168.101.1/24, vlanif201 201.1.1.1/24, Lo0 2.2.2.2/32 |
| `L3` | 192.168.100.201/24 | 192.168.200.201/24 | vlanif102 192.168.102.1/24, Lo0 3.3.3.3/32 |
| VRRP VIP | 192.168.100.254 | 192.168.200.254 | |

PC gateways point at the VRRP virtual IPs.

## Running it

```bash
python scripts/ensp.py config L1 examples/configs/campus_vrrp_lacp/L1.cfg --topo lab.topo
python scripts/ensp.py config L2 examples/configs/campus_vrrp_lacp/L2.cfg --topo lab.topo
python scripts/ensp.py config L3 examples/configs/campus_vrrp_lacp/L3.cfg --topo lab.topo
python scripts/ensp.py config R1 examples/configs/campus_vrrp_lacp/R1.cfg --topo lab.topo
python scripts/ensp.py config R2 examples/configs/campus_vrrp_lacp/R2.cfg --topo lab.topo
python scripts/ensp.py verify examples/checks/campus_vrrp_lacp.json --topo lab.topo
```

Then **File → Save Topology** in eNSP, or the device configs are discarded when
the topology closes.

## Two ordering traps this example encodes

- `interface Eth-Trunk1` comes before the `eth-trunk 1` member commands. A
  member port cannot join a trunk that does not exist yet.
- The PC IPs and gateways are `.topo` attributes (`-simpc_ip`, `-simpc_mask`,
  `-simpc_gateway`), not device CLI. Editing them needs the topology closed in
  eNSP, or the change is overwritten on save.
