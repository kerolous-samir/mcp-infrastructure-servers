import logging
import ldap3
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn
from ..core.connection import ldap_pool, winrm_pool

logger = logging.getLogger(__name__)
_PS_SQUOTES = "'‘’‚‛"


def _q(s) -> str:
    s = str(s)
    for ch in _PS_SQUOTES:
        s = s.replace(ch, ch * 2)
    return s


UAC_NORMAL = 512
UAC_DISABLED = 2
UAC_LOCKOUT = 16
USER_ATTRS = [
    "sAMAccountName",
    "userPrincipalName",
    "givenName",
    "sn",
    "displayName",
    "mail",
    "telephoneNumber",
    "department",
    "title",
    "description",
    "distinguishedName",
    "objectGUID",
    "userAccountControl",
    "whenCreated",
    "whenChanged",
    "memberOf",
]


def _v(entry, attr: str):
    try:
        val = getattr(entry, attr).value
        if val is None:
            return ""
        if isinstance(val, list):
            return [str(x) for x in val]
        return str(val)
    except Exception:
        return ""


def _enabled(uac) -> bool:
    try:
        return not bool(int(uac) & UAC_DISABLED)
    except Exception:
        return True


def _locked(uac) -> bool:
    try:
        return bool(int(uac) & UAC_LOCKOUT)
    except Exception:
        return False


def _find_user_dn(conn, base_dn: str, username: str) -> str:
    safe = escape_filter_chars(username)
    conn.search(
        base_dn, f"(&(objectClass=user)(sAMAccountName={safe}))", attributes=["distinguishedName"]
    )
    if not conn.entries:
        raise RuntimeError(f"User '{username}' not found")
    return conn.entries[0].distinguishedName.value


def list_users(host: str, ou: str = "", enabled_only: bool = False) -> list:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    base = ou if ou else cfg.base_dn
    attrs = [
        "sAMAccountName",
        "displayName",
        "mail",
        "userAccountControl",
        "distinguishedName",
        "whenCreated",
        "department",
    ]
    filt = "(&(objectClass=user)(objectCategory=person))"
    all_entries = []
    cookie = True
    while cookie:
        conn.search(
            base,
            filt,
            attributes=attrs,
            search_scope=ldap3.SUBTREE,
            paged_size=500,
            paged_cookie=None if cookie is True else cookie,
        )
        all_entries.extend(conn.entries)
        ctrl = conn.result.get("controls", {}).get("1.2.840.113556.1.4.319", {})
        cookie = ctrl.get("value", {}).get("cookie") if ctrl else None
    result = []
    for e in all_entries:
        uac = _v(e, "userAccountControl")
        enabled = _enabled(uac)
        if enabled_only and (not enabled):
            continue
        result.append(
            {
                "username": _v(e, "sAMAccountName"),
                "display_name": _v(e, "displayName"),
                "email": _v(e, "mail"),
                "enabled": enabled,
                "department": _v(e, "department"),
                "created": _v(e, "whenCreated"),
                "dn": _v(e, "distinguishedName"),
            }
        )
    return result


def get_user(host: str, username: str) -> dict:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    safe = escape_filter_chars(username)
    conn.search(cfg.base_dn, f"(&(objectClass=user)(sAMAccountName={safe}))", attributes=USER_ATTRS)
    if not conn.entries:
        raise RuntimeError(f"User '{username}' not found")
    e = conn.entries[0]
    uac = _v(e, "userAccountControl")
    return {
        "username": _v(e, "sAMAccountName"),
        "upn": _v(e, "userPrincipalName"),
        "first_name": _v(e, "givenName"),
        "last_name": _v(e, "sn"),
        "display_name": _v(e, "displayName"),
        "email": _v(e, "mail"),
        "phone": _v(e, "telephoneNumber"),
        "department": _v(e, "department"),
        "title": _v(e, "title"),
        "description": _v(e, "description"),
        "enabled": _enabled(uac),
        "locked": _locked(uac),
        "dn": _v(e, "distinguishedName"),
        "object_guid": _v(e, "objectGUID"),
        "created": _v(e, "whenCreated"),
        "changed": _v(e, "whenChanged"),
        "member_of": _v(e, "memberOf"),
    }


def create_user(
    host: str,
    username: str,
    password: str,
    first_name: str = "",
    last_name: str = "",
    display_name: str = "",
    email: str = "",
    ou: str = "",
    description: str = "",
) -> dict:
    cfg = ldap_pool.get_config(host)
    target_ou = ou if ou else f"CN=Users,{cfg.base_dn}"
    cn = display_name or f"{first_name} {last_name}".strip() or username
    upn = f"{username}@{cfg.domain}"
    safe_username = _q(username)
    safe_password = _q(password)
    safe_cn = _q(cn)
    safe_upn = _q(upn)
    safe_ou = _q(target_ou)
    safe_fn = _q(first_name)
    safe_ln = _q(last_name)
    safe_email = _q(email)
    safe_desc = _q(description)
    ps_parts = [
        f"New-ADUser",
        f"  -SamAccountName '{safe_username}'",
        f"  -UserPrincipalName '{safe_upn}'",
        f"  -Name '{safe_cn}'",
        f"  -Path '{safe_ou}'",
        f"  -AccountPassword (ConvertTo-SecureString '{safe_password}' -AsPlainText -Force)",
        f"  -Enabled $true",
    ]
    if first_name:
        ps_parts.append(f"  -GivenName '{safe_fn}'")
    if last_name:
        ps_parts.append(f"  -Surname '{safe_ln}'")
    if email:
        ps_parts.append(f"  -EmailAddress '{safe_email}'")
    if description:
        ps_parts.append(f"  -Description '{safe_desc}'")
    ps_parts.append("Write-Output 'ok'")
    ps = " `\n".join(ps_parts[:-1]) + "\n" + ps_parts[-1]
    r = winrm_pool.run_ps(host, ps)
    if not r["success"]:
        return {
            "status": "error",
            "username": username,
            "error": r["stderr"] or "New-ADUser failed via WinRM",
        }
    dn = f"CN={(escape_rdn(cn) if cn else cn)},{target_ou}"
    return {"status": "ok", "username": username, "dn": dn, "upn": upn}


def reset_password(host: str, username: str, new_password: str) -> dict:
    safe_username = _q(username)
    safe_password = _q(new_password)
    ps = f"""\nSet-ADAccountPassword -Identity '{safe_username}' -NewPassword (ConvertTo-SecureString '{safe_password}' -AsPlainText -Force) -Reset\nWrite-Output "ok"\n"""
    r = winrm_pool.run_ps(host, ps)
    return {
        "status": "ok" if r["success"] else "error",
        "username": username,
        "output": r["stdout"] if r["success"] else r["stderr"],
    }


def unlock_user(host: str, username: str) -> dict:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    safe = escape_filter_chars(username)
    conn.search(
        cfg.base_dn,
        f"(&(objectClass=user)(sAMAccountName={safe}))",
        attributes=["distinguishedName", "userAccountControl"],
    )
    if not conn.entries:
        return {"status": "error", "error": f"User '{username}' not found"}
    e = conn.entries[0]
    dn = e.distinguishedName.value
    uac = int(e.userAccountControl.value)
    conn.modify(dn, {"userAccountControl": [(ldap3.MODIFY_REPLACE, [str(uac & ~UAC_LOCKOUT)])]})
    ok = conn.result["result"] == 0
    return {
        "status": "ok" if ok else "error",
        "username": username,
        "output": conn.result.get("message", "unlocked" if ok else "failed"),
    }


def update_user(
    host: str,
    username: str,
    first_name: str = None,
    last_name: str = None,
    display_name: str = None,
    email: str = None,
    phone: str = None,
    department: str = None,
    title: str = None,
    description: str = None,
) -> dict:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    dn = _find_user_dn(conn, cfg.base_dn, username)
    attr_map = {
        "givenName": first_name,
        "sn": last_name,
        "displayName": display_name,
        "mail": email,
        "telephoneNumber": phone,
        "department": department,
        "title": title,
        "description": description,
    }
    changes = {k: [(ldap3.MODIFY_REPLACE, [v])] for k, v in attr_map.items() if v is not None}
    if not changes:
        return {"status": "no_changes", "username": username}
    conn.modify(dn, changes)
    ok = conn.result["result"] == 0
    return {
        "status": "ok" if ok else "error",
        "username": username,
        "updated": list(changes.keys()),
        "output": conn.result.get("message", "updated" if ok else "failed"),
    }


def search_users(host: str, query: str) -> list:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    safe = escape_filter_chars(query)
    filt = f"(&(objectClass=user)(objectCategory=person)(|(sAMAccountName=*{safe}*)(displayName=*{safe}*)(mail=*{safe}*)(givenName=*{safe}*)(sn=*{safe}*)))"
    attrs = ["sAMAccountName", "displayName", "mail", "userAccountControl", "distinguishedName"]
    all_entries = []
    cookie = True
    while cookie:
        conn.search(
            cfg.base_dn,
            filt,
            attributes=attrs,
            search_scope=ldap3.SUBTREE,
            paged_size=500,
            paged_cookie=None if cookie is True else cookie,
        )
        all_entries.extend(conn.entries)
        ctrl = conn.result.get("controls", {}).get("1.2.840.113556.1.4.319", {})
        cookie = ctrl.get("value", {}).get("cookie") if ctrl else None
    return [
        {
            "username": _v(e, "sAMAccountName"),
            "display_name": _v(e, "displayName"),
            "email": _v(e, "mail"),
            "enabled": _enabled(_v(e, "userAccountControl")),
            "dn": _v(e, "distinguishedName"),
        }
        for e in all_entries
    ]
