"""
tests/test_hooks.py — Tests for capabilities/hooks.py
"""
import unittest
import tempfile
import json
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from capabilities.hooks import HookManager, HOOK_EVENTS, HOOK_TIMEOUT


class TestHookManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.hook_file = Path(self.tmpdir) / ".hooks.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_loads_valid_config(self):
        config = {"hooks": {"PreToolUse": [], "PostToolUse": [], "SessionStart": []}}
        self.hook_file.write_text(json.dumps(config))
        hm = HookManager(config_path=self.hook_file)
        self.assertEqual(len(hm.hooks["PreToolUse"]), 0)

    def test_hook_events_defined(self):
        self.assertIn("PreToolUse", HOOK_EVENTS)
        self.assertIn("PostToolUse", HOOK_EVENTS)
        self.assertIn("SessionStart", HOOK_EVENTS)

    def test_run_hooks_no_workspace_trust(self):
        # 无 .claude/.claude_trusted 且非 sdk_mode
        hm = HookManager(config_path=self.hook_file)
        result = hm.run_hooks("PreToolUse", {"tool_name": "bash", "tool_input": {}})
        self.assertFalse(result["blocked"])

    def test_trust_marker_allows_hooks(self):
        # 创建 trust marker
        trust_dir = Path(self.tmpdir) / ".claude"
        trust_dir.mkdir()
        (trust_dir / ".claude_trusted").touch()

        # 创建 hook 配置，执行一个 echo 命令
        config = {"hooks": {
            "PreToolUse": [{"matcher": "bash", "command": f'echo "hook ran"' }],
            "PostToolUse": [],
            "SessionStart": [],
        }}
        self.hook_file.write_text(json.dumps(config))

        import os
        orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)
        try:
            hm = HookManager(config_path=self.hook_file)
            result = hm.run_hooks("PreToolUse", {"tool_name": "bash", "tool_input": {}})
            # exit code 0 -> hook ran
            self.assertFalse(result["blocked"])
        finally:
            os.chdir(orig_cwd)


if __name__ == "__main__":
    unittest.main()
