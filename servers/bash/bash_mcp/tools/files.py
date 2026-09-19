import os
import shutil
import glob as _glob


class PathNotAllowed(Exception):
    pass


def _managed_default_root() -> str:
    for candidate in ("/var/lib/mcp/bash_mcp", "/srv/mcp/bash_mcp"):
        try:
            os.makedirs(candidate, exist_ok=True)
            return os.path.realpath(candidate)
        except Exception:
            continue
    fallback = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bash_mcp_root")
    try:
        os.makedirs(fallback, exist_ok=True)
    except Exception:
        pass
    return os.path.realpath(fallback)


def _allowed_roots() -> list:
    raw = os.environ.get("BASH_MCP_ALLOWED_ROOTS") or os.environ.get("BASH_MCP_ROOT")
    roots = []
    if raw:
        for part in raw.split(os.pathsep):
            part = part.strip()
            if not part:
                continue
            try:
                rp = os.path.realpath(part)
            except Exception:
                continue
            if os.path.isabs(rp):
                roots.append(rp)
    if not roots:
        roots.append(_managed_default_root())
    return roots


def _is_within(child: str, root: str) -> bool:
    root = root.rstrip(os.sep) or os.sep
    if child == root:
        return True
    return child.startswith(root + os.sep)


def _safe_resolve(path: str) -> str:
    if path is None or not str(path).strip():
        raise PathNotAllowed("empty path")
    roots = _allowed_roots()
    if not os.path.isabs(path):
        path = os.path.join(roots[0], path)
    cur = path
    tail = []
    while True:
        if os.path.lexists(cur):
            real_existing = os.path.realpath(cur)
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            real_existing = os.path.realpath(cur)
            break
        tail.append(os.path.basename(cur))
        cur = parent
    resolved = real_existing
    for comp in reversed(tail):
        resolved = os.path.join(resolved, comp)
    resolved = os.path.normpath(resolved)
    for root in roots:
        if _is_within(resolved, root):
            return resolved
    raise PathNotAllowed("path '%s' resolves outside the permitted root(s)" % path)


def read_file(path: str, offset: int = 0, limit: int = 200) -> dict:
    try:
        safe = _safe_resolve(path)
    except PathNotAllowed as e:
        return {"error": "path not allowed: %s" % e, "path": path}
    try:
        with open(safe, "r", errors="replace") as f:
            lines = f.readlines()
        total = len(lines)
        chunk = lines[offset : offset + limit]
        return {
            "path": path,
            "total_lines": total,
            "offset": offset,
            "returned_lines": len(chunk),
            "content": "".join(chunk),
        }
    except Exception as e:
        return {"error": str(e), "path": path}


def write_file(path: str, content: str, append: bool = False) -> dict:
    try:
        safe = _safe_resolve(path)
    except PathNotAllowed as e:
        return {"status": "error", "path": path, "error": "path not allowed: %s" % e}
    try:
        os.makedirs(os.path.dirname(safe) or ".", exist_ok=True)
        mode = "a" if append else "w"
        with open(safe, mode) as f:
            f.write(content)
        return {"status": "ok", "path": path, "bytes_written": len(content.encode())}
    except Exception as e:
        return {"status": "error", "path": path, "error": str(e)}


def list_directory(path: str = "/", show_hidden: bool = False) -> list:
    try:
        safe = _safe_resolve(path)
    except PathNotAllowed as e:
        return [{"error": "path not allowed: %s" % e}]
    try:
        entries = []
        for name in sorted(os.listdir(safe)):
            if not show_hidden and name.startswith("."):
                continue
            full = os.path.join(safe, name)
            try:
                st = os.stat(full)
                entries.append(
                    {
                        "name": name,
                        "type": "dir" if os.path.isdir(full) else "file",
                        "size": st.st_size,
                        "permissions": oct(st.st_mode)[-4:],
                    }
                )
            except Exception:
                entries.append({"name": name, "type": "unknown", "size": 0})
        return entries
    except Exception as e:
        return [{"error": str(e)}]


def delete_file(path: str, recursive: bool = False) -> dict:
    try:
        safe = _safe_resolve(path)
    except PathNotAllowed as e:
        return {"status": "error", "path": path, "error": "path not allowed: %s" % e}
    if safe in _allowed_roots():
        return {
            "status": "error",
            "path": path,
            "error": "refusing to delete a permitted root directory",
        }
    try:
        if os.path.isdir(safe) and (not os.path.islink(safe)):
            if recursive:
                shutil.rmtree(safe)
            else:
                os.rmdir(safe)
        else:
            os.remove(safe)
        return {"status": "ok", "path": path}
    except Exception as e:
        return {"status": "error", "path": path, "error": str(e)}


def copy_file(src: str, dst: str) -> dict:
    try:
        safe_src = _safe_resolve(src)
        safe_dst = _safe_resolve(dst)
    except PathNotAllowed as e:
        return {"status": "error", "src": src, "dst": dst, "error": "path not allowed: %s" % e}
    try:
        if os.path.isdir(safe_src) and (not os.path.islink(safe_src)):
            shutil.copytree(safe_src, safe_dst)
        else:
            os.makedirs(os.path.dirname(safe_dst) or ".", exist_ok=True)
            shutil.copy2(safe_src, safe_dst)
        return {"status": "ok", "src": src, "dst": dst}
    except Exception as e:
        return {"status": "error", "src": src, "dst": dst, "error": str(e)}


def move_file(src: str, dst: str) -> dict:
    try:
        safe_src = _safe_resolve(src)
        safe_dst = _safe_resolve(dst)
    except PathNotAllowed as e:
        return {"status": "error", "src": src, "dst": dst, "error": "path not allowed: %s" % e}
    try:
        os.makedirs(os.path.dirname(safe_dst) or ".", exist_ok=True)
        shutil.move(safe_src, safe_dst)
        return {"status": "ok", "src": src, "dst": dst}
    except Exception as e:
        return {"status": "error", "src": src, "dst": dst, "error": str(e)}


def find_files(path: str, pattern: str = "*", max_results: int = 100) -> list:
    try:
        safe = _safe_resolve(path)
    except PathNotAllowed as e:
        return [{"error": "path not allowed: %s" % e}]
    try:
        matches = _glob.glob(os.path.join(safe, "**", pattern), recursive=True)
        results = []
        for m in sorted(matches):
            try:
                _safe_resolve(m)
            except PathNotAllowed:
                continue
            results.append(
                {
                    "path": m,
                    "type": "dir" if os.path.isdir(m) else "file",
                    "size": os.path.getsize(m) if os.path.isfile(m) else 0,
                }
            )
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        return [{"error": str(e)}]
