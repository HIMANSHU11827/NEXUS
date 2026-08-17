"""MCP Server Catalog — structured discovery and management of MCP servers."""
__version__ = "1.0.0"

import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MCP_CATALOG_DIR = "mcp_servers"
MCP_CONFIG_FILE = "mcp_config.json"
_ENV_REFERENCE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
_SECRET_ENV_KEY = re.compile(r"(?i)(api[_-]?key|token|secret|password|credential)")
_SECRET_VALUE = re.compile(
    r"(?i)(?:"
    r"sk-[A-Za-z0-9_-]{12,}|"
    r"sk-or-[A-Za-z0-9_-]{12,}|"
    r"github_pat_[A-Za-z0-9_]{12,}|"
    r"ghp_[A-Za-z0-9_]{12,}|"
    r"xox[baprs]-[A-Za-z0-9-]{12,}|"
    r"bearer\s+[A-Za-z0-9._-]{12,}"
    r")"
)


def _is_env_reference(value: str) -> bool:
    return bool(_ENV_REFERENCE.match(str(value or "").strip()))


def _env_reference_name(value: str) -> str:
    return str(value).strip()[2:-1]


def _validate_env(name: str, env: Dict[str, str]) -> Dict[str, str]:
    validated: Dict[str, str] = {}
    for key, value in (env or {}).items():
        env_key = str(key or "").strip()
        env_value = str(value or "").strip()
        if not env_key:
            raise ValueError(f"MCP server '{name}' has an empty env key")
        if not env_value:
            continue
        if _is_env_reference(env_value):
            validated[env_key] = env_value
            continue
        if _SECRET_ENV_KEY.search(env_key) or _SECRET_VALUE.search(env_value):
            raise ValueError(
                f"MCP server '{name}' env '{env_key}' looks like a secret; "
                f"store it in the process environment and use ${{{env_key}}}"
            )
        validated[env_key] = env_value
    return validated


def _resolve_env_references(env: Dict[str, str]) -> Dict[str, str]:
    resolved: Dict[str, str] = {}
    for key, value in (env or {}).items():
        if _is_env_reference(value):
            env_name = _env_reference_name(value)
            if env_name in os.environ:
                resolved[key] = os.environ[env_name]
            continue
        resolved[key] = value
    return resolved


@dataclass
class MCPServerDef:
    """Definition of an MCP server."""
    name: str
    description: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    category: str = "general"
    version: str = "1.0.0"
    requires_env: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)


class MCPServerCatalog:
    """Catalog of available MCP servers for NEXUS."""

    def __init__(self, nexus_home: Optional[Path] = None):
        self.nexus_home = nexus_home or Path.cwd()
        self.catalog_file = self.nexus_home / MCP_CONFIG_FILE
        self.servers: Dict[str, MCPServerDef] = {}
        self._load()

    def _load(self):
        if self.catalog_file.exists():
            try:
                data = json.loads(self.catalog_file.read_text())
                for name, entry in data.get("servers", {}).items():
                    self.servers[name] = MCPServerDef(**entry)
            except Exception as e:
                logger.error(f"Failed to load MCP catalog: {e}")

    def _save(self):
        self.catalog_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "2.0",
            "servers": {
                name: {
                    "name": s.name,
                    "description": s.description,
                    "command": s.command,
                    "args": s.args,
                    "env": s.env,
                    "enabled": s.enabled,
                    "category": s.category,
                    "version": s.version,
                    "requires_env": s.requires_env,
                    "tools": s.tools,
                }
                for name, s in self.servers.items()
            }
        }
        self.catalog_file.write_text(json.dumps(data, indent=2))

    def register(self, server: MCPServerDef):
        """Register or update an MCP server."""
        server.env = _validate_env(server.name, server.env)
        self.servers[server.name] = server
        self._save()
        logger.info(f"MCP server '{server.name}' registered.")

    def unregister(self, name: str):
        """Remove an MCP server from the catalog."""
        if name in self.servers:
            del self.servers[name]
            self._save()
            logger.info(f"MCP server '{name}' unregistered.")

    def get_enabled_servers(self) -> List[MCPServerDef]:
        """Get all enabled servers with satisfied requirements."""
        enabled = []
        for server in self.servers.values():
            if not server.enabled:
                continue
            missing = [e for e in server.requires_env if not os.environ.get(e)]
            if missing:
                logger.debug(f"MCP server '{server.name}' skipped: missing {missing}")
                continue
            enabled.append(server)
        return enabled

    def start_server(self, name: str) -> Optional[subprocess.Popen]:
        """Start an MCP server process."""
        server = self.servers.get(name)
        if not server:
            logger.error(f"MCP server '{name}' not found.")
            return None

        try:
            env = os.environ.copy()
            env.update(_resolve_env_references(server.env))
            proc = subprocess.Popen(
                [server.command] + server.args,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            logger.info(f"MCP server '{name}' started (PID {proc.pid}).")
            return proc
        except Exception as e:
            logger.error(f"Failed to start MCP server '{name}': {e}")
            return None

    def list_servers(self) -> List[Dict[str, Any]]:
        """List all registered MCP servers with status."""
        result = []
        for name, s in self.servers.items():
            missing = [e for e in s.requires_env if not os.environ.get(e)]
            result.append({
                "name": name,
                "description": s.description,
                "category": s.category,
                "version": s.version,
                "enabled": s.enabled,
                "ready": len(missing) == 0,
                "missing_env": missing,
                "tools": s.tools,
            })
        return result

    @classmethod
    def builtin_servers(cls) -> List[MCPServerDef]:
        """Return built-in MCP server definitions."""
        return [
            MCPServerDef(
                name="nexus-ai",
                description="NEXUS AI — all local tools via MCP",
                command=sys.executable,
                args=["-m", "mcp.server"],
                category="development",
                tools=["*"],
            ),
            MCPServerDef(
                name="filesystem",
                description="Safe filesystem access with allowed directories",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", str(Path.cwd())],
                category="filesystem",
                tools=["read_file", "write_file", "list_directory", "search_files"],
            ),
            MCPServerDef(
                name="github",
                description="GitHub API integration",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-github"],
                category="development",
                requires_env=["GITHUB_TOKEN"],
                tools=["create_repository", "get_issue", "search_repositories"],
            ),
        ]
