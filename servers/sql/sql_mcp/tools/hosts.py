import json
from ..core.connection import db_pool


def add_host(
    name: str,
    host: str,
    ip: str,
    type: str = "physical",
    os: str = "",
    cpu_cores: int = None,
    memory_gb: float = None,
    disk_gb: float = None,
    status: str = "unknown",
    tags: list = None,
    notes: str = "",
) -> dict:
    result = db_pool.execute(
        name,
        "\n        INSERT INTO hosts (name, ip, type, os, cpu_cores, memory_gb, disk_gb, status, tags, notes)\n        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)\n        RETURNING id, name, ip, status\n    ",
        [host, ip, type, os, cpu_cores, memory_gb, disk_gb, status, json.dumps(tags or []), notes],
    )
    return {"status": "ok", **result["rows"][0]}


def list_hosts(name: str, status: str = "") -> list:
    if status:
        result = db_pool.execute(
            name,
            "SELECT id, name, ip, type, os, cpu_cores, memory_gb, disk_gb, status, tags, notes, created_at FROM hosts WHERE status = %s ORDER BY name",
            [status],
        )
    else:
        result = db_pool.execute(
            name,
            "SELECT id, name, ip, type, os, cpu_cores, memory_gb, disk_gb, status, tags, notes, created_at FROM hosts ORDER BY name",
        )
    return result["rows"]


def get_host(name: str, host_name: str) -> dict:
    result = db_pool.execute(name, "SELECT * FROM hosts WHERE name = %s", [host_name])
    if not result["rows"]:
        return {"error": f"Host '{host_name}' not found"}
    host = result["rows"][0]
    vms = db_pool.execute(
        name,
        "SELECT id, name, ip, os, status, cpu_cores, memory_gb FROM vms WHERE host_id = %s ORDER BY name",
        [host["id"]],
    )
    host["vms"] = vms["rows"]
    return host


def update_host(
    name: str,
    host_name: str,
    ip: str = None,
    type: str = None,
    os: str = None,
    cpu_cores: int = None,
    memory_gb: float = None,
    disk_gb: float = None,
    status: str = None,
    tags: list = None,
    notes: str = None,
) -> dict:
    fields, values = ([], [])
    for col, val in [
        ("ip", ip),
        ("type", type),
        ("os", os),
        ("cpu_cores", cpu_cores),
        ("memory_gb", memory_gb),
        ("disk_gb", disk_gb),
        ("status", status),
        ("notes", notes),
    ]:
        if val is not None:
            fields.append(f"{col} = %s")
            values.append(val)
    if tags is not None:
        fields.append("tags = %s")
        values.append(json.dumps(tags))
    if not fields:
        return {"status": "no_changes", "host": host_name}
    values.append(host_name)
    result = db_pool.execute(
        name,
        f"UPDATE hosts SET {', '.join(fields)} WHERE name = %s RETURNING id, name, status",
        values,
    )
    if not result["rows"]:
        return {"status": "error", "error": f"Host '{host_name}' not found"}
    return {"status": "ok", **result["rows"][0]}


def delete_host(name: str, host_name: str) -> dict:
    result = db_pool.execute(
        name, "DELETE FROM hosts WHERE name = %s RETURNING id, name", [host_name]
    )
    if not result["rows"]:
        return {"status": "error", "error": f"Host '{host_name}' not found"}
    return {"status": "ok", "deleted": result["rows"][0]}


def search_hosts(name: str, query: str) -> list:
    result = db_pool.execute(
        name,
        "\n        SELECT id, name, ip, type, os, status, tags\n        FROM hosts\n        WHERE name ILIKE %s OR ip ILIKE %s OR os ILIKE %s\n           OR tags::text ILIKE %s\n        ORDER BY name\n    ",
        [f"%{query}%"] * 4,
    )
    return result["rows"]
