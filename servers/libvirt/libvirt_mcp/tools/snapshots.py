import libvirt
import logging
import xml.etree.ElementTree as ET
from ..core.connection import pool

logger = logging.getLogger(__name__)


def _build_snapshot_xml(snapshot_name: str, description: str = "") -> str:
    root = ET.Element("domainsnapshot")
    ET.SubElement(root, "name").text = str(snapshot_name)
    if description:
        ET.SubElement(root, "description").text = str(description)
    return ET.tostring(root, encoding="unicode")


def list_snapshots(vm_name: str, host: str = "localhost") -> list[dict]:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    snapshots = domain.listAllSnapshots(0)
    result = []
    for snap in snapshots:
        snap_xml = ET.fromstring(snap.getXMLDesc(0))
        creation_time = snap_xml.findtext("creationTime", "")
        state = snap_xml.findtext("state", "")
        description = snap_xml.findtext("description", "")
        result.append(
            {
                "name": snap.getName(),
                "state": state,
                "creation_time": creation_time,
                "description": description,
                "is_current": snap.isCurrent(0) == 1,
                "has_children": snap.numChildren(0) > 0,
            }
        )
    return sorted(result, key=lambda x: x.get("creation_time", ""))


def create_snapshot(
    vm_name: str,
    snapshot_name: str,
    description: str = "",
    disk_only: bool = False,
    host: str = "localhost",
) -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    snapshot_xml = _build_snapshot_xml(snapshot_name, description)
    flags = 0
    if disk_only:
        flags |= libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY
    snap = domain.snapshotCreateXML(snapshot_xml, flags)
    return {
        "status": "created",
        "vm_name": vm_name,
        "snapshot_name": snap.getName(),
        "host": host,
        "disk_only": disk_only,
    }


def revert_snapshot(
    vm_name: str, snapshot_name: str, start_after_revert: bool = True, host: str = "localhost"
) -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    snapshot = domain.snapshotLookupByName(snapshot_name, 0)
    state, _ = domain.state()
    was_running = state == libvirt.VIR_DOMAIN_RUNNING
    if was_running:
        domain.destroy()
    domain.revertToSnapshot(snapshot, 0)
    if start_after_revert:
        domain.create()
    return {
        "status": "reverted",
        "vm_name": vm_name,
        "snapshot_name": snapshot_name,
        "host": host,
        "was_running": was_running,
        "started_after_revert": start_after_revert,
    }


def delete_snapshot(
    vm_name: str, snapshot_name: str, delete_children: bool = False, host: str = "localhost"
) -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    snapshot = domain.snapshotLookupByName(snapshot_name, 0)
    flags = 0
    if delete_children:
        flags |= libvirt.VIR_DOMAIN_SNAPSHOT_DELETE_CHILDREN
    snapshot.delete(flags)
    return {
        "status": "deleted",
        "vm_name": vm_name,
        "snapshot_name": snapshot_name,
        "host": host,
        "children_deleted": delete_children,
    }
