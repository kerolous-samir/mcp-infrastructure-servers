import logging
import ldap3
from ldap3.utils.dn import escape_rdn, parse_dn
from ..core.connection import ldap_pool

logger = logging.getLogger(__name__)


def _v(entry, attr: str):
    try:
        val = getattr(entry, attr).value
        return str(val) if val is not None else ""
    except Exception:
        return ""


def list_ous(host: str, search_base: str = "") -> list:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    base = search_base if search_base else cfg.base_dn
    conn.search(
        base,
        "(objectClass=organizationalUnit)",
        attributes=["ou", "description", "distinguishedName", "whenCreated"],
        search_scope=ldap3.SUBTREE,
    )
    return [
        {
            "name": _v(e, "ou"),
            "description": _v(e, "description"),
            "dn": _v(e, "distinguishedName"),
            "created": _v(e, "whenCreated"),
        }
        for e in conn.entries
    ]


def get_ou(host: str, ou_dn: str) -> dict:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    conn.search(
        ou_dn,
        "(objectClass=organizationalUnit)",
        attributes=["ou", "description", "distinguishedName", "whenCreated", "whenChanged"],
        search_scope=ldap3.BASE,
    )
    if not conn.entries:
        raise RuntimeError(f"OU not found: {ou_dn}")
    e = conn.entries[0]
    return {
        "name": _v(e, "ou"),
        "description": _v(e, "description"),
        "dn": _v(e, "distinguishedName"),
        "created": _v(e, "whenCreated"),
        "changed": _v(e, "whenChanged"),
    }


def create_ou(host: str, ou_name: str, parent_dn: str = "", description: str = "") -> dict:
    if not ou_name or not str(ou_name).strip():
        return {"status": "error", "ou": ou_name, "output": "ou_name must not be empty"}
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    parent = parent_dn if parent_dn else cfg.base_dn
    dn = f"OU={escape_rdn(ou_name)},{parent}"
    attrs = {"objectClass": ["top", "organizationalUnit"], "ou": ou_name}
    if description:
        attrs["description"] = description
    conn.add(dn, attributes=attrs)
    ok = conn.result["result"] == 0
    return {
        "status": "ok" if ok else "error",
        "ou": ou_name,
        "dn": dn,
        "output": conn.result.get("message", "created" if ok else "failed"),
    }


def move_object(host: str, object_dn: str, target_ou: str) -> dict:
    conn = ldap_pool.get_connection(host)
    try:
        attr, value, _sep = parse_dn(object_dn, escape=False)[0]
    except Exception:
        return {
            "status": "error",
            "object_dn": object_dn,
            "target_ou": target_ou,
            "output": "Invalid object DN",
        }
    rdn = f"{attr}={value}"
    conn.modify_dn(object_dn, rdn, new_superior=target_ou)
    ok = conn.result["result"] == 0
    return {
        "status": "ok" if ok else "error",
        "object_dn": object_dn,
        "target_ou": target_ou,
        "output": conn.result.get("message", "moved" if ok else "failed"),
    }
