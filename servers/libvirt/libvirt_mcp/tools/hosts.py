import logging
from typing import Optional
from ..core.connection import pool, HostConfig

logger = logging.getLogger(__name__)


def add_host(
    host: str,
    username: str = "root",
    ssh_key_path: Optional[str] = None,
    password: Optional[str] = None,
    port: int = 22,
) -> dict:
    config = HostConfig(
        host=host, username=username, ssh_key_path=ssh_key_path, password=password, port=port
    )
    pool.register_host(config)
    try:
        conn = pool.get_connection(host)
        version = conn.getVersion()
        return {
            "status": "registered_and_connected",
            "host": host,
            "username": username,
            "auth_method": "ssh_key" if ssh_key_path else "password",
            "libvirt_version": version,
        }
    except Exception as e:
        return {
            "status": "registered_but_connection_failed",
            "host": host,
            "error": str(e),
            "tip": "Check SSH access and that libvirtd is running on the remote host",
        }


def list_hosts() -> list[dict]:
    ip_to_name: dict[str, str] = {}
    name_to_ip: dict[str, str] = {}
    try:
        import psycopg2, os as _os

        pg = psycopg2.connect(
            host=_os.environ.get("DB_HOST", "localhost"),
            port=int(_os.environ.get("DB_PORT", "5432")),
            dbname=_os.environ.get("DB_DATABASE", ""),
            user=_os.environ.get("DB_USERNAME", ""),
            password=_os.environ.get("DB_PASSWORD", ""),
            connect_timeout=2,
        )
        cur = pg.cursor()
        cur.execute("SELECT name, ip FROM hosts WHERE ip IS NOT NULL AND ip != ''")
        for row in cur.fetchall():
            db_name, db_ip = (row[0], row[1])
            ip_to_name[db_ip] = db_name
            name_to_ip[db_name] = db_ip
        pg.close()
    except Exception:
        pass
    raw_hosts = pool.list_hosts()
    seen_ips: set[str] = set()
    result = []
    import re

    _is_ip = re.compile("^\\d+\\.\\d+\\.\\d+\\.\\d+$")
    sorted_hosts = sorted(raw_hosts, key=lambda h: 0 if _is_ip.match(h) or h == "localhost" else 1)
    for host in sorted_hosts:
        if host == "localhost":
            canonical_ip = "localhost"
        elif _is_ip.match(host):
            canonical_ip = host
        else:
            canonical_ip = name_to_ip.get(host, host)
        if canonical_ip in seen_ips:
            continue
        seen_ips.add(canonical_ip)
        friendly = ip_to_name.get(host) or ip_to_name.get(canonical_ip) or host
        try:
            conn = pool.get_connection(host)
            node_info = conn.getInfo()
            result.append(
                {
                    "host": host,
                    "name": friendly,
                    "ip": canonical_ip if canonical_ip != host else "",
                    "status": "connected",
                    "cpus": node_info[2],
                    "memory_mb": node_info[1],
                }
            )
        except Exception as e:
            result.append(
                {
                    "host": host,
                    "name": friendly,
                    "ip": canonical_ip if canonical_ip != host else "",
                    "status": "disconnected",
                    "error": str(e),
                }
            )
    return result


def get_host_info(host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    node_info = conn.getInfo()
    free_memory = conn.getFreeMemory()
    return {
        "host": host,
        "cpu_model": node_info[0],
        "total_memory_mb": node_info[1],
        "free_memory_mb": free_memory // (1024 * 1024),
        "used_memory_mb": node_info[1] - free_memory // (1024 * 1024),
        "total_cpus": node_info[2],
        "cpu_mhz": node_info[3],
        "numa_nodes": node_info[4],
        "cpu_sockets": node_info[5],
        "cpu_cores_per_socket": node_info[6],
        "cpu_threads_per_core": node_info[7],
        "libvirt_version": conn.getVersion(),
        "active_vms": conn.numOfDomains(),
        "defined_vms": conn.numOfDefinedDomains(),
    }


def test_connection(host: str) -> dict:
    try:
        conn = pool.get_connection(host)
        conn.getVersion()
        node_info = conn.getInfo()
        return {
            "status": "ok",
            "host": host,
            "reachable": True,
            "cpus": node_info[2],
            "memory_mb": node_info[1],
        }
    except Exception as e:
        return {"status": "failed", "host": host, "reachable": False, "error": str(e)}


def remove_host(host: str) -> dict:
    if host in ("localhost", "127.0.0.1"):
        return {"status": "error", "message": "Cannot remove localhost"}
    with pool._lock:
        pool._configs.pop(host, None)
        conn = pool._connections.pop(host, None)
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return {"status": "removed", "host": host}
