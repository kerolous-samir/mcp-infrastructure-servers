import os
import subprocess
from ..core.connection import db_pool

_DEFAULT_BACKUP_DIR = "/var/backups"


def _resolve_backup_path(output_path: str) -> str:
    if output_path is None or not str(output_path).strip():
        raise ValueError("empty output_path")
    base = os.path.realpath(os.environ.get("SQL_MCP_BACKUP_DIR") or _DEFAULT_BACKUP_DIR)
    candidate = str(output_path)
    if not os.path.isabs(candidate):
        candidate = os.path.join(base, candidate)
    resolved = os.path.realpath(candidate)
    if resolved == base or resolved.startswith(base + os.sep):
        return resolved
    raise ValueError("output_path resolves outside the permitted backup directory %r" % base)


SCHEMA_SQL = "\n-- Hosts: physical machines or hypervisors\nCREATE TABLE IF NOT EXISTS hosts (\n    id          SERIAL PRIMARY KEY,\n    name        TEXT NOT NULL UNIQUE,\n    ip          TEXT NOT NULL,\n    type        TEXT DEFAULT 'physical',  -- physical, hypervisor, container\n    os          TEXT,\n    cpu_cores   INTEGER,\n    memory_gb   NUMERIC(8,2),\n    disk_gb     NUMERIC(8,2),\n    status      TEXT DEFAULT 'unknown',   -- online, offline, unknown\n    tags        JSONB DEFAULT '[]',\n    notes       TEXT DEFAULT '',\n    created_at  TIMESTAMPTZ DEFAULT NOW(),\n    updated_at  TIMESTAMPTZ DEFAULT NOW()\n);\n\n-- VMs: virtual machines linked to a host\nCREATE TABLE IF NOT EXISTS vms (\n    id            SERIAL PRIMARY KEY,\n    name          TEXT NOT NULL UNIQUE,\n    host_id       INTEGER REFERENCES hosts(id) ON DELETE SET NULL,\n    ip            TEXT,\n    os            TEXT,\n    cpu_cores     INTEGER,\n    memory_gb     NUMERIC(8,2),\n    disk_gb       NUMERIC(8,2),\n    status        TEXT DEFAULT 'unknown',  -- running, stopped, paused, unknown\n    vnc_port      INTEGER,\n    mac_address   TEXT,\n    golden_image  TEXT,\n    assigned_user TEXT DEFAULT '',        -- username assigned to this VM\n    tags          JSONB DEFAULT '[]',\n    notes         TEXT DEFAULT '',\n    created_at    TIMESTAMPTZ DEFAULT NOW(),\n    updated_at    TIMESTAMPTZ DEFAULT NOW()\n);\n\n-- Users: AD users, local admins, and service accounts\nCREATE TABLE IF NOT EXISTS users (\n    id          SERIAL PRIMARY KEY,\n    username    TEXT NOT NULL UNIQUE,\n    full_name   TEXT DEFAULT '',\n    user_type   TEXT DEFAULT 'ad_user',   -- ad_user, local_admin, service\n    password    TEXT DEFAULT '',\n    domain      TEXT DEFAULT '',\n    email       TEXT DEFAULT '',\n    assigned_vm TEXT DEFAULT '',          -- VM name this user is assigned to\n    status      TEXT DEFAULT 'active',    -- active, disabled\n    notes       TEXT DEFAULT '',\n    created_at  TIMESTAMPTZ DEFAULT NOW()\n);\n\n-- Networks: virtual networks\nCREATE TABLE IF NOT EXISTS networks (\n    id         SERIAL PRIMARY KEY,\n    name       TEXT NOT NULL UNIQUE,\n    cidr       TEXT,\n    gateway    TEXT,\n    vlan_id    INTEGER,\n    bridge     TEXT,\n    notes      TEXT DEFAULT '',\n    created_at TIMESTAMPTZ DEFAULT NOW()\n);\n\n-- Auto-update updated_at on row change\nCREATE OR REPLACE FUNCTION update_updated_at()\nRETURNS TRIGGER AS $$\nBEGIN NEW.updated_at = NOW(); RETURN NEW; END;\n$$ LANGUAGE plpgsql;\n\nDROP TRIGGER IF EXISTS trg_hosts_updated ON hosts;\nCREATE TRIGGER trg_hosts_updated\n    BEFORE UPDATE ON hosts\n    FOR EACH ROW EXECUTE FUNCTION update_updated_at();\n\nDROP TRIGGER IF EXISTS trg_vms_updated ON vms;\nCREATE TRIGGER trg_vms_updated\n    BEFORE UPDATE ON vms\n    FOR EACH ROW EXECUTE FUNCTION update_updated_at();\n"


def init_schema(name: str) -> dict:
    try:
        db_pool.execute(name, SCHEMA_SQL, fetch=False)
        return {"status": "ok", "message": "Schema created: hosts, vms, networks, users"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def backup_db(name: str, output_path: str = "/var/backups/db.sql") -> dict:
    from ..core.connection import db_pool as pool

    cfg = pool._configs.get(name)
    if not cfg:
        return {"status": "error", "error": f"Connection '{name}' not found"}
    try:
        safe_path = _resolve_backup_path(output_path)
    except ValueError as e:
        return {"status": "error", "error": f"output_path not allowed: {e}"}
    try:
        env = {**os.environ, "PGPASSWORD": cfg.password}
        r = subprocess.run(
            [
                "pg_dump",
                "-h",
                cfg.host,
                "-p",
                str(cfg.port),
                "-U",
                cfg.username,
                "-d",
                cfg.database,
                "-f",
                safe_path,
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        if r.returncode == 0:
            return {"status": "ok", "output_path": safe_path}
        return {"status": "error", "error": r.stderr}
    except Exception as e:
        return {"status": "error", "error": str(e)}
