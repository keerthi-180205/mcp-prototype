"""Async subprocess helper for the platform CLIs (yt-dlp, rdt, twitter)."""

import asyncio
import logging
import os
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("mcp_server.collection.cli")


class CliError(Exception):
    """Raised when a CLI cannot be started, times out or exits non-zero."""

    def __init__(self, message: str, returncode: Optional[int] = None, stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


async def run_cli(
    args: List[str],
    timeout: float = 60.0,
    env: Optional[Dict[str, str]] = None,
    allow_nonzero: bool = False,
) -> Tuple[int, str, str]:
    """Run a CLI and return (returncode, stdout, stderr).

    Credentials are only passed through the environment, never on the command line, and
    are never logged. Raises CliError on start failure, timeout, or (unless allow_nonzero)
    a non-zero exit code.
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
        )
    except (FileNotFoundError, PermissionError) as exc:
        raise CliError(f"cannot start '{args[0]}': {exc}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise CliError(f"'{os.path.basename(args[0])}' timed out after {timeout:.0f}s") from exc

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0 and not allow_nonzero:
        tail = err.strip().splitlines()[-1] if err.strip() else ""
        raise CliError(
            f"'{os.path.basename(args[0])}' exited with code {proc.returncode}: {tail[:300]}",
            returncode=proc.returncode,
            stderr=err,
        )
    return proc.returncode or 0, out, err


def find_binary(name: str) -> Optional[str]:
    """Locate a CLI on PATH, falling back to the running interpreter's bin dir (venv without activate)."""
    import shutil
    import sys

    found = shutil.which(name)
    if found:
        return found
    candidate = os.path.join(os.path.dirname(sys.executable), name)
    return candidate if os.path.isfile(candidate) and os.access(candidate, os.X_OK) else None
