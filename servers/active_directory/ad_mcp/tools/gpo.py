import json, logging
from ..core.connection import winrm_pool as pool

logger = logging.getLogger(__name__)
_PS_SQUOTES = "'‘’‚‛"


def _q(s) -> str:
    s = str(s)
    for ch in _PS_SQUOTES:
        s = s.replace(ch, ch * 2)
    return s


def list_gpos(host: str) -> list:
    r = pool.run_ps(
        host,
        "\n@(Get-GPO -All |\n    Select-Object DisplayName, Id,\n        @{N='GpoStatus'; E={$_.GpoStatus.ToString()}},\n        Description,\n        @{N='Created';  E={$_.CreationTime.ToString('yyyy-MM-dd')}},\n        @{N='Modified'; E={$_.ModificationTime.ToString('yyyy-MM-dd')}}) |\n    ConvertTo-Json",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def get_gpo(host: str, gpo_name: str) -> dict:
    r = pool.run_ps(
        host,
        f"\n$g = Get-GPO -Name '{_q(gpo_name)}'\n[PSCustomObject]@{{\n    Name         = $g.DisplayName\n    Id           = $g.Id.ToString()\n    Status       = $g.GpoStatus.ToString()\n    Description  = $g.Description\n    Created      = $g.CreationTime.ToString('yyyy-MM-dd')\n    Modified     = $g.ModificationTime.ToString('yyyy-MM-dd HH:mm')\n    ComputerEnabled = $g.Computer.Enabled\n    UserEnabled     = $g.User.Enabled\n}} | ConvertTo-Json",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"])


def create_gpo(host: str, gpo_name: str, comment: str = "") -> dict:
    r = pool.run_ps(
        host,
        f"\nNew-GPO -Name '{_q(gpo_name)}' -Comment '{_q(comment)}' -ErrorAction Stop |\n    Select-Object DisplayName, Id | ConvertTo-Json",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return {"status": "ok", "gpo": gpo_name, **json.loads(r["stdout"])}


def delete_gpo(host: str, gpo_name: str) -> dict:
    r = pool.run_ps(host, f"Remove-GPO -Name '{_q(gpo_name)}' -Confirm:$false -ErrorAction Stop")
    return {
        "status": "ok" if r["success"] else "error",
        "gpo": gpo_name,
        "output": r["stderr"] if not r["success"] else f"GPO '{gpo_name}' deleted",
    }


def link_gpo(host: str, gpo_name: str, target_ou: str, enabled: bool = True) -> dict:
    r = pool.run_ps(
        host,
        f"""\nNew-GPLink -Name '{_q(gpo_name)}' -Target '{_q(target_ou)}' `\n    -LinkEnabled {('Yes' if enabled else 'No')} -ErrorAction Stop\nWrite-Output "GPO linked"\n""",
    )
    return {
        "status": "ok" if r["success"] else "error",
        "gpo": gpo_name,
        "target_ou": target_ou,
        "output": r["stdout"] if r["success"] else r["stderr"],
    }


def unlink_gpo(host: str, gpo_name: str, target_ou: str) -> dict:
    r = pool.run_ps(
        host, f"Remove-GPLink -Name '{_q(gpo_name)}' -Target '{_q(target_ou)}' -ErrorAction Stop"
    )
    return {
        "status": "ok" if r["success"] else "error",
        "gpo": gpo_name,
        "target_ou": target_ou,
        "output": r["stderr"] if not r["success"] else f"GPO unlinked from {target_ou}",
    }


def restore_gpo(
    host: str, gpo_name: str, backup_path: str = "C:\\GPOBackups", backup_id: str = ""
) -> dict:
    if backup_id:
        cmd = f"Restore-GPO -Name '{_q(gpo_name)}' -Path '{_q(backup_path)}' -BackupId '{_q(backup_id)}' -ErrorAction Stop"
    else:
        cmd = f"Restore-GPO -Name '{_q(gpo_name)}' -Path '{_q(backup_path)}' -ErrorAction Stop"
    r = pool.run_ps(host, cmd + "\nWrite-Output 'GPO restored'")
    return {
        "status": "ok" if r["success"] else "error",
        "gpo": gpo_name,
        "backup_path": backup_path,
        "backup_id": backup_id or "latest",
        "output": r["stdout"] if r["success"] else r["stderr"],
    }


def backup_gpo(host: str, gpo_name: str, backup_path: str = "C:\\GPOBackups") -> dict:
    r = pool.run_ps(
        host,
        f"\nNew-Item -ItemType Directory -Path '{_q(backup_path)}' -Force | Out-Null\n$b = Backup-GPO -Name '{_q(gpo_name)}' -Path '{_q(backup_path)}'\n[PSCustomObject]@{{\n    GpoName  = $b.DisplayName\n    BackupId = $b.Id.ToString()\n    Path     = '{_q(backup_path)}'\n    Time     = $b.CreationTime.ToString('yyyy-MM-dd HH:mm:ss')\n}} | ConvertTo-Json",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return {"status": "ok", **json.loads(r["stdout"])}
