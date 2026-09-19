import shlex
import subprocess


def _run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    return r.stdout.strip()


def get_disk_usage() -> list:
    out = _run("df -h --output=source,fstype,size,used,avail,pcent,target")
    lines = out.splitlines()
    if not lines:
        return []
    result = []
    for line in lines[1:]:
        parts = line.split(None, 6)
        if len(parts) == 7:
            result.append(
                {
                    "device": parts[0],
                    "fstype": parts[1],
                    "size": parts[2],
                    "used": parts[3],
                    "avail": parts[4],
                    "use_pct": parts[5],
                    "mount": parts[6],
                }
            )
    return result


def list_mounts() -> list:
    out = _run("findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS --list --noheadings")
    result = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3:
            result.append(
                {
                    "target": parts[0],
                    "source": parts[1],
                    "fstype": parts[2],
                    "options": parts[3] if len(parts) > 3 else "",
                }
            )
    return result


def get_directory_size(path: str) -> dict:
    out = _run(f"du -sh {shlex.quote(path)} 2>/dev/null")
    if not out:
        return {"error": f"Path not found: {path}"}
    parts = out.split(None, 1)
    return {"path": path, "size": parts[0] if parts else "?"}
