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


def list_users(host: str) -> list:
    r = pool.run_ps(
        host,
        "\n@(Get-LocalUser | Select-Object Name, Enabled,\n    @{N='LastLogon';       E={if($_.LastLogon)      {$_.LastLogon.ToString('yyyy-MM-dd HH:mm:ss')}      else{$null}}},\n    PasswordRequired,\n    @{N='PasswordLastSet'; E={if($_.PasswordLastSet){$_.PasswordLastSet.ToString('yyyy-MM-dd HH:mm:ss')}else{$null}}},\n    PasswordNeverExpires, Description) |\n    ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def list_local_groups(host: str) -> list:
    r = pool.run_ps(host, "@(Get-LocalGroup | Select-Object Name, Description) | ConvertTo-Json")
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def get_group_members(host: str, group_name: str) -> list:
    r = pool.run_ps(
        host,
        f"\n@(Get-LocalGroupMember -Group '{_q(group_name)}' |\n    Select-Object Name, ObjectClass, PrincipalSource) |\n    ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def add_local_user(
    host: str,
    username: str,
    password: str,
    full_name: str = "",
    description: str = "",
    add_to_groups: Optional[list] = None,
    password_never_expires: bool = True,
) -> dict:
    u = _q(username)
    groups_script = ""
    if add_to_groups:
        for group in add_to_groups:
            groups_script += f"\nAdd-LocalGroupMember -Group '{_q(group)}' -Member '{u}'"
    r = pool.run_ps(
        host,
        f"\n$pass = ConvertTo-SecureString '{_q(password)}' -AsPlainText -Force\nNew-LocalUser -Name '{u}' -Password $pass -FullName '{_q(full_name)}' -Description '{_q(description)}' -PasswordNeverExpires:${str(password_never_expires).lower()} -ErrorAction Stop\n{groups_script}\nWrite-Output 'User ''{u}'' created successfully'\n",
    )
    return {
        "status": "ok" if r["success"] else "error",
        "host": host,
        "username": username,
        "groups": add_to_groups or [],
        "output": r["stdout"] if r["success"] else r["stderr"],
    }


def remove_local_user(host: str, username: str) -> dict:
    r = pool.run_ps(host, f"Remove-LocalUser -Name '{_q(username)}' -ErrorAction Stop")
    return {
        "status": "ok" if r["success"] else "error",
        "host": host,
        "username": username,
        "output": r["stderr"] if not r["success"] else f"User '{username}' removed",
    }
