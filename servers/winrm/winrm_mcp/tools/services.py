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


def list_services(host: str, filter_status: Optional[str] = None) -> list:
    where_clause = ""
    if filter_status:
        where_clause = f"| Where-Object Status -eq '{_q(filter_status)}'"
    r = pool.run_ps(
        host,
        f"\n@(Get-Service {where_clause} |\n    Select-Object Name, DisplayName,\n        @{{N='Status';    E={{$_.Status.ToString()}}}},\n        @{{N='StartType'; E={{$_.StartType.ToString()}}}}) |\n    ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def get_service(host: str, service_name: str) -> dict:
    r = pool.run_ps(
        host,
        f"\n$svc = Get-Service -Name '{_q(service_name)}' -ErrorAction Stop\n[PSCustomObject]@{{\n    Name            = $svc.Name\n    DisplayName     = $svc.DisplayName\n    Status          = $svc.Status.ToString()\n    StartType       = $svc.StartType.ToString()\n    CanStop         = $svc.CanStop\n    CanPauseAndContinue = $svc.CanPauseAndContinue\n    DependentServices   = ($svc.DependentServices | Select-Object -ExpandProperty Name)\n    ServicesDependedOn  = ($svc.ServicesDependedOn | Select-Object -ExpandProperty Name)\n}} | ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"])


def manage_service(host: str, service_name: str, action: str) -> dict:
    svc = _q(service_name)
    action_map = {
        "start": f"Start-Service -Name '{svc}' -ErrorAction Stop",
        "stop": f"Stop-Service -Name '{svc}' -Force -ErrorAction Stop",
        "restart": f"Restart-Service -Name '{svc}' -Force -ErrorAction Stop",
        "pause": f"Suspend-Service -Name '{svc}' -ErrorAction Stop",
        "resume": f"Resume-Service -Name '{svc}' -ErrorAction Stop",
        "enable": f"Set-Service -Name '{svc}' -StartupType Automatic -ErrorAction Stop",
        "disable": f"Set-Service -Name '{svc}' -StartupType Disabled -ErrorAction Stop",
    }
    if action not in action_map:
        return {"error": f"Invalid action '{action}'. Valid: {', '.join(action_map.keys())}"}
    r = pool.run_ps(host, action_map[action])
    return {
        "status": "ok" if r["success"] else "error",
        "host": host,
        "service": service_name,
        "action": action,
        "output": (
            r["stderr"] if not r["success"] else f"Service '{service_name}' {action} successful"
        ),
    }
