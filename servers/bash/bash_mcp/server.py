import asyncio, json, logging, sys
from typing import Any
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from bash_mcp.tools.exec import run_command, run_script
from bash_mcp.tools.files import (
    read_file,
    write_file,
    list_directory,
    delete_file,
    copy_file,
    move_file,
    find_files,
)
from bash_mcp.tools.processes import list_processes, get_process, kill_process
from bash_mcp.tools.services import list_services, get_service, manage_service
from bash_mcp.tools.system import get_os_info, get_uptime, get_hostname, set_hostname, get_env
from bash_mcp.tools.network import get_interfaces, get_routes, ping, get_connections
from bash_mcp.tools.packages import (
    list_packages,
    install_package,
    remove_package,
    search_package,
    update_packages,
)
from bash_mcp.tools.disk import get_disk_usage, list_mounts, get_directory_size
from bash_mcp.tools.users import list_users, get_user, add_user, delete_user, change_password

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("bash_mcp")
server = Server("bash-mcp")
TOOLS = [
    types.Tool(
        name="run_command",
        description="Run a bash command locally or on a remote host via SSH. Returns stdout, stderr, returncode.",
        inputSchema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Bash command to run"},
                "cwd": {"type": "string", "description": "Working directory", "default": "/"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 120},
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (omit or 'localhost' for local)",
                    "default": "localhost",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "password": {
                    "type": "string",
                    "description": "SSH password (uses sshpass)",
                    "default": "",
                },
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key",
                    "default": "",
                },
            },
            "required": ["command"],
        },
    ),
    types.Tool(
        name="run_script",
        description="Run a multi-line bash script locally or on a remote host via SSH.",
        inputSchema={
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "Bash script content (no shebang needed)",
                },
                "cwd": {"type": "string", "default": "/"},
                "timeout": {"type": "integer", "default": 60},
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (omit or 'localhost' for local)",
                    "default": "localhost",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "password": {
                    "type": "string",
                    "description": "SSH password (uses sshpass)",
                    "default": "",
                },
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key",
                    "default": "",
                },
            },
            "required": ["script"],
        },
    ),
    types.Tool(
        name="read_file",
        description="Read a file from the local filesystem.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "description": "Start line (0-based)", "default": 0},
                "limit": {"type": "integer", "description": "Max lines to return", "default": 200},
            },
            "required": ["path"],
        },
    ),
    types.Tool(
        name="write_file",
        description="Write or append content to a file. Creates parent dirs if needed.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "append": {"type": "boolean", "default": False},
            },
            "required": ["path", "content"],
        },
    ),
    types.Tool(
        name="list_directory",
        description="List contents of a directory.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "/"},
                "show_hidden": {"type": "boolean", "default": False},
            },
            "required": ["path"],
        },
    ),
    types.Tool(
        name="delete_file",
        description="Delete a file or directory.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "recursive": {
                    "type": "boolean",
                    "description": "Required for non-empty directories",
                    "default": False,
                },
            },
            "required": ["path"],
        },
    ),
    types.Tool(
        name="copy_file",
        description="Copy a file or directory.",
        inputSchema={
            "type": "object",
            "properties": {"src": {"type": "string"}, "dst": {"type": "string"}},
            "required": ["src", "dst"],
        },
    ),
    types.Tool(
        name="move_file",
        description="Move or rename a file or directory.",
        inputSchema={
            "type": "object",
            "properties": {"src": {"type": "string"}, "dst": {"type": "string"}},
            "required": ["src", "dst"],
        },
    ),
    types.Tool(
        name="find_files",
        description="Find files matching a glob pattern under a directory.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern e.g. *.log, *.py",
                    "default": "*",
                },
                "max_results": {"type": "integer", "default": 100},
            },
            "required": ["path"],
        },
    ),
    types.Tool(
        name="list_processes",
        description="List running processes sorted by CPU or memory.",
        inputSchema={
            "type": "object",
            "properties": {
                "sort_by": {"type": "string", "description": "cpu or memory", "default": "cpu"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_process",
        description="Get details about a specific process by PID.",
        inputSchema={
            "type": "object",
            "properties": {"pid": {"type": "integer"}},
            "required": ["pid"],
        },
    ),
    types.Tool(
        name="kill_process",
        description="Kill a process by PID. signal: TERM (graceful) or KILL (force).",
        inputSchema={
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "signal": {"type": "string", "description": "TERM or KILL", "default": "TERM"},
            },
            "required": ["pid"],
        },
    ),
    types.Tool(
        name="list_services",
        description="List systemd services. Optionally filter by state: active, inactive, failed.",
        inputSchema={
            "type": "object",
            "properties": {
                "filter_state": {
                    "type": "string",
                    "description": "active, inactive, failed (optional)",
                    "default": "",
                }
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_service",
        description="Get detailed status of a systemd service.",
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
    types.Tool(
        name="manage_service",
        description="Start, stop, restart, enable, or disable a systemd service.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "action": {
                    "type": "string",
                    "description": "start, stop, restart, enable, disable, reload",
                },
            },
            "required": ["name", "action"],
        },
    ),
    types.Tool(
        name="get_os_info",
        description="Get OS version, kernel, CPU, memory, disk, and load average. Supports remote hosts via SSH.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (omit or 'localhost' for local)",
                    "default": "localhost",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "password": {"type": "string", "description": "SSH password", "default": ""},
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key",
                    "default": "",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_uptime",
        description="Get system uptime and load average. Supports remote hosts via SSH.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (omit or 'localhost' for local)",
                    "default": "localhost",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "password": {"type": "string", "description": "SSH password", "default": ""},
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key",
                    "default": "",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_hostname",
        description="Get hostname, FQDN, and primary IP. Supports remote hosts via SSH.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (omit or 'localhost' for local)",
                    "default": "localhost",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "password": {"type": "string", "description": "SSH password", "default": ""},
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key",
                    "default": "",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="set_hostname",
        description="Change the system hostname. Supports remote hosts via SSH.",
        inputSchema={
            "type": "object",
            "properties": {
                "new_hostname": {"type": "string"},
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (omit or 'localhost' for local)",
                    "default": "localhost",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "password": {"type": "string", "description": "SSH password", "default": ""},
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key",
                    "default": "",
                },
            },
            "required": ["new_hostname"],
        },
    ),
    types.Tool(
        name="get_env",
        description="Get environment variables. Pass variable name for one, or leave empty for all.",
        inputSchema={
            "type": "object",
            "properties": {
                "variable": {
                    "type": "string",
                    "description": "Variable name (optional)",
                    "default": "",
                }
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_interfaces",
        description="List network interfaces with IPs, MACs, and state.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="get_routes",
        description="Show the routing table.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="ping",
        description="Ping a host and return reachability and RTT stats.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string"}, "count": {"type": "integer", "default": 4}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_connections",
        description="List active network connections. Optionally filter by port.",
        inputSchema={
            "type": "object",
            "properties": {"port": {"type": "integer", "description": "Filter by port (optional)"}},
            "required": [],
        },
    ),
    types.Tool(
        name="list_packages",
        description="List installed apt packages. Optionally filter by name. Supports remote hosts via SSH.",
        inputSchema={
            "type": "object",
            "properties": {
                "filter_name": {"type": "string", "default": ""},
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (omit or 'localhost' for local)",
                    "default": "localhost",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "password": {"type": "string", "description": "SSH password", "default": ""},
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key",
                    "default": "",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="install_package",
        description="Install one or more apt packages (space-separated). Supports remote hosts via SSH.",
        inputSchema={
            "type": "object",
            "properties": {
                "packages": {"type": "string", "description": "Package name(s) space-separated"},
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (omit or 'localhost' for local)",
                    "default": "localhost",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "password": {"type": "string", "description": "SSH password", "default": ""},
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key",
                    "default": "",
                },
            },
            "required": ["packages"],
        },
    ),
    types.Tool(
        name="remove_package",
        description="Remove one or more apt packages. Supports remote hosts via SSH.",
        inputSchema={
            "type": "object",
            "properties": {
                "packages": {"type": "string"},
                "purge": {
                    "type": "boolean",
                    "description": "Also remove config files",
                    "default": False,
                },
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (omit or 'localhost' for local)",
                    "default": "localhost",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "password": {"type": "string", "description": "SSH password", "default": ""},
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key",
                    "default": "",
                },
            },
            "required": ["packages"],
        },
    ),
    types.Tool(
        name="search_package",
        description="Search apt cache for packages matching a query. Supports remote hosts via SSH.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (omit or 'localhost' for local)",
                    "default": "localhost",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "password": {"type": "string", "description": "SSH password", "default": ""},
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key",
                    "default": "",
                },
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="update_packages",
        description="Run apt-get update to refresh package lists. Supports remote hosts via SSH.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (omit or 'localhost' for local)",
                    "default": "localhost",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "password": {"type": "string", "description": "SSH password", "default": ""},
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key",
                    "default": "",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_disk_usage",
        description="Get disk usage for all mounted filesystems.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="list_mounts",
        description="List all active mount points.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="get_directory_size",
        description="Get the total size of a directory.",
        inputSchema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    types.Tool(
        name="list_users",
        description="List local system users.",
        inputSchema={
            "type": "object",
            "properties": {
                "system_users": {
                    "type": "boolean",
                    "description": "Include system users (UID < 1000)",
                    "default": False,
                }
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_user",
        description="Get details about a local user including groups.",
        inputSchema={
            "type": "object",
            "properties": {"username": {"type": "string"}},
            "required": ["username"],
        },
    ),
    types.Tool(
        name="add_user",
        description="Create a new local user.",
        inputSchema={
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "password": {"type": "string", "default": ""},
                "groups": {
                    "type": "string",
                    "description": "Comma-separated supplementary groups",
                    "default": "",
                },
                "shell": {"type": "string", "default": "/bin/bash"},
                "create_home": {"type": "boolean", "default": True},
            },
            "required": ["username"],
        },
    ),
    types.Tool(
        name="delete_user",
        description="Delete a local user.",
        inputSchema={
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "remove_home": {
                    "type": "boolean",
                    "description": "Also delete home directory",
                    "default": False,
                },
            },
            "required": ["username"],
        },
    ),
    types.Tool(
        name="change_password",
        description="Change a local user's password.",
        inputSchema={
            "type": "object",
            "properties": {"username": {"type": "string"}, "new_password": {"type": "string"}},
            "required": ["username", "new_password"],
        },
    ),
]
TOOL_DISPATCH = {
    "run_command": run_command,
    "run_script": run_script,
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
    "delete_file": delete_file,
    "copy_file": copy_file,
    "move_file": move_file,
    "find_files": find_files,
    "list_processes": list_processes,
    "get_process": get_process,
    "kill_process": kill_process,
    "list_services": list_services,
    "get_service": get_service,
    "manage_service": manage_service,
    "get_os_info": get_os_info,
    "get_uptime": get_uptime,
    "get_hostname": get_hostname,
    "set_hostname": set_hostname,
    "get_env": get_env,
    "get_interfaces": get_interfaces,
    "get_routes": get_routes,
    "ping": ping,
    "get_connections": get_connections,
    "list_packages": list_packages,
    "install_package": install_package,
    "remove_package": remove_package,
    "search_package": search_package,
    "update_packages": update_packages,
    "get_disk_usage": get_disk_usage,
    "list_mounts": list_mounts,
    "get_directory_size": get_directory_size,
    "list_users": list_users,
    "get_user": get_user,
    "add_user": add_user,
    "delete_user": delete_user,
    "change_password": change_password,
}


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    if name not in TOOL_DISPATCH:
        raise ValueError(f"Unknown tool: {name}")
    try:
        args = dict(arguments)
        for _k in ("password", "key_path"):
            if _k in args and args[_k] == "":
                args[_k] = None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: TOOL_DISPATCH[name](**args))
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
    logger.info("Starting Bash MCP Server with %d tools", len(TOOLS))
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
