import asyncio
import json
import logging
import sys
from typing import Any
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from winrm_mcp.tools.hosts import add_host, list_hosts, remove_host, test_connection
from winrm_mcp.tools.exec import run_ps, run_cmd
from winrm_mcp.tools.system import get_system_info, get_os_info, set_hostname, reboot, shutdown
from winrm_mcp.tools.services import list_services, get_service, manage_service
from winrm_mcp.tools.processes import list_processes, kill_process
from winrm_mcp.tools.network import get_network_adapters, get_network_config, get_routes, set_dns
from winrm_mcp.tools.users import (
    list_users,
    list_local_groups,
    get_group_members,
    add_local_user,
    remove_local_user,
)
from winrm_mcp.tools.disk import get_disk_info, list_volumes, get_drive_usage
from winrm_mcp.tools.eventlog import get_event_logs, query_event_log
from winrm_mcp.tools.files import upload_file, download_file, list_directory, delete_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("winrm_mcp")
server = Server("winrm-mcp")
TOOLS = [
    types.Tool(
        name="add_host",
        description="Register one or more Windows hosts for WinRM management. Pass a single IP or a list of IPs with the same credentials.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                    "description": "Hostname/IP string, or list of hostnames/IPs to register all at once",
                },
                "username": {
                    "type": "string",
                    "description": "Windows username e.g. Administrator or DOMAIN\\\\user",
                },
                "password": {"type": "string", "description": "Windows password"},
                "port": {
                    "type": "integer",
                    "description": "WinRM port (5985=HTTP, 5986=HTTPS)",
                    "default": 5985,
                },
                "transport": {
                    "type": "string",
                    "description": "Auth transport: ntlm (default), basic, kerberos",
                    "default": "ntlm",
                },
                "use_ssl": {
                    "type": "boolean",
                    "description": "Use HTTPS (default: false)",
                    "default": False,
                },
                "validate_ssl": {
                    "type": "boolean",
                    "description": "Validate the server TLS cert when HTTPS is used (default: true; set false only for trusted self-signed certs)",
                    "default": True,
                },
            },
            "required": ["host", "username", "password"],
        },
    ),
    types.Tool(
        name="list_hosts",
        description="List all registered Windows hosts and their WinRM connection status.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="remove_host",
        description="Unregister a Windows host from the WinRM pool.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Hostname or IP to remove"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="test_connection",
        description="Test WinRM connectivity to a registered Windows host. Returns OS version, uptime, and PowerShell version.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Hostname or IP to test"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="run_ps",
        description="Run a PowerShell script on a Windows host and return stdout/stderr.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "script": {"type": "string", "description": "PowerShell script to execute"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 60)",
                    "default": 60,
                },
            },
            "required": ["host", "script"],
        },
    ),
    types.Tool(
        name="run_cmd",
        description="Run a CMD command on a Windows host and return stdout/stderr.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "command": {"type": "string", "description": "CMD command to execute"},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of arguments",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 60)",
                    "default": 60,
                },
            },
            "required": ["host", "command"],
        },
    ),
    types.Tool(
        name="get_system_info",
        description="Get full system info: OS, CPU, RAM, hostname, domain, last boot, PowerShell version.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target Windows host"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_os_info",
        description="Get OS version, build number, architecture, uptime and last boot time.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target Windows host"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="set_hostname",
        description="Rename the Windows computer. Reboot required for change to take effect.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "new_hostname": {"type": "string", "description": "New computer name"},
            },
            "required": ["host", "new_hostname"],
        },
    ),
    types.Tool(
        name="reboot",
        description="Restart a Windows host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "delay_seconds": {
                    "type": "integer",
                    "description": "Delay before reboot in seconds (default: 0)",
                    "default": 0,
                },
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="shutdown",
        description="Shut down a Windows host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "delay_seconds": {
                    "type": "integer",
                    "description": "Delay before shutdown in seconds (default: 0)",
                    "default": 0,
                },
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="list_services",
        description="List Windows services with their status and start type.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "filter_status": {
                    "type": "string",
                    "description": "Filter by status: Running, Stopped, Paused (default: all)",
                },
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_service",
        description="Get detailed info about a specific Windows service including dependencies.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "service_name": {
                    "type": "string",
                    "description": "Service short name e.g. wuauserv, spooler",
                },
            },
            "required": ["host", "service_name"],
        },
    ),
    types.Tool(
        name="manage_service",
        description="Start, stop, restart, pause, resume, enable, or disable a Windows service.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "service_name": {"type": "string", "description": "Service short name"},
                "action": {
                    "type": "string",
                    "description": "Action: start, stop, restart, pause, resume, enable, disable",
                },
            },
            "required": ["host", "service_name", "action"],
        },
    ),
    types.Tool(
        name="list_processes",
        description="List top running processes on a Windows host sorted by CPU or memory.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "sort_by": {
                    "type": "string",
                    "description": "Sort by 'cpu' or 'memory' (default: cpu)",
                    "default": "cpu",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of processes to return (default: 30)",
                    "default": 30,
                },
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="kill_process",
        description="Kill a process on a Windows host by PID or name.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "pid": {"type": "integer", "description": "Process ID to kill"},
                "name": {"type": "string", "description": "Process name to kill"},
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_network_adapters",
        description="List all network adapters with IPs, MACs, link speed and state.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target Windows host"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_network_config",
        description="Get full network configuration per adapter: IPs, gateway, DNS.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target Windows host"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_routes",
        description="Show the Windows routing table.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target Windows host"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="set_dns",
        description="Set DNS server addresses on a Windows network adapter.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "adapter_name": {
                    "type": "string",
                    "description": "Network adapter name e.g. Ethernet, Ethernet0",
                },
                "dns_servers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of DNS server IPs e.g. ['8.8.8.8', '8.8.4.4']",
                },
            },
            "required": ["host", "adapter_name", "dns_servers"],
        },
    ),
    types.Tool(
        name="list_users",
        description="List local user accounts on a Windows host.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target Windows host"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="list_local_groups",
        description="List local groups on a Windows host.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target Windows host"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_group_members",
        description="List members of a local group on a Windows host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "group_name": {
                    "type": "string",
                    "description": "Group name e.g. Administrators, Remote Desktop Users",
                },
            },
            "required": ["host", "group_name"],
        },
    ),
    types.Tool(
        name="add_local_user",
        description="Create a local user account on a Windows host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "username": {"type": "string", "description": "Username to create"},
                "password": {"type": "string", "description": "Password for the new user"},
                "full_name": {
                    "type": "string",
                    "description": "Full name (optional)",
                    "default": "",
                },
                "description": {
                    "type": "string",
                    "description": "Account description (optional)",
                    "default": "",
                },
                "add_to_groups": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Groups to add user to e.g. ['Administrators']",
                },
                "password_never_expires": {
                    "type": "boolean",
                    "description": "Password never expires (default: true)",
                    "default": True,
                },
            },
            "required": ["host", "username", "password"],
        },
    ),
    types.Tool(
        name="remove_local_user",
        description="Delete a local user account from a Windows host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "username": {"type": "string", "description": "Username to delete"},
            },
            "required": ["host", "username"],
        },
    ),
    types.Tool(
        name="get_disk_info",
        description="Get physical disk information: size, type, bus, health status.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target Windows host"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="list_volumes",
        description="List drive volumes with size, free space, filesystem and health status.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target Windows host"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_drive_usage",
        description="Get disk usage summary for all drives or a specific drive letter.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "drive_letter": {
                    "type": "string",
                    "description": "Drive letter e.g. C (default: all drives)",
                },
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_event_logs",
        description="Get recent events from a Windows event log (System, Application, Security).",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "log_name": {
                    "type": "string",
                    "description": "Log name: System, Application, Security (default: System)",
                    "default": "System",
                },
                "level": {
                    "type": "string",
                    "description": "Filter by level: Error, Warning, Information (default: all)",
                },
                "max_events": {
                    "type": "integer",
                    "description": "Max events to return (default: 50)",
                    "default": 50,
                },
                "hours_back": {
                    "type": "integer",
                    "description": "How many hours back to look (default: 24)",
                    "default": 24,
                },
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="query_event_log",
        description="Query a Windows event log by EventID and/or Source.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "log_name": {
                    "type": "string",
                    "description": "Log name: System, Application, Security",
                    "default": "System",
                },
                "event_id": {"type": "integer", "description": "Filter by Event ID (optional)"},
                "source": {
                    "type": "string",
                    "description": "Filter by source/provider name (optional)",
                },
                "max_events": {
                    "type": "integer",
                    "description": "Max events to return (default: 100)",
                    "default": 100,
                },
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="upload_file",
        description="Upload a local file to a Windows host via WinRM (base64 encoded, chunked).",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "local_path": {"type": "string", "description": "Local file path to upload"},
                "remote_path": {
                    "type": "string",
                    "description": "Destination path on Windows e.g. C:\\\\Temp\\\\file.txt",
                },
            },
            "required": ["host", "local_path", "remote_path"],
        },
    ),
    types.Tool(
        name="download_file",
        description="Download a file from a Windows host to the local machine via WinRM.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "remote_path": {
                    "type": "string",
                    "description": "File path on Windows e.g. C:\\\\Temp\\\\file.txt",
                },
                "local_path": {"type": "string", "description": "Local destination path"},
            },
            "required": ["host", "remote_path", "local_path"],
        },
    ),
    types.Tool(
        name="list_directory",
        description="List contents of a directory on a Windows host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "path": {
                    "type": "string",
                    "description": "Directory path e.g. C:\\\\Windows or C:\\\\Users",
                },
            },
            "required": ["host", "path"],
        },
    ),
    types.Tool(
        name="delete_file",
        description="Delete a file or folder on a Windows host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target Windows host"},
                "path": {"type": "string", "description": "Path to delete"},
                "recursive": {
                    "type": "boolean",
                    "description": "Delete folder recursively (default: false)",
                    "default": False,
                },
            },
            "required": ["host", "path"],
        },
    ),
]
TOOL_DISPATCH = {
    "add_host": add_host,
    "list_hosts": list_hosts,
    "remove_host": remove_host,
    "test_connection": test_connection,
    "run_ps": run_ps,
    "run_cmd": run_cmd,
    "get_system_info": get_system_info,
    "get_os_info": get_os_info,
    "set_hostname": set_hostname,
    "reboot": reboot,
    "shutdown": shutdown,
    "list_services": list_services,
    "get_service": get_service,
    "manage_service": manage_service,
    "list_processes": list_processes,
    "kill_process": kill_process,
    "get_network_adapters": get_network_adapters,
    "get_network_config": get_network_config,
    "get_routes": get_routes,
    "set_dns": set_dns,
    "list_users": list_users,
    "list_local_groups": list_local_groups,
    "get_group_members": get_group_members,
    "add_local_user": add_local_user,
    "remove_local_user": remove_local_user,
    "get_disk_info": get_disk_info,
    "list_volumes": list_volumes,
    "get_drive_usage": get_drive_usage,
    "get_event_logs": get_event_logs,
    "query_event_log": query_event_log,
    "upload_file": upload_file,
    "download_file": download_file,
    "list_directory": list_directory,
    "delete_file": delete_file,
}


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return TOOLS


_SECRET_ARG_SUBSTRINGS = ("password", "passwd", "pwd", "secret", "token", "passphrase")


def _redact_args(arguments: "dict[str, Any]") -> "dict[str, Any]":
    out: dict[str, Any] = {}
    for k, v in (arguments or {}).items():
        if any((s in str(k).lower() for s in _SECRET_ARG_SUBSTRINGS)):
            out[k] = "***REDACTED***"
        else:
            out[k] = v
    return out


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    if name not in TOOL_DISPATCH:
        raise ValueError(f"Unknown tool: {name}")
    func = TOOL_DISPATCH[name]
    try:
        if name == "add_host" and isinstance(arguments.get("host"), str):
            h = arguments["host"].strip()
            if h.startswith("["):
                arguments = {**arguments, "host": json.loads(h)}
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: func(**arguments))
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
    logger.info("Starting WinRM MCP Server with %d tools", len(TOOLS))
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
