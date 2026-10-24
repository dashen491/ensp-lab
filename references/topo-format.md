# The .topo file format

An eNSP topology is a plain XML file. This skill reads it to map device names
to console ports, and you can read it the same way when you need to know the
wiring without opening the GUI.

## Structure

```xml
<?xml version="1.0" encoding="UNICODE" ?>
<topo>
    <devices>
        <dev id="135C9ACE-B0CE-4a32-8DF2-2B227EBC16BE"
             name="R1" model="AR1220" settings=""
             com_port="2000" bootmode="0"
             cx="341.000000" cy="125.000000"
             edit_left="308" edit_top="148">
            <slot number="slot17" isMainBoard="1">
                <interface sztype="Ethernet" interfacename="GE" count="2" />
                <interface sztype="Ethernet" interfacename="Ethernet" count="8" />
            </slot>
        </dev>
    </devices>
    <lines>
        <line srcDeviceID="135C9ACE-..." destDeviceID="A3B3E3D3-...">
            <interfacePair lineName="Copper"
                           srcIndex="0" tarIndex="2"
                           srcBoundRect_X="368.0" srcBoundRect_Y="195.1"
                           tarBoundRect_X="311.9" tarBoundRect_Y="379.7" />
        </line>
    </lines>
    <shapes />
    <txttips>
        <txttip left="287" top="92" content="Loopback:10.0.1.1/24" ... />
    </txttips>
</topo>
```

## The fields that matter

| Field | Meaning |
|---|---|
| `dev/@name` | Device label shown in the GUI, e.g. `R1` |
| `dev/@model` | Hardware model, e.g. `AR1220`, `S5700`, `PC` |
| `dev/@com_port` | **Console TCP port.** Starts at 2000, +1 per device |
| `dev/@id` | GUID, used to resolve link endpoints |
| `line/@srcDeviceID` | One end of a cable |
| `line/@destDeviceID` | The other end |
| `interfacePair/@srcIndex` | Interface index on the source device |
| `interfacePair/@tarIndex` | Interface index on the destination |
| `interfacePair/@lineName` | `Copper`, `Serial`, `Fiber` |
| `txttip/@content` | Free-text notes the author left on the canvas |

## Reading the wiring

`srcIndex` and `tarIndex` are zero-based positions within the device's port
list, ordered as the `<interface>` elements under `<slot>`. For an AR1220 with
`GE` count 2 then `Ethernet` count 8, index 0 is `GigabitEthernet0/0/0`,
index 1 is `GigabitEthernet0/0/1`, index 2 is `Ethernet0/0/0`, and so on.

The index-to-name mapping is not written in the file, so confirm it on the
device with `display interface brief` before writing config that depends on it.
The `txttips` often record the intended addressing, which is worth reading.

## Console port assignment

Ports are handed out in the order devices were created, not in canvas order or
alphabetical order. Deleting a device and adding another can reuse a port, so
re-read the file after editing the topology rather than assuming a port is
still what it was.

Devices with `com_port="0"` (typically `PC`, `Cloud`, `Hub`) have no console.

## Parsing it yourself

```python
import sys
sys.path.insert(0, "scripts")
import ensp_lib

topo = ensp_lib.parse_topo("lab.topo")
for device in topo.devices:
    print(device.name, device.model, device.com_port)

for link in topo.links:
    print(topo.by_name(topo.devices[0].name))  # or resolve via ids
```

`parse_topo` tolerates UTF-8, UTF-8 with BOM, UTF-16 and GB18030, because eNSP
writes the file with a system-dependent encoding depending on the locale it was
installed under.
