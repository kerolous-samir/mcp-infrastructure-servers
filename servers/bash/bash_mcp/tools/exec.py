import base64
import os
import tempfile
from .remote import run as _run, _local, is_remote


def run_command(
    command: str,
    host: str = "localhost",
    username: str = "root",
    password: str = None,
    key_path: str = None,
    cwd: str = "/",
    timeout: int = 120,
) -> dict:
    return _run(
        command,
        host=host,
        username=username,
        password=password,
        key_path=key_path,
        timeout=timeout,
        cwd=cwd,
    )


def run_script(
    script: str,
    host: str = "localhost",
    username: str = "root",
    password: str = None,
    key_path: str = None,
    cwd: str = "/",
    timeout: int = 60,
) -> dict:
    if not is_remote(host):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write("#!/bin/bash\nset -e\n")
            f.write(script)
            path = f.name
        try:
            os.chmod(path, 448)
            return _local(path, timeout=timeout, cwd=cwd)
        finally:
            os.unlink(path)
    else:
        full = "#!/bin/bash\nset -e\n" + script
        encoded = base64.b64encode(full.encode("utf-8")).decode("ascii")
        cmd = f"echo {encoded} | base64 -d | bash -s"
        return _run(
            cmd, host=host, username=username, password=password, key_path=key_path, timeout=timeout
        )
