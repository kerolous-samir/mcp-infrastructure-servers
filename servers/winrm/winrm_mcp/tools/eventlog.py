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


def get_event_logs(
    host: str,
    log_name: str = "System",
    level: Optional[str] = None,
    max_events: int = 50,
    hours_back: int = 24,
) -> list:
    entry_type = f"-EntryType '{_q(level)}'" if level else ""
    r = pool.run_ps(
        host,
        f"\n$since = (Get-Date).AddHours(-{int(hours_back)})\n@(Get-EventLog -LogName '{_q(log_name)}' {entry_type} -Newest {int(max_events)} -After $since -ErrorAction Stop |\n    Select-Object @{{N='Time';     E={{$_.TimeGenerated.ToString('yyyy-MM-dd HH:mm:ss')}}}},\n                  @{{N='Level';    E={{$_.EntryType.ToString()}}}},\n                  Source, EventID,\n                  @{{N='Message';  E={{$_.Message.Substring(0, [Math]::Min(300, $_.Message.Length))}}}}) |\n    ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def query_event_log(
    host: str,
    log_name: str = "System",
    event_id: Optional[int] = None,
    source: Optional[str] = None,
    max_events: int = 100,
) -> list:
    filter_ht = f"LogName='{_q(log_name)}'"
    if event_id:
        filter_ht += f"; Id={int(event_id)}"
    if source:
        filter_ht += f"; ProviderName='{_q(source)}'"
    r = pool.run_ps(
        host,
        f"\n@(Get-WinEvent -FilterHashtable @{{{filter_ht}}} -MaxEvents {int(max_events)} -ErrorAction Stop |\n    Select-Object @{{N='Time';    E={{$_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss')}}}},\n                  @{{N='Level';   E={{$_.LevelDisplayName}}}},\n                  @{{N='Source';  E={{$_.ProviderName}}}},\n                  @{{N='EventID'; E={{$_.Id}}}},\n                  @{{N='Message'; E={{$_.Message.Substring(0, [Math]::Min(500, $_.Message.Length))}}}}) |\n    ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []
