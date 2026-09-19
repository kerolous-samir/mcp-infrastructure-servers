import re
import shlex
import subprocess


def _run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    return (r.stdout.strip(), r.stderr.strip(), r.returncode)


def list_services(filter_state: str = "") -> list:
    cmd = "systemctl list-units --type=service --no-pager --no-legend"
    if filter_state:
        cmd += f" --state={shlex.quote(filter_state)}"
    out, _, _ = _run(cmd)
    result = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4:
            result.append(
                {
                    "name": parts[0],
                    "load": parts[1],
                    "active": parts[2],
                    "sub": parts[3],
                    "description": parts[4] if len(parts) > 4 else "",
                }
            )
    return result


_SAFE_SERVICE = re.compile("^[\\w@:.\\\\-]+$")


def get_service(name: str) -> dict:
    if not _SAFE_SERVICE.match(name):
        return {"name": name, "error": "Invalid service name"}
    safe = shlex.quote(name)
    out, err, rc = _run(f"systemctl status {safe} --no-pager -l")
    enabled_out, _, _ = _run(f"systemctl is-enabled {safe} 2>/dev/null")
    return {"name": name, "enabled": enabled_out.strip(), "status_output": out, "returncode": rc}


def manage_service(name: str, action: str) -> dict:
    valid = {"start", "stop", "restart", "enable", "disable", "reload"}
    if action not in valid:
        return {"status": "error", "error": f"Invalid action '{action}'. Valid: {valid}"}
    if not _SAFE_SERVICE.match(name):
        return {"status": "error", "error": "Invalid service name"}
    out, err, rc = _run(f"systemctl {action} {shlex.quote(name)}")
    ok = rc == 0
    return {
        "status": "ok" if ok else "error",
        "service": name,
        "action": action,
        "output": out or err or ("ok" if ok else "failed"),
    }
