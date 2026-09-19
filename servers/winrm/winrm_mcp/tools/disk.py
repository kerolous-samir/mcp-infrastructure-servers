import json
import logging
from typing import Optional
from ..core.connection import pool

logger = logging.getLogger(__name__)
_PS_SQUOTES = "'‘’‚‛"


def _q(s) -> str:
    s = str(s)
    for ch in _PS_SQUOTES:
        s = s.replace(ch, ch * 2)
    return s


def get_disk_info(host: str) -> list:
    r = pool.run_ps(
        host,
        "\n@(Get-PhysicalDisk |\n    Select-Object FriendlyName,\n        @{N='Size_GB'; E={[math]::Round($_.Size / 1GB, 2)}},\n        MediaType, BusType, OperationalStatus, HealthStatus) |\n    ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def list_volumes(host: str) -> list:
    r = pool.run_ps(
        host,
        "\n@(Get-Volume | Where-Object {$_.DriveLetter} |\n    Select-Object DriveLetter, FileSystemLabel, FileSystem, HealthStatus,\n        @{N='Size_GB';     E={[math]::Round($_.Size / 1GB, 2)}},\n        @{N='Free_GB';     E={[math]::Round($_.SizeRemaining / 1GB, 2)}},\n        @{N='Used_GB';     E={[math]::Round(($_.Size - $_.SizeRemaining) / 1GB, 2)}},\n        @{N='Used_Pct';    E={if($_.Size -gt 0){[math]::Round((($_.Size - $_.SizeRemaining) / $_.Size) * 100, 1)}else{0}}}) |\n    ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def get_drive_usage(host: str, drive_letter: Optional[str] = None) -> list:
    filter_clause = (
        f"| Where-Object {{$_.DeviceID -eq '{_q(drive_letter)}:'}}" if drive_letter else ""
    )
    r = pool.run_ps(
        host,
        f"\n@(Get-PSDrive -PSProvider FileSystem {filter_clause} |\n    Select-Object Name,\n        @{{N='Used_GB'; E={{[math]::Round($_.Used / 1GB, 2)}}}},\n        @{{N='Free_GB'; E={{[math]::Round($_.Free / 1GB, 2)}}}},\n        @{{N='Total_GB'; E={{[math]::Round(($_.Used + $_.Free) / 1GB, 2)}}}},\n        @{{N='Used_Pct'; E={{if(($_.Used + $_.Free) -gt 0){{[math]::Round($_.Used / ($_.Used + $_.Free) * 100, 1)}}else{{0}}}}}}) |\n    ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []
