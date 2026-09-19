import logging
import os
import select as _select
import socket as _socket
import ssl as _ssl
import threading
from dataclasses import dataclass
import ldap3
import winrm

logger = logging.getLogger(__name__)


def _cleartext_bind_allowed() -> bool:
    return os.environ.get("AD_ALLOW_CLEARTEXT_BIND", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _is_alive(conn: ldap3.Connection) -> bool:
    if not conn or conn.closed or (not getattr(conn, "socket", None)):
        return False
    try:
        rlist, _, _ = _select.select([conn.socket], [], [], 0)
        if not rlist:
            return True
        data = conn.socket.recv(1, _socket.MSG_PEEK)
        return bool(data)
    except Exception:
        return False


@dataclass
class DCConfig:
    host: str
    username: str
    password: str
    domain: str
    base_dn: str = ""
    port: int = 389
    use_ssl: bool = False

    def __post_init__(self):
        if not self.base_dn:
            self.base_dn = ",".join((f"DC={p}" for p in self.domain.split(".")))

    @property
    def bind_dn(self) -> str:
        if "@" in self.username:
            return self.username
        user = self.username.split("\\")[-1]
        return f"{user}@{self.domain}"

    @property
    def auth_type(self):
        return ldap3.SIMPLE


class LDAPPool:

    def __init__(self):
        self._lock = threading.Lock()
        self._configs: dict[str, DCConfig] = {}
        self._connections: dict[str, ldap3.Connection] = {}

    def add_dc(
        self,
        host: str,
        username: str,
        password: str,
        domain: str,
        port: int = 389,
        use_ssl: bool = False,
    ) -> DCConfig:
        cfg = DCConfig(
            host=host,
            username=username,
            password=password,
            domain=domain,
            port=port,
            use_ssl=use_ssl,
        )
        with self._lock:
            self._configs[host] = cfg
            self._connections.pop(host, None)
        logger.info("DC registered: %s  domain=%s  base_dn=%s", host, domain, cfg.base_dn)
        return cfg

    def remove_dc(self, host: str):
        with self._lock:
            conn = self._connections.pop(host, None)
            if conn:
                try:
                    conn.unbind()
                except Exception:
                    pass
            self._configs.pop(host, None)

    def list_dcs(self) -> list:
        with self._lock:
            return [
                {
                    "host": c.host,
                    "domain": c.domain,
                    "base_dn": c.base_dn,
                    "port": c.port,
                    "use_ssl": c.use_ssl,
                }
                for c in self._configs.values()
            ]

    def get_config(self, host: str) -> DCConfig:
        with self._lock:
            cfg = self._configs.get(host)
        if not cfg:
            raise KeyError(f"DC '{host}' not registered. Call add_dc first.")
        return cfg

    def get_connection(self, host: str) -> ldap3.Connection:
        with self._lock:
            cfg = self._configs.get(host)
            if not cfg:
                raise KeyError(f"DC '{host}' not registered. Call add_dc first.")
            conn = self._connections.get(host)
            if conn and conn.bound and _is_alive(conn):
                return conn
            if conn is not None:
                logger.debug("LDAP connection to %s is stale — reconnecting", host)
                self._connections.pop(host, None)
                try:
                    conn.unbind()
                except Exception:
                    pass
            ca_bundle = os.environ.get("AD_TLS_CA_BUNDLE", "").strip()
            tls = None
            if cfg.use_ssl:
                auto_bind = ldap3.AUTO_BIND_NO_TLS
                if ca_bundle:
                    tls = ldap3.Tls(validate=_ssl.CERT_REQUIRED, ca_certs_file=ca_bundle)
            elif _cleartext_bind_allowed():
                logger.warning(
                    "AD LDAP bind to %s is CLEARTEXT (AD_ALLOW_CLEARTEXT_BIND set) — the bind password is sent unencrypted.",
                    cfg.host,
                )
                auto_bind = ldap3.AUTO_BIND_NO_TLS
            else:
                validate = _ssl.CERT_REQUIRED if ca_bundle else _ssl.CERT_NONE
                tls = ldap3.Tls(validate=validate, ca_certs_file=ca_bundle or None)
                auto_bind = ldap3.AUTO_BIND_TLS_BEFORE_BIND
            server = ldap3.Server(
                cfg.host,
                port=cfg.port,
                use_ssl=cfg.use_ssl,
                get_info=ldap3.ALL,
                connect_timeout=4,
                tls=tls,
            )
            conn = ldap3.Connection(
                server,
                user=cfg.bind_dn,
                password=cfg.password,
                authentication=cfg.auth_type,
                auto_bind=auto_bind,
                receive_timeout=6,
            )
            self._connections[host] = conn
            logger.debug("LDAP (re)bound to %s as %s", cfg.host, cfg.bind_dn)
            return conn


ldap_pool = LDAPPool()


@dataclass
class WinRMConfig:
    host: str
    username: str
    password: str
    port: int = 5985
    transport: str = "ntlm"
    use_ssl: bool = False
    server_cert_validation: str = "validate"

    def __post_init__(self):
        if self.use_ssl and self.port == 5985:
            self.port = 5986


class WinRMPool:

    def __init__(self):
        self._lock = threading.Lock()
        self._configs: dict[str, WinRMConfig] = {}

    def ensure_host(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 5985,
        transport: str = "ntlm",
        use_ssl: bool = False,
        server_cert_validation: str = "validate",
    ):
        with self._lock:
            self._configs[host] = WinRMConfig(
                host=host,
                username=username,
                password=password,
                port=port,
                transport=transport,
                use_ssl=use_ssl,
                server_cert_validation=server_cert_validation,
            )

    def remove_host(self, host: str):
        with self._lock:
            self._configs.pop(host, None)

    def run_ps(self, host: str, script: str) -> dict:
        with self._lock:
            cfg = self._configs.get(host)
        if not cfg:
            raise KeyError(f"Host '{host}' not in WinRM pool. Register DC first.")
        scheme = "https" if cfg.use_ssl else "http"
        s = winrm.Session(
            f"{scheme}://{cfg.host}:{cfg.port}/wsman",
            auth=(cfg.username, cfg.password),
            transport=cfg.transport,
            server_cert_validation=cfg.server_cert_validation if cfg.use_ssl else "ignore",
            operation_timeout_sec=60,
            read_timeout_sec=90,
        )
        r = s.run_ps(script)
        return {
            "success": r.status_code == 0,
            "stdout": r.std_out.decode("utf-8", errors="replace").strip(),
            "stderr": r.std_err.decode("utf-8", errors="replace").strip(),
            "status_code": r.status_code,
        }


winrm_pool = WinRMPool()


def _bootstrap_active_dc() -> None:
    host = os.environ.get("AD_DC_HOST", "").strip()
    username = os.environ.get("AD_DC_USERNAME", "").strip()
    password = os.environ.get("AD_DC_PASSWORD", "")
    domain = os.environ.get("AD_DC_DOMAIN", "").strip()
    if not host or not username or not password or not domain:
        return
    try:
        ldap_pool.add_dc(host, username, password, domain)
        winrm_pool.ensure_host(host, username, password)
        logger.info("registered DC %s (%s) from environment", host, domain)
    except Exception as e:
        logger.warning("DC bootstrap from environment failed (non-fatal): %s", e)


try:
    _bootstrap_active_dc()
except Exception as _e:
    logger.warning("AD MCP DC bootstrap raised: %s", _e)
