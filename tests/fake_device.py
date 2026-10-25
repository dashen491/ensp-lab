"""Run a fake VRP device on a fixed port for manual end-to-end testing.

    python tests/fake_device.py 2000 R1

Then, in another shell, address it by port (no topology file needed):

    python scripts/ensp.py exec 2000 "display version"
    python scripts/ensp.py config 2000 examples/configs/ospf_single_area/R1.cfg
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_ensp import FakeVRP


class FixedPortVRP(FakeVRP):
    def __init__(self, hostname: str, port: int):
        super().__init__(hostname)
        self.sock.close()
        import socket

        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.listen(1)
        self.port = port


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    name = sys.argv[2] if len(sys.argv) > 2 else "R1"
    with FixedPortVRP(name, port) as fake:
        print(f"fake {name} listening on 127.0.0.1:{port}", flush=True)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
