# Multi-agent infrastructure: MCP Client & Plugin System
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class MCPClient:
    """
    Minimal MCP client over stdio.
    Connects to an MCP server, lists its tools, and can call them.
    """

    def __init__(self, server_name: str, command: str, args: list | None = None, env: dict | None = None):
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self.env = {**subprocess.os.environ.copy(), **(env or {})}
        self.process: subprocess.Popen | None = None
        self._request_id = 0
        self._tools: list = []

    def connect(self) -> bool:
        try:
            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                text=True,
            )
            self._send({"method": "initialize", "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agent_code", "version": "1.0"},
            }})
            response = self._recv()
            if response and "result" in response:
                self._send({"method": "notifications/initialized"})
                return True
        except FileNotFoundError:
            print(f"[MCP] Server command not found: {self.command}")
        except Exception as e:
            print(f"[MCP] Connection failed: {e}")
        return False

    def list_tools(self) -> list:
        self._send({"method": "tools/list", "params": {}})
        response = self._recv()
        if response and "result" in response:
            self._tools = response["result"].get("tools", [])
        return self._tools

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        self._send({"method": "tools/call", "params": {"name": tool_name, "arguments": arguments}})
        response = self._recv()
        if response and "result" in response:
            content = response["result"].get("content", [])
            return "\n".join(c.get("text", str(c)) for c in content)
        if response and "error" in response:
            return f"MCP Error: {response['error'].get('message', 'unknown')}"
        return "MCP Error: no response"

    def get_agent_tools(self) -> list:
        """Convert MCP tools to the agent tool format with mcp__ prefix."""
        agent_tools = []
        for tool in self._tools:
            prefixed_name = f"mcp__{self.server_name}__{tool['name']}"
            agent_tools.append({
                "name": prefixed_name,
                "description": tool.get("description", ""),
                "input_schema": tool.get("inputSchema", {"type": "object", "properties": {}}),
                "_mcp_server": self.server_name,
                "_mcp_tool": tool["name"],
            })
        return agent_tools

    def disconnect(self) -> None:
        if self.process:
            try:
                self._send({"method": "shutdown"})
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None

    def _send(self, message: dict) -> None:
        if not self.process or self.process.poll() is not None:
            return
        self._request_id += 1
        envelope = {"jsonrpc": "2.0", "id": self._request_id, **message}
        line = json.dumps(envelope) + "\n"
        try:
            self.process.stdin.write(line)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def _recv(self) -> dict | None:
        if not self.process or self.process.poll() is not None:
            return None
        try:
            line = self.process.stdout.readline()
            if line:
                return json.loads(line)
        except (json.JSONDecodeError, OSError):
            pass
        return None


class PluginLoader:
    """
    Load plugins from .claude-plugin/plugin.json manifests.
    Each plugin can declare MCP servers that are started on demand.
    """

    def __init__(self, search_dirs: list[Path] | None = None):
        self.search_dirs = search_dirs or [Path.cwd()]
        self.plugins: dict = {}

    def scan(self) -> list:
        found = []
        for search_dir in self.search_dirs:
            manifest_path = Path(search_dir) / ".claude-plugin" / "plugin.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text())
                    name = manifest.get("name", manifest_path.parent.parent.name)
                    self.plugins[name] = manifest
                    found.append(name)
                except (json.JSONDecodeError, OSError) as e:
                    print(f"[Plugin] Failed to load {manifest_path}: {e}")
        return found

    def get_mcp_servers(self) -> dict:
        """Returns {server_name: {command, args, env}}."""
        servers = {}
        for plugin_name, manifest in self.plugins.items():
            for server_name, config in manifest.get("mcpServers", {}).items():
                servers[f"{plugin_name}__{server_name}"] = config
        return servers


class MCPToolRouter:
    """
    Route MCP tool calls to the correct server.
    Tools are prefixed mcp__<server>__<tool>.
    """

    def __init__(self):
        self.clients: dict[str, MCPClient] = {}

    def register_client(self, client: MCPClient) -> None:
        self.clients[client.server_name] = client

    def is_mcp_tool(self, tool_name: str) -> bool:
        return tool_name.startswith("mcp__")

    def call(self, tool_name: str, arguments: dict) -> str:
        parts = tool_name.split("__", 2)
        if len(parts) != 3:
            return f"Error: Invalid MCP tool name: {tool_name}"
        _, server_name, actual_tool = parts
        client = self.clients.get(server_name)
        if not client:
            return f"Error: MCP server not found: {server_name}"
        return client.call_tool(actual_tool, arguments)

    def get_all_tools(self) -> list:
        tools = []
        for client in self.clients.values():
            tools.extend(client.get_agent_tools())
        return tools
