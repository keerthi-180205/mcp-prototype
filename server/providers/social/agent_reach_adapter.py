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
        """
        Execute an agent-reach command with JSON output format.
        Example: agent-reach get youtube.info <url> --json
        """
        if not self.is_installed():
            logger.warning("agent-reach not installed, command '%s' skipped", channel_cmd)
            return None

        cmd = [self.executable, "get", channel_cmd, target, "--json"]
        if limit is not None:
            cmd.extend(["--limit", str(limit)])
        if max_tokens is not None:
            cmd.extend(["--max-tokens", str(max_tokens)])

        logger.info("Executing Agent Reach command: %s", " ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out_str = stdout.decode("utf-8", errors="replace").strip()
            err_str = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                logger.error("Agent Reach command failed (code %d): %s", proc.returncode, err_str)
                return None

            if not out_str:
                return {}

            try:
                return json.loads(out_str)
            except json.JSONDecodeError:
                # Some commands may output plain text or markdown
                return {"raw_text": out_str}
        except asyncio.TimeoutError:
            logger.error("Agent Reach command '%s' timed out after %ds", channel_cmd, timeout)
            return None
        except Exception as e:
            logger.error("Exception executing Agent Reach command '%s': %s", channel_cmd, e)
            return None
