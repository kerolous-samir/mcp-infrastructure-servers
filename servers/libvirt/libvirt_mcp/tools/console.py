import libvirt
import logging
import xml.etree.ElementTree as ET
from ..core.connection import pool

logger = logging.getLogger(__name__)


def get_vnc_info(vm_name: str, host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    state, _ = domain.state()
    if state != libvirt.VIR_DOMAIN_RUNNING:
        return {"vm_name": vm_name, "host": host, "status": "vm_not_running", "vnc_port": None}
    xml = ET.fromstring(domain.XMLDesc(libvirt.VIR_DOMAIN_XML_SECURE))
    graphics = xml.find(".//graphics[@type='vnc']")
    if graphics is None:
        return {
            "vm_name": vm_name,
            "host": host,
            "status": "no_vnc",
            "message": "VM has no VNC display configured",
        }
    port = graphics.get("port", "-1")
    vnc_host = graphics.get("listen", "127.0.0.1")
    password = graphics.get("passwd", None)
    display_num = int(port) - 5900 if port and int(port) > 0 else None
    return {
        "vm_name": vm_name,
        "host": host,
        "status": "ok",
        "vnc_host": vnc_host,
        "vnc_port": int(port) if port else None,
        "display": display_num,
        "has_password": password is not None,
        "connection_string": f"{host}:{port}" if host != "localhost" else f"localhost:{port}",
        "viewer_command": (
            f"vncviewer {host}:{display_num}"
            if host != "localhost"
            else f"vncviewer :{display_num}"
        ),
    }


def list_vnc_ports(host: str = "localhost") -> list[dict]:
    conn = pool.get_connection(host)
    domains = conn.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_RUNNING)
    result = []
    for domain in domains:
        try:
            xml = ET.fromstring(domain.XMLDesc(libvirt.VIR_DOMAIN_XML_SECURE))
            graphics = xml.find(".//graphics[@type='vnc']")
            if graphics is not None:
                port = graphics.get("port", "-1")
                result.append(
                    {
                        "vm_name": domain.name(),
                        "vnc_port": int(port) if port else None,
                        "display": int(port) - 5900 if port and int(port) > 0 else None,
                        "listen": graphics.get("listen", "127.0.0.1"),
                        "viewer_command": (
                            f"vncviewer :{int(port) - 5900}" if port and int(port) > 0 else None
                        ),
                    }
                )
        except Exception as e:
            result.append({"vm_name": domain.name(), "error": str(e)})
    return sorted(result, key=lambda x: x.get("vm_name", ""))


def get_console_uri(vm_name: str, host: str = "localhost") -> dict:
    conn = pool.get_connection(host)
    domain = conn.lookupByName(vm_name)
    xml = ET.fromstring(domain.XMLDesc(libvirt.VIR_DOMAIN_XML_SECURE))
    consoles = []
    vnc = xml.find(".//graphics[@type='vnc']")
    if vnc is not None:
        port = vnc.get("port", "-1")
        listen = vnc.get("listen", "127.0.0.1")
        consoles.append(
            {
                "type": "vnc",
                "uri": f"vnc://{host}:{port}" if host != "localhost" else f"vnc://localhost:{port}",
                "port": int(port) if port else None,
            }
        )
    spice = xml.find(".//graphics[@type='spice']")
    if spice is not None:
        port = spice.get("port", "-1")
        listen = spice.get("listen", "127.0.0.1")
        consoles.append(
            {
                "type": "spice",
                "uri": (
                    f"spice://{host}:{port}" if host != "localhost" else f"spice://localhost:{port}"
                ),
                "port": int(port) if port else None,
            }
        )
    serial = xml.find(".//console[@type='pty']")
    if serial is not None:
        consoles.append({"type": "serial", "command": f"virsh console {vm_name}"})
    return {
        "vm_name": vm_name,
        "host": host,
        "consoles": consoles,
        "primary": consoles[0] if consoles else None,
    }
