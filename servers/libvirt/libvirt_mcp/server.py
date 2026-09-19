import asyncio
import json
import logging
import sys
from typing import Any
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from libvirt_mcp.tools.hosts import (
    add_host,
    list_hosts,
    remove_host,
    get_host_info,
    test_connection,
)
from libvirt_mcp.tools.lifecycle import (
    list_vms,
    get_vm_info,
    create_vm,
    start_vm,
    stop_vm,
    force_stop_vm,
    reboot_vm,
    delete_vm,
    get_vm_ip,
)
from libvirt_mcp.tools.clone import (
    clone_vm_local,
    clone_image_to_host,
    clone_vm_remote,
    clone_to_all_hosts,
    clone_vm_remote_by_template,
)
from libvirt_mcp.tools.snapshots import (
    list_snapshots,
    create_snapshot,
    revert_snapshot,
    delete_snapshot,
)
from libvirt_mcp.tools.storage import (
    list_storage_pools,
    list_volumes,
    create_volume,
    delete_volume,
    resize_volume,
    get_disk_usage,
    create_golden_image,
)
from libvirt_mcp.tools.network import (
    list_networks,
    get_network_info,
    get_dhcp_leases,
    list_bridges,
    list_vm_interfaces,
)
from libvirt_mcp.tools.console import get_vnc_info, list_vnc_ports, get_console_uri
from libvirt_mcp.tools.host_os import (
    host_shutdown,
    host_reboot,
    run_command,
    get_os_info,
    list_host_interfaces,
    set_host_ip,
    get_host_routes,
    set_default_gateway,
    list_services,
    manage_service,
    install_package,
    remove_package,
    get_host_processes,
    set_hostname,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("libvirt_mcp")
server = Server("libvirt-mcp")
TOOLS = [
    types.Tool(
        name="add_host",
        description="Register a remote libvirt host for management. Supports SSH key or password auth.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Hostname or IP address"},
                "username": {
                    "type": "string",
                    "description": "SSH username (default: root)",
                    "default": "root",
                },
                "ssh_key_path": {"type": "string", "description": "Path to SSH private key file"},
                "password": {"type": "string", "description": "SSH password (prefer key auth)"},
                "port": {"type": "integer", "description": "SSH port (default: 22)", "default": 22},
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="list_hosts",
        description="List all registered remote hosts and their connection status.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="remove_host",
        description="Remove a host from the registry and close its connection.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Hostname to remove"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="get_host_info",
        description="Get CPU, memory, and libvirt info for a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                }
            },
        },
    ),
    types.Tool(
        name="test_connection",
        description="Test connectivity to a registered host.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Host to test"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="list_vms",
        description="List all VMs on a host with their state (running, shutoff, paused, etc).",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                }
            },
        },
    ),
    types.Tool(
        name="get_vm_info",
        description="Get detailed info about a VM including CPU, memory, disks, and network interfaces.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="create_vm",
        description="Create a new VM. Optionally boot from ISO or import existing disk image.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name for the new VM"},
                "vcpus": {"type": "integer", "description": "Number of virtual CPUs"},
                "memory_mb": {"type": "integer", "description": "RAM in MB"},
                "disk_size_gb": {"type": "integer", "description": "Disk size in GB"},
                "iso_path": {
                    "type": "string",
                    "description": "Path to installation ISO (optional)",
                },
                "disk_path": {
                    "type": "string",
                    "description": "Full path for disk image (optional)",
                },
                "network_bridge": {
                    "type": "string",
                    "description": "Network bridge name (default: virbr0)",
                    "default": "virbr0",
                },
                "os_variant": {
                    "type": "string",
                    "description": "OS variant e.g. win2k22, ubuntu22.04 (default: generic)",
                    "default": "generic",
                },
                "uefi": {
                    "type": "boolean",
                    "description": "Enable UEFI/OVMF firmware instead of legacy BIOS (default: false)",
                    "default": False,
                },
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name", "vcpus", "memory_mb", "disk_size_gb"],
        },
    ),
    types.Tool(
        name="start_vm",
        description="Start a VM.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM to start"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="stop_vm",
        description="Gracefully shut down a VM via ACPI signal.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM to stop"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="force_stop_vm",
        description="Force stop a VM immediately (equivalent to pulling the power plug).",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM to force stop"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="reboot_vm",
        description="Reboot a VM gracefully.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM to reboot"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="delete_vm",
        description="Delete a VM and optionally its disk files.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM to delete"},
                "delete_disk": {
                    "type": "boolean",
                    "description": "Delete disk files too (default: true)",
                    "default": True,
                },
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="get_vm_ip",
        description="Get the IP address of a running VM. Uses guest agent first, falls back to DHCP leases.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="clone_vm_local",
        description="Clone a VM locally on the same host. Source VM must be shut off.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_vm": {"type": "string", "description": "Name of the source VM"},
                "new_vm_name": {"type": "string", "description": "Name for the cloned VM"},
                "new_disk_path": {"type": "string", "description": "Path for new disk (optional)"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["source_vm", "new_vm_name"],
        },
    ),
    types.Tool(
        name="clone_image_to_host",
        description="Transfer a golden disk image to a remote host via rsync/scp.",
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Local path to .qcow2 image"},
                "target_host": {"type": "string", "description": "Remote host to send image to"},
                "remote_path": {
                    "type": "string",
                    "description": "Destination path on remote host (optional)",
                },
                "username": {
                    "type": "string",
                    "description": "SSH username (default: root)",
                    "default": "root",
                },
                "ssh_key_path": {"type": "string", "description": "Path to SSH private key"},
                "ssh_port": {
                    "type": "integer",
                    "description": "SSH port (default: 22)",
                    "default": 22,
                },
            },
            "required": ["image_path", "target_host"],
        },
    ),
    types.Tool(
        name="clone_vm_remote",
        description="Full pipeline: transfer golden image to remote host and create a VM from it using a thin overlay (fast, space-efficient).",
        inputSchema={
            "type": "object",
            "properties": {
                "source_image_path": {
                    "type": "string",
                    "description": "Local path to golden .qcow2 image",
                },
                "new_vm_name": {"type": "string", "description": "Name for the new VM"},
                "target_host": {"type": "string", "description": "Remote host to create VM on"},
                "vcpus": {"type": "integer", "description": "Number of vCPUs"},
                "memory_mb": {"type": "integer", "description": "RAM in MB"},
                "network_bridge": {
                    "type": "string",
                    "description": "Network bridge (default: virbr0)",
                    "default": "virbr0",
                },
                "os_variant": {
                    "type": "string",
                    "description": "OS variant (default: win2k22)",
                    "default": "win2k22",
                },
                "remote_image_dir": {
                    "type": "string",
                    "description": "Image dir on remote host",
                    "default": "/var/lib/libvirt/images",
                },
                "username": {
                    "type": "string",
                    "description": "SSH username (default: root)",
                    "default": "root",
                },
                "ssh_key_path": {"type": "string", "description": "SSH key path"},
                "ssh_port": {
                    "type": "integer",
                    "description": "SSH port (default: 22)",
                    "default": 22,
                },
                "uefi": {
                    "type": "boolean",
                    "description": "Use UEFI/OVMF firmware with q35 machine type (default: true — matches golden_image_uefi.qcow2)",
                    "default": True,
                },
            },
            "required": ["source_image_path", "new_vm_name", "target_host", "vcpus", "memory_mb"],
        },
    ),
    types.Tool(
        name="clone_to_all_hosts",
        description="Clone golden image to multiple remote hosts creating N VMs per host. Your main tool for mass deployment.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_image_path": {
                    "type": "string",
                    "description": "Local path to golden .qcow2 image",
                },
                "vm_name_prefix": {
                    "type": "string",
                    "description": "Prefix for VM names e.g. 'winserver'",
                },
                "target_hosts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of remote hosts",
                },
                "vcpus": {"type": "integer", "description": "vCPUs per VM"},
                "memory_mb": {"type": "integer", "description": "RAM per VM in MB"},
                "network_bridge": {
                    "type": "string",
                    "description": "Network bridge name",
                    "default": "virbr0",
                },
                "os_variant": {"type": "string", "description": "OS variant", "default": "win2k22"},
                "remote_image_dir": {
                    "type": "string",
                    "description": "Image dir on remote hosts",
                    "default": "/var/lib/libvirt/images",
                },
                "username": {"type": "string", "description": "SSH username", "default": "root"},
                "ssh_key_path": {"type": "string", "description": "SSH key path"},
                "vms_per_host": {
                    "type": "integer",
                    "description": "Number of VMs per host (default: 4)",
                    "default": 4,
                },
                "uefi": {
                    "type": "boolean",
                    "description": "Use UEFI/OVMF firmware (default: true)",
                    "default": True,
                },
            },
            "required": [
                "source_image_path",
                "vm_name_prefix",
                "target_hosts",
                "vcpus",
                "memory_mb",
            ],
        },
    ),
    types.Tool(
        name="clone_vm_remote_by_template",
        description="Clone a VM from an OS template by name. Looks up the template image, UEFI setting, and credentials from the database, clones to the remote host, and automatically saves VM credentials to the users table.",
        inputSchema={
            "type": "object",
            "properties": {
                "template_name": {
                    "type": "string",
                    "description": "Name of the OS template (must be registered and ready)",
                },
                "new_vm_name": {"type": "string", "description": "Name for the new VM"},
                "target_host": {"type": "string", "description": "Remote host IP to create VM on"},
                "vcpus": {"type": "integer", "description": "Number of vCPUs"},
                "memory_mb": {"type": "integer", "description": "RAM in MB"},
                "network_bridge": {
                    "type": "string",
                    "description": "Network bridge (default: virbr0)",
                    "default": "virbr0",
                },
                "remote_image_dir": {
                    "type": "string",
                    "description": "Image dir on remote host",
                    "default": "/var/lib/libvirt/images",
                },
                "username": {
                    "type": "string",
                    "description": "SSH username (default: root)",
                    "default": "root",
                },
                "ssh_key_path": {"type": "string", "description": "SSH key path"},
                "ssh_port": {
                    "type": "integer",
                    "description": "SSH port (default: 22)",
                    "default": 22,
                },
                "disk_size_gb": {
                    "type": "integer",
                    "description": "Resize disk to this size in GB after clone (optional)",
                },
            },
            "required": ["template_name", "new_vm_name", "target_host", "vcpus", "memory_mb"],
        },
    ),
    types.Tool(
        name="list_snapshots",
        description="List all snapshots for a VM.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="create_snapshot",
        description="Create a snapshot of a VM. VM can be running or stopped.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM"},
                "snapshot_name": {"type": "string", "description": "Name for the snapshot"},
                "description": {"type": "string", "description": "Optional description"},
                "disk_only": {
                    "type": "boolean",
                    "description": "Only snapshot disk, not RAM (default: false)",
                    "default": False,
                },
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name", "snapshot_name"],
        },
    ),
    types.Tool(
        name="revert_snapshot",
        description="Revert a VM to a snapshot. VM will be stopped before reverting.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM"},
                "snapshot_name": {"type": "string", "description": "Snapshot to revert to"},
                "start_after_revert": {
                    "type": "boolean",
                    "description": "Start VM after reverting (default: true)",
                    "default": True,
                },
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name", "snapshot_name"],
        },
    ),
    types.Tool(
        name="delete_snapshot",
        description="Delete a snapshot.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM"},
                "snapshot_name": {"type": "string", "description": "Snapshot to delete"},
                "delete_children": {
                    "type": "boolean",
                    "description": "Also delete child snapshots (default: false)",
                    "default": False,
                },
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name", "snapshot_name"],
        },
    ),
    types.Tool(
        name="list_storage_pools",
        description="List all storage pools on a host with capacity info.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                }
            },
        },
    ),
    types.Tool(
        name="list_volumes",
        description="List all disk volumes in a storage pool.",
        inputSchema={
            "type": "object",
            "properties": {
                "pool_name": {"type": "string", "description": "Name of the storage pool"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["pool_name"],
        },
    ),
    types.Tool(
        name="create_volume",
        description="Create a new disk volume in a storage pool.",
        inputSchema={
            "type": "object",
            "properties": {
                "pool_name": {"type": "string", "description": "Storage pool name"},
                "volume_name": {"type": "string", "description": "Name for the new volume"},
                "size_gb": {"type": "integer", "description": "Size in GB"},
                "format": {
                    "type": "string",
                    "description": "Disk format (default: qcow2)",
                    "default": "qcow2",
                },
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["pool_name", "volume_name", "size_gb"],
        },
    ),
    types.Tool(
        name="delete_volume",
        description="Delete a disk volume from a storage pool.",
        inputSchema={
            "type": "object",
            "properties": {
                "pool_name": {"type": "string", "description": "Storage pool name"},
                "volume_name": {"type": "string", "description": "Volume to delete"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["pool_name", "volume_name"],
        },
    ),
    types.Tool(
        name="resize_volume",
        description="Resize a disk volume. Can only grow, not shrink.",
        inputSchema={
            "type": "object",
            "properties": {
                "pool_name": {"type": "string", "description": "Storage pool name"},
                "volume_name": {"type": "string", "description": "Volume to resize"},
                "new_size_gb": {
                    "type": "integer",
                    "description": "New size in GB (must be larger than current)",
                },
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["pool_name", "volume_name", "new_size_gb"],
        },
    ),
    types.Tool(
        name="get_disk_usage",
        description="Get disk usage summary for all storage pools on a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                }
            },
        },
    ),
    types.Tool(
        name="create_golden_image",
        description="Create a compressed golden image (qcow2) from a VM's disk for instant future cloning. Optionally shuts down and restarts the VM automatically.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM to image"},
                "output_path": {
                    "type": "string",
                    "description": "Destination path for the golden image (default: /var/lib/libvirt/images/golden/<vm_name>-golden.qcow2)",
                },
                "compress": {
                    "type": "boolean",
                    "description": "Compress the output image (default: true)",
                    "default": True,
                },
                "stop_vm_first": {
                    "type": "boolean",
                    "description": "Shut down VM before imaging for consistency (default: true)",
                    "default": True,
                },
                "restart_after": {
                    "type": "boolean",
                    "description": "Restart the VM after imaging (default: true)",
                    "default": True,
                },
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="list_networks",
        description="List all virtual networks on a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                }
            },
        },
    ),
    types.Tool(
        name="get_network_info",
        description="Get detailed configuration of a virtual network.",
        inputSchema={
            "type": "object",
            "properties": {
                "network_name": {"type": "string", "description": "Name of the network"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["network_name"],
        },
    ),
    types.Tool(
        name="get_dhcp_leases",
        description="Get current DHCP leases for a network. Shows which VMs have which IPs.",
        inputSchema={
            "type": "object",
            "properties": {
                "network_name": {"type": "string", "description": "Name of the network"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["network_name"],
        },
    ),
    types.Tool(
        name="list_bridges",
        description="List all network bridges on a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                }
            },
        },
    ),
    types.Tool(
        name="list_vm_interfaces",
        description="List all network interfaces of a VM with MAC and source bridge info.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="host_shutdown",
        description="Shutdown a host machine. Always targets the named host — never the panel/management host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target host to shut down (REQUIRED — e.g. an IP or registered host id)",
                },
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
        name="host_reboot",
        description="Reboot a host machine. Always targets the named host — never the panel/management host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target host to reboot (REQUIRED — e.g. an IP or registered host id)",
                },
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
        name="run_command",
        description='Run a command on a named host and return stdout/stderr. Pass the command as an argv list (e.g. ["ls","-la"]); free-form shell strings are rejected and there is no shell=True path on the panel.',
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target host to run on (REQUIRED — never the panel)",
                },
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Command as an argv list, e.g. ["systemctl","status","libvirtd"]',
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
        name="get_os_info",
        description="Get OS version, kernel, uptime, hostname, CPU, memory and disk summary of a host.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target host (REQUIRED)"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="list_host_interfaces",
        description="List all network interfaces on a host with their IPs, MACs and state.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target host (REQUIRED)"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="set_host_ip",
        description="Set a static IP address on a host network interface.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target host (REQUIRED)"},
                "interface": {"type": "string", "description": "Interface name e.g. eth0, ens3"},
                "ip_address": {
                    "type": "string",
                    "description": "IP address to set e.g. 192.168.1.100",
                },
                "prefix_length": {
                    "type": "integer",
                    "description": "Subnet prefix length (default: 24)",
                    "default": 24,
                },
                "flush_existing": {
                    "type": "boolean",
                    "description": "Remove existing IPs first (default: true)",
                    "default": True,
                },
            },
            "required": ["host", "interface", "ip_address"],
        },
    ),
    types.Tool(
        name="get_host_routes",
        description="Show the routing table of a host.",
        inputSchema={
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Target host (REQUIRED)"}},
            "required": ["host"],
        },
    ),
    types.Tool(
        name="set_default_gateway",
        description="Set the default gateway on a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target host (REQUIRED)"},
                "gateway_ip": {"type": "string", "description": "Gateway IP address"},
                "interface": {
                    "type": "string",
                    "description": "Optional interface to bind the route to",
                },
            },
            "required": ["host", "gateway_ip"],
        },
    ),
    types.Tool(
        name="list_services",
        description="List systemd services on a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target host (REQUIRED)"},
                "filter_state": {
                    "type": "string",
                    "description": "Filter by state: running, stopped, failed (default: all)",
                },
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="manage_service",
        description="Start, stop, restart, enable, or disable a systemd service on a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target host (REQUIRED)"},
                "service": {
                    "type": "string",
                    "description": "Service name e.g. libvirtd, nginx, ssh",
                },
                "action": {
                    "type": "string",
                    "description": "One of: start, stop, restart, enable, disable, status",
                },
            },
            "required": ["host", "service", "action"],
        },
    ),
    types.Tool(
        name="install_package",
        description="Install one or more apt packages on a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target host (REQUIRED)"},
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of package names to install",
                },
                "update_first": {
                    "type": "boolean",
                    "description": "Run apt update before installing (default: false)",
                    "default": False,
                },
            },
            "required": ["host", "packages"],
        },
    ),
    types.Tool(
        name="remove_package",
        description="Remove one or more apt packages from a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target host (REQUIRED)"},
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of package names to remove",
                },
                "purge": {
                    "type": "boolean",
                    "description": "Also remove config files (default: false)",
                    "default": False,
                },
            },
            "required": ["host", "packages"],
        },
    ),
    types.Tool(
        name="get_host_processes",
        description="List top processes on a host sorted by CPU or memory usage.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target host (REQUIRED)"},
                "sort_by": {
                    "type": "string",
                    "description": "Sort by 'cpu' or 'memory' (default: cpu)",
                    "default": "cpu",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of processes to return (default: 20)",
                    "default": 20,
                },
            },
            "required": ["host"],
        },
    ),
    types.Tool(
        name="set_hostname",
        description="Change the hostname of a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Target host (REQUIRED)"},
                "new_hostname": {"type": "string", "description": "New hostname to set"},
            },
            "required": ["host", "new_hostname"],
        },
    ),
    types.Tool(
        name="get_vnc_info",
        description="Get VNC connection info for a running VM including port and viewer command.",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
    types.Tool(
        name="list_vnc_ports",
        description="List all running VMs with their VNC ports on a host.",
        inputSchema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                }
            },
        },
    ),
    types.Tool(
        name="get_console_uri",
        description="Get console URI for a VM (VNC, SPICE, or serial).",
        inputSchema={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "Name of the VM"},
                "host": {
                    "type": "string",
                    "description": "Target host (default: localhost)",
                    "default": "localhost",
                },
            },
            "required": ["vm_name"],
        },
    ),
]
TOOL_DISPATCH = {
    "add_host": add_host,
    "list_hosts": list_hosts,
    "remove_host": remove_host,
    "get_host_info": get_host_info,
    "test_connection": test_connection,
    "list_vms": list_vms,
    "get_vm_info": get_vm_info,
    "create_vm": create_vm,
    "start_vm": start_vm,
    "stop_vm": stop_vm,
    "force_stop_vm": force_stop_vm,
    "reboot_vm": reboot_vm,
    "delete_vm": delete_vm,
    "get_vm_ip": get_vm_ip,
    "clone_vm_local": clone_vm_local,
    "clone_image_to_host": clone_image_to_host,
    "clone_vm_remote": clone_vm_remote,
    "clone_to_all_hosts": clone_to_all_hosts,
    "clone_vm_remote_by_template": clone_vm_remote_by_template,
    "list_snapshots": list_snapshots,
    "create_snapshot": create_snapshot,
    "revert_snapshot": revert_snapshot,
    "delete_snapshot": delete_snapshot,
    "list_storage_pools": list_storage_pools,
    "list_volumes": list_volumes,
    "create_volume": create_volume,
    "delete_volume": delete_volume,
    "resize_volume": resize_volume,
    "get_disk_usage": get_disk_usage,
    "create_golden_image": create_golden_image,
    "list_networks": list_networks,
    "get_network_info": get_network_info,
    "get_dhcp_leases": get_dhcp_leases,
    "list_bridges": list_bridges,
    "list_vm_interfaces": list_vm_interfaces,
    "get_vnc_info": get_vnc_info,
    "list_vnc_ports": list_vnc_ports,
    "get_console_uri": get_console_uri,
    "host_shutdown": host_shutdown,
    "host_reboot": host_reboot,
    "run_command": run_command,
    "get_os_info": get_os_info,
    "list_host_interfaces": list_host_interfaces,
    "set_host_ip": set_host_ip,
    "get_host_routes": get_host_routes,
    "set_default_gateway": set_default_gateway,
    "list_services": list_services,
    "manage_service": manage_service,
    "install_package": install_package,
    "remove_package": remove_package,
    "get_host_processes": get_host_processes,
    "set_hostname": set_hostname,
}


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return TOOLS


_SECRET_ARG_SUBSTRINGS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "passphrase",
    "ssh_key",
    "private_key",
    "credential",
)


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
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: func(**arguments))
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        logger.error("Tool %s failed: %s", name, type(e).__name__, exc_info=True)
        error_response = {
            "error": type(e).__name__,
            "message": str(e),
            "tool": name,
            "arguments": _redact_args(arguments),
        }
        return [types.TextContent(type="text", text=json.dumps(error_response, indent=2))]


async def main():
    logger.info("Starting Libvirt MCP Server with %d tools", len(TOOLS))
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
