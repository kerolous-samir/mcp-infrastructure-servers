import re
import shlex
from .remote import run as _run

_SAFE_PKG = re.compile("^[\\w.+\\-]+$")
_APT_ENV = f"DEBIAN_FRONTEND=noninteractive"


def _apt(cmd: str, host: str, username: str, password: str, key_path: str, timeout: int = 120):
    return _run(
        f"{_APT_ENV} {cmd}",
        host=host,
        username=username,
        password=password,
        key_path=key_path,
        timeout=timeout,
    )


def list_packages(
    filter_name: str = "",
    host: str = "localhost",
    username: str = "root",
    password: str = None,
    key_path: str = None,
) -> list:
    cmd = "dpkg -l"
    if filter_name:
        cmd += f" | grep -i {shlex.quote(filter_name)}"
    result = _run(cmd, host=host, username=username, password=password, key_path=key_path)
    out = result.get("stdout", "")
    packages = []
    for line in out.splitlines():
        if not line.startswith("ii"):
            continue
        parts = line.split(None, 4)
        if len(parts) >= 4:
            packages.append(
                {
                    "name": parts[1],
                    "version": parts[2],
                    "arch": parts[3],
                    "description": parts[4] if len(parts) > 4 else "",
                }
            )
    return packages


def install_package(
    packages: str,
    host: str = "localhost",
    username: str = "root",
    password: str = None,
    key_path: str = None,
) -> dict:
    pkg_list = packages.split()
    if not pkg_list or not all((_SAFE_PKG.match(p) for p in pkg_list)):
        return {"status": "error", "packages": packages, "output": "Invalid package name(s)"}
    safe_pkgs = " ".join((shlex.quote(p) for p in pkg_list))
    r = _apt(f"apt-get install -y -- {safe_pkgs}", host, username, password, key_path)
    ok = r.get("success", False)
    return {
        "status": "ok" if ok else "error",
        "host": host,
        "packages": packages,
        "output": r["stdout"] if ok else r["stderr"],
    }


def remove_package(
    packages: str,
    purge: bool = False,
    host: str = "localhost",
    username: str = "root",
    password: str = None,
    key_path: str = None,
) -> dict:
    pkg_list = packages.split()
    if not pkg_list or not all((_SAFE_PKG.match(p) for p in pkg_list)):
        return {"status": "error", "packages": packages, "output": "Invalid package name(s)"}
    safe_pkgs = " ".join((shlex.quote(p) for p in pkg_list))
    cmd = f"apt-get {('purge' if purge else 'remove')} -y -- {safe_pkgs}"
    r = _apt(cmd, host, username, password, key_path)
    ok = r.get("success", False)
    return {
        "status": "ok" if ok else "error",
        "host": host,
        "packages": packages,
        "output": r["stdout"] if ok else r["stderr"],
    }


def search_package(
    query: str,
    host: str = "localhost",
    username: str = "root",
    password: str = None,
    key_path: str = None,
) -> list:
    r = _run(
        f"apt-cache search {shlex.quote(query)}",
        host=host,
        username=username,
        password=password,
        key_path=key_path,
    )
    result = []
    for line in r.get("stdout", "").splitlines():
        if " - " in line:
            name, desc = line.split(" - ", 1)
            result.append({"name": name.strip(), "description": desc.strip()})
    return result[:50]


def update_packages(
    host: str = "localhost", username: str = "root", password: str = None, key_path: str = None
) -> dict:
    r = _apt("apt-get update", host, username, password, key_path, timeout=180)
    ok = r.get("success", False)
    return {
        "status": "ok" if ok else "error",
        "host": host,
        "output": r["stdout"] if ok else r["stderr"],
    }
