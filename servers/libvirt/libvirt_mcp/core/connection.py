import libvirt
import threading
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)
_LOCAL_IPS_CACHE: set | None = None


def _local_ips() -> set:
    global _LOCAL_IPS_CACHE
    if _LOCAL_IPS_CACHE is not None:
        return _LOCAL_IPS_CACHE
    ips = {"127.0.0.1", "::1", "localhost"}
    try:
        import socket as _sock

        ips.add(_sock.gethostbyname(_sock.gethostname()))
    except Exception:
        pass
    try:
        import json as _json, subprocess as _sp

        out = _sp.run(["ip", "-j", "addr"], capture_output=True, text=True, timeout=2).stdout
        for iface in _json.loads(out):
            for ai in iface.get("addr_info", []):
                if ai.get("family") == "inet" and ai.get("local"):
                    ips.add(ai["local"])
    except Exception:
        pass
    _LOCAL_IPS_CACHE = ips
    return ips


@dataclass
class HostConfig:
    host: str
    port: int = 22
    username: str = "root"
    ssh_key_path: Optional[str] = None
    password: Optional[str] = None

    def build_uri(self) -> str:
        if self.host in ("localhost", "127.0.0.1"):
            return "qemu:///system"
        auth = self.username
        port_str = f":{self.port}" if self.port != 22 else ""
        return f"qemu+ssh://{auth}@{self.host}{port_str}/system"

    def build_uri_with_key(self) -> str:
        if self.ssh_key_path:
            port_str = f":{self.port}" if self.port != 22 else ""
            return f"qemu+ssh://{self.username}@{self.host}{port_str}/system?keyfile={self.ssh_key_path}&known_hosts_verify=auto"
        return self.build_uri()


class LibvirtConnectionPool:

    def __init__(self):
        self._connections: dict[str, libvirt.virConnect] = {}
        self._configs: dict[str, HostConfig] = {}
        self._lock = threading.Lock()

    def register_host(self, config: HostConfig):
        with self._lock:
            self._configs[config.host] = config
            logger.info(f"Registered host: {config.host}")

    def remove_host(self, host: str):
        with self._lock:
            conn = self._connections.pop(host, None)
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            self._configs.pop(host, None)
            logger.info(f"Removed host: {host}")

    def get_connection(self, host: str) -> libvirt.virConnect:
        with self._lock:
            if host not in self._configs:
                if host in ("localhost", "127.0.0.1"):
                    self._configs[host] = HostConfig(host=host)
                else:
                    self._lock.release()
                    try:
                        _bootstrap_remote_hosts()
                    finally:
                        self._lock.acquire()
                    if host not in self._configs:
                        raise ValueError(
                            f"Host '{host}' not registered. Call register_host() first or use add_host tool."
                        )
            conn = self._connections.get(host)
            if conn is not None:
                try:
                    conn.getVersion()
                    return conn
                except libvirt.libvirtError:
                    logger.warning(f"Connection to {host} died, reconnecting...")
                    self._connections.pop(host, None)
            conn = self._connect(self._configs[host])
            self._connections[host] = conn
            return conn

    def _connect(self, config: HostConfig) -> libvirt.virConnect:
        uri = config.build_uri_with_key() if config.ssh_key_path else config.build_uri()
        if config.password and (not config.ssh_key_path):

            def auth_callback(credentials, user_data):
                for cred in credentials:
                    if cred[0] == libvirt.VIR_CRED_AUTHNAME:
                        cred[4] = config.username
                    elif cred[0] == libvirt.VIR_CRED_PASSPHRASE:
                        cred[4] = config.password
                return 0

            auth = [[libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE], auth_callback, None]
            conn = libvirt.openAuth(uri, auth, 0)
        else:
            conn = libvirt.open(uri)
        if conn is None:
            raise ConnectionError(f"Failed to connect to libvirt on {config.host}")
        logger.info(f"Connected to libvirt on {config.host} via {uri}")
        return conn

    def list_hosts(self) -> list[str]:
        with self._lock:
            return list(self._configs.keys())


pool = LibvirtConnectionPool()
pool.register_host(HostConfig(host="localhost"))


def _bootstrap_remote_hosts() -> None:
    import os as _os

    DEFAULT_KEY = _os.environ.get("MCP_SSH_KEY_PATH", "/root/.ssh/id_ed25519")
    _db_database = _os.environ.get("DB_DATABASE", "")
    _db_username = _os.environ.get("DB_USERNAME", "")
    if not _db_database or not _db_username:
        logger.warning("DB_DATABASE or DB_USERNAME not set in env — skipping remote host bootstrap")
        return
    for _attempt in range(3):
        try:
            import psycopg2

            pg_conn = psycopg2.connect(
                host=_os.environ.get("DB_HOST", "localhost"),
                port=int(_os.environ.get("DB_PORT", "5432")),
                dbname=_db_database,
                user=_db_username,
                password=_os.environ.get("DB_PASSWORD", ""),
                connect_timeout=3,
            )
            cur = pg_conn.cursor()
            cur.execute(
                "\n                SELECT name, ip, ssh_user, ssh_port\n                FROM hosts\n                WHERE ip IS NOT NULL AND ip != ''\n                  AND name != 'localhost'\n            "
            )
            rows = cur.fetchall()
            pg_conn.close()
            break
        except Exception as e:
            logger.warning(
                "Could not fetch hosts from PostgreSQL (attempt %d/3): %s", _attempt + 1, e
            )
            import time as _t

            _t.sleep(1)
    else:
        logger.warning("All PostgreSQL attempts failed — no remote hosts loaded")
        return
    local_ips = _local_ips()
    for name, host_ip, ssh_user, ssh_port in rows:
        if host_ip in local_ips:
            continue
        key_path = DEFAULT_KEY if _os.path.exists(DEFAULT_KEY) else None
        cfg = HostConfig(
            host=host_ip, port=ssh_port or 22, username=ssh_user or "root", ssh_key_path=key_path
        )
        pool.register_host(cfg)
        logger.info(
            "Bootstrapped remote host: %s (%s) ssh=%s key=%s",
            name,
            host_ip,
            ssh_user,
            bool(key_path),
        )


try:
    _bootstrap_remote_hosts()
except Exception as _e:
    logger.warning("Remote host bootstrap failed (non-fatal): %s", _e)
