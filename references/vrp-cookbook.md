# VRP cookbook

Short, working configurations for the labs this skill covers. Interface names
come from an AR1220 router and an S5700 switch; adjust them to the actual
topology.

## Address plan used in the examples

```
R1 -- 10.0.12.0/24 -- R2 -- 10.0.23.0/24 -- R3
loopbacks: R1 10.0.1.1  R2 10.0.2.2  R3 10.0.3.3   (/24 each)
```

## Interfaces

```text
interface GigabitEthernet0/0/1
 ip address 10.0.12.1 255.255.255.0

interface LoopBack0
 ip address 10.0.1.1 255.255.255.0
```

Verify with `display ip interface brief`. `Physical` and `Protocol` must both
read `up`.

## Static routing

```text
ip route-static 10.0.3.0 255.255.255.0 10.0.12.2
```

A default route is `ip route-static 0.0.0.0 0.0.0.0 <next-hop>`. Check with
`display ip routing-table`, where the source column reads `Static`.

## OSPF, single area

```text
ospf 1 router-id 10.0.1.1
 area 0.0.0.0
  network 10.0.1.0 0.0.0.255
  network 10.0.12.0 0.0.0.255
```

`network` uses a wildcard mask. The router ID should be a loopback, and that
loopback must also be advertised or neighbours have nothing stable to reach.

Verify, in order:

1. `display ospf peer brief` — state `Full`. Stuck at `Init` or `2-Way` means a
   one-way path or a mismatched area.
2. `display ip routing-table` — remote loopbacks present with source `OSPF`.
3. `ping -c 2 <remote loopback>`.

## OSPF, multiple areas

On the ABR, put each interface in its area:

```text
ospf 1 router-id 10.0.2.2
 area 0.0.0.0
  network 10.0.12.0 0.0.0.255
 area 0.0.0.1
  network 10.0.23.0 0.0.0.255
  abr-summary 10.1.0.0 255.255.0.0
```

Area 0 must be contiguous, and every other area must touch it through an ABR.
`display ospf brief` shows whether the router considers itself an
`Area Border Router`.

## BGP, eBGP between two ASes

```text
bgp 65001
 router-id 10.0.1.1
 peer 10.0.12.2 as-number 65002
 ipv4-family unicast
  network 10.0.1.0 255.255.255.0
  peer 10.0.12.2 enable
```

Two things bite here. The `network` statement only advertises a prefix that is
already in the routing table, so the loopback must exist first. And a session
built on physical addresses needs those addresses to be reachable, which is why
labs usually add a static route or an IGP underneath.

Verify with `display bgp peer`, where `State` must read `Established`, then
`display bgp routing-table` for the received prefix.

## VLAN and trunk

```text
vlan batch 10 20

interface GigabitEthernet0/0/1
 port link-type trunk
 port trunk allow-pass vlan 10 20

interface GigabitEthernet0/0/2
 port link-type access
 port default vlan 10
```

Verify with `display port vlan <interface>`. A trunk shows `PVID 1` and the
allowed VLAN list; an access port shows its VLAN and `access`.

## Spanning tree

```text
stp mode mstp
stp instance 0 root primary
```

`display stp` on the intended root shows `CIST Root/ERPC` with cost `0`, and
`display stp interface <interface>` shows `FORWARDING` on the live link and
`DISCARDING` on the blocked one.

## Handy show commands

| Goal | Command |
|---|---|
| Interface state and addresses | `display ip interface brief` |
| Full routing table | `display ip routing-table` |
| One prefix | `display ip routing-table 10.0.3.0` |
| OSPF neighbours | `display ospf peer brief` |
| OSPF interface parameters | `display ospf interface` |
| OSPF link state database | `display ospf lsdb` |
| BGP peers | `display bgp peer` |
| BGP table | `display bgp routing-table` |
| VLAN membership | `display vlan` |
| Port VLAN mode | `display port vlan <interface>` |
| Spanning tree | `display stp` |
| ARP table | `display arp` |
| Current config | `display current-configuration` |
| Saved config | `display saved-configuration` |
