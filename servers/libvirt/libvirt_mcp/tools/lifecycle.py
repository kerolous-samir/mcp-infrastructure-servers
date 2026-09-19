import subprocess
import libvirt
import logging
from typing import Optional
from ..core.connection import pool

logger = logging.getLogger(__name__)


def list_vms(host: str = "localhost") -> list[dict]:
    conn = pool.get_connection(host)
    domains = conn.listAllDomains(0)
    state_map = {
        libvirt.VIR_DOMAIN_NOSTATE: "nostate",
        libvirt.VIR_DOMAIN_RUNNING: "running",
        libvirt.VIR_DOMAIN_BLOCKED: "blocked",
        libvirt.VIR_DOMAIN_PAUSED: "paused",
        libvirt.VIR_DOMAIN_SHUTDOWN: "shutdown",
        libvirt.VIR_DOMAIN_SHUTOFF: "shutoff",
        libvirt.VIR_DOMAIN_CRASHED: "crashed",
        libvirt.VIR_DOMAIN_PMSUSPENDED: "suspended",
    }
    result = []
    for domain in domains:
        state, _ = domain.state()
        result.append(
            {
                "name": domain.name(),
                "uuid": domain.UUIDString(),
                "domain_id": domain.ID() if domain.ID() != -1 else None,
                "state": state_map.get(state, "unknown"),
            }
        )
    return sorted(result, key=lambda x: x["name"])


def get_vm_info(vm_name: str, host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    state, max_mem, mem, vcpus, cpu_time = domain.info()
    state_map = {
        0: "nostate",
        1: "running",
        2: "blocked",
        3: "paused",
        4: "shutdown",
        5: "shutoff",
        6: "crashed",
        7: "suspended",
    }
    import xml.etree.ElementTree as ET

    try:
        xml = ET.fromstring(domain.XMLDesc(0))
    except ET.ParseError as e:
        return {
            "name": vm_name,
            "host": host,
            "state": state_map.get(state, "unknown"),
            "vcpus": vcpus,
            "memory_mb": mem // 1024,
            "max_memory_mb": max_mem // 1024,
            "disks": [],
            "interfaces": [],
            "uuid": domain.UUIDString(),
            "warning": f"XML parse error: {e}",
        }
    disks = []
    for disk in xml.findall(".//disk[@device='disk']"):
        source = disk.find("source")
        target = disk.find("target")
        if source is not None and target is not None:
            disks.append(
                {
                    "device": target.get("dev"),
                    "path": source.get("file") or source.get("dev", ""),
                    "bus": target.get("bus"),
                }
            )
    interfaces = []
    for iface in xml.findall(".//interface"):
        mac = iface.find("mac")
        source = iface.find("source")
        if mac is not None:
            interfaces.append(
                {
                    "mac": mac.get("address"),
                    "source": (
                        source.get("bridge") or source.get("network", "")
                        if source is not None
                        else ""
                    ),
                    "type": iface.get("type"),
                }
            )
    return {
        "name": vm_name,
        "host": host,
        "state": state_map.get(state, "unknown"),
        "vcpus": vcpus,
        "memory_mb": mem // 1024,
        "max_memory_mb": max_mem // 1024,
        "disks": disks,
        "interfaces": interfaces,
        "uuid": domain.UUIDString(),
    }


def create_vm(
    vm_name: str,
    vcpus: int,
    memory_mb: int,
    disk_size_gb: int,
    iso_path: Optional[str] = None,
    disk_path: Optional[str] = None,
    network_bridge: str = "virbr0",
    os_variant: str = "generic",
    uefi: bool = False,
    host: str = "localhost",
) -> dict:
    if disk_path is None:
        disk_path = f"/var/lib/libvirt/images/{vm_name}.qcow2"
    conn = pool.get_connection(host)
    connect_uri = conn.getURI()
    disk_arg = f"path={disk_path},size={disk_size_gb},format=qcow2"
    cmd = [
        "virt-install",
        "--connect",
        connect_uri,
        "--name",
        vm_name,
        "--vcpus",
        str(vcpus),
        "--memory",
        str(memory_mb),
        "--disk",
        disk_arg,
        "--network",
        f"bridge={network_bridge}",
        "--os-variant",
        os_variant,
        "--graphics",
        "vnc",
        "--noautoconsole",
    ]
    cmd += ["--controller", "type=virtio-serial,index=0"]
    cmd += [
        "--channel",
        "unix,target_type=virtio,name=org.qemu.guest_agent.0,address.type=virtio-serial,address.controller=0,address.bus=0,address.port=1",
    ]
    if iso_path:
        cmd += ["--cdrom", iso_path]
        if uefi:
            cmd += ["--machine", "q35", "--boot", "firmware=efi"]
    elif uefi:
        cmd += ["--machine", "q35", "--import", "--boot", "firmware=efi,hd"]
    else:
        cmd += ["--import", "--boot", "hd"]
    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"virt-install failed: {result.stderr}")
    return {
        "status": "created",
        "vm_name": vm_name,
        "host": host,
        "vcpus": vcpus,
        "memory_mb": memory_mb,
        "disk_path": disk_path,
        "disk_size_gb": disk_size_gb,
        "uefi": uefi,
    }


def start_vm(vm_name: str, host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    state, _ = domain.state()
    if state == libvirt.VIR_DOMAIN_RUNNING:
        return {"status": "already_running", "vm_name": vm_name, "host": host}
    domain.create()
    return {"status": "started", "vm_name": vm_name, "host": host}


def stop_vm(vm_name: str, host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    state, _ = domain.state()
    if state == libvirt.VIR_DOMAIN_SHUTOFF:
        return {"status": "already_stopped", "vm_name": vm_name, "host": host}
    domain.shutdown()
    return {"status": "shutdown_initiated", "vm_name": vm_name, "host": host}


def force_stop_vm(vm_name: str, host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    domain.destroy()
    return {"status": "force_stopped", "vm_name": vm_name, "host": host}


def reboot_vm(vm_name: str, host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    domain.reboot(0)
    return {"status": "rebooting", "vm_name": vm_name, "host": host}


def delete_vm(vm_name: str, delete_disk: bool = True, host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    deleted_disks = []
    if delete_disk:
        import xml.etree.ElementTree as ET

        try:
            xml = ET.fromstring(domain.XMLDesc(0))
        except ET.ParseError:
            xml = None
        if xml is not None:
            for disk in xml.findall(".//disk[@device='disk']"):
                source = disk.find("source")
                if source is not None:
                    path = source.get("file") or source.get("dev")
                    if path:
                        deleted_disks.append(path)
    state, _ = domain.state()
    if state == libvirt.VIR_DOMAIN_RUNNING:
        domain.destroy()
    flags = libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
    if delete_disk:
        flags |= libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE
        domain.undefineFlags(flags)
        disk_results = []
        for disk_path in deleted_disks:
            entry = {"path": disk_path}
            try:
                vol = conn.storageVolLookupByPath(disk_path)
                vol.delete(0)
                entry["status"] = "deleted"
            except libvirt.libvirtError as e:
                entry["status"] = "not_deleted"
                entry["error"] = str(e)
            disk_results.append(entry)
    else:
        domain.undefineFlags(flags)
        disk_results = []
    return {
        "status": "deleted",
        "vm_name": vm_name,
        "host": host,
        "deleted_disks": deleted_disks if delete_disk else [],
        "disk_results": disk_results,
    }


def get_vm_ip(vm_name: str, host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    state, _ = domain.state()
    if state != libvirt.VIR_DOMAIN_RUNNING:
        return {"status": "vm_not_running", "vm_name": vm_name, "ips": []}
    ips = []
    agent_error = ""
    lease_error = ""
    try:
        ifaces = domain.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT, 0)
        for iface_name, iface_data in ifaces.items():
            if iface_name == "lo":
                continue
            for addr in iface_data.get("addrs", []):
                if addr["type"] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                    ips.append(
                        {"interface": iface_name, "ip": addr["addr"], "source": "guest_agent"}
                    )
    except libvirt.libvirtError as e:
        agent_error = str(e)
    if not ips:
        try:
            ifaces = domain.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE, 0)
            for iface_name, iface_data in ifaces.items():
                for addr in iface_data.get("addrs", []):
                    if addr["type"] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                        ips.append(
                            {"interface": iface_name, "ip": addr["addr"], "source": "dhcp_lease"}
                        )
        except libvirt.libvirtError as e:
            lease_error = str(e)
    if not ips:
        if agent_error:
            note = f"IP detection via guest agent failed — VM XML likely missing the virtio-serial channel device (org.qemu.guest_agent.0). Agent error: {agent_error}. Use list_vm_interfaces() + get_dhcp_leases() to find IP by MAC instead."
        else:
            note = "Guest agent returned no addresses and DHCP lease lookup also found nothing. Use list_vm_interfaces() + get_dhcp_leases() to find IP by MAC instead."
    else:
        note = ""
    return {"status": "ok", "vm_name": vm_name, "host": host, "ips": ips, "note": note}
