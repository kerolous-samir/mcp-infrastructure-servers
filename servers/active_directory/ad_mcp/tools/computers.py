import logging
import ldap3
from ldap3.utils.conv import escape_filter_chars
from ..core.connection import ldap_pool

logger = logging.getLogger(__name__)
UAC_DISABLED = 2
COMPUTER_ATTRS = [
    "name",
    "sAMAccountName",
    "dNSHostName",
    "operatingSystem",
    "operatingSystemVersion",
    "description",
    "userAccountControl",
    "distinguishedName",
    "objectGUID",
    "whenCreated",
    "lastLogon",
]


def _v(entry, attr: str):
    try:
        val = getattr(entry, attr).value
        return str(val) if val is not None else ""
    except Exception:
        return ""


def _enabled(uac) -> bool:
    try:
        return not bool(int(uac) & UAC_DISABLED)
    except Exception:
        return True


def list_computers(host: str, ou: str = "", enabled_only: bool = False) -> list:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    base = ou if ou else cfg.base_dn
    conn.search(
        base,
        "(objectClass=computer)",
        attributes=[
            "name",
            "dNSHostName",
            "operatingSystem",
            "userAccountControl",
            "distinguishedName",
            "whenCreated",
        ],
        search_scope=ldap3.SUBTREE,
    )
    result = []
    for e in conn.entries:
        uac = _v(e, "userAccountControl")
        enabled = _enabled(uac)
        if enabled_only and (not enabled):
            continue
        result.append(
            {
                "name": _v(e, "name"),
                "dns_host": _v(e, "dNSHostName"),
                "os": _v(e, "operatingSystem"),
                "enabled": enabled,
                "created": _v(e, "whenCreated"),
                "dn": _v(e, "distinguishedName"),
            }
        )
    return result


def search_computers(host: str, query: str) -> list:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    safe = escape_filter_chars(query)
    filt = (
        f"(&(objectClass=computer)(|(name=*{safe}*)(dNSHostName=*{safe}*)(description=*{safe}*)))"
    )
    conn.search(
        cfg.base_dn,
        filt,
        attributes=[
            "name",
            "dNSHostName",
            "operatingSystem",
            "userAccountControl",
            "distinguishedName",
        ],
        search_scope=ldap3.SUBTREE,
    )
    return [
        {
            "name": _v(e, "name"),
            "dns_host": _v(e, "dNSHostName"),
            "os": _v(e, "operatingSystem"),
            "enabled": _enabled(_v(e, "userAccountControl")),
            "dn": _v(e, "distinguishedName"),
        }
        for e in conn.entries
    ]


def get_computer(host: str, computer_name: str) -> dict:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    safe = escape_filter_chars(computer_name)
    conn.search(cfg.base_dn, f"(&(objectClass=computer)(name={safe}))", attributes=COMPUTER_ATTRS)
    if not conn.entries:
        raise RuntimeError(f"Computer '{computer_name}' not found")
    e = conn.entries[0]
    uac = _v(e, "userAccountControl")
    return {
        "name": _v(e, "name"),
        "sam_account": _v(e, "sAMAccountName"),
        "dns_host": _v(e, "dNSHostName"),
        "os": _v(e, "operatingSystem"),
        "os_version": _v(e, "operatingSystemVersion"),
        "description": _v(e, "description"),
        "enabled": _enabled(uac),
        "dn": _v(e, "distinguishedName"),
        "object_guid": _v(e, "objectGUID"),
        "created": _v(e, "whenCreated"),
    }
