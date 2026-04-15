"""
tests/test_mcp_client.py — Tests for multiagent/mcp_client.py
"""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from multiagent.mcp_client import MCPClient, PluginLoader, MCPToolRouter


class TestMCPClient(unittest.TestCase):
    def test_init(self):
        client = MCPClient("test_server", "nonexistent_command")
        self.assertEqual(client.server_name, "test_server")
        self.assertEqual(client._tools, [])

    def test_is_connected_false_initially(self):
        client = MCPClient("test_server", "nonexistent_command")
        self.assertIsNone(client.process)

    def test_get_agent_tools_empty(self):
        client = MCPClient("test_server", "nonexistent_command")
        tools = client.get_agent_tools()
        self.assertEqual(tools, [])

    def test_prefixed_tool_name(self):
        client = MCPClient("test_server", "cmd")
        client._tools = [{"name": "my_tool", "description": "A test tool",
                          "inputSchema": {"type": "object", "properties": {}}}]
        tools = client.get_agent_tools()
        self.assertEqual(len(tools), 1)
        self.assertTrue(tools[0]["name"].startswith("mcp__test_server__"))
        self.assertEqual(tools[0]["name"], "mcp__test_server__my_tool")


class TestPluginLoader(unittest.TestCase):
    def test_init_empty(self):
        loader = PluginLoader()
        self.assertEqual(loader.plugins, {})

    def test_scan_no_plugins(self):
        loader = PluginLoader(search_dirs=[Path("/nonexistent")])
        found = loader.scan()
        self.assertEqual(found, [])

    def test_get_mcp_servers_empty(self):
        loader = PluginLoader()
        servers = loader.get_mcp_servers()
        self.assertEqual(servers, {})


class TestMCPToolRouter(unittest.TestCase):
    def test_init(self):
        router = MCPToolRouter()
        self.assertEqual(router.clients, {})

    def test_is_mcp_tool(self):
        router = MCPToolRouter()
        self.assertTrue(router.is_mcp_tool("mcp__server__tool"))
        self.assertFalse(router.is_mcp_tool("bash"))

    def test_call_unknown_server(self):
        router = MCPToolRouter()
        result = router.call("mcp__unknown__tool", {})
        self.assertIn("not found", result)

    def test_call_invalid_name(self):
        router = MCPToolRouter()
        result = router.call("not_mcp_format", {})
        self.assertIn("Invalid MCP tool name", result)

    def test_get_all_tools_empty(self):
        router = MCPToolRouter()
        tools = router.get_all_tools()
        self.assertEqual(tools, [])


if __name__ == "__main__":
    unittest.main()
