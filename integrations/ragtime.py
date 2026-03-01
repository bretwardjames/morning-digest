"""Ragtime integration for memory and feedback storage.

Attempts MCP server approach first, falls back to subprocess CLI calls.
"""

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class RagtimeClient:
    def __init__(self, project_path: str = ".", namespace: str = "digest"):
        self.project_path = project_path
        self.namespace = namespace
        self._use_mcp: bool | None = None

    def remember(self, content: str, type: str = "context", component: str = "") -> None:
        """Store a memory in ragtime."""
        cmd = [
            "ragtime", "remember", content,
            "--namespace", self.namespace,
            "--type", type,
        ]
        if component:
            cmd.extend(["--component", component])

        self._run(cmd)
        logger.info(f"Stored memory: {content[:80]}...")

    def search(self, query: str) -> list[dict]:
        """Search ragtime for relevant memories."""
        cmd = [
            "ragtime", "search", query,
            "--namespace", self.namespace,
        ]
        result = self._run(cmd, capture=True)

        if result and result.stdout:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return [{"text": result.stdout}]
        return []

    def get_mcp_server_config(self) -> dict:
        """Return MCP server config for use with Anthropic API calls."""
        return {
            "type": "stdio",
            "command": "ragtime-mcp",
            "args": ["--path", self.project_path],
            "name": "ragtime",
        }

    def _run(self, cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess | None:
        """Run a ragtime CLI command."""
        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_path,
                capture_output=capture,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning(f"ragtime command failed: {' '.join(cmd)}")
                if result.stderr:
                    logger.warning(f"stderr: {result.stderr}")
            return result
        except FileNotFoundError:
            logger.error("ragtime CLI not found. Install ragtime first.")
            raise
        except subprocess.TimeoutExpired:
            logger.error(f"ragtime command timed out: {' '.join(cmd)}")
            return None
