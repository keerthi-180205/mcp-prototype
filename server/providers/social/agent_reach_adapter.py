"""Capability layer adapter for Agent Reach CLI."""

import asyncio
import json
import logging
import shutil
from typing import Any, Dict, Optional

logger = logging.getLogger("mcp_server.capability.agent_reach")


class AgentReachAdapter:
    """
    Subprocess adapter communicating with Agent Reach CLI.
    Enables low-configuration access to supported tools like yt-dlp, Jina, feedparser, etc.
    """

    def __init__(self, executable: Optional[str] = None):
        self.executable = executable or shutil.which("agent-reach") or "agent-reach"

    def is_installed(self) -> bool:
        """Check if the agent-reach CLI binary is accessible on PATH."""
        return shutil.which(self.executable) is not None

    async def get_doctor_status(self) -> Dict[str, Any]:
        """Run 'agent-reach doctor' to determine installed channels and tools."""
        if not self.is_installed():
            return {"installed": False, "error": "agent-reach executable not found"}

        try:
            proc = await asyncio.create_subprocess_exec(
                self.executable,
                "doctor",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            output = stdout.decode("utf-8", errors="replace")
            return {
                "installed": True,
                "returncode": proc.returncode,
                "output": output,
                "available_channels": [
                    ch
                    for ch in ["youtube", "rss", "web", "github", "reddit", "twitter", "instagram"]
                    if ch in output.lower()
                ],
            }
        except Exception as e:
            logger.warning("Error running agent-reach doctor: %s", e)
            return {"installed": False, "error": str(e)}

    async def execute_command(
        self,
        channel_cmd: str,
        target: str,
        limit: Optional[int] = None,
        max_tokens: Optional[int] = None,
        timeout: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        """Deprecated no-op.

        Agent Reach only installs and health-checks its tools ('agent-reach doctor'); it has no
        'agent-reach get ...' command. Callers must invoke the underlying tools directly
        (yt-dlp, rdt, twitter). Always returns None.
        """
        logger.warning(
            "AgentReachAdapter.execute_command('%s') is unsupported: agent-reach has no 'get' command; "
            "call the underlying tool directly",
            channel_cmd,
        )
        return None
