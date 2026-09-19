import logging
import threading
from dataclasses import dataclass
from typing import Optional
import winrm

logger = logging.getLogger(__name__)


@dataclass
class WinRMHostConfig:
    host: str
    username: str
    password: str
    port: int = 5985
    transport: str = "ntlm"
    use_ssl: bool = False
    validate_ssl: bool = True
    operation_timeout: int = 600
    connection_timeout: int = 620


class WinRMConnectionPool:

    def __init__(self):
        self._sessions: dict[str, winrm.Session] = {}
        self._configs: dict[str, WinRMHostConfig] = {}
        self._lock = threading.Lock()

    def register_host(self, config: WinRMHostConfig) -> None:
        with self._lock:
            self._configs[config.host] = config
            self._sessions.pop(config.host, None)
        logger.info(f"Registered WinRM host: {config.host}")

    def _create_session(self, config: WinRMHostConfig) -> winrm.Session:
        scheme = "https" if config.use_ssl else "http"
        endpoint = f"{scheme}://{config.host}:{config.port}/wsman"
        session = winrm.Session(
            target=endpoint,
            auth=(config.username, config.password),
            transport=config.transport,
            server_cert_validation="ignore" if not config.validate_ssl else "validate",
            operation_timeout_sec=config.operation_timeout,
            read_timeout_sec=config.connection_timeout,
        )
        logger.info(f"Created WinRM session → {endpoint} (transport={config.transport})")
        return session

    def get_session(self, host: str) -> winrm.Session:
        with self._lock:
            if host not in self._configs:
                raise ValueError(f"Host '{host}' not registered. Use add_host first.")
            if host not in self._sessions:
                self._sessions[host] = self._create_session(self._configs[host])
            return self._sessions[host]

    def run_ps(self, host: str, script: str, timeout: int = 600) -> dict:
        session = self.get_session(host)
        if timeout != session.protocol.operation_timeout_sec:
            session.protocol.operation_timeout_sec = timeout
            session.protocol.read_timeout_sec = timeout + 20
        try:
            result = session.run_ps(script)
            stdout = result.std_out.decode("utf-8", errors="replace").strip()
            stderr = result.std_err.decode("utf-8", errors="replace").strip()
            return {
                "stdout": stdout,
                "stderr": stderr,
                "status_code": result.status_code,
                "success": result.status_code == 0,
            }
        except Exception as e:
            with self._lock:
                self._sessions.pop(host, None)
            raise

    def run_cmd(
        self, host: str, command: str, args: Optional[list] = None, timeout: int = 60
    ) -> dict:
        session = self.get_session(host)
        if timeout != session.protocol.operation_timeout_sec:
            session.protocol.operation_timeout_sec = timeout
            session.protocol.read_timeout_sec = timeout + 20
        try:
            result = session.run_cmd(command, args or [])
            stdout = result.std_out.decode("utf-8", errors="replace").strip()
            stderr = result.std_err.decode("utf-8", errors="replace").strip()
            return {
                "stdout": stdout,
                "stderr": stderr,
                "status_code": result.status_code,
                "success": result.status_code == 0,
            }
        except Exception as e:
            with self._lock:
                self._sessions.pop(host, None)
            raise

    def remove_host(self, host: str) -> None:
        with self._lock:
            self._configs.pop(host, None)
            self._sessions.pop(host, None)

    def list_hosts(self) -> list[str]:
        with self._lock:
            return list(self._configs.keys())

    def get_config(self, host: str) -> Optional[WinRMHostConfig]:
        with self._lock:
            return self._configs.get(host)


pool = WinRMConnectionPool()
