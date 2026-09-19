from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import select
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVERS = ROOT / "servers"
READ_TIMEOUT = 60.0
EXIT_TIMEOUT = 20.0

LAYOUT = {
    "libvirt": ("libvirt", None, "server.py"),
    "active_directory": ("active_directory", "ad_mcp.server", None),
    "winrm": ("winrm_server", "winrm_mcp.server", None),
    "sql": ("sql", "sql_mcp.server", None),
    "bash": ("bash", "bash_mcp.server", None),
}

EXPECTED_TOOLS = {
    "libvirt": 52,
    "active_directory": 50,
    "winrm": 34,
    "sql": 36,
    "bash": 37,
}

REQUIRED_MODULES = {
    "libvirt": ("mcp", "libvirt"),
    "active_directory": ("mcp", "ldap3", "winrm"),
    "winrm": ("mcp", "winrm"),
    "sql": ("mcp", "psycopg2"),
    "bash": ("mcp",),
}


def missing_modules(name: str) -> list[str]:
    out = []
    for module in REQUIRED_MODULES[name]:
        try:
            if importlib.util.find_spec(module) is None:
                out.append(module)
        except (ImportError, ValueError):
            out.append(module)
    return out


class Server:
    def __init__(self, name: str, extra_env: dict | None = None):
        folder, module, script = LAYOUT[name]
        self.name = name
        self.cwd = SERVERS / folder
        argv = [sys.executable] + (["-m", module] if module else [str(self.cwd / script)])
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.cwd)
        env.pop("VIRTUAL_ENV", None)
        if extra_env:
            env.update(extra_env)
        self.proc = subprocess.Popen(
            argv, cwd=str(self.cwd), env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        self._next_id = 0
        self._closed = False

    def _send(self, payload: dict) -> None:
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def _read_message(self) -> dict:
        deadline = time.monotonic() + READ_TIMEOUT
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.proc.stdout], [], [], 0.25)
            if ready:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError(f"{self.name}: stdout closed unexpectedly")
                line = line.strip()
                if line.startswith("{"):
                    return json.loads(line)
                continue
            if self.proc.poll() is not None:
                raise RuntimeError(f"{self.name}: exited early rc={self.proc.returncode}")
        raise TimeoutError(f"{self.name}: no response within {READ_TIMEOUT}s")

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        want = self._next_id
        self._send({"jsonrpc": "2.0", "id": want, "method": method, "params": params or {}})
        while True:
            message = self._read_message()
            if message.get("id") == want:
                return message

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> dict:
        reply = self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        )
        self.notify("notifications/initialized")
        return reply

    def tools(self) -> list[dict]:
        reply = self.request("tools/list")
        assert "error" not in reply, f"{self.name}: tools/list returned {reply.get('error')}"
        return reply["result"]["tools"]

    def call(self, tool: str, arguments: dict) -> dict:
        return self.request("tools/call", {"name": tool, "arguments": arguments})

    def shutdown(self) -> int:
        if self._closed:
            return self.proc.returncode
        self._closed = True
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            code = self.proc.wait(timeout=EXIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            code = self.proc.wait(timeout=EXIT_TIMEOUT)
        for stream in (self.proc.stdout, self.proc.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        return code


@pytest.fixture
def start():
    started: list[Server] = []

    def _start(name: str, extra_env: dict | None = None) -> Server:
        absent = missing_modules(name)
        if absent:
            pytest.skip(
                f"{name}: python module(s) {', '.join(absent)} not installed, so the "
                "server process cannot start and its protocol surface is unreachable"
            )
        server = Server(name, extra_env)
        started.append(server)
        server.initialize()
        return server

    yield _start
    for server in started:
        server.shutdown()


def check_schema(tool: dict) -> None:
    assert "inputSchema" in tool, f"{tool.get('name')}: no inputSchema"
    schema = tool["inputSchema"]
    assert isinstance(schema, dict), f"{tool['name']}: inputSchema is not an object"
    assert schema.get("type") == "object", f"{tool['name']}: inputSchema type is not object"
    assert isinstance(schema.get("properties", {}), dict), f"{tool['name']}: bad properties"
