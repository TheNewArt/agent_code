"""
tests/test_agent_loop.py — Tests for core/agent_loop.py
"""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.agent_loop import (
    ToolRouter, ControlPlane, PreResult,
    AgentRegistry, AgentRunner,
    BASE_TOOLS, BASE_HANDLERS,
)


class TestToolRouter(unittest.TestCase):
    def test_register_and_dispatch(self):
        router = ToolRouter()
        router.register("test_tool", lambda a, c: "ok", {"name": "test_tool", "input_schema": {}})
        result = router.dispatch("test_tool", {}, {})
        self.assertEqual(result, "ok")

    def test_dispatch_unknown(self):
        router = ToolRouter()
        result = router.dispatch("unknown_tool", {}, {})
        self.assertIn("Unknown tool", result)

    def test_dispatch_with_args(self):
        router = ToolRouter()
        router.register("add", lambda a, c: str(a["x"] + a["y"]),
                        {"name": "add", "input_schema": {"type": "object", "properties": {}}})
        result = router.dispatch("add", {"x": 2, "y": 3}, {})
        self.assertEqual(result, "5")

    def test_tools_for_llm(self):
        router = ToolRouter()
        tools = router.tools_for_llm()
        # 有 BASE_TOOLS 注册
        self.assertGreater(len(tools), 0)


class TestControlPlane(unittest.TestCase):
    def test_init(self):
        router = ToolRouter()
        plane = ControlPlane(router)
        self.assertIs(plane.router, router)

    def test_pre_tool_no_hooks_no_perms(self):
        router = ToolRouter()
        plane = ControlPlane(router)
        result = plane.pre_tool("bash", {"command": "echo hi"})
        self.assertTrue(result.has_permission)
        self.assertFalse(result.blocked)
        self.assertEqual(result.injected_messages, [])

    def test_pre_tool_blocked_by_hook(self):
        router = ToolRouter()
        plane = ControlPlane(router)

        class FakeHookMgr:
            def run_hooks(self, event, ctx):
                return {"blocked": True, "block_reason": "test block", "messages": []}
        plane.set_hooks(FakeHookMgr())
        result = plane.pre_tool("bash", {"command": "echo hi"})
        self.assertTrue(result.blocked)
        self.assertIn("test block", result.output)

    def test_post_tool_passes_through(self):
        router = ToolRouter()
        plane = ControlPlane(router)
        result = plane.post_tool("bash", {}, "original output")
        self.assertEqual(result, "original output")


class TestPreResult(unittest.TestCase):
    def test_dataclass_fields(self):
        pr = PreResult(True, False, None, ["msg1"])
        self.assertTrue(pr.has_permission)
        self.assertFalse(pr.blocked)
        self.assertEqual(pr.injected_messages, ["msg1"])


class TestAgentRegistry(unittest.TestCase):
    def test_default_registry(self):
        reg = AgentRegistry()
        self.assertIsNone(reg.skills)
        self.assertIsNone(reg.memory)
        self.assertIsNone(reg.tasks)
        self.assertIsNone(reg.cron)
        self.assertIsNone(reg.background)
        self.assertIsNone(reg.permissions)
        self.assertIsNone(reg.compact)
        self.assertIsNone(reg.worktrees)
        self.assertIsNone(reg.message_bus)

    def test_with_capabilities(self):
        reg = AgentRegistry(skills="mock_skills", memory="mock_memory")
        self.assertEqual(reg.skills, "mock_skills")
        self.assertEqual(reg.memory, "mock_memory")


class TestBaseTools(unittest.TestCase):
    def test_base_tools_count(self):
        self.assertGreaterEqual(len(BASE_TOOLS), 4)
        names = [t["name"] for t in BASE_TOOLS]
        for name in ["bash", "read_file", "write_file", "edit_file"]:
            self.assertIn(name, names)

    def test_bash_schema(self):
        bash_tool = next(t for t in BASE_TOOLS if t["name"] == "bash")
        self.assertEqual(bash_tool["input_schema"]["properties"]["command"]["type"], "string")


if __name__ == "__main__":
    unittest.main()
