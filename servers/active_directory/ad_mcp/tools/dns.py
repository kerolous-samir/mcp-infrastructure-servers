import json, logging
from typing import Optional
from ..core.connection import winrm_pool as pool

logger = logging.getLogger(__name__)
DNS_RECORD_TYPES = frozenset(["A", "AAAA", "CNAME", "PTR", "MX", "TXT", "NS", "SRV"])
_PS_SQUOTES = "'‘’‚‛"


def _q(s) -> str:
    s = str(s)
    for ch in _PS_SQUOTES:
        s = s.replace(ch, ch * 2)
    return s


def list_dns_zones(host: str) -> list:
    r = pool.run_ps(
        host,
        "\n@(Get-DnsServerZone |\n    Select-Object ZoneName, ZoneType, IsAutoCreated, IsDsIntegrated, IsReverseLookupZone, ZoneFile) |\n    ConvertTo-Json",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def list_dns_records(host: str, zone_name: str, record_type: Optional[str] = None) -> list:
    type_filter = f"| Where-Object RecordType -eq '{_q(record_type)}'" if record_type else ""
    r = pool.run_ps(
        host,
        f"\n@(Get-DnsServerResourceRecord -ZoneName '{_q(zone_name)}' {type_filter} |\n    Select-Object HostName, RecordType,\n        @{{N='TTL_s'; E={{[int]$_.TimeToLive.TotalSeconds}}}},\n        @{{N='RecordData'; E={{\n            if ($_.RecordData.IPv4Address) {{ $_.RecordData.IPv4Address.ToString() }}\n            elseif ($_.RecordData.IPv6Address) {{ $_.RecordData.IPv6Address.ToString() }}\n            elseif ($_.RecordData.NameHost) {{ $_.RecordData.NameHost }}\n            elseif ($_.RecordData.DomainName) {{ $_.RecordData.DomainName }}\n            else {{ '' }}\n        }}}}) |\n    ConvertTo-Json",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def add_dns_record(
    host: str, zone_name: str, name: str, record_type: str, value: str, ttl: int = 3600
) -> dict:
    try:
        ttl_i = int(ttl)
    except (TypeError, ValueError):
        return {"error": f"Invalid ttl: {ttl!r} (must be an integer)"}
    z, n, v = (_q(zone_name), _q(name), _q(value))
    if record_type.upper() == "A":
        cmd = f"Add-DnsServerResourceRecordA -ZoneName '{z}' -Name '{n}' -IPv4Address '{v}' -TimeToLive (New-TimeSpan -Seconds {ttl_i})"
    elif record_type.upper() == "AAAA":
        cmd = f"Add-DnsServerResourceRecordAAAA -ZoneName '{z}' -Name '{n}' -IPv6Address '{v}' -TimeToLive (New-TimeSpan -Seconds {ttl_i})"
    elif record_type.upper() == "CNAME":
        cmd = f"Add-DnsServerResourceRecordCName -ZoneName '{z}' -Name '{n}' -HostNameAlias '{v}' -TimeToLive (New-TimeSpan -Seconds {ttl_i})"
    elif record_type.upper() == "PTR":
        cmd = f"Add-DnsServerResourceRecordPtr -ZoneName '{z}' -Name '{n}' -PtrDomainName '{v}' -TimeToLive (New-TimeSpan -Seconds {ttl_i})"
    elif record_type.upper() == "TXT":
        cmd = f"Add-DnsServerResourceRecord -Txt -ZoneName '{z}' -Name '{n}' -DescriptiveText '{v}' -TimeToLive (New-TimeSpan -Seconds {ttl_i})"
    elif record_type.upper() == "NS":
        cmd = f"Add-DnsServerResourceRecord -NS -ZoneName '{z}' -Name '{n}' -NameServer '{v}' -TimeToLive (New-TimeSpan -Seconds {ttl_i})"
    else:
        return {
            "error": f"Unsupported record type: {record_type}. Supported: A, AAAA, CNAME, PTR, TXT, NS (MX/SRV require multiple fields — not supported here)"
        }
    r = pool.run_ps(host, cmd + "\nWrite-Output 'DNS record added'")
    return {
        "status": "ok" if r["success"] else "error",
        "zone": zone_name,
        "name": name,
        "type": record_type,
        "value": value,
        "output": r["stdout"] if r["success"] else r["stderr"],
    }


def update_dns_record(
    host: str, zone_name: str, name: str, record_type: str, new_value: str, ttl: int = 3600
) -> dict:
    delete_result = delete_dns_record(host, zone_name, name, record_type)
    if delete_result["status"] != "ok":
        return {
            "status": "error",
            "zone": zone_name,
            "name": name,
            "type": record_type,
            "output": f"Delete step failed: {delete_result['output']}",
        }
    return add_dns_record(host, zone_name, name, record_type, new_value, ttl)


def delete_dns_record(host: str, zone_name: str, name: str, record_type: str) -> dict:
    r = pool.run_ps(
        host,
        f"\nRemove-DnsServerResourceRecord -ZoneName '{_q(zone_name)}' -Name '{_q(name)}' -RRType '{_q(record_type)}' -Force -ErrorAction Stop\nWrite-Output 'DNS record deleted'\n",
    )
    return {
        "status": "ok" if r["success"] else "error",
        "zone": zone_name,
        "name": name,
        "type": record_type,
        "output": r["stdout"] if r["success"] else r["stderr"],
    }
