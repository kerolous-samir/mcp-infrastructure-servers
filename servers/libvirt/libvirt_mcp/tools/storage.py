import libvirt
import logging
import os
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET
from typing import Optional
from ..core.connection import pool

logger = logging.getLogger(__name__)
_POOL_STATES = ["inactive", "building", "running", "degraded", "inaccessible"]
_VOL_TYPES = ["file", "block", "dir", "network", "netdir"]


def _build_volume_xml(volume_name: str, size_bytes: int, format: str) -> str:
    if not isinstance(size_bytes, int) or size_bytes <= 0:
        raise ValueError("size_bytes must be a positive integer")
    if not re.fullmatch("[A-Za-z0-9]+", format or ""):
        raise ValueError(f"invalid volume format: {format!r}")
    vol = ET.Element("volume")
    ET.SubElement(vol, "name").text = str(volume_name)
    cap = ET.SubElement(vol, "capacity")
    cap.set("unit", "bytes")
    cap.text = str(size_bytes)
    target = ET.SubElement(vol, "target")
    ET.SubElement(target, "format").set("type", format)
    return ET.tostring(vol, encoding="unicode")


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _exec_on_host(host: str, argv: list, timeout: int = 600) -> subprocess.CompletedProcess:
    if host in _LOCAL_HOSTS:
        full = list(argv)
    else:
        pool.get_connection(host)
        cfg = pool._configs.get(host)
        if cfg is None:
            raise ValueError(f"Host '{host}' is not registered")
        ssh_opts = ["-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
        if cfg.ssh_key_path:
            ssh_opts += ["-i", cfg.ssh_key_path]
        if cfg.port and cfg.port != 22:
            ssh_opts += ["-p", str(int(cfg.port))]
        remote_cmd = " ".join((shlex.quote(str(a)) for a in argv))
        full = ["ssh", *ssh_opts, f"{cfg.username}@{cfg.host}", remote_cmd]
    return subprocess.run(full, capture_output=True, text=True, timeout=timeout)


def list_storage_pools(host: str = "localhost") -> list[dict]:
    conn = pool.get_connection(host)
    pools = conn.listAllStoragePools(0)
    result = []
    for p in pools:
        try:
            info = p.info()
            result.append(
                {
                    "name": p.name(),
                    "uuid": p.UUIDString(),
                    "state": _POOL_STATES[info[0]] if info[0] < len(_POOL_STATES) else "unknown",
                    "capacity_gb": round(info[1] / 1024**3, 2),
                    "allocation_gb": round(info[2] / 1024**3, 2),
                    "available_gb": round(info[3] / 1024**3, 2),
                    "active": p.isActive() == 1,
                }
            )
        except libvirt.libvirtError as e:
            result.append({"name": p.name(), "error": str(e)})
    return result


def list_volumes(pool_name: str, host: str = "localhost") -> list[dict]:
    conn = pool.get_connection(host)
    storage_pool = conn.storagePoolLookupByName(pool_name)
    storage_pool.refresh(0)
    volumes = storage_pool.listAllVolumes(0)
    result = []
    for vol in volumes:
        try:
            info = vol.info()
            result.append(
                {
                    "name": vol.name(),
                    "path": vol.path(),
                    "type": _VOL_TYPES[info[0]] if info[0] < len(_VOL_TYPES) else "unknown",
                    "capacity_gb": round(info[1] / 1024**3, 2),
                    "allocation_gb": round(info[2] / 1024**3, 2),
                }
            )
        except libvirt.libvirtError as e:
            result.append({"name": vol.name(), "error": str(e)})
    return sorted(result, key=lambda x: x.get("name", ""))


def create_volume(
    pool_name: str, volume_name: str, size_gb: int, format: str = "qcow2", host: str = "localhost"
) -> dict:
    conn = pool.get_connection(host)
    storage_pool = conn.storagePoolLookupByName(pool_name)
    size_bytes = size_gb * 1024**3
    vol_xml = _build_volume_xml(volume_name, size_bytes, format)
    vol = storage_pool.createXML(vol_xml, 0)
    return {
        "status": "created",
        "name": vol.name(),
        "path": vol.path(),
        "size_gb": size_gb,
        "format": format,
        "pool": pool_name,
        "host": host,
    }


def delete_volume(pool_name: str, volume_name: str, host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    storage_pool = conn.storagePoolLookupByName(pool_name)
    vol = storage_pool.storageVolLookupByName(volume_name)
    path = vol.path()
    vol.delete(0)
    return {"status": "deleted", "name": volume_name, "path": path, "pool": pool_name, "host": host}


def resize_volume(
    pool_name: str, volume_name: str, new_size_gb: int, host: str = "localhost"
) -> dict:
    conn = pool.get_connection(host)
    storage_pool = conn.storagePoolLookupByName(pool_name)
    vol = storage_pool.storageVolLookupByName(volume_name)
    info = vol.info()
    current_gb = round(info[1] / 1024**3, 2)
    if new_size_gb <= current_gb:
        raise ValueError(
            f"New size ({new_size_gb}GB) must be larger than current ({current_gb}GB). Cannot shrink volumes."
        )
    new_size_bytes = new_size_gb * 1024**3
    vol.resize(new_size_bytes, 0)
    return {
        "status": "resized",
        "name": volume_name,
        "old_size_gb": current_gb,
        "new_size_gb": new_size_gb,
        "pool": pool_name,
        "host": host,
    }


def create_golden_image(
    vm_name: str,
    output_path: Optional[str] = None,
    compress: bool = True,
    stop_vm_first: bool = True,
    restart_after: bool = True,
    host: str = "localhost",
) -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    xml = ET.fromstring(domain.XMLDesc(0))
    disk_path = None
    for disk in xml.findall(".//disk[@device='disk']"):
        source = disk.find("source")
        if source is not None:
            disk_path = source.get("file") or source.get("dev")
            break
    if not disk_path:
        raise RuntimeError(f"Could not find disk path for VM '{vm_name}'")
    if output_path is None:
        golden_dir = "/var/lib/libvirt/images/golden"
        output_path = f"{golden_dir}/{vm_name}-golden.qcow2"
    out_dir = os.path.dirname(os.path.abspath(output_path))
    mk = _exec_on_host(host, ["mkdir", "-p", out_dir], timeout=30)
    if mk.returncode != 0:
        raise RuntimeError(f"could not create golden dir on {host}: {mk.stderr}")
    was_running = domain.isActive() == 1
    if stop_vm_first and was_running:
        domain.shutdown()
        import time

        for _ in range(60):
            time.sleep(2)
            if domain.isActive() == 0:
                break
        else:
            domain.destroy()
    cmd = ["qemu-img", "convert", "-f", "qcow2", "-O", "qcow2"]
    if compress:
        cmd.append("-c")
    cmd += [disk_path, output_path]
    result = _exec_on_host(host, cmd, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"qemu-img convert failed on {host}: {result.stderr}")
    size_res = _exec_on_host(host, ["stat", "-c", "%s", output_path], timeout=30)
    try:
        image_size = int(size_res.stdout.strip())
    except (ValueError, AttributeError):
        image_size = 0
    if restart_after and was_running:
        domain.create()
    return {
        "status": "ok",
        "vm_name": vm_name,
        "source_disk": disk_path,
        "golden_image": output_path,
        "size_gb": round(image_size / 1024**3, 2),
        "compressed": compress,
        "vm_restarted": restart_after and was_running,
        "note": f"Use clone_vm_local or clone_to_all_hosts with this image to deploy new VMs instantly",
    }


def get_disk_usage(host: str = "localhost") -> dict:
    pools_info = list_storage_pools(host)
    total_capacity = sum((p.get("capacity_gb", 0) for p in pools_info))
    total_used = sum((p.get("allocation_gb", 0) for p in pools_info))
    total_free = sum((p.get("available_gb", 0) for p in pools_info))
    return {
        "host": host,
        "pools": pools_info,
        "totals": {
            "capacity_gb": round(total_capacity, 2),
            "used_gb": round(total_used, 2),
            "free_gb": round(total_free, 2),
            "usage_percent": round(
                total_used / total_capacity * 100 if total_capacity > 0 else 0, 1
            ),
        },
    }
