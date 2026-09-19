import shlex
import subprocess


def _run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return (r.stdout.strip(), r.returncode)
    except Exception as e:
        return (str(e), -1)


def get_interfaces() -> list:
    out, _ = _run("ip -o addr show")
    ifaces = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        name = parts[1]
        family = parts[2]
        addr = parts[3]
        if name not in ifaces:
            ifaces[name] = {"name": name, "addresses": [], "state": "unknown"}
        ifaces[name]["addresses"].append({"family": family, "address": addr})
    out2, _ = _run("ip -o link show")
    for line in out2.splitlines():
        parts = line.split()
        if len(parts) < 9:
            continue
        name = parts[1].rstrip(":")
        if name in ifaces:
            ifaces[name]["state"] = "up" if "UP" in parts else "down"
            if "link/ether" in line:
                idx = line.index("link/ether")
                ifaces[name]["mac"] = line[idx:].split()[1]
    return list(ifaces.values())


def get_routes() -> list:
    out, _ = _run("ip route show")
    routes = []
    for line in out.splitlines():
        parts = line.split()
        routes.append({"destination": parts[0] if parts else "", "raw": line})
    return routes


def ping(host: str, count: int = 4) -> dict:
    count = max(1, min(int(count), 20))
    out, rc = _run(f"ping -c {count} -W 2 {shlex.quote(host)}")
    return {"host": host, "reachable": rc == 0, "output": out}


def get_connections(port: int = None) -> list:
    cmd = "ss -tunp"
    if port:
        cmd += f" | grep ':{int(port)}'"
    out, _ = _run(cmd)
    result = []
    for line in out.splitlines():
        if line.startswith("Netid") or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 5:
            result.append(
                {
                    "proto": parts[0],
                    "state": parts[1],
                    "local": parts[4] if len(parts) > 4 else "",
                    "remote": parts[5] if len(parts) > 5 else "",
                    "process": parts[6] if len(parts) > 6 else "",
                }
            )
    return result
