import json, logging
from ..core.connection import winrm_pool as pool

logger = logging.getLogger(__name__)
_DHCP_IMPORT = "Import-Module DhcpServer -ErrorAction SilentlyContinue\n"
_PS_SQUOTES = "'‘’‚‛"


def _q(s) -> str:
    s = str(s)
    for ch in _PS_SQUOTES:
        s = s.replace(ch, ch * 2)
    return s


def list_dhcp_scopes(host: str) -> list:
    r = pool.run_ps(
        host,
        _DHCP_IMPORT
        + "\n@(Get-DhcpServerv4Scope |\n    Select-Object ScopeId, Name, SubnetMask, StartRange, EndRange, State, LeaseDuration) |\n    ConvertTo-Json",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def get_dhcp_scope(host: str, scope_id: str) -> dict:
    sid = _q(scope_id)
    r = pool.run_ps(
        host,
        _DHCP_IMPORT
        + f"\n$s = Get-DhcpServerv4Scope -ScopeId '{sid}'\n[PSCustomObject]@{{\n    ScopeId       = $s.ScopeId.ToString()\n    Name          = $s.Name\n    SubnetMask    = $s.SubnetMask.ToString()\n    StartRange    = $s.StartRange.ToString()\n    EndRange      = $s.EndRange.ToString()\n    State         = $s.State.ToString()\n    LeaseDuration = $s.LeaseDuration.ToString()\n    TotalAddresses = (Get-DhcpServerv4ScopeStatistics -ScopeId '{sid}').TotalAddresses\n    InUse          = (Get-DhcpServerv4ScopeStatistics -ScopeId '{sid}').InUse\n    Available      = (Get-DhcpServerv4ScopeStatistics -ScopeId '{sid}').Available\n}} | ConvertTo-Json",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"])


def add_dhcp_scope(
    host: str,
    scope_id: str,
    name: str,
    start_range: str,
    end_range: str,
    subnet_mask: str = "255.255.255.0",
    description: str = "",
    lease_duration: str = "8.00:00:00",
) -> dict:
    r = pool.run_ps(
        host,
        _DHCP_IMPORT
        + f"\n$ErrorActionPreference = 'Stop'\nAdd-DhcpServerv4Scope -ScopeId '{_q(scope_id)}' -Name '{_q(name)}' `\n    -StartRange '{_q(start_range)}' -EndRange '{_q(end_range)}' `\n    -SubnetMask '{_q(subnet_mask)}' -Description '{_q(description)}' `\n    -LeaseDuration '{_q(lease_duration)}'\nWrite-Output 'Scope {_q(scope_id)} added'\n",
    )
    return {
        "status": "ok" if r["success"] else "error",
        "scope_id": scope_id,
        "name": name,
        "start_range": start_range,
        "end_range": end_range,
        "output": r["stdout"] if r["success"] else r["stderr"],
    }


def remove_dhcp_scope(host: str, scope_id: str, force: bool = True) -> dict:
    force_flag = "-Force" if force else ""
    r = pool.run_ps(
        host,
        _DHCP_IMPORT
        + f"\n$ErrorActionPreference = 'Stop'\nRemove-DhcpServerv4Scope -ScopeId '{_q(scope_id)}' {force_flag}\nWrite-Output 'Scope {_q(scope_id)} removed'\n",
    )
    return {
        "status": "ok" if r["success"] else "error",
        "scope_id": scope_id,
        "output": r["stdout"] if r["success"] else r["stderr"],
    }


def list_dhcp_leases(host: str, scope_id: str) -> list:
    r = pool.run_ps(
        host,
        _DHCP_IMPORT
        + f"\n@(Get-DhcpServerv4Lease -ScopeId '{_q(scope_id)}' |\n    Select-Object IPAddress, ClientId, HostName, AddressState,\n        @{{N='LeaseExpiry'; E={{if($_.LeaseExpiryTime){{$_.LeaseExpiryTime.ToString('yyyy-MM-dd HH:mm')}}else{{'-'}}}}}}) |\n    ConvertTo-Json",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def add_dhcp_reservation(
    host: str, scope_id: str, ip_address: str, mac_address: str, name: str, description: str = ""
) -> dict:
    r = pool.run_ps(
        host,
        _DHCP_IMPORT
        + f"\n$ErrorActionPreference = 'Stop'\nAdd-DhcpServerv4Reservation -ScopeId '{_q(scope_id)}' -IPAddress '{_q(ip_address)}' `\n    -ClientId '{_q(mac_address)}' -Name '{_q(name)}' -Description '{_q(description)}'\nWrite-Output 'Reservation added: {_q(ip_address)} -> {_q(mac_address)}'\n",
    )
    return {
        "status": "ok" if r["success"] else "error",
        "scope_id": scope_id,
        "ip": ip_address,
        "mac": mac_address,
        "name": name,
        "output": r["stdout"] if r["success"] else r["stderr"],
    }


def delete_dhcp_reservation(host: str, scope_id: str, ip_address: str) -> dict:
    r = pool.run_ps(
        host,
        _DHCP_IMPORT
        + f"\n$ErrorActionPreference = 'Stop'\nRemove-DhcpServerv4Reservation -ScopeId '{_q(scope_id)}' -IPAddress '{_q(ip_address)}'\nWrite-Output 'Reservation {_q(ip_address)} deleted'\n",
    )
    return {
        "status": "ok" if r["success"] else "error",
        "scope_id": scope_id,
        "ip": ip_address,
        "output": r["stdout"] if r["success"] else r["stderr"],
    }
