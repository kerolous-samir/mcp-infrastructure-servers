import logging
import ldap3
from ..core.connection import ldap_pool

logger = logging.getLogger(__name__)
UAC_DISABLED = 2


def delete_object(host: str, dn: str) -> dict:
    conn = ldap_pool.get_connection(host)
    conn.delete(dn)
    ok = conn.result["result"] == 0
    return {
        "status": "ok" if ok else "error",
        "dn": dn,
        "output": conn.result.get("message", "deleted" if ok else "failed"),
    }


def set_object_enabled(host: str, dn: str, enabled: bool) -> dict:
    conn = ldap_pool.get_connection(host)
    conn.search(dn, "(objectClass=*)", search_scope=ldap3.BASE, attributes=["userAccountControl"])
    if not conn.entries:
        return {"status": "error", "dn": dn, "error": "Object not found"}
    uac = int(conn.entries[0].userAccountControl.value)
    new_uac = uac & ~UAC_DISABLED if enabled else uac | UAC_DISABLED
    conn.modify(dn, {"userAccountControl": [(ldap3.MODIFY_REPLACE, [new_uac])]})
    ok = conn.result["result"] == 0
    return {
        "status": "ok" if ok else "error",
        "dn": dn,
        "enabled": enabled,
        "output": conn.result.get("message", "ok" if ok else "failed"),
    }
