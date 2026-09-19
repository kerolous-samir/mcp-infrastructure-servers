import os
import shlex
import subprocess

_IS_LOCAL = {"localhost", "127.0.0.1", "::1", ""}


def is_remote(host: str) -> bool:
    return host.strip().lower() not in _IS_LOCAL


def run(
    cmd: str,
    host: str = "localhost",
    username: str = "root",
    password: str | None = None,
    key_path: str | None = None,
    timeout: int = 120,
    cwd: str | None = None,
) -> dict:
    if cwd and is_remote(host):
        cmd = f"cd {shlex.quote(cwd)} && {cmd}"
    if not is_remote(host):
        return _local(cmd, timeout=timeout, cwd=cwd)
    ssh_opts = "-o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15"
    if key_path:
        ssh_opts += f" -i {shlex.quote(key_path)}"
    remote_cmd = f"ssh {ssh_opts} {shlex.quote(f'{username}@{host}')} {shlex.quote(cmd)}"
    if password:
        remote_cmd = "sshpass -e " + remote_cmd
        return _local(remote_cmd, timeout=timeout, env={"SSHPASS": password})
    return _local(remote_cmd, timeout=timeout)


def _local(cmd: str, timeout: int = 120, cwd: str | None = None, env: dict | None = None) -> dict:
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or "/",
            env={**os.environ, **env} if env else None,
        )
        return {
            "returncode": r.returncode,
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip(),
            "success": r.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Timed out after {timeout}s",
            "success": False,
        }
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e), "success": False}
