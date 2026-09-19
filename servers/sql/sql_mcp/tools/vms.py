import json
from ..core.connection import db_pool


def _resolve_host_id(name: str, host_name: str) -> int:
    result = db_pool.execute(name, "SELECT id FROM hosts WHERE name = %s ORDER BY id", [host_name])
    if not result["rows"]:
        raise ValueError(f"Host '{host_name}' not found in database")
    if len(result["rows"]) > 1:
        raise ValueError(f"Ambiguous host lookup: {len(result['rows'])} hosts named '{host_name}'")
    return result["rows"][0]["id"]


def _resolve_unique_vm_id(name: str, vm_name: str):
    rows = db_pool.execute(name, "SELECT id FROM vms WHERE name = %s ORDER BY id", [vm_name])[
        "rows"
    ]
    if not rows:
        return (None, {"status": "error", "error": f"VM '{vm_name}' not found"})
    if len(rows) > 1:
        return (
            None,
            {
                "status": "error",
                "error": f"Ambiguous VM lookup: {len(rows)} VMs named '{vm_name}'; refusing to silently pick one.",
            },
        )
    return (rows[0]["id"], None)


def add_vm(
    name: str,
    vm_name: str,
    ip: str = "",
    os: str = "",
    host_name: str = None,
    cpu_cores: int = None,
    memory_gb: float = None,
    disk_gb: float = None,
    status: str = "unknown",
    vnc_port: int = None,
    mac_address: str = "",
    golden_image: str = "",
    assigned_user: str = "",
    tags: list = None,
    notes: str = "",
) -> dict:
    host_id = _resolve_host_id(name, host_name) if host_name else None
    result = db_pool.execute(
        name,
        "\n        INSERT INTO vms (name, host_id, ip, os, cpu_cores, memory_gb, disk_gb,\n                         status, vnc_port, mac_address, golden_image, assigned_user, tags, notes)\n        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)\n        RETURNING id, name, ip, status\n    ",
        [
            vm_name,
            host_id,
            ip,
            os,
            cpu_cores,
            memory_gb,
            disk_gb,
            status,
            vnc_port,
            mac_address,
            golden_image,
            assigned_user,
            json.dumps(tags or []),
            notes,
        ],
    )
    return {"status": "ok", **result["rows"][0]}


def list_vms(name: str, status: str = "") -> list:
    query = "\n        SELECT v.id, v.name, v.ip, v.os, v.cpu_cores, v.memory_gb, v.disk_gb,\n               v.status, v.vnc_port, v.mac_address, v.assigned_user, v.tags,\n               h.name AS host_name, h.ip AS host_ip\n        FROM vms v\n        LEFT JOIN hosts h ON v.host_id = h.id\n    "
    params = []
    if status:
        query += " WHERE v.status = %s"
        params.append(status)
    query += " ORDER BY v.name"
    return db_pool.execute(name, query, params)["rows"]


def get_vm(name: str, vm_name: str) -> dict:
    vm_id, err = _resolve_unique_vm_id(name, vm_name)
    if err:
        return {"error": err["error"]}
    result = db_pool.execute(
        name,
        "\n        SELECT v.*, h.name AS host_name, h.ip AS host_ip, h.type AS host_type\n        FROM vms v\n        LEFT JOIN hosts h ON v.host_id = h.id\n        WHERE v.id = %s\n    ",
        [vm_id],
    )
    if not result["rows"]:
        return {"error": f"VM '{vm_name}' not found"}
    return result["rows"][0]


def update_vm(
    name: str,
    vm_name: str,
    ip: str = None,
    os: str = None,
    host_name: str = None,
    cpu_cores: int = None,
    memory_gb: float = None,
    disk_gb: float = None,
    status: str = None,
    vnc_port: int = None,
    mac_address: str = None,
    golden_image: str = None,
    assigned_user: str = None,
    tags: list = None,
    notes: str = None,
) -> dict:
    fields, values = ([], [])
    if host_name is not None:
        fields.append("host_id = %s")
        values.append(_resolve_host_id(name, host_name))
    for col, val in [
        ("ip", ip),
        ("os", os),
        ("cpu_cores", cpu_cores),
        ("memory_gb", memory_gb),
        ("disk_gb", disk_gb),
        ("status", status),
        ("vnc_port", vnc_port),
        ("mac_address", mac_address),
        ("golden_image", golden_image),
        ("assigned_user", assigned_user),
        ("notes", notes),
    ]:
        if val is not None:
            fields.append(f"{col} = %s")
            values.append(val)
    if tags is not None:
        fields.append("tags = %s")
        values.append(json.dumps(tags))
    if not fields:
        return {"status": "no_changes", "vm": vm_name}
    vm_id, err = _resolve_unique_vm_id(name, vm_name)
    if err:
        return err
    values.append(vm_id)
    result = db_pool.execute(
        name, f"UPDATE vms SET {', '.join(fields)} WHERE id = %s RETURNING id, name, status", values
    )
    if not result["rows"]:
        return {"status": "error", "error": f"VM '{vm_name}' not found"}
    return {"status": "ok", **result["rows"][0]}


def delete_vm(name: str, vm_name: str) -> dict:
    vm_id, err = _resolve_unique_vm_id(name, vm_name)
    if err:
        return err
    result = db_pool.execute(name, "DELETE FROM vms WHERE id = %s RETURNING id, name", [vm_id])
    if not result["rows"]:
        return {"status": "error", "error": f"VM '{vm_name}' not found"}
    return {"status": "ok", "deleted": result["rows"][0]}


def get_vms_by_host(name: str, host_name: str) -> list:
    result = db_pool.execute(
        name,
        "\n        SELECT v.id, v.name, v.ip, v.os, v.status, v.cpu_cores,\n               v.memory_gb, v.disk_gb, v.vnc_port, v.tags\n        FROM vms v\n        JOIN hosts h ON v.host_id = h.id\n        WHERE h.name = %s\n        ORDER BY v.name\n    ",
        [host_name],
    )
    return result["rows"]


def search_vms(name: str, query: str) -> list:
    result = db_pool.execute(
        name,
        "\n        SELECT v.id, v.name, v.ip, v.os, v.status, v.tags,\n               h.name AS host_name\n        FROM vms v\n        LEFT JOIN hosts h ON v.host_id = h.id\n        WHERE v.name ILIKE %s OR v.ip ILIKE %s OR v.os ILIKE %s\n           OR v.tags::text ILIKE %s\n        ORDER BY v.name\n    ",
        [f"%{query}%"] * 4,
    )
    return result["rows"]


def get_summary(name: str) -> dict:
    hosts = db_pool.execute(
        name, "SELECT status, COUNT(*) AS count FROM hosts GROUP BY status ORDER BY status"
    )
    vms = db_pool.execute(
        name, "SELECT status, COUNT(*) AS count FROM vms GROUP BY status ORDER BY status"
    )
    total_h = db_pool.execute(name, "SELECT COUNT(*) AS total FROM hosts")
    total_v = db_pool.execute(name, "SELECT COUNT(*) AS total FROM vms")
    return {
        "total_hosts": total_h["rows"][0]["total"],
        "total_vms": total_v["rows"][0]["total"],
        "hosts_by_status": hosts["rows"],
        "vms_by_status": vms["rows"],
    }
