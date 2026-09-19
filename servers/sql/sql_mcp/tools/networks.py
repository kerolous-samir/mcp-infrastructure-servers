from ..core.connection import db_pool


def add_network(
    name: str,
    net_name: str,
    cidr: str = "",
    gateway: str = "",
    vlan_id: int = None,
    bridge: str = "",
    notes: str = "",
) -> dict:
    result = db_pool.execute(
        name,
        "\n        INSERT INTO networks (name, cidr, gateway, vlan_id, bridge, notes)\n        VALUES (%s, %s, %s, %s, %s, %s)\n        RETURNING id, name, cidr\n    ",
        [net_name, cidr, gateway, vlan_id, bridge, notes],
    )
    return {"status": "ok", **result["rows"][0]}


def list_networks(name: str) -> list:
    return db_pool.execute(name, "SELECT * FROM networks ORDER BY name")["rows"]


def get_network(name: str, net_name: str) -> dict:
    result = db_pool.execute(name, "SELECT * FROM networks WHERE name = %s", [net_name])
    if not result["rows"]:
        return {"error": f"Network '{net_name}' not found"}
    return result["rows"][0]


def update_network(
    name: str,
    net_name: str,
    cidr: str = None,
    gateway: str = None,
    vlan_id: int = None,
    bridge: str = None,
    notes: str = None,
) -> dict:
    fields, values = ([], [])
    for col, val in [
        ("cidr", cidr),
        ("gateway", gateway),
        ("vlan_id", vlan_id),
        ("bridge", bridge),
        ("notes", notes),
    ]:
        if val is not None:
            fields.append(f"{col} = %s")
            values.append(val)
    if not fields:
        return {"status": "no_changes", "network": net_name}
    values.append(net_name)
    result = db_pool.execute(
        name, f"UPDATE networks SET {', '.join(fields)} WHERE name = %s RETURNING id, name", values
    )
    if not result["rows"]:
        return {"status": "error", "error": f"Network '{net_name}' not found"}
    return {"status": "ok", **result["rows"][0]}


def delete_network(name: str, net_name: str) -> dict:
    result = db_pool.execute(
        name, "DELETE FROM networks WHERE name = %s RETURNING id, name", [net_name]
    )
    if not result["rows"]:
        return {"status": "error", "error": f"Network '{net_name}' not found"}
    return {"status": "ok", "deleted": result["rows"][0]}
