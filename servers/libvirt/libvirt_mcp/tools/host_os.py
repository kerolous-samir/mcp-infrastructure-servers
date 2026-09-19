import ipaddress
import re
import shlex
import subprocess
import logging
from typing import Optional, Union
from ..core.connection import pool

logger = logging.getLogger(__name__)
_IFNAME_RE = re.compile("^[A-Za-z0-9.@_:-]{1,32}$")
_PKG_RE = re.compile("^[A-Za-z0-9.+@_:-]{1,128}$")
_HOSTNAME_RE = re.compile("^[A-Za-z0-9]([A-Za-z0-9.-]{0,253}[A-Za-z0-9])?$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_local(host: str) -> bool:
    return host in _LOCAL_HOSTS


def _resolve_host(host: str):
    if not isinstance(host, str) or not host.strip():
        raise ValueError("host is required and must be a non-empty string")
    if _is_local(host):
        return None
    pool.get_connection(host)
    cfg = pool._configs.get(host)
    if cfg is None:
        raise ValueError(f"Host '{host}' is not registered")
    return cfg


def _ssh_argv(cfg, remote_argv: list, port_override: Optional[int] = None) -> list:
    ssh_opts = ["-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
    if cfg.ssh_key_path:
        ssh_opts += ["-i", cfg.ssh_key_path]
    port = port_override or cfg.port
    if port and port != 22:
        ssh_opts += ["-p", str(int(port))]
    remote_cmd = " ".join((shlex.quote(str(a)) for a in remote_argv))
    return ["ssh", *ssh_opts, f"{cfg.username}@{cfg.host}", remote_cmd]


def _exec_on_host(host: str, argv: list, timeout: int = 30) -> dict:
    if not isinstance(argv, (list, tuple)) or not argv:
        raise ValueError("argv must be a non-empty list")
    cfg = _resolve_host(host)
    if cfg is None:
        full = list(argv)
    else:
        full = _ssh_argv(cfg, list(argv))
    result = subprocess.run(full, shell=False, capture_output=True, text=True, timeout=timeout)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _sh_on_host(host: str, script: str, timeout: int = 30) -> dict:
    return _exec_on_host(host, ["sh", "-c", script], timeout=timeout)


def _validate_ifname(interface: str) -> None:
    if not isinstance(interface, str) or not _IFNAME_RE.match(interface):
        raise ValueError(f"Invalid interface name {interface!r}")


def _validate_ip(ip: str) -> str:
    try:
        return str(ipaddress.ip_address(str(ip).strip()))
    except ValueError:
        raise ValueError(f"Invalid IP address {ip!r}")


def _validate_hostname(hostname: str) -> None:
    if not isinstance(hostname, str) or not _HOSTNAME_RE.match(hostname):
        raise ValueError(f"Invalid hostname {hostname!r}")


def _validate_pkgs(packages: list) -> list:
    if not isinstance(packages, (list, tuple)) or not packages:
        raise ValueError("packages must be a non-empty list")
    out = []
    for p in packages:
        if not isinstance(p, str) or not _PKG_RE.match(p):
            raise ValueError(f"Invalid package name {p!r}")
        out.append(p)
    return out


def host_shutdown(host: str, delay_seconds: int = 0) -> dict:
    argv = (
        ["shutdown", "-h", f"+{int(delay_seconds) // 60}"]
        if delay_seconds >= 60
        else ["shutdown", "-h", "now"]
    )
    result = _exec_on_host(host, argv)
    return {
        "status": "shutdown_initiated" if result["returncode"] == 0 else "error",
        "host": host,
        "command": " ".join(argv),
        "output": result["stdout"] or result["stderr"],
    }


def host_reboot(host: str, delay_seconds: int = 0) -> dict:
    argv = (
        ["shutdown", "-r", f"+{int(delay_seconds) // 60}"]
        if delay_seconds >= 60
        else ["shutdown", "-r", "now"]
    )
    result = _exec_on_host(host, argv)
    return {
        "status": "reboot_initiated" if result["returncode"] == 0 else "error",
        "host": host,
        "command": " ".join(argv),
        "output": result["stdout"] or result["stderr"],
    }


def run_command(host: str, command: list, timeout: int = 60) -> dict:
    if isinstance(command, str):
        raise ValueError(
            'command must be an argv list (e.g. ["ls", "-la"]), not a shell string — free-form shell execution on a host is not permitted'
        )
    if not isinstance(command, (list, tuple)) or not command:
        raise ValueError("command must be a non-empty argv list")
    argv = [str(c) for c in command]
    result = _exec_on_host(host, argv, timeout=timeout)
    return {
        "host": host,
        "command": argv,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "success": result["returncode"] == 0,
    }


def get_os_info(host: str) -> dict:
    return {
        "host": host,
        "hostname": _exec_on_host(host, ["hostname"])["stdout"],
        "os": _sh_on_host(
            host,
            "lsb_release -d 2>/dev/null | cut -f2 || cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'",
        )["stdout"],
        "kernel": _exec_on_host(host, ["uname", "-r"])["stdout"],
        "arch": _exec_on_host(host, ["uname", "-m"])["stdout"],
        "uptime": _exec_on_host(host, ["uptime", "-p"])["stdout"],
        "load_avg": _sh_on_host(host, "cat /proc/loadavg | awk '{print $1, $2, $3}'")["stdout"],
        "memory": _sh_on_host(
            host, "free -h | awk 'NR==2{printf \"total: %s, used: %s, free: %s\", $2, $3, $4}'"
        )["stdout"],
        "disk": _sh_on_host(
            host,
            "df -h / | awk 'NR==2{printf \"total: %s, used: %s, free: %s, use%%: %s\", $2, $3, $4, $5}'",
        )["stdout"],
        "cpu_cores": _exec_on_host(host, ["nproc"])["stdout"],
    }


def list_host_interfaces(host: str) -> list:
    import json as _json

    raw = _exec_on_host(host, ["ip", "-j", "addr", "show"])
    if raw["returncode"] != 0:
        return [{"error": raw["stderr"]}]
    try:
        data = _json.loads(raw["stdout"])
    except Exception:
        return [{"error": "Failed to parse ip output"}]
    result = []
    for iface in data:
        addrs = []
        for addr in iface.get("addr_info", []):
            addrs.append(f"{addr['local']}/{addr['prefixlen']}")
        result.append(
            {
                "name": iface["ifname"],
                "state": iface.get("operstate", "unknown"),
                "mac": iface.get("address", ""),
                "ips": addrs,
                "mtu": iface.get("mtu", ""),
            }
        )
    return result


def set_host_ip(
    host: str, interface: str, ip_address: str, prefix_length: int = 24, flush_existing: bool = True
) -> dict:
    _validate_ifname(interface)
    ip_clean = _validate_ip(ip_address)
    prefix = int(prefix_length)
    if not 0 <= prefix <= 128:
        raise ValueError(f"Invalid prefix length {prefix_length!r}")
    if flush_existing:
        _exec_on_host(host, ["ip", "addr", "flush", "dev", interface])
    result = _exec_on_host(host, ["ip", "addr", "add", f"{ip_clean}/{prefix}", "dev", interface])
    _exec_on_host(host, ["ip", "link", "set", interface, "up"])
    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "host": host,
        "interface": interface,
        "ip": f"{ip_clean}/{prefix}",
        "output": result["stdout"] or result["stderr"],
    }


def get_host_routes(host: str) -> list:
    import json as _json

    raw = _exec_on_host(host, ["ip", "-j", "route", "show"])
    if raw["returncode"] != 0:
        return [{"error": raw["stderr"]}]
    try:
        return _json.loads(raw["stdout"])
    except Exception:
        return [{"raw": raw["stdout"]}]


def set_default_gateway(host: str, gateway_ip: str, interface: Optional[str] = None) -> dict:
    gw_clean = _validate_ip(gateway_ip)
    if interface:
        _validate_ifname(interface)
    _sh_on_host(host, "ip route del default 2>/dev/null || true")
    argv = ["ip", "route", "add", "default", "via", gw_clean]
    if interface:
        argv += ["dev", interface]
    result = _exec_on_host(host, argv)
    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "host": host,
        "gateway": gw_clean,
        "interface": interface,
        "output": result["stdout"] or result["stderr"],
    }


def list_services(host: str, filter_state: Optional[str] = None) -> list:
    state_filter = ""
    if filter_state == "running":
        state_filter = "--state=running"
    elif filter_state == "stopped":
        state_filter = "--state=inactive"
    elif filter_state == "failed":
        state_filter = "--state=failed"
    raw = _sh_on_host(
        host,
        f"systemctl list-units --type=service {state_filter} --no-pager --no-legend --output=json 2>/dev/null || systemctl list-units --type=service {state_filter} --no-pager --no-legend",
    )
    import json as _json

    try:
        return _json.loads(raw["stdout"])
    except Exception:
        services = []
        for line in raw["stdout"].splitlines():
            parts = line.split()
            if len(parts) >= 4:
                services.append(
                    {
                        "unit": parts[0],
                        "load": parts[1],
                        "active": parts[2],
                        "sub": parts[3],
                        "description": " ".join(parts[4:]),
                    }
                )
        return services


def manage_service(host: str, service: str, action: str) -> dict:
    valid_actions = {"start", "stop", "restart", "enable", "disable", "status"}
    if action not in valid_actions:
        return {"error": f"Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}"}
    if not isinstance(service, str) or not _PKG_RE.match(service):
        return {"error": f"Invalid service name {service!r}"}
    result = _exec_on_host(host, ["systemctl", action, service])
    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "host": host,
        "service": service,
        "action": action,
        "output": result["stdout"] or result["stderr"],
    }


def install_package(host: str, packages: list, update_first: bool = False) -> dict:
    pkgs = _validate_pkgs(packages)
    if update_first:
        _exec_on_host(host, ["apt-get", "update", "-q"], timeout=120)
    result = _exec_on_host(
        host,
        ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", *pkgs],
        timeout=300,
    )
    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "host": host,
        "packages": packages,
        "output": result["stdout"][-3000:] if len(result["stdout"]) > 3000 else result["stdout"],
        "stderr": result["stderr"][-1000:] if len(result["stderr"]) > 1000 else result["stderr"],
    }


def remove_package(host: str, packages: list, purge: bool = False) -> dict:
    pkgs = _validate_pkgs(packages)
    cmd_action = "purge" if purge else "remove"
    result = _exec_on_host(
        host,
        ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", cmd_action, "-y", *pkgs],
        timeout=120,
    )
    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "host": host,
        "packages": packages,
        "purge": purge,
        "output": result["stdout"],
        "stderr": result["stderr"],
    }


def get_host_processes(host: str, sort_by: str = "cpu", limit: int = 20) -> list:
    sort_key = "%cpu" if sort_by == "cpu" else "%mem"
    limit_i = int(limit)
    raw = _sh_on_host(
        host,
        f"""ps aux --sort=-{sort_key} | head -n {limit_i + 1} | awk 'NR>1 {{printf "%s %s %s %s %s\\n", $2, $1, $3, $4, $11}}'""",
    )
    processes = []
    for line in raw["stdout"].splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4:
            processes.append(
                {
                    "pid": parts[0],
                    "user": parts[1],
                    "cpu_pct": parts[2],
                    "mem_pct": parts[3],
                    "command": parts[4] if len(parts) > 4 else "",
                }
            )
    return processes


def set_hostname(host: str, new_hostname: str) -> dict:
    _validate_hostname(new_hostname)
    result = _exec_on_host(host, ["hostnamectl", "set-hostname", new_hostname])
    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "host": host,
        "hostname": new_hostname,
        "output": result["stdout"] or result["stderr"],
    }
