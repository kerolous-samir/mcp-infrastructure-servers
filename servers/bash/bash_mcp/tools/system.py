import os
import re
import shlex
from .remote import run as _run

_SECRET_ENV_RE = re.compile(
    "(SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|_TOKEN|TOKEN$|_DB_URL|CREDENTIAL_KEY|PRIVATE_KEY|_KEY$|SECRET_KEY)",
    re.IGNORECASE,
)
_HOSTNAME_RE = re.compile("^[A-Za-z0-9]([A-Za-z0-9.-]{0,253}[A-Za-z0-9])?$")


def get_os_info(
    host: str = "localhost", username: str = "root", password: str = None, key_path: str = None
) -> dict:
    script = '\necho "hostname=$(hostname)"\necho "os=$(lsb_release -d 2>/dev/null | cut -d: -f2 | xargs || grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d \'"\')"\necho "kernel=$(uname -r)"\necho "arch=$(uname -m)"\necho "uptime=$(uptime -p)"\necho "cpu_model=$(grep \'model name\' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)"\necho "cpu_cores=$(nproc)"\necho "memory_total=$(free -h | awk \'/^Mem:/{print $2}\')"\necho "memory_used=$(free -h | awk \'/^Mem:/{print $3}\')"\necho "memory_free=$(free -h | awk \'/^Mem:/{print $4}\')"\necho "disk_summary=$(df -h --total 2>/dev/null | tail -1)"\necho "load_avg=$(cat /proc/loadavg)"\n'
    r = _run(script.strip(), host=host, username=username, password=password, key_path=key_path)
    result = {"host": host}
    for line in r.get("stdout", "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    if not result.get("hostname"):
        result["error"] = r.get("stderr", "unknown error")
    return result


def get_uptime(
    host: str = "localhost", username: str = "root", password: str = None, key_path: str = None
) -> dict:
    script = '\necho "uptime=$(uptime -p)"\necho "since=$(uptime -s)"\necho "load_avg=$(cat /proc/loadavg)"\necho "logged_in_users=$(who | wc -l)"\n'
    r = _run(script.strip(), host=host, username=username, password=password, key_path=key_path)
    result = {"host": host}
    for line in r.get("stdout", "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def get_hostname(
    host: str = "localhost", username: str = "root", password: str = None, key_path: str = None
) -> dict:
    script = '\necho "hostname=$(hostname)"\necho "fqdn=$(hostname -f 2>/dev/null || hostname)"\necho "ip=$(hostname -I | awk \'{print $1}\')"\n'
    r = _run(script.strip(), host=host, username=username, password=password, key_path=key_path)
    result = {"host": host}
    for line in r.get("stdout", "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def set_hostname(
    new_hostname: str,
    host: str = "localhost",
    username: str = "root",
    password: str = None,
    key_path: str = None,
) -> dict:
    if not isinstance(new_hostname, str) or not _HOSTNAME_RE.match(new_hostname):
        return {
            "status": "error",
            "host": host,
            "hostname": new_hostname,
            "output": "Invalid hostname: must be RFC-1123 (alphanumeric labels with '.'/'-' separators, no spaces or shell metacharacters)",
        }
    r = _run(
        f"hostnamectl set-hostname {shlex.quote(new_hostname)}",
        host=host,
        username=username,
        password=password,
        key_path=key_path,
    )
    ok = r.get("success", False)
    return {
        "status": "ok" if ok else "error",
        "host": host,
        "hostname": new_hostname,
        "output": "Hostname updated" if ok else r.get("stderr", ""),
    }


def get_env(variable: str = "") -> dict:
    if not variable:
        return {
            "error": "A specific variable name is required. Dumping the full environment is not permitted."
        }
    is_set = variable in os.environ
    if _SECRET_ENV_RE.search(variable):
        return {"variable": variable, "value": "***redacted***", "set": is_set}
    return {"variable": variable, "value": os.environ.get(variable, ""), "set": is_set}
