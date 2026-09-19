from ..core.connection import db_pool


def add_user(
    name: str,
    username: str,
    full_name: str = "",
    user_type: str = "ad_user",
    password: str = "",
    domain: str = "",
    email: str = "",
    assigned_vm: str = "",
    status: str = "active",
    notes: str = "",
) -> dict:
    result = db_pool.execute(
        name,
        "\n        INSERT INTO ad_users (username, full_name, user_type, domain,\n                           email, assigned_vm, status, notes)\n        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)\n        RETURNING id, username, user_type, status\n    ",
        [username, full_name, user_type, domain, email, assigned_vm, status, notes],
    )
    out = {"status": "ok", **result["rows"][0]}
    if password:
        out["password_ignored"] = (
            "password not stored: sql_mcp cannot encrypt secrets at rest; set per-VM/AD credentials via the panel's encrypted credential path"
        )
    return out


def list_users(name: str, user_type: str = "", status: str = "") -> list:
    query = "\n        SELECT id, username, full_name, user_type, domain, email,\n               assigned_vm, status, notes, created_at\n        FROM ad_users\n"
    conditions, params = ([], [])
    if user_type:
        conditions.append("user_type = %s")
        params.append(user_type)
    if status:
        conditions.append("status = %s")
        params.append(status)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY username"
    return db_pool.execute(name, query, params)["rows"]


def _resolve_unique_user_id(name: str, username: str):
    rows = db_pool.execute(
        name, "SELECT id FROM ad_users WHERE username = %s ORDER BY id", [username]
    )["rows"]
    if not rows:
        return (None, {"status": "error", "error": f"User '{username}' not found"})
    if len(rows) > 1:
        return (
            None,
            {
                "status": "error",
                "error": f"Ambiguous user lookup: {len(rows)} rows named '{username}' — refusing to silently pick one.",
            },
        )
    return (rows[0]["id"], None)


def get_user(name: str, username: str) -> dict:
    result = db_pool.execute(
        name,
        "\n        SELECT id, username, full_name, user_type, domain, email,\n               assigned_vm, status, notes, created_at\n        FROM ad_users WHERE username = %s\n        ORDER BY id\n    ",
        [username],
    )
    rows = result["rows"]
    if not rows:
        return {"error": f"User '{username}' not found"}
    if len(rows) > 1:
        return {
            "error": f"Ambiguous user lookup: {len(rows)} rows named '{username}' — refusing to silently pick one."
        }
    row = rows[0]
    row.pop("password", None)
    return row


def update_user(
    name: str,
    username: str,
    full_name: str = None,
    user_type: str = None,
    password: str = None,
    domain: str = None,
    email: str = None,
    assigned_vm: str = None,
    status: str = None,
    notes: str = None,
) -> dict:
    fields, values = ([], [])
    for col, val in [
        ("full_name", full_name),
        ("user_type", user_type),
        ("domain", domain),
        ("email", email),
        ("assigned_vm", assigned_vm),
        ("status", status),
        ("notes", notes),
    ]:
        if val is not None:
            fields.append(f"{col} = %s")
            values.append(val)
    _pw_note = (
        "password not stored: sql_mcp cannot encrypt secrets at rest; set per-VM/AD credentials via the panel's encrypted credential path"
        if password is not None
        else None
    )
    if not fields:
        out = {"status": "no_changes", "username": username}
        if _pw_note:
            out["password_ignored"] = _pw_note
        return out
    user_id, err = _resolve_unique_user_id(name, username)
    if err:
        return err
    values.append(user_id)
    result = db_pool.execute(
        name,
        f"UPDATE ad_users SET {', '.join(fields)} WHERE id = %s RETURNING id, username, status",
        values,
    )
    if not result["rows"]:
        return {"status": "error", "error": f"User '{username}' not found"}
    out = {"status": "ok", **result["rows"][0]}
    if _pw_note:
        out["password_ignored"] = _pw_note
    return out


def delete_user(name: str, username: str) -> dict:
    user_id, err = _resolve_unique_user_id(name, username)
    if err:
        return err
    result = db_pool.execute(
        name, "DELETE FROM ad_users WHERE id = %s RETURNING id, username", [user_id]
    )
    if not result["rows"]:
        return {"status": "error", "error": f"User '{username}' not found"}
    return {"status": "ok", "deleted": result["rows"][0]}


def get_users_by_vm(name: str, vm_name: str) -> list:
    result = db_pool.execute(
        name,
        "\n        SELECT id, username, full_name, user_type, domain, email, status, notes\n        FROM ad_users\n        WHERE assigned_vm = %s\n        ORDER BY username\n    ",
        [vm_name],
    )
    return result["rows"]
