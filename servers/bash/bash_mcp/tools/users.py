import shlex
import subprocess


def _run(cmd, timeout=15):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return (r.stdout.strip(), r.stderr.strip(), r.returncode)


def _chpasswd(username: str, password: str) -> tuple:
    if "\n" in username or "\r" in username or ":" in username:
        return ("", "Invalid username: must not contain ':' or newline", 1)
    if "\n" in password or "\r" in password:
        return ("", "Invalid password: must not contain newline", 1)
    r = subprocess.run(
        ["chpasswd"], input=f"{username}:{password}\n", capture_output=True, text=True, timeout=15
    )
    return (r.stdout.strip(), r.stderr.strip(), r.returncode)


def list_users(system_users: bool = False) -> list:
    out, _, _ = _run("getent passwd")
    result = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 7:
            continue
        uid = int(parts[2])
        if not system_users and uid < 1000 and (uid != 0):
            continue
        result.append(
            {
                "username": parts[0],
                "uid": uid,
                "gid": parts[3],
                "description": parts[4],
                "home": parts[5],
                "shell": parts[6],
            }
        )
    return result


def get_user(username: str) -> dict:
    safe = shlex.quote(username)
    out, err, rc = _run(f"id {safe}")
    if rc != 0:
        return {"error": f"User '{username}' not found"}
    passwd_out, _, _ = _run(f"getent passwd {safe}")
    parts = passwd_out.split(":") if passwd_out else []
    groups_out, _, _ = _run(f"groups {safe}")
    return {
        "username": username,
        "id_info": out,
        "home": parts[5] if len(parts) > 5 else "",
        "shell": parts[6] if len(parts) > 6 else "",
        "groups": groups_out.split(":", 1)[-1].strip() if groups_out else "",
    }


def add_user(
    username: str,
    password: str = "",
    groups: str = "",
    shell: str = "/bin/bash",
    create_home: bool = True,
) -> dict:
    safe_user = shlex.quote(username)
    safe_shell = shlex.quote(shell)
    safe_groups = shlex.quote(groups) if groups else ""
    cmd = f"useradd -m -s {safe_shell}" if create_home else f"useradd -s {safe_shell}"
    if groups:
        cmd += f" -G {safe_groups}"
    cmd += f" {safe_user}"
    out, err, rc = _run(cmd)
    if rc != 0:
        return {"status": "error", "username": username, "error": err}
    if password:
        _, perr, prc = _chpasswd(username, password)
        if prc != 0:
            return {
                "status": "partial",
                "username": username,
                "warning": "User created but password not set",
                "error": perr,
            }
    return {"status": "ok", "username": username}


def delete_user(username: str, remove_home: bool = False) -> dict:
    cmd = f"userdel {('--remove' if remove_home else '')} {shlex.quote(username)}"
    out, err, rc = _run(cmd)
    ok = rc == 0
    return {
        "status": "ok" if ok else "error",
        "username": username,
        "output": err if not ok else "deleted",
    }


def change_password(username: str, new_password: str) -> dict:
    _, err, rc = _chpasswd(username, new_password)
    ok = rc == 0
    return {
        "status": "ok" if ok else "error",
        "username": username,
        "output": err if not ok else "password changed",
    }
