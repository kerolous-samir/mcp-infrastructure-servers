import logging
from typing import Optional
from ..core.connection import pool

logger = logging.getLogger(__name__)


def run_ps(host: str, script: str, timeout: int = 60) -> dict:
    result = pool.run_ps(host, script, timeout=timeout)
    return {"host": host, "script": script, **result}


def run_cmd(host: str, command: str, args: Optional[list] = None, timeout: int = 60) -> dict:
    result = pool.run_cmd(host, command, args=args, timeout=timeout)
    return {"host": host, "command": command, **result}
