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


def list_processes(host: str, sort_by: str = "cpu", limit: int = 30) -> list:
    sort_prop = "CPU" if sort_by == "cpu" else "WorkingSet"
    r = pool.run_ps(
        host,
        f"\n$procs = Get-Process | Sort-Object -Property {sort_prop} -Descending | Select-Object -First {int(limit)} |\n    Select-Object Id, ProcessName,\n        @{{N='CPU_s';     E={{[math]::Round($_.CPU, 2)}}}},\n        @{{N='RAM_MB';    E={{[math]::Round($_.WorkingSet / 1MB, 2)}}}},\n        @{{N='Threads';   E={{$_.Threads.Count}}}},\n        @{{N='StartTime'; E={{if($_.StartTime){{$_.StartTime.ToString('HH:mm:ss')}}else{{'-'}}}}}}\n@($procs) | ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def kill_process(host: str, pid: Optional[int] = None, name: Optional[str] = None) -> dict:
    if pid is None and name is None:
        return {"error": "Provide at least one of: pid, name"}
    if pid is not None:
        cmd = f"Stop-Process -Id {int(pid)} -Force -ErrorAction Stop"
        target = f"PID {pid}"
    else:
        cmd = f"Stop-Process -Name '{_q(name)}' -Force -ErrorAction Stop"
        target = f"name '{name}'"
    r = pool.run_ps(host, cmd)
    return {
        "status": "ok" if r["success"] else "error",
        "host": host,
        "killed": target,
        "output": r["stderr"] if not r["success"] else f"Process {target} killed",
    }
