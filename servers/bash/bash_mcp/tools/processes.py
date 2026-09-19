import os
import signal as _signal
import subprocess


def _run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    return r.stdout.strip()


def list_processes(sort_by: str = "cpu", limit: int = 20) -> list:
    sort_flag = "%cpu" if sort_by == "cpu" else "%mem"
    limit = max(1, min(int(limit), 500))
    out = _run(f"ps aux --sort=-{sort_flag} | head -{limit + 1}")
    lines = out.splitlines()
    if len(lines) < 2:
        return []
    result = []
    for line in lines[1:]:
        parts = line.split(None, 10)
        if len(parts) >= 11:
            result.append(
                {
                    "user": parts[0],
                    "pid": parts[1],
                    "cpu": parts[2],
                    "mem": parts[3],
                    "vsz": parts[4],
                    "rss": parts[5],
                    "stat": parts[7],
                    "start": parts[8],
                    "time": parts[9],
                    "command": parts[10],
                }
            )
    return result


def get_process(pid: int) -> dict:
    pid = int(pid)
    out = _run(f"ps -p {pid} -o pid,user,%cpu,%mem,vsz,rss,stat,start,time,cmd --no-headers")
    if not out:
        return {"error": f"PID {pid} not found"}
    parts = out.split(None, 9)
    if len(parts) < 10:
        return {"error": "Could not parse process info"}
    return {
        "pid": parts[0],
        "user": parts[1],
        "cpu": parts[2],
        "mem": parts[3],
        "vsz": parts[4],
        "rss": parts[5],
        "stat": parts[6],
        "start": parts[7],
        "time": parts[8],
        "command": parts[9],
    }


def kill_process(pid: int, signal: str = "TERM") -> dict:
    _signal_map = {
        "TERM": _signal.SIGTERM,
        "KILL": _signal.SIGKILL,
        "HUP": _signal.SIGHUP,
        "INT": _signal.SIGINT,
    }
    sig = _signal_map.get(signal.upper())
    if sig is None:
        return {
            "status": "error",
            "pid": pid,
            "signal": signal,
            "output": f"Invalid signal '{signal}'. Allowed: {list(_signal_map)}",
        }
    try:
        os.kill(int(pid), sig)
        return {
            "status": "ok",
            "pid": pid,
            "signal": signal,
            "output": f"Signal {signal} sent to PID {pid}",
        }
    except ProcessLookupError:
        return {"status": "error", "pid": pid, "signal": signal, "output": f"PID {pid} not found"}
    except PermissionError:
        return {
            "status": "error",
            "pid": pid,
            "signal": signal,
            "output": f"Permission denied to signal PID {pid}",
        }
    except Exception as e:
        return {"status": "error", "pid": pid, "signal": signal, "output": str(e)}
