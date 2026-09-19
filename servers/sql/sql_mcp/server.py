import asyncio, json, logging, os, sys
from pathlib import Path
from typing import Any
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass
from sql_mcp.tools.db import (
    connect_db,
    disconnect_db,
    list_connections,
    test_connection,
    execute_query,
    execute_statement,
    list_tables,
    describe_table,
    get_table_stats,
)
from sql_mcp.tools.schema import init_schema, backup_db
from sql_mcp.tools.hosts import (
    add_host,
    list_hosts,
    get_host,
    update_host,
    delete_host,
    search_hosts,
)
from sql_mcp.tools.vms import (
    add_vm,
    list_vms,
    get_vm,
    update_vm,
    delete_vm,
    get_vms_by_host,
    search_vms,
    get_summary,
)
from sql_mcp.tools.networks import (
    add_network,
    list_networks,
    get_network,
    update_network,
    delete_network,
)
from sql_mcp.tools.users import (
    add_user,
    list_users,
    get_user,
    update_user,
    delete_user,
    get_users_by_vm,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("sql_mcp")
server = Server("sql-mcp")
_DB_ALIAS = os.environ.get("DB_DATABASE", "the lab database")


def _db_name_desc():
    return f"Connection alias (use '{_DB_ALIAS}')"


TOOLS = [
    types.Tool(
        name="connect_db",
        description="Connect to a PostgreSQL database.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Alias for this connection e.g. inventory",
                },
                "host": {"type": "string", "description": "DB host IP or hostname"},
                "database": {"type": "string", "description": "Database name"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "port": {"type": "integer", "default": 5432},
            },
            "required": ["name", "host", "database", "username", "password"],
        },
    ),
    types.Tool(
        name="disconnect_db",
        description="Close and remove a database connection.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"}
            },
            "required": [],
        },
    ),
    types.Tool(
        name="list_connections",
        description="List all registered database connections.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="test_connection",
        description="Test a database connection.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"}
            },
            "required": [],
        },
    ),
    types.Tool(
        name="execute_query",
        description="Run a SELECT query and return rows.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "query": {"type": "string", "description": "SQL SELECT query"},
                "params": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="execute_statement",
        description="Run an INSERT, UPDATE, DELETE, or DDL statement.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "statement": {"type": "string"},
                "params": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["statement"],
        },
    ),
    types.Tool(
        name="list_tables",
        description="List all tables in the database.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "schema": {"type": "string", "default": "public"},
            },
            "required": [],
        },
    ),
    types.Tool(
        name="describe_table",
        description="Show columns, types, and constraints of a table.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "table": {"type": "string"},
                "schema": {"type": "string", "default": "public"},
            },
            "required": ["table"],
        },
    ),
    types.Tool(
        name="get_table_stats",
        description="Get row counts and sizes for all tables.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "schema": {"type": "string", "default": "public"},
            },
            "required": [],
        },
    ),
    types.Tool(
        name="init_schema",
        description="Create the hosts, vms, and networks tables with triggers.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"}
            },
            "required": [],
        },
    ),
    types.Tool(
        name="backup_db",
        description="Dump the database to a SQL file using pg_dump.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "output_path": {"type": "string", "default": "/var/backups/inventory.sql"},
            },
            "required": [],
        },
    ),
    types.Tool(
        name="add_host",
        description="Add a host (physical machine or hypervisor) to the inventory.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias"},
                "host": {"type": "string", "description": "Hostname/label for this machine"},
                "ip": {"type": "string"},
                "type": {
                    "type": "string",
                    "description": "physical, hypervisor, container",
                    "default": "physical",
                },
                "os": {"type": "string", "default": ""},
                "cpu_cores": {"type": "integer"},
                "memory_gb": {"type": "number"},
                "disk_gb": {"type": "number"},
                "status": {
                    "type": "string",
                    "description": "online, offline, unknown",
                    "default": "unknown",
                },
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                "notes": {"type": "string", "default": ""},
            },
            "required": ["host", "ip"],
        },
    ),
    types.Tool(
        name="list_hosts",
        description="List all hosts in the inventory.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "status": {
                    "type": "string",
                    "description": "Filter by status (optional)",
                    "default": "",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_host",
        description="Get full host details including its VMs.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "host_name": {"type": "string"},
            },
            "required": ["host_name"],
        },
    ),
    types.Tool(
        name="update_host",
        description="Update host fields.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "host_name": {"type": "string"},
                "ip": {"type": "string"},
                "type": {"type": "string"},
                "os": {"type": "string"},
                "cpu_cores": {"type": "integer"},
                "memory_gb": {"type": "number"},
                "disk_gb": {"type": "number"},
                "status": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
            },
            "required": ["host_name"],
        },
    ),
    types.Tool(
        name="delete_host",
        description="Delete a host from the inventory.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "host_name": {"type": "string"},
            },
            "required": ["host_name"],
        },
    ),
    types.Tool(
        name="search_hosts",
        description="Search hosts by name, IP, OS, or tags.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="add_vm",
        description="Add a VM to the inventory.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias"},
                "vm_name": {"type": "string"},
                "ip": {"type": "string", "default": ""},
                "os": {"type": "string", "default": ""},
                "host_name": {"type": "string", "description": "Link to a host by name (optional)"},
                "cpu_cores": {"type": "integer"},
                "memory_gb": {"type": "number"},
                "disk_gb": {"type": "number"},
                "status": {"type": "string", "default": "unknown"},
                "vnc_port": {"type": "integer"},
                "mac_address": {"type": "string", "default": ""},
                "golden_image": {"type": "string", "default": ""},
                "assigned_user": {
                    "type": "string",
                    "description": "Username assigned to this VM",
                    "default": "",
                },
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                "notes": {"type": "string", "default": ""},
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="list_vms",
        description="List all VMs with their host. Optionally filter by status.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "status": {"type": "string", "default": ""},
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_vm",
        description="Get full VM details including host info.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "vm_name": {"type": "string"},
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="update_vm",
        description="Update VM fields.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "vm_name": {"type": "string"},
                "ip": {"type": "string"},
                "os": {"type": "string"},
                "host_name": {"type": "string"},
                "cpu_cores": {"type": "integer"},
                "memory_gb": {"type": "number"},
                "disk_gb": {"type": "number"},
                "status": {"type": "string"},
                "vnc_port": {"type": "integer"},
                "mac_address": {"type": "string"},
                "golden_image": {"type": "string"},
                "assigned_user": {"type": "string", "description": "Username assigned to this VM"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="delete_vm",
        description="Delete a VM from the inventory.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "vm_name": {"type": "string"},
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="get_vms_by_host",
        description="Get all VMs assigned to a specific host.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "host_name": {"type": "string"},
            },
            "required": ["host_name"],
        },
    ),
    types.Tool(
        name="search_vms",
        description="Search VMs by name, IP, OS, or tags.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="get_summary",
        description="Get a summary count of hosts and VMs by status.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"}
            },
            "required": [],
        },
    ),
    types.Tool(
        name="add_network",
        description="Add a network to the inventory.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias"},
                "net_name": {"type": "string"},
                "cidr": {"type": "string", "default": ""},
                "gateway": {"type": "string", "default": ""},
                "vlan_id": {"type": "integer"},
                "bridge": {"type": "string", "default": ""},
                "notes": {"type": "string", "default": ""},
            },
            "required": ["net_name"],
        },
    ),
    types.Tool(
        name="list_networks",
        description="List all networks.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"}
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_network",
        description="Get details of a network.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "net_name": {"type": "string"},
            },
            "required": ["net_name"],
        },
    ),
    types.Tool(
        name="update_network",
        description="Update network fields.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "net_name": {"type": "string"},
                "cidr": {"type": "string"},
                "gateway": {"type": "string"},
                "vlan_id": {"type": "integer"},
                "bridge": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["net_name"],
        },
    ),
    types.Tool(
        name="delete_network",
        description="Delete a network.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "net_name": {"type": "string"},
            },
            "required": ["net_name"],
        },
    ),
    types.Tool(
        name="add_user",
        description="Add a user (AD user, local admin, or service account) to the inventory. Passwords are NOT stored via this tool (no encryption key in this process) — set credentials through the panel's encrypted credential path.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias"},
                "username": {
                    "type": "string",
                    "description": "Login name e.g. kero-test or Administrator",
                },
                "full_name": {"type": "string", "default": ""},
                "user_type": {
                    "type": "string",
                    "description": "ad_user, local_admin, service",
                    "default": "ad_user",
                },
                "password": {
                    "type": "string",
                    "description": "IGNORED — never persisted (sql_mcp cannot encrypt secrets at rest)",
                    "default": "",
                },
                "domain": {
                    "type": "string",
                    "description": "Domain or machine e.g. lab.local or vm-name",
                    "default": "",
                },
                "email": {"type": "string", "default": ""},
                "assigned_vm": {
                    "type": "string",
                    "description": "VM name this user is assigned to",
                    "default": "",
                },
                "status": {
                    "type": "string",
                    "description": "active, disabled",
                    "default": "active",
                },
                "notes": {"type": "string", "default": ""},
            },
            "required": ["username"],
        },
    ),
    types.Tool(
        name="list_users",
        description="List all users. Optionally filter by user_type or status.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "user_type": {
                    "type": "string",
                    "description": "ad_user, local_admin, service",
                    "default": "",
                },
                "status": {"type": "string", "description": "active, disabled", "default": ""},
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_user",
        description="Get full user details. The password is NEVER returned (secret at rest).",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "username": {"type": "string"},
            },
            "required": ["username"],
        },
    ),
    types.Tool(
        name="update_user",
        description="Update user fields. Only provided fields are updated. Passwords are NOT stored via this tool (no encryption key in this process).",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "username": {"type": "string"},
                "full_name": {"type": "string"},
                "user_type": {"type": "string"},
                "password": {
                    "type": "string",
                    "description": "IGNORED — never persisted (sql_mcp cannot encrypt secrets at rest)",
                },
                "domain": {"type": "string"},
                "email": {"type": "string"},
                "assigned_vm": {"type": "string"},
                "status": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["username"],
        },
    ),
    types.Tool(
        name="delete_user",
        description="Delete a user record.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "username": {"type": "string"},
            },
            "required": ["username"],
        },
    ),
    types.Tool(
        name="get_users_by_vm",
        description="Get all users assigned to a specific VM.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Connection alias (e.g. 'inventory')"},
                "vm_name": {"type": "string"},
            },
            "required": ["vm_name"],
        },
    ),
]
for _t in TOOLS:
    if isinstance(_t.inputSchema, dict):
        for _prop in _t.inputSchema.get("properties", {}).values():
            if isinstance(_prop, dict) and "e.g. 'inventory'" in _prop.get("description", ""):
                _prop["description"] = _db_name_desc()
TOOL_DISPATCH = {
    "connect_db": connect_db,
    "disconnect_db": disconnect_db,
    "list_connections": list_connections,
    "test_connection": test_connection,
    "execute_query": execute_query,
    "execute_statement": execute_statement,
    "list_tables": list_tables,
    "describe_table": describe_table,
    "get_table_stats": get_table_stats,
    "init_schema": init_schema,
    "backup_db": backup_db,
    "add_host": add_host,
    "list_hosts": list_hosts,
    "get_host": get_host,
    "update_host": update_host,
    "delete_host": delete_host,
    "search_hosts": search_hosts,
    "add_vm": add_vm,
    "list_vms": list_vms,
    "get_vm": get_vm,
    "update_vm": update_vm,
    "delete_vm": delete_vm,
    "get_vms_by_host": get_vms_by_host,
    "search_vms": search_vms,
    "get_summary": get_summary,
    "add_network": add_network,
    "list_networks": list_networks,
    "get_network": get_network,
    "update_network": update_network,
    "delete_network": delete_network,
    "add_user": add_user,
    "list_users": list_users,
    "get_user": get_user,
    "update_user": update_user,
    "delete_user": delete_user,
    "get_users_by_vm": get_users_by_vm,
}


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    if name not in TOOL_DISPATCH:
        raise ValueError(f"Unknown tool: {name}")
    if "name" in (
        TOOL_DISPATCH[name].__code__.co_varnames if hasattr(TOOL_DISPATCH[name], "__code__") else []
    ):
        if not arguments.get("name"):
            arguments = dict(arguments)
            arguments["name"] = _DB_ALIAS
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: TOOL_DISPATCH[name](**arguments))
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}", exc_info=True)
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
                    {"error": type(e).__name__, "message": str(e), "tool": name}, indent=2
                ),
            )
        ]


async def main():
    logger.info("Starting SQL MCP Server with %d tools", len(TOOLS))
    _db_name = os.environ.get("DB_DATABASE", "")
    _db_host = os.environ.get("DB_HOST", "localhost")
    _db_port = int(os.environ.get("DB_PORT", "5432"))
    _db_user = os.environ.get("DB_USERNAME", "")
    _db_pass = os.environ.get("DB_PASSWORD", "")
    if not _db_name or not _db_user:
        logger.warning("DB_DATABASE or DB_USERNAME not set — skipping auto-connect")
    try:
        result = connect_db(
            name=_db_name,
            host=_db_host,
            database=_db_name,
            username=_db_user,
            password=_db_pass,
            port=_db_port,
        )
        logger.info("Auto-connected to DB '%s' at %s: %s", _db_name, _db_host, result.get("status"))
    except Exception as e:
        logger.warning(
            "Auto-connect to DB '%s' failed: %s — agent must call connect_db manually", _db_name, e
        )
    from sql_mcp.tools.db import _ensure_ro_connection, _ro_credentials

    _ro = _ro_credentials()
    if _ro:
        try:
            _ensure_ro_connection(_db_name, *_ro)
            logger.info("Read-only role '%s' connected — execute_query routes through it", _ro[0])
        except Exception as e:
            logger.warning(
                "Read-only role connect failed (execute_query will retry per query): %s", e
            )
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
