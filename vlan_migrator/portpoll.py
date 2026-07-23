"""Background connectivity poller (description.md section 2: Background Port Polling).

Continuously TCP-probes port 2121 on the configured CVM/host targets while a
migration runs, logging connectivity for observability/debugging.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from typing import List

log = logging.getLogger("vlan_migrator.portpoll")


class PortPoller:
    def __init__(self, targets: List[str], port: int = 2121, interval: int = 5):
        self.targets = list(targets)
        self.port = port
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples = 0
        self.failures = 0

    def _probe(self, host: str) -> bool:
        try:
            with socket.create_connection((host, self.port), timeout=self.interval):
                return True
        except OSError:
            return False

    def _run(self) -> None:
        while not self._stop.is_set():
            for host in self.targets:
                ok = self._probe(host)
                self.samples += 1
                if ok:
                    log.debug("port %s on %s: reachable", self.port, host)
                else:
                    self.failures += 1
                    log.warning("port %s on %s: UNREACHABLE", self.port, host)
            self._stop.wait(self.interval)

    def __enter__(self) -> "PortPoller":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        if not self.targets:
            log.info("port polling: no targets configured, skipping")
            return
        log.info(
            "port polling started: targets=%s port=%s interval=%ss",
            self.targets, self.port, self.interval,
        )
        self._thread = threading.Thread(target=self._run, name="port-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 1)
            log.info(
                "port polling stopped: %d samples, %d failures",
                self.samples, self.failures,
            )
