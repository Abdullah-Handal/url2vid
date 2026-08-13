"""Tests for the desktop shell.

These cover the ways a *packaged* build differs from a source run, which is
where the failures that reach users actually live.
"""

from __future__ import annotations

import json
import sys
import urllib.request

import desktop


class TestWindowlessStartup:
    def test_server_starts_with_no_console_attached(self, monkeypatch):
        """A windowed build has sys.stdout and sys.stderr set to None.

        uvicorn's default logging config declares handlers pointing at
        ext://sys.stderr, so configuring it against None raised "Unable to
        configure formatter 'default'" and the app died before opening its
        window. Piping output -- which the build's smoke test did -- hands the
        process a real stream and hides this completely, so it has to be
        asserted directly.
        """
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)

        sock, port = desktop._reserve_port()
        server = desktop._Server(sock)
        try:
            assert server.start() is True
            body = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=15)
            assert json.load(body)["max_concurrent"] >= 1
        finally:
            server.stop()


class TestPortSelection:
    def test_zero_asks_the_os_for_a_free_port(self):
        sock, port = desktop._reserve_port(0)
        try:
            assert port > 0
        finally:
            sock.close()

    def test_two_instances_do_not_collide(self):
        first_sock, first = desktop._reserve_port()
        second_sock, second = desktop._reserve_port()
        try:
            assert first != second
        finally:
            first_sock.close()
            second_sock.close()
