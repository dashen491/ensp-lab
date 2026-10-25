# Notice

## What this project is

`ensp-lab` is an independent, unofficial tool. It is not affiliated with,
endorsed by, sponsored by, or supported by Huawei Technologies Co., Ltd. or the
maintainers of eNSP.

It talks to the TCP console ports that eNSP exposes on `127.0.0.1` for devices
the user has already started. Those ports are the same ones the eNSP GUI's own
terminal window uses, and the commands sent over them are ordinary VRP
commands that the user could type by hand.

## What this project does not contain or do

- **No Huawei software, firmware, images, or binaries.** The repository ships
  no part of eNSP, VRP, VirtualBox, or any device image. You must install and
  license those yourself.
- **No license circumvention.** It does not patch, crack, emulate, or bypass
  licensing, activation, or entitlement checks in any Huawei product.
- **No vendor files.** Reference material under `references/` is original
  writing based on observing the tool's own documented behaviour and the
  contents of a user's own `.topo` files. It does not reproduce files shipped
  inside the eNSP installer.
- **No network access to Huawei.** Everything runs against `127.0.0.1`. The
  tool never contacts Huawei servers, and never performs update, activation, or
  telemetry calls.
- **No credentials.** The example configurations contain no passwords,
  community strings, or keys. Console username/password are optional CLI flags
  that the user supplies for their own lab.

## Trademarks

Huawei, eNSP, VRP, and AR/S-series model names are trademarks or registered
trademarks of Huawei Technologies Co., Ltd. VirtualBox is a trademark of Oracle
and/or its affiliates. All other trademarks are the property of their respective
owners. These names are used here only to describe what the software
interoperates with, in a nominative and descriptive sense.

## Intended use

For your own lab and learning use, against devices you built and started
yourself in your own copy of eNSP. You are responsible for complying with the
licence terms of eNSP and any Huawei software you have installed, and with your
employer's or institution's policies.

## Licensing of this repository

The code and documentation in this repository are released under the MIT
License; see [LICENSE](LICENSE).
