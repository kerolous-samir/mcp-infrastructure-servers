import libvirt
import logging
import xml.etree.ElementTree as ET
from ..core.connection import pool

logger = logging.getLogger(__name__)


def list_networks(host: str = "localhost") -> list[dict]:
    conn = pool.get_connection(host)
    networks = conn.listAllNetworks(0)
    result = []
    for net in networks:
        try:
            xml = ET.fromstring(net.XMLDesc(0))
            bridge = xml.find("bridge")
            ip_elem = xml.find("ip")
            dhcp_range = None
            if ip_elem is not None:
                dhcp = ip_elem.find("dhcp/range")
                if dhcp is not None:
                    dhcp_range = {"start": dhcp.get("start"), "end": dhcp.get("end")}
            result.append(
                {
                    "name": net.name(),
                    "uuid": net.UUIDString(),
                    "active": net.isActive() == 1,
                    "persistent": net.isPersistent() == 1,
                    "autostart": net.autostart() == 1,
                    "bridge": bridge.get("name") if bridge is not None else None,
                    "ip": ip_elem.get("address") if ip_elem is not None else None,
                    "netmask": ip_elem.get("netmask") if ip_elem is not None else None,
                    "dhcp_range": dhcp_range,
                }
            )
        except Exception as e:
            result.append({"name": net.name(), "error": str(e)})
    return sorted(result, key=lambda x: x.get("name", ""))


def get_network_info(network_name: str, host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    net = conn.networkLookupByName(network_name)
    xml = ET.fromstring(net.XMLDesc(0))
    ip_elem = xml.find("ip")
    dhcp_hosts = []
    dhcp_range = None
    if ip_elem is not None:
        dhcp_range_elem = ip_elem.find("dhcp/range")
        if dhcp_range_elem is not None:
            dhcp_range = {"start": dhcp_range_elem.get("start"), "end": dhcp_range_elem.get("end")}
        for host_elem in ip_elem.findall("dhcp/host"):
            dhcp_hosts.append(
                {
                    "mac": host_elem.get("mac"),
                    "name": host_elem.get("name"),
                    "ip": host_elem.get("ip"),
                }
            )
    bridge = xml.find("bridge")
    forward = xml.find("forward")
    return {
        "name": net.name(),
        "uuid": net.UUIDString(),
        "active": net.isActive() == 1,
        "bridge": bridge.get("name") if bridge is not None else None,
        "forward_mode": forward.get("mode", "") if forward is not None else "",
        "ip_address": ip_elem.get("address") if ip_elem is not None else None,
        "netmask": ip_elem.get("netmask") if ip_elem is not None else None,
        "dhcp_range": dhcp_range,
        "static_dhcp_hosts": dhcp_hosts,
    }


def get_dhcp_leases(network_name: str, host: str = "localhost") -> list[dict]:
    conn = pool.get_connection(host)
    net = conn.networkLookupByName(network_name)
    try:
        leases = net.DHCPLeases(None, 0)
    except libvirt.libvirtError:
        return []
    result = []
    for lease in leases:
        result.append(
            {
                "ip": lease.get("ipaddr"),
                "mac": lease.get("mac"),
                "hostname": lease.get("hostname"),
                "expiry_time": lease.get("expirytime"),
                "type": "ipv4" if lease.get("type") == 0 else "ipv6",
            }
        )
    return result


def list_bridges(host: str = "localhost") -> list[dict]:
    conn = pool.get_connection(host)
    networks = conn.listAllNetworks(0)
    bridges = {}
    for net in networks:
        xml = ET.fromstring(net.XMLDesc(0))
        bridge = xml.find("bridge")
        if bridge is not None:
            bridge_name = bridge.get("name")
            bridges[bridge_name] = {
                "name": bridge_name,
                "libvirt_network": net.name(),
                "active": net.isActive() == 1,
                "source": "libvirt",
            }
    return list(bridges.values())


def list_vm_interfaces(vm_name: str, host: str = "localhost") -> list[dict]:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    xml = ET.fromstring(domain.XMLDesc(0))
    interfaces = []
    for iface in xml.findall(".//interface"):
        mac_elem = iface.find("mac")
        source_elem = iface.find("source")
        model_elem = iface.find("model")
        mac = mac_elem.get("address") if mac_elem is not None else None
        source = (
            source_elem.get("bridge") or source_elem.get("network") or source_elem.get("dev")
            if source_elem is not None
            else None
        )
        interfaces.append(
            {
                "type": iface.get("type"),
                "mac": mac,
                "source": source,
                "model": model_elem.get("type") if model_elem is not None else None,
            }
        )
    return interfaces
