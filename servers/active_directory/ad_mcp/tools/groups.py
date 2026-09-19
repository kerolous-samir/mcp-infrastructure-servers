import logging
import ldap3
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn
from ..core.connection import ldap_pool

logger = logging.getLogger(__name__)
GROUP_ATTRS = [
    "sAMAccountName",
    "distinguishedName",
    "objectGUID",
    "groupType",
    "description",
    "member",
    "memberOf",
    "whenCreated",
]
GROUP_SECURITY = -2147483646
GROUP_UNIVERSAL = -2147483640
GROUP_DIST_GLOBAL = 2


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


def _find_dn(conn, base_dn: str, name: str, obj_class: str = "group") -> str:
    safe_name = escape_filter_chars(name)
    safe_class = escape_filter_chars(obj_class)
    conn.search(
        base_dn,
        f"(&(objectClass={safe_class})(sAMAccountName={safe_name}))",
        attributes=["distinguishedName"],
    )
    if not conn.entries:
        raise RuntimeError(f"'{name}' not found")
    return conn.entries[0].distinguishedName.value


def list_groups(host: str, ou: str = "") -> list:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    base = ou if ou else cfg.base_dn
    conn.search(
        base,
        "(objectClass=group)",
        attributes=[
            "sAMAccountName",
            "description",
            "groupType",
            "distinguishedName",
            "whenCreated",
        ],
        search_scope=ldap3.SUBTREE,
    )
    return [
        {
            "name": _v(e, "sAMAccountName"),
            "description": _v(e, "description"),
            "group_type": _v(e, "groupType"),
            "dn": _v(e, "distinguishedName"),
            "created": _v(e, "whenCreated"),
        }
        for e in conn.entries
    ]


def get_group(host: str, group_name: str) -> dict:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    safe = escape_filter_chars(group_name)
    conn.search(
        cfg.base_dn, f"(&(objectClass=group)(sAMAccountName={safe}))", attributes=GROUP_ATTRS
    )
    if not conn.entries:
        raise RuntimeError(f"Group '{group_name}' not found")
    e = conn.entries[0]
    members = _v(e, "member")
    if isinstance(members, str) and members:
        members = [members]
    return {
        "name": _v(e, "sAMAccountName"),
        "description": _v(e, "description"),
        "group_type": _v(e, "groupType"),
        "dn": _v(e, "distinguishedName"),
        "object_guid": _v(e, "objectGUID"),
        "member_count": len(members) if isinstance(members, list) else 1 if members else 0,
        "created": _v(e, "whenCreated"),
        "member_of": _v(e, "memberOf"),
    }


def create_group(
    host: str, group_name: str, ou: str = "", description: str = "", group_scope: str = "Global"
) -> dict:
    if not group_name or not str(group_name).strip():
        return {"status": "error", "group": group_name, "output": "group_name must not be empty"}
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    target_ou = ou if ou else f"CN=Users,{cfg.base_dn}"
    dn = f"CN={escape_rdn(group_name)},{target_ou}"
    scope_map = {"Global": -2147483646, "Universal": -2147483640, "DomainLocal": -2147483644}
    gtype = scope_map.get(group_scope, -2147483646)
    attrs = {"objectClass": ["top", "group"], "sAMAccountName": group_name, "groupType": str(gtype)}
    if description:
        attrs["description"] = description
    conn.add(dn, attributes=attrs)
    ok = conn.result["result"] == 0
    return {
        "status": "ok" if ok else "error",
        "group": group_name,
        "dn": dn,
        "output": conn.result.get("message", "created" if ok else "failed"),
    }


def get_group_members(host: str, group_name: str) -> list:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    safe = escape_filter_chars(group_name)
    conn.search(
        cfg.base_dn, f"(&(objectClass=group)(sAMAccountName={safe}))", attributes=["member"]
    )
    if not conn.entries:
        raise RuntimeError(f"Group '{group_name}' not found")
    members_raw = conn.entries[0].member.values if conn.entries[0].member else []
    result = []
    for dn in members_raw:
        conn.search(
            cfg.base_dn,
            f"(distinguishedName={escape_filter_chars(str(dn))})",
            attributes=["sAMAccountName", "objectClass", "displayName"],
        )
        if conn.entries:
            e = conn.entries[0]
            result.append(
                {
                    "username": _v(e, "sAMAccountName"),
                    "display_name": _v(e, "displayName"),
                    "type": "group" if "group" in (_v(e, "objectClass") or []) else "user",
                    "dn": str(dn),
                }
            )
        else:
            result.append({"dn": str(dn), "username": "", "display_name": "", "type": "unknown"})
    return result


def add_group_member(host: str, group_name: str, member_username: str) -> dict:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    group_dn = _find_dn(conn, cfg.base_dn, group_name)
    conn.search(
        cfg.base_dn,
        f"(sAMAccountName={escape_filter_chars(member_username)})",
        attributes=["distinguishedName"],
    )
    if not conn.entries:
        return {"status": "error", "error": f"'{member_username}' not found"}
    member_dn = conn.entries[0].distinguishedName.value
    conn.modify(group_dn, {"member": [(ldap3.MODIFY_ADD, [member_dn])]})
    ok = conn.result["result"] == 0
    return {
        "status": "ok" if ok else "error",
        "group": group_name,
        "member": member_username,
        "output": conn.result.get("message", "added" if ok else "failed"),
    }


def search_groups(host: str, query: str) -> list:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    safe = escape_filter_chars(query)
    filt = f"(&(objectClass=group)(|(sAMAccountName=*{safe}*)(description=*{safe}*)))"
    conn.search(
        cfg.base_dn,
        filt,
        attributes=["sAMAccountName", "description", "groupType", "distinguishedName"],
        search_scope=ldap3.SUBTREE,
    )
    return [
        {
            "name": _v(e, "sAMAccountName"),
            "description": _v(e, "description"),
            "group_type": _v(e, "groupType"),
            "dn": _v(e, "distinguishedName"),
        }
        for e in conn.entries
    ]


def remove_group_member(host: str, group_name: str, member_username: str) -> dict:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    group_dn = _find_dn(conn, cfg.base_dn, group_name)
    conn.search(
        cfg.base_dn,
        f"(sAMAccountName={escape_filter_chars(member_username)})",
        attributes=["distinguishedName"],
    )
    if not conn.entries:
        return {"status": "error", "error": f"'{member_username}' not found"}
    member_dn = conn.entries[0].distinguishedName.value
    conn.modify(group_dn, {"member": [(ldap3.MODIFY_DELETE, [member_dn])]})
    ok = conn.result["result"] == 0
    return {
        "status": "ok" if ok else "error",
        "group": group_name,
        "member": member_username,
        "output": conn.result.get("message", "removed" if ok else "failed"),
    }
