import asyncio, json, logging, sys
from typing import Any
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from ad_mcp.tools.dc import (
    add_dc,
    list_dcs,
    remove_dc,
    test_dc,
    get_domain_info,
    get_forest_info,
    get_dc_list,
)
from ad_mcp.tools.users import (
    list_users,
    get_user,
    create_user,
    update_user,
    reset_password,
    unlock_user,
    search_users,
)
from ad_mcp.tools.groups import (
    list_groups,
    get_group,
    create_group,
    search_groups,
    get_group_members,
    add_group_member,
    remove_group_member,
)
from ad_mcp.tools.ous import list_ous, get_ou, create_ou, move_object
from ad_mcp.tools.computers import list_computers, get_computer, search_computers
from ad_mcp.tools.objects import delete_object, set_object_enabled
from ad_mcp.tools.gpo import (
    list_gpos,
    get_gpo,
    create_gpo,
    delete_gpo,
    link_gpo,
    unlink_gpo,
    backup_gpo,
    restore_gpo,
)
from ad_mcp.tools.dns import (
    list_dns_zones,
    list_dns_records,
    add_dns_record,
    update_dns_record,
    delete_dns_record,
)
from ad_mcp.tools.dhcp import (
    list_dhcp_scopes,
    get_dhcp_scope,
    add_dhcp_scope,
    remove_dhcp_scope,
    list_dhcp_leases,
    add_dhcp_reservation,
    delete_dhcp_reservation,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("ad_mcp")
server = Server("ad-mcp")
TOOLS = [
    types.Tool(
        name="add_dc",
        description="Register a Domain Controller. Uses LDAP for directory ops, WinRM for DNS/DHCP/GPO.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "DC IP or hostname"},
                "username": {"type": "string", "description": "Admin username e.g. Administrator"},
                "password": {"type": "string"},
                "domain": {"type": "string", "description": "Domain name e.g. lab.local"},
                "port": {"type": "integer", "default": 389},
                "use_ssl": {"type": "boolean", "default": False},
            },
            "required": ["host", "username", "password", "domain"],
        },
    ),
    types.Tool(
        name="list_dcs",
        description="List all registered DCs.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="remove_dc",
        description="Unregister a DC.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="test_dc",
        description="Test LDAP connectivity to a DC.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_domain_info",
        description="Get domain info: name, GUID, functional level.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_forest_info",
        description="Get AD forest info: naming contexts, DC DNS name, LDAP versions.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_dc_list",
        description="List all domain controllers in the domain.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="list_users",
        description="List AD users. Use get_user to get the DN needed by delete_object/set_object_enabled/move_object.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "ou": {"type": "string", "description": "OU DN to filter (optional)"},
                "enabled_only": {"type": "boolean", "default": False},
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_user",
        description="Get full details of an AD user including DN and group memberships.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "username": {"type": "string", "description": "sAMAccountName"},
            },
            "required": ["host", "username"],
        },
    ),
    types.Tool(
        name="create_user",
        description="Create a new AD user account (enabled with password set).",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "first_name": {"type": "string", "default": ""},
                "last_name": {"type": "string", "default": ""},
                "display_name": {"type": "string", "default": ""},
                "email": {"type": "string", "default": ""},
                "ou": {"type": "string", "description": "Target OU DN (default: CN=Users)"},
                "description": {"type": "string", "default": ""},
            },
            "required": ["host", "username", "password"],
        },
    ),
    types.Tool(
        name="reset_password",
        description="Reset an AD user's password via WinRM.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "new_password": {"type": "string"},
            },
            "required": ["host", "username", "new_password"],
        },
    ),
    types.Tool(
        name="unlock_user",
        description="Unlock a locked-out AD user account.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}, "username": {"type": "string"}},
            "required": ["host", "username"],
        },
    ),
    types.Tool(
        name="update_user",
        description="Update attributes of an existing AD user (email, phone, department, title, etc.).",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "username": {
                    "type": "string",
                    "description": "sAMAccountName of the user to update",
                },
                "first_name": {"type": "string"},
                "last_name": {"type": "string"},
                "display_name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "department": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["host", "username"],
        },
    ),
    types.Tool(
        name="search_users",
        description="Search AD users by name, username, or email.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "query": {"type": "string", "description": "Partial match on name/username/email"},
            },
            "required": ["host", "query"],
        },
    ),
    types.Tool(
        name="list_groups",
        description="List AD groups. Use get_group to get the DN for delete_object/move_object.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "ou": {"type": "string", "description": "OU DN to filter (optional)"},
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_group",
        description="Get details about an AD group including member count and DN.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}, "group_name": {"type": "string"}},
            "required": ["host", "group_name"],
        },
    ),
    types.Tool(
        name="create_group",
        description="Create a new AD security group.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "group_name": {"type": "string"},
                "ou": {"type": "string", "description": "Target OU DN (default: CN=Users)"},
                "description": {"type": "string", "default": ""},
                "group_scope": {
                    "type": "string",
                    "description": "Global, Universal, DomainLocal",
                    "default": "Global",
                },
            },
            "required": ["host", "group_name"],
        },
    ),
    types.Tool(
        name="get_group_members",
        description="List members of an AD group.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}, "group_name": {"type": "string"}},
            "required": ["host", "group_name"],
        },
    ),
    types.Tool(
        name="add_group_member",
        description="Add a user or group to an AD group.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "group_name": {"type": "string"},
                "member_username": {
                    "type": "string",
                    "description": "sAMAccountName of the member to add",
                },
            },
            "required": ["host", "group_name", "member_username"],
        },
    ),
    types.Tool(
        name="search_groups",
        description="Search AD groups by name or description.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "query": {
                    "type": "string",
                    "description": "Partial match on group name or description",
                },
            },
            "required": ["host", "query"],
        },
    ),
    types.Tool(
        name="remove_group_member",
        description="Remove a member from an AD group.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "group_name": {"type": "string"},
                "member_username": {"type": "string"},
            },
            "required": ["host", "group_name", "member_username"],
        },
    ),
    types.Tool(
        name="list_ous",
        description="List Organizational Units.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "search_base": {"type": "string", "description": "Search under this DN (optional)"},
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_ou",
        description="Get OU details by DN.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "ou_dn": {"type": "string", "description": "OU distinguished name"},
            },
            "required": ["host", "ou_dn"],
        },
    ),
    types.Tool(
        name="create_ou",
        description="Create a new Organizational Unit.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "ou_name": {"type": "string"},
                "parent_dn": {"type": "string", "description": "Parent DN (default: domain root)"},
                "description": {"type": "string", "default": ""},
            },
            "required": ["host", "ou_name"],
        },
    ),
    types.Tool(
        name="move_object",
        description="Move any AD object (user/computer/group/OU) to a different OU by DN.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "object_dn": {"type": "string", "description": "DN of the object to move"},
                "target_ou": {"type": "string", "description": "Target OU DN"},
            },
            "required": ["host", "object_dn", "target_ou"],
        },
    ),
    types.Tool(
        name="list_computers",
        description="List AD computer accounts. Use get_computer to get the DN.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "ou": {"type": "string", "description": "OU DN to filter (optional)"},
                "enabled_only": {"type": "boolean", "default": False},
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="search_computers",
        description="Search AD computers by name, DNS hostname, or description.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "query": {
                    "type": "string",
                    "description": "Partial match on computer name, DNS hostname, or description",
                },
            },
            "required": ["host", "query"],
        },
    ),
    types.Tool(
        name="get_computer",
        description="Get full details of an AD computer account including DN.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}, "computer_name": {"type": "string"}},
            "required": ["host", "computer_name"],
        },
    ),
    types.Tool(
        name="delete_object",
        description="Delete any AD object by DN (user, group, computer, OU). Get DN from get_user/get_group/get_computer/get_ou first.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "dn": {
                    "type": "string",
                    "description": "Distinguished name of the object to delete",
                },
            },
            "required": ["host", "dn"],
        },
    ),
    types.Tool(
        name="set_object_enabled",
        description="Enable or disable any AD account (user or computer) by DN.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "dn": {"type": "string", "description": "Distinguished name of the account"},
                "enabled": {"type": "boolean", "description": "True to enable, False to disable"},
            },
            "required": ["host", "dn", "enabled"],
        },
    ),
    types.Tool(
        name="list_gpos",
        description="List all Group Policy Objects in the domain.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_gpo",
        description="Get details about a specific GPO.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}, "gpo_name": {"type": "string"}},
            "required": ["host", "gpo_name"],
        },
    ),
    types.Tool(
        name="create_gpo",
        description="Create a new GPO.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "gpo_name": {"type": "string"},
                "comment": {"type": "string", "default": ""},
            },
            "required": ["host", "gpo_name"],
        },
    ),
    types.Tool(
        name="delete_gpo",
        description="Delete a GPO.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}, "gpo_name": {"type": "string"}},
            "required": ["host", "gpo_name"],
        },
    ),
    types.Tool(
        name="link_gpo",
        description="Link a GPO to an OU.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "gpo_name": {"type": "string"},
                "target_ou": {"type": "string"},
                "enabled": {"type": "boolean", "default": True},
            },
            "required": ["host", "gpo_name", "target_ou"],
        },
    ),
    types.Tool(
        name="unlink_gpo",
        description="Unlink a GPO from an OU.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "gpo_name": {"type": "string"},
                "target_ou": {"type": "string"},
            },
            "required": ["host", "gpo_name", "target_ou"],
        },
    ),
    types.Tool(
        name="restore_gpo",
        description="Restore a GPO from a backup folder. Uses the most recent backup if backup_id is omitted.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "gpo_name": {"type": "string"},
                "backup_path": {"type": "string", "default": "C:\\\\GPOBackups"},
                "backup_id": {
                    "type": "string",
                    "description": "Specific backup GUID to restore (default: most recent)",
                    "default": "",
                },
            },
            "required": ["host", "gpo_name"],
        },
    ),
    types.Tool(
        name="backup_gpo",
        description="Backup a GPO to a folder on the DC.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "gpo_name": {"type": "string"},
                "backup_path": {"type": "string", "default": "C:\\\\GPOBackups"},
            },
            "required": ["host", "gpo_name"],
        },
    ),
    types.Tool(
        name="list_dns_zones",
        description="List all DNS zones on the DC.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="list_dns_records",
        description="List DNS records in a zone.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "zone_name": {"type": "string"},
                "record_type": {"type": "string", "description": "A, AAAA, CNAME, PTR (optional)"},
            },
            "required": ["host", "zone_name"],
        },
    ),
    types.Tool(
        name="add_dns_record",
        description="Add a DNS record (A, AAAA, CNAME, PTR).",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "zone_name": {"type": "string"},
                "name": {"type": "string"},
                "record_type": {"type": "string"},
                "value": {"type": "string"},
                "ttl": {"type": "integer", "default": 3600},
            },
            "required": ["host", "zone_name", "name", "record_type", "value"],
        },
    ),
    types.Tool(
        name="update_dns_record",
        description="Update an existing DNS record with a new value (delete + re-add atomically).",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "zone_name": {"type": "string"},
                "name": {"type": "string"},
                "record_type": {"type": "string", "description": "A, AAAA, CNAME, PTR"},
                "new_value": {"type": "string", "description": "New record value"},
                "ttl": {"type": "integer", "default": 3600},
            },
            "required": ["host", "zone_name", "name", "record_type", "new_value"],
        },
    ),
    types.Tool(
        name="delete_dns_record",
        description="Delete a DNS record from a zone.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "zone_name": {"type": "string"},
                "name": {"type": "string"},
                "record_type": {"type": "string"},
            },
            "required": ["host", "zone_name", "name", "record_type"],
        },
    ),
    types.Tool(
        name="list_dhcp_scopes",
        description="List DHCP scopes on the DC.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_dhcp_scope",
        description="Get DHCP scope details including usage stats.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}, "scope_id": {"type": "string"}},
            "required": ["host", "scope_id"],
        },
    ),
    types.Tool(
        name="add_dhcp_scope",
        description="Create a new DHCP scope on the DC.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "scope_id": {"type": "string", "description": "Scope network ID e.g. 192.168.1.0"},
                "name": {"type": "string", "description": "Scope name"},
                "start_range": {"type": "string", "description": "Start IP e.g. 192.168.1.100"},
                "end_range": {"type": "string", "description": "End IP e.g. 192.168.1.200"},
                "subnet_mask": {"type": "string", "default": "255.255.255.0"},
                "description": {"type": "string", "default": ""},
                "lease_duration": {
                    "type": "string",
                    "description": "Lease duration in d.hh:mm:ss format",
                    "default": "8.00:00:00",
                },
            },
            "required": ["host", "scope_id", "name", "start_range", "end_range"],
        },
    ),
    types.Tool(
        name="remove_dhcp_scope",
        description="Delete a DHCP scope from the DC.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "scope_id": {"type": "string", "description": "Scope network ID e.g. 192.168.1.0"},
                "force": {
                    "type": "boolean",
                    "description": "Force removal even if scope has leases (default: true)",
                    "default": True,
                },
            },
            "required": ["host", "scope_id"],
        },
    ),
    types.Tool(
        name="list_dhcp_leases",
        description="List active DHCP leases in a scope.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}, "scope_id": {"type": "string"}},
            "required": ["host", "scope_id"],
        },
    ),
    types.Tool(
        name="add_dhcp_reservation",
        description="Add a DHCP reservation (IP to MAC mapping).",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "scope_id": {"type": "string"},
                "ip_address": {"type": "string"},
                "mac_address": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string", "default": ""},
            },
            "required": ["host", "scope_id", "ip_address", "mac_address", "name"],
        },
    ),
    types.Tool(
        name="delete_dhcp_reservation",
        description="Delete a DHCP reservation.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "scope_id": {"type": "string"},
                "ip_address": {"type": "string"},
            },
            "required": ["host", "scope_id", "ip_address"],
        },
    ),
]
TOOL_DISPATCH = {
    "add_dc": add_dc,
    "list_dcs": list_dcs,
    "remove_dc": remove_dc,
    "test_dc": test_dc,
    "get_domain_info": get_domain_info,
    "get_forest_info": get_forest_info,
    "get_dc_list": get_dc_list,
    "list_users": list_users,
    "get_user": get_user,
    "create_user": create_user,
    "update_user": update_user,
    "reset_password": reset_password,
    "unlock_user": unlock_user,
    "search_users": search_users,
    "list_groups": list_groups,
    "get_group": get_group,
    "create_group": create_group,
    "search_groups": search_groups,
    "get_group_members": get_group_members,
    "add_group_member": add_group_member,
    "remove_group_member": remove_group_member,
    "list_ous": list_ous,
    "get_ou": get_ou,
    "create_ou": create_ou,
    "move_object": move_object,
    "list_computers": list_computers,
    "get_computer": get_computer,
    "search_computers": search_computers,
    "delete_object": delete_object,
    "set_object_enabled": set_object_enabled,
    "list_gpos": list_gpos,
    "get_gpo": get_gpo,
    "create_gpo": create_gpo,
    "delete_gpo": delete_gpo,
    "link_gpo": link_gpo,
    "unlink_gpo": unlink_gpo,
    "backup_gpo": backup_gpo,
    "restore_gpo": restore_gpo,
    "list_dns_zones": list_dns_zones,
    "list_dns_records": list_dns_records,
    "add_dns_record": add_dns_record,
    "update_dns_record": update_dns_record,
    "delete_dns_record": delete_dns_record,
    "list_dhcp_scopes": list_dhcp_scopes,
    "get_dhcp_scope": get_dhcp_scope,
    "add_dhcp_scope": add_dhcp_scope,
    "remove_dhcp_scope": remove_dhcp_scope,
    "list_dhcp_leases": list_dhcp_leases,
    "add_dhcp_reservation": add_dhcp_reservation,
    "delete_dhcp_reservation": delete_dhcp_reservation,
}


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return TOOLS


_SECRET_ARG_SUBSTRINGS = ("password", "passwd", "pwd", "secret", "token", "credential")


def _redact_args(arguments: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for k, v in (arguments or {}).items():
        if any((s in str(k).lower() for s in _SECRET_ARG_SUBSTRINGS)):
            redacted[k] = "***REDACTED***"
        else:
            redacted[k] = v
    return redacted


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    if name not in TOOL_DISPATCH:
        raise ValueError(f"Unknown tool: {name}")
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: TOOL_DISPATCH[name](**arguments))
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        logger.error("Tool %s failed: %s", name, type(e).__name__, exc_info=True)
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": type(e).__name__,
                        "message": str(e),
                        "tool": name,
                        "arguments": _redact_args(arguments),
                    },
                    indent=2,
                ),
            )
        ]


async def main():
    logger.info("Starting AD MCP Server with %d tools", len(TOOLS))
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
