import base64
import json
import logging
import os
from ..core.connection import pool

logger = logging.getLogger(__name__)
CHUNK_SIZE = 400 * 1024
_PS_SQUOTES = "'‘’‚‛"
_DEFAULT_STAGING_ROOT = "/var/lib/mcp-winrm/staging"


def _staging_root() -> str:
    return os.environ.get("WINRM_MCP_STAGING_ROOT", _DEFAULT_STAGING_ROOT)


def _confine(local_path: str) -> str:
    root = os.path.realpath(_staging_root())
    candidate = local_path if os.path.isabs(local_path) else os.path.join(root, local_path)
    resolved = os.path.realpath(candidate)
    if resolved != root and (not resolved.startswith(root + os.sep)):
        raise ValueError(
            f"local_path escapes the WinRM staging root ({root}); pass a path inside the staging directory."
        )
    return resolved


def _q(s) -> str:
    s = str(s)
    for ch in _PS_SQUOTES:
        s = s.replace(ch, ch * 2)
    return s


def upload_file(host: str, local_path: str, remote_path: str) -> dict:
    try:
        local_path = _confine(local_path)
    except ValueError as e:
        return {"error": str(e)}
    if not os.path.exists(local_path):
        return {"error": f"Local file not found: {local_path}"}
    with open(local_path, "rb") as f:
        data = f.read()
    file_size = len(data)
    chunks = [data[i : i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]
    b64 = base64.b64encode(chunks[0]).decode()
    r = pool.run_ps(
        host,
        f"\n$bytes = [System.Convert]::FromBase64String('{b64}')\n[System.IO.File]::WriteAllBytes('{_q(remote_path)}', $bytes)\n",
    )
    if not r["success"]:
        return {"error": r["stderr"]}
    for chunk in chunks[1:]:
        b64 = base64.b64encode(chunk).decode()
        r = pool.run_ps(
            host,
            f"\n$bytes = [System.Convert]::FromBase64String('{b64}')\n$stream = [System.IO.File]::Open('{_q(remote_path)}', [System.IO.FileMode]::Append)\n$stream.Write($bytes, 0, $bytes.Length)\n$stream.Close()\n",
        )
        if not r["success"]:
            return {"error": r["stderr"]}
    return {
        "status": "ok",
        "host": host,
        "local_path": local_path,
        "remote_path": remote_path,
        "size_bytes": file_size,
        "chunks": len(chunks),
    }


def download_file(host: str, remote_path: str, local_path: str) -> dict:
    r = pool.run_ps(
        host,
        f"\n$bytes = [System.IO.File]::ReadAllBytes('{_q(remote_path)}')\n[System.Convert]::ToBase64String($bytes)\n",
    )
    if not r["success"]:
        return {"error": r["stderr"]}
    try:
        local_path = _confine(local_path)
    except ValueError as e:
        return {"error": str(e)}
    data = base64.b64decode(r["stdout"])
    os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(data)
    return {
        "status": "ok",
        "host": host,
        "remote_path": remote_path,
        "local_path": local_path,
        "size_bytes": len(data),
    }


def list_directory(host: str, path: str) -> list:
    r = pool.run_ps(
        host,
        f"\n@(Get-ChildItem -Path '{_q(path)}' -ErrorAction Stop |\n    Select-Object Name,\n        @{{N='Size_KB';   E={{if($_.PSIsContainer){{$null}}else{{[math]::Round($_.Length / 1KB, 2)}}}}}},\n        @{{N='Modified';  E={{$_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')}}}},\n        @{{N='Type';      E={{if($_.PSIsContainer){{'Directory'}}else{{'File'}}}}}},\n        @{{N='Hidden';    E={{$_.Attributes -band [System.IO.FileAttributes]::Hidden -ne 0}}}}) |\n    ConvertTo-Json\n",
    )
    if not r["success"]:
        raise RuntimeError(r["stderr"])
    return json.loads(r["stdout"]) if r["stdout"] else []


def delete_file(host: str, path: str, recursive: bool = False) -> dict:
    recurse_flag = "-Recurse" if recursive else ""
    r = pool.run_ps(host, f"Remove-Item -Path '{_q(path)}' {recurse_flag} -Force -ErrorAction Stop")
    return {
        "status": "ok" if r["success"] else "error",
        "host": host,
        "path": path,
        "output": r["stderr"] if not r["success"] else f"'{path}' deleted",
    }
