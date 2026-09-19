import ipaddress
import json
import logging
from ..core.connection import pool

logger = logging.getLogger(__name__)
_PS_SQUOTES = "'‘’‚‛"


def _q(s) -> str:
    s = str(s)
    for ch in _PS_SQUOTES:
        s = s.replace(ch, ch * 2)
    return s


def get_network_adapters(host: str) -> list:
    r = pool.run_ps(
        host,
        "\n@(Get-NetAdapter | ForEach-Object {\n    $adapter = $_\n    $ips = @(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -ErrorAction SilentlyContinue |\n           Select-Object IPAddress, PrefixLength, AddressFamily)\n    [PSCustomObject]@{\n        Name        = $adapter.Name\n        Description = $adapter.InterfaceDescription\n        Status      = $adapter.Status\n        MacAddress  = $adapter.MacAddress\n        LinkSpeed   = $adapter.LinkSpeed\n        IPs         = $ips\n    }\n}) | ConvertTo-Json -Depth 4\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def get_network_config(host: str) -> list:
    r = pool.run_ps(
        host,
        "\n@(Get-NetIPConfiguration | ForEach-Object {\n    [PSCustomObject]@{\n        Interface = $_.InterfaceAlias\n        IPv4      = ($_.IPv4Address | Select-Object -ExpandProperty IPAddress -ErrorAction SilentlyContinue)\n        IPv6      = ($_.IPv6Address | Select-Object -ExpandProperty IPAddress -ErrorAction SilentlyContinue)\n        Gateway   = ($_.IPv4DefaultGateway | Select-Object -ExpandProperty NextHop -ErrorAction SilentlyContinue)\n        DNS       = ($_.DNSServer | Select-Object -ExpandProperty ServerAddresses -ErrorAction SilentlyContinue)\n    }\n}) | ConvertTo-Json -Depth 3\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def get_routes(host: str) -> list:
    r = pool.run_ps(
        host,
        "\n@(Get-NetRoute |\n    Select-Object DestinationPrefix, NextHop, InterfaceAlias, RouteMetric, Protocol) |\n    ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def set_dns(host: str, adapter_name: str, dns_servers: list) -> dict:
    validated = []
    for s in dns_servers:
        try:
            validated.append(str(ipaddress.ip_address(str(s).strip())))
        except ValueError:
            raise ValueError(f"Invalid DNS server address: {s!r} (must be an IPv4/IPv6 address)")
    servers_str = ",".join((f'"{ip}"' for ip in validated))
    r = pool.run_ps(
        host,
        f"\nSet-DnsClientServerAddress -InterfaceAlias '{_q(adapter_name)}' -ServerAddresses ({servers_str})\n",
    )
    return {
        "status": "ok" if r["success"] else "error",
        "host": host,
        "adapter": adapter_name,
        "dns_servers": dns_servers,
        "output": r["stderr"] if not r["success"] else "DNS updated successfully",
    }
