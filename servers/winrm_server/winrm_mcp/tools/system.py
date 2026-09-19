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


def get_system_info(host: str) -> dict:
    r = pool.run_ps(
        host,
        "\n$os  = Get-CimInstance Win32_OperatingSystem\n$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1\n$cs  = Get-CimInstance Win32_ComputerSystem\n[PSCustomObject]@{\n    Hostname        = $env:COMPUTERNAME\n    Domain          = $cs.Domain\n    OS              = $os.Caption\n    OSVersion       = $os.Version\n    OSBuild         = $os.BuildNumber\n    Architecture    = $os.OSArchitecture\n    InstallDate     = $os.InstallDate.ToString('yyyy-MM-dd')\n    LastBoot        = $os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm:ss')\n    Uptime          = ((Get-Date) - $os.LastBootUpTime).ToString('dd\\.hh\\:mm\\:ss')\n    TotalRAM_GB     = [math]::Round($cs.TotalPhysicalMemory / 1GB, 2)\n    FreeRAM_GB      = [math]::Round($os.FreePhysicalMemory / 1MB, 2)\n    CPU             = $cpu.Name\n    CPUCores        = $cpu.NumberOfCores\n    CPULogical      = $cpu.NumberOfLogicalProcessors\n    PSVersion       = $PSVersionTable.PSVersion.ToString()\n} | ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    try:
        return json.loads(r["stdout"])
    except json.JSONDecodeError:
        return {"raw_output": r["stdout"]}


def get_os_info(host: str) -> dict:
    r = pool.run_ps(
        host,
        "\n$os = Get-CimInstance Win32_OperatingSystem\n[PSCustomObject]@{\n    OS       = $os.Caption\n    Version  = $os.Version\n    Build    = $os.BuildNumber\n    SP       = $os.ServicePackMajorVersion\n    Arch     = $os.OSArchitecture\n    LastBoot = $os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm:ss')\n    Uptime   = ((Get-Date) - $os.LastBootUpTime).ToString('dd\\.hh\\:mm\\:ss')\n} | ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    try:
        return json.loads(r["stdout"])
    except json.JSONDecodeError:
        return {"raw_output": r["stdout"]}


def set_hostname(host: str, new_hostname: str) -> dict:
    safe_hostname = _q(new_hostname)
    r = pool.run_ps(
        host,
        f"\n$old = $env:COMPUTERNAME\nRename-Computer -NewName '{safe_hostname}' -Force\n[PSCustomObject]@{{\n    OldName = $old\n    NewName = '{safe_hostname}'\n    RebootRequired = $true\n}} | ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    try:
        return {
            **json.loads(r["stdout"]),
            "note": "Reboot required for hostname change to take effect",
        }
    except json.JSONDecodeError:
        return {
            "raw_output": r["stdout"],
            "note": "Reboot required for hostname change to take effect",
        }


def reboot(host: str, delay_seconds: int = 0) -> dict:
    r = pool.run_ps(host, f"Restart-Computer -Force -Delay {int(delay_seconds)}")
    return {"status": "reboot_initiated", "host": host, "delay_seconds": delay_seconds}


def shutdown(host: str, delay_seconds: int = 0) -> dict:
    r = pool.run_ps(host, f"Stop-Computer -Force")
    return {"status": "shutdown_initiated", "host": host, "delay_seconds": delay_seconds}
