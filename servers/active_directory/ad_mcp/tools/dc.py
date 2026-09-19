import logging
from ..core.connection import ldap_pool, winrm_pool

logger = logging.getLogger(__name__)


def add_dc(
    host: str, username: str, password: str, domain: str, port: int = 389, use_ssl: bool = False
) -> dict:
    cfg = ldap_pool.add_dc(host, username, password, domain, port, use_ssl)
    winrm_pool.ensure_host(host, username, password)
    try:
        conn = ldap_pool.get_connection(host)
        default_nc = ""
        if conn.server.info:
            default_nc = str(conn.server.info.other.get("defaultNamingContext", [""])[0])
        return {
            "status": "ok",
            "host": host,
            "domain": domain,
            "base_dn": cfg.base_dn,
            "bound_as": cfg.bind_dn,
            "default_naming_context": default_nc,
        }
    except Exception as e:
        return {"status": "error", "host": host, "domain": domain, "error": str(e)}


def list_dcs() -> list:
    return ldap_pool.list_dcs()


def remove_dc(host: str) -> dict:
    ldap_pool.remove_dc(host)
    winrm_pool.remove_host(host)
    return {"status": "ok", "host": host, "message": "DC removed"}


def test_dc(host: str) -> dict:
    try:
        cfg = ldap_pool.get_config(host)
        conn = ldap_pool.get_connection(host)
        conn.search(cfg.base_dn, "(objectClass=domain)", size_limit=1)
        return {
            "status": "ok",
            "host": host,
            "bound": conn.bound,
            "server": conn.server.host,
            "result": conn.result.get("description", "success"),
        }
    except Exception as e:
        return {"status": "error", "host": host, "error": str(e)}


def get_domain_info(host: str) -> dict:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    conn.search(
        cfg.base_dn,
        "(objectClass=domain)",
        attributes=[
            "dc",
            "name",
            "distinguishedName",
            "objectGUID",
            "whenCreated",
            "msDS-Behavior-Version",
        ],
    )
    if not conn.entries:
        raise RuntimeError("Domain object not found")
    e = conn.entries[0]

    def v(attr):
        try:
            val = getattr(e, attr).value
            return str(val) if val is not None else ""
        except Exception:
            return ""

    return {
        "domain": cfg.domain,
        "base_dn": cfg.base_dn,
        "name": v("name"),
        "dc": v("dc"),
        "distinguished_name": v("distinguishedName"),
        "object_guid": v("objectGUID"),
        "when_created": v("whenCreated"),
        "functional_level": v("msDS-Behavior-Version"),
    }


def get_forest_info(host: str) -> dict:
    conn = ldap_pool.get_connection(host)
    info = conn.server.info
    if not info:
        raise RuntimeError("No server info available — is the DC reachable?")

    def oi(key):
        val = info.other.get(key, [""])
        if isinstance(val, list):
            return str(val[0]) if val else ""
        return str(val)

    return {
        "forest_root_dn": oi("rootDomainNamingContext"),
        "configuration_dn": oi("configurationNamingContext"),
        "schema_dn": oi("schemaNamingContext"),
        "dc_dns_name": oi("dnsHostName"),
        "supported_ldap_versions": [str(v) for v in info.supported_ldap_versions or []],
        "supported_sasl_mechanisms": [str(m) for m in info.supported_sasl_mechanisms or []],
    }


def get_dc_list(host: str) -> list:
    cfg = ldap_pool.get_config(host)
    conn = ldap_pool.get_connection(host)
    dc_ou = f"OU=Domain Controllers,{cfg.base_dn}"
    conn.search(
        dc_ou,
        "(objectClass=computer)",
        attributes=[
            "name",
            "dNSHostName",
            "operatingSystem",
            "operatingSystemVersion",
            "whenCreated",
        ],
    )
    result = []
    for e in conn.entries:

        def v(attr):
            try:
                val = getattr(e, attr).value
                return str(val) if val is not None else ""
            except Exception:
                return ""

        result.append(
            {
                "name": v("name"),
                "dns_host": v("dNSHostName"),
                "os": v("operatingSystem"),
                "os_version": v("operatingSystemVersion"),
                "created": v("whenCreated"),
            }
        )
    return result
