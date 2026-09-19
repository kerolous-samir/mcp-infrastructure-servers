import logging
from ..core.connection import pool, WinRMHostConfig

logger = logging.getLogger(__name__)


def _register_single(
    host: str,
    username: str,
    password: str,
    port: int,
    transport: str,
    use_ssl: bool,
    validate_ssl: bool,
) -> dict:
    config = WinRMHostConfig(
        host=host,
        username=username,
        password=password,
        port=port,
        transport=transport,
        use_ssl=use_ssl,
        validate_ssl=validate_ssl,
    )
    pool.register_host(config)
    try:
        result = pool.run_ps(host, "$env:COMPUTERNAME")
        if result["success"]:
            return {
                "status": "registered_and_connected",
                "host": host,
                "computer_name": result["stdout"],
                "transport": transport,
                "port": port,
            }
        else:
            return {"status": "registered_but_auth_failed", "host": host, "error": result["stderr"]}
    except Exception as e:
        return {
            "status": "registered_but_connection_failed",
            "host": host,
            "error": str(e),
            "tip": "Ensure WinRM is enabled on the target: run 'winrm quickconfig' as Administrator",
        }


def add_host(
    host,
    username: str,
    password: str,
    port: int = 5985,
    transport: str = "ntlm",
    use_ssl: bool = False,
    validate_ssl: bool = True,
):
    if isinstance(host, list):
        return [
            _register_single(h, username, password, port, transport, use_ssl, validate_ssl)
            for h in host
        ]
    return _register_single(host, username, password, port, transport, use_ssl, validate_ssl)


def list_hosts() -> list:
    hosts = pool.list_hosts()
    result = []
    for host in hosts:
        config = pool.get_config(host)
        try:
            r = pool.run_ps(host, "$env:COMPUTERNAME")
            result.append(
                {
                    "host": host,
                    "status": "connected",
                    "computer_name": r["stdout"],
                    "transport": config.transport,
                    "port": config.port,
                }
            )
        except Exception as e:
            result.append({"host": host, "status": "disconnected", "error": str(e)})
    return result


def remove_host(host: str) -> dict:
    pool.remove_host(host)
    return {"status": "removed", "host": host}


def test_connection(host: str) -> dict:
    try:
        r = pool.run_ps(
            host,
            "\n[PSCustomObject]@{\n    ComputerName = $env:COMPUTERNAME\n    OSVersion    = (Get-CimInstance Win32_OperatingSystem).Caption\n    Uptime       = ((Get-Date) - (gcim Win32_OperatingSystem).LastBootUpTime).ToString('dd\\.hh\\:mm\\:ss')\n    PSVersion    = $PSVersionTable.PSVersion.ToString()\n} | ConvertTo-Json\n",
        )
        if r["success"]:
            import json

            info = json.loads(r["stdout"])
            return {"status": "ok", "host": host, "reachable": True, **info}
        else:
            return {"status": "failed", "host": host, "reachable": False, "error": r["stderr"]}
    except Exception as e:
        return {"status": "failed", "host": host, "reachable": False, "error": str(e)}
