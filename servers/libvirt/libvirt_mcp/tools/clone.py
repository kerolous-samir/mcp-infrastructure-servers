import re
import shlex
import subprocess
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)
_VM_NAME_RE = re.compile("^[A-Za-z0-9._-]{1,64}$")
_REMOTE_DIR_RE = re.compile("^/[A-Za-z0-9._/-]{1,255}$")
_HOST_RE = re.compile("^[A-Za-z0-9.:_-]{1,253}$")
_USERNAME_RE = re.compile("^[a-z_][a-z0-9_-]{0,31}$")
_KEY_PATH_RE = re.compile("^/[A-Za-z0-9._/-]{1,255}$")


def _validate_host(host: str) -> None:
    if not isinstance(host, str) or not _HOST_RE.match(host):
        raise ValueError(f"Invalid host {host!r}: must match ^[A-Za-z0-9.:_-]{{1,253}}$")


def _validate_username(username: str) -> None:
    if not isinstance(username, str) or not _USERNAME_RE.match(username):
        raise ValueError(f"Invalid username {username!r}: must match ^[a-z_][a-z0-9_-]{{0,31}}$")


def _validate_key_path(ssh_key_path: Optional[str]) -> None:
    if ssh_key_path is None:
        return
    if not isinstance(ssh_key_path, str) or not _KEY_PATH_RE.match(ssh_key_path):
        raise ValueError(
            f"Invalid ssh_key_path {ssh_key_path!r}: must be an absolute path matching ^/[A-Za-z0-9._/-]+$"
        )


def _encrypt_credential(secret: str) -> "Optional[str]":
    if not secret:
        return None
    try:
        from libvirt_mcp.creds import enc_cred

        wrapped = enc_cred(secret)
    except Exception as e:
        logger.warning("cannot encrypt VM credential (%s) - not persisting", e)
        return None
    if not isinstance(wrapped, str) or not wrapped.startswith("ENC:"):
        logger.warning(
            "no usable MCP_CREDENTIAL_KEY - refusing to store the VM credential in plaintext"
        )
        return None
    return wrapped


def _validate_vm_name(new_vm_name: str) -> None:
    if not isinstance(new_vm_name, str) or not _VM_NAME_RE.match(new_vm_name):
        raise ValueError(
            f"Invalid VM name {new_vm_name!r}: must match ^[A-Za-z0-9._-]{{1,64}}$ (no spaces or shell metacharacters)"
        )


def _validate_remote_dir(remote_image_dir: str) -> None:
    if not isinstance(remote_image_dir, str) or not _REMOTE_DIR_RE.match(remote_image_dir):
        raise ValueError(
            f"Invalid remote_image_dir {remote_image_dir!r}: must be an absolute path matching ^/[A-Za-z0-9._/-]+$ (no spaces or shell metacharacters)"
        )


def clone_vm_local(
    source_vm: str, new_vm_name: str, new_disk_path: Optional[str] = None, host: str = "localhost"
) -> dict:
    _validate_vm_name(new_vm_name)
    if new_disk_path is None:
        new_disk_path = f"/var/lib/libvirt/images/{new_vm_name}.qcow2"
    connect_arg = []
    if host not in ("localhost", "127.0.0.1"):
        _validate_host(host)
        connect_arg = ["--connect", f"qemu+ssh://{host}/system"]
    cmd = [
        "virt-clone",
        *connect_arg,
        "--original",
        source_vm,
        "--name",
        new_vm_name,
        "--file",
        new_disk_path,
        "--auto-clone",
    ]
    logger.info(f"Cloning {source_vm} -> {new_vm_name} on {host}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"virt-clone failed: {result.stderr}")
    return {
        "status": "cloned",
        "source_vm": source_vm,
        "new_vm_name": new_vm_name,
        "new_disk_path": new_disk_path,
        "host": host,
    }


def clone_image_to_host(
    image_path: str,
    target_host: str,
    remote_path: Optional[str] = None,
    username: str = "root",
    ssh_key_path: Optional[str] = None,
    ssh_port: int = 22,
) -> dict:
    _validate_host(target_host)
    _validate_username(username)
    _validate_key_path(ssh_key_path)
    if remote_path is None:
        remote_path = image_path
    ssh_opts = ["-p", str(int(ssh_port)), "-o", "StrictHostKeyChecking=accept-new"]
    if ssh_key_path:
        ssh_opts += ["-i", ssh_key_path]
    ssh_opt_str = " ".join((shlex.quote(o) for o in ssh_opts))
    cmd = [
        "rsync",
        "-avz",
        "--progress",
        "-e",
        "ssh " + ssh_opt_str,
        image_path,
        f"{username}@{target_host}:{remote_path}",
    ]
    logger.info(f"Transferring {image_path} to {target_host}:{remote_path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        logger.warning("rsync failed, falling back to scp...")
        scp_cmd = ["scp"]
        if ssh_key_path:
            scp_cmd += ["-i", ssh_key_path]
        scp_cmd += [
            "-P",
            str(ssh_port),
            "-o",
            "StrictHostKeyChecking=accept-new",
            image_path,
            f"{username}@{target_host}:{remote_path}",
        ]
        result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            raise RuntimeError(f"Image transfer failed: {result.stderr}")
    image_size = os.path.getsize(image_path) if os.path.exists(image_path) else 0
    return {
        "status": "transferred",
        "image_path": image_path,
        "target_host": target_host,
        "remote_path": remote_path,
        "image_size_gb": round(image_size / 1024**3, 2),
    }


def clone_vm_remote(
    source_image_path: str,
    new_vm_name: str,
    target_host: str,
    vcpus: int,
    memory_mb: int,
    network_bridge: str = "virbr0",
    os_variant: str = "win2k22",
    remote_image_dir: str = "/var/lib/libvirt/images",
    username: str = "root",
    ssh_key_path: Optional[str] = None,
    ssh_port: int = 22,
    skip_transfer: bool = False,
    uefi: bool = True,
    disk_size_gb: Optional[int] = None,
    keep_golden: bool = False,
) -> dict:
    _validate_vm_name(new_vm_name)
    _validate_remote_dir(remote_image_dir)
    _validate_host(target_host)
    _validate_username(username)
    _validate_key_path(ssh_key_path)
    image_filename = os.path.basename(source_image_path)
    remote_golden_path = f"{remote_image_dir}/{image_filename}"
    remote_vm_disk = f"{remote_image_dir}/{new_vm_name}.qcow2"
    results = {}
    if not skip_transfer:
        logger.info(f"Step 1: Transferring golden image to {target_host}")
        transfer_result = clone_image_to_host(
            image_path=source_image_path,
            target_host=target_host,
            remote_path=remote_golden_path,
            username=username,
            ssh_key_path=ssh_key_path,
            ssh_port=ssh_port,
        )
        results["image_transfer"] = transfer_result
    else:
        logger.info(f"Step 1: Skipping image transfer (already on {target_host})")
        results["image_transfer"] = {"status": "skipped", "remote_path": remote_golden_path}
    logger.info(f"Step 2: Creating full standalone clone on {target_host}")
    ssh_opts = ["-o", "StrictHostKeyChecking=accept-new"]
    if ssh_key_path:
        ssh_opts += ["-i", ssh_key_path]
    if ssh_port != 22:
        ssh_opts += ["-p", str(ssh_port)]
    qemu_img_cmd = f"qemu-img convert -f qcow2 -O qcow2 {shlex.quote(remote_golden_path)} {shlex.quote(remote_vm_disk)}"
    ssh_cmd = ["ssh"] + ssh_opts + [f"{username}@{target_host}", qemu_img_cmd]
    result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"qemu-img convert failed: {result.stderr}")
    results["disk_clone"] = {"status": "created", "path": remote_vm_disk, "type": "full_standalone"}
    if disk_size_gb:
        logger.info(f"Step 2b: Resizing disk to {disk_size_gb}GB on {target_host}")
        resize_cmd = (
            ["ssh"]
            + ssh_opts
            + [
                f"{username}@{target_host}",
                f"qemu-img resize {shlex.quote(remote_vm_disk)} {int(disk_size_gb)}G",
            ]
        )
        res = subprocess.run(resize_cmd, capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            logger.warning(f"qemu-img resize failed (non-fatal): {res.stderr}")
            results["disk_resize"] = {"status": "failed", "error": res.stderr}
        else:
            results["disk_resize"] = {"status": "resized", "size_gb": disk_size_gb}
    if keep_golden:
        logger.info(f"Step 2c: keeping golden image on {target_host} (batch clone)")
    else:
        logger.info(f"Step 2c: Removing golden image from {target_host} to free space")
        rm_cmd = (
            ["ssh"]
            + ssh_opts
            + [f"{username}@{target_host}", f"rm -f {shlex.quote(remote_golden_path)}"]
        )
        rm_result = subprocess.run(rm_cmd, capture_output=True, text=True, timeout=30)
        if rm_result.returncode != 0:
            logger.warning(f"Could not remove golden image from {target_host}: {rm_result.stderr}")
        else:
            logger.info(f"Golden image removed from {target_host}")
    logger.info(f"Step 3: Defining VM {new_vm_name} on {target_host}")
    from ..core.connection import pool, HostConfig

    if target_host not in pool.list_hosts():
        pool.register_host(
            HostConfig(
                host=target_host, username=username, ssh_key_path=ssh_key_path, port=ssh_port
            )
        )
    connect_uri = f"qemu+ssh://{username}@{target_host}/system"
    if ssh_key_path:
        connect_uri += f"?keyfile={ssh_key_path}&known_hosts_verify=auto"
    define_cmd = [
        "virt-install",
        "--connect",
        connect_uri,
        "--name",
        new_vm_name,
        "--vcpus",
        str(vcpus),
        "--memory",
        str(memory_mb),
        "--disk",
        f"path={remote_vm_disk},format=qcow2",
        "--network",
        f"bridge={network_bridge}",
        "--os-variant",
        os_variant,
        "--graphics",
        "vnc",
        "--noautoconsole",
    ]
    define_cmd += ["--import"]
    if uefi:
        define_cmd += ["--machine", "q35", "--boot", "firmware=efi,hd"]
    result = subprocess.run(define_cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"VM definition failed: {result.stderr}")
    results["vm_created"] = {
        "status": "defined_and_started",
        "vm_name": new_vm_name,
        "host": target_host,
        "vcpus": vcpus,
        "memory_mb": memory_mb,
    }
    return {
        "status": "success",
        "vm_name": new_vm_name,
        "target_host": target_host,
        "pipeline": results,
    }


def clone_to_all_hosts(
    source_image_path: str,
    vm_name_prefix: str,
    target_hosts: list[str],
    vcpus: int,
    memory_mb: int,
    network_bridge: str = "virbr0",
    os_variant: str = "win2k22",
    remote_image_dir: str = "/var/lib/libvirt/images",
    username: str = "root",
    ssh_key_path: Optional[str] = None,
    vms_per_host: int = 4,
    uefi: bool = True,
) -> dict:
    _validate_username(username)
    _validate_key_path(ssh_key_path)
    _validate_remote_dir(remote_image_dir)
    for _h in target_hosts:
        _validate_host(_h)
    results = {}
    for host in target_hosts:
        host_results = []
        host_label = host.replace(".", "-")
        logger.info(f"Transferring golden image to {host}")
        try:
            transfer = clone_image_to_host(
                image_path=source_image_path,
                target_host=host,
                username=username,
                ssh_key_path=ssh_key_path,
            )
            host_results.append({"image_transfer": transfer})
        except Exception as e:
            results[host] = {"status": "failed", "error": str(e)}
            continue
        for i in range(1, vms_per_host + 1):
            vm_name = f"{vm_name_prefix}-{host_label}-{i}"
            logger.info(f"Creating VM {vm_name} on {host}")
            try:
                vm_result = clone_vm_remote(
                    source_image_path=source_image_path,
                    new_vm_name=vm_name,
                    target_host=host,
                    vcpus=vcpus,
                    memory_mb=memory_mb,
                    network_bridge=network_bridge,
                    os_variant=os_variant,
                    remote_image_dir=remote_image_dir,
                    username=username,
                    ssh_key_path=ssh_key_path,
                    skip_transfer=True,
                    uefi=uefi,
                    keep_golden=True,
                )
                host_results.append({vm_name: vm_result})
            except Exception as e:
                host_results.append({vm_name: {"status": "failed", "error": str(e)}})
        try:
            import os as _os

            _golden_remote = f"{remote_image_dir}/{_os.path.basename(source_image_path)}"
            _ssh_opts = ["-o", "StrictHostKeyChecking=accept-new"]
            if ssh_key_path:
                _ssh_opts += ["-i", ssh_key_path]
            _rm = subprocess.run(
                ["ssh"]
                + _ssh_opts
                + [f"{username}@{host}", f"rm -f {shlex.quote(_golden_remote)}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            golden_cleanup = "removed" if _rm.returncode == 0 else f"failed: {_rm.stderr.strip()}"
        except Exception as _e:
            golden_cleanup = f"failed: {_e}"
        results[host] = {
            "status": "completed",
            "golden_cleanup": golden_cleanup,
            "vms_requested": vms_per_host,
            "details": host_results,
        }
    return {"status": "all_hosts_processed", "hosts": target_hosts, "results": results}


def clone_vm_remote_by_template(
    template_name: str,
    new_vm_name: str,
    target_host: str,
    vcpus: int,
    memory_mb: int,
    network_bridge: str = "virbr0",
    remote_image_dir: str = "/var/lib/libvirt/images",
    username: str = "root",
    ssh_key_path: Optional[str] = None,
    ssh_port: int = 22,
    disk_size_gb: Optional[int] = None,
) -> dict:
    _validate_vm_name(new_vm_name)
    _validate_host(target_host)
    _validate_username(username)
    _validate_key_path(ssh_key_path)
    _validate_remote_dir(remote_image_dir)
    import psycopg2 as _psycopg2

    _db_conn_params = dict(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_DATABASE", ""),
        user=os.environ.get("DB_USERNAME", ""),
        password=os.environ.get("DB_PASSWORD", ""),
        connect_timeout=5,
    )
    conn = _psycopg2.connect(**_db_conn_params)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT image_path, uefi, os_type, admin_username, admin_password FROM os_templates WHERE name=%s AND status='ready'",
                (template_name,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError(f"Template '{template_name}' not found or not ready")
    image_path, uefi, os_type, admin_user, admin_pass = row
    os_variant = "win2k22" if os_type == "windows" else "ubuntu22.04"
    result = clone_vm_remote(
        source_image_path=image_path,
        new_vm_name=new_vm_name,
        target_host=target_host,
        vcpus=vcpus,
        memory_mb=memory_mb,
        network_bridge=network_bridge,
        os_variant=os_variant,
        remote_image_dir=remote_image_dir,
        username=username,
        ssh_key_path=ssh_key_path,
        ssh_port=ssh_port,
        uefi=uefi,
        disk_size_gb=disk_size_gb,
    )
    if result.get("status") == "success":
        enc_pass = _encrypt_credential(admin_pass)
        if enc_pass is None:
            result["credentials_saved"] = False
            result["credentials_skipped_reason"] = (
                "no usable CREDENTIAL_KEY in the libvirt MCP env — refused to store the VM credential in plaintext"
            )
        else:
            try:
                conn2 = _psycopg2.connect(**_db_conn_params)
                with conn2.cursor() as cur:
                    cur.execute(
                        "\n                        INSERT INTO ad_users (username, user_type, password, assigned_vm, notes)\n                        VALUES (%s, 'local_admin', %s, %s, %s)\n                        ON CONFLICT (username) DO UPDATE SET\n                            password    = EXCLUDED.password,\n                            assigned_vm = EXCLUDED.assigned_vm,\n                            notes       = EXCLUDED.notes\n                    ",
                        (
                            admin_user,
                            enc_pass,
                            new_vm_name,
                            f"auto-created from template '{template_name}'",
                        ),
                    )
                    conn2.commit()
                conn2.close()
                result["credentials_saved"] = True
            except Exception as _ce:
                logger.warning(f"Failed to save credentials for {new_vm_name}: {_ce}")
                result["credentials_saved"] = False
    return result
