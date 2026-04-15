"""
tests/test_permissions.py — Tests for capabilities/permissions.py
"""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from capabilities.permissions import (
    BashSecurityValidator, PermissionManager,
    PERMISSION_MODES, READ_ONLY_TOOLS, WRITE_TOOLS,
)


class TestBashSecurityValidator(unittest.TestCase):
    def setUp(self):
        self.v = BashSecurityValidator()

    def test_detects_sudo(self):
        self.assertFalse(self.v.is_safe("sudo apt update"))
        self.assertTrue(self.v.describe_failures("sudo apt update").startswith("Security flags"))

    def test_detects_shell_metachar(self):
        # semicolon
        self.assertFalse(self.v.is_safe("echo hi; rm -rf"))
        # pipe
        self.assertFalse(self.v.is_safe("cat file | grep pattern"))

    def test_detects_rm_rf(self):
        self.assertFalse(self.v.is_safe("rm -rf /tmp/test"))

    def test_detects_cmd_substitution(self):
        self.assertFalse(self.v.is_safe("$(whoami)"))
        self.assertFalse(self.v.is_safe("`whoami`"))

    def test_detects_ifs_injection(self):
        self.assertFalse(self.v.is_safe("IFS= read x"))

    def test_safe_commands(self):
        self.assertTrue(self.v.is_safe("dir"))
        self.assertTrue(self.v.is_safe("echo hello"))
        self.assertTrue(self.v.is_safe("type nul > file"))


class TestPermissionManager(unittest.TestCase):
    def test_default_mode_is_valid(self):
        self.assertIn("default", PERMISSION_MODES)
        self.assertIn("plan", PERMISSION_MODES)
        self.assertIn("auto", PERMISSION_MODES)

    def test_read_file_always_allowed_in_plan_mode(self):
        pm = PermissionManager(mode="plan")
        result = pm.check("read_file", {"path": "/etc/passwd"})
        self.assertEqual(result["behavior"], "allow")

    def test_write_denied_in_plan_mode(self):
        pm = PermissionManager(mode="plan")
        result = pm.check("write_file", {"path": "/tmp/test.txt"})
        self.assertEqual(result["behavior"], "deny")

    def test_read_allowed_in_auto_mode(self):
        pm = PermissionManager(mode="auto")
        result = pm.check("read_file", {"path": "/etc/passwd"})
        self.assertEqual(result["behavior"], "allow")

    def test_write_asks_in_auto_mode(self):
        pm = PermissionManager(mode="auto")
        result = pm.check("write_file", {"path": "/tmp/test.txt"})
        self.assertEqual(result["behavior"], "ask")

    def test_deny_rule_blocks(self):
        pm = PermissionManager(
            mode="default",
            rules=[{"tool": "bash", "content": "rm *", "behavior": "deny"}]
        )
        result = pm.check("bash", {"command": "rm file.txt"})
        self.assertEqual(result["behavior"], "deny")

    def test_allow_rule_permits(self):
        pm = PermissionManager(
            mode="default",
            rules=[{"tool": "bash", "content": "echo *", "behavior": "allow"}]
        )
        result = pm.check("bash", {"command": "echo hello"})
        self.assertEqual(result["behavior"], "allow")

    def test_dangerous_bash_blocked_by_validator(self):
        pm = PermissionManager(mode="default")
        result = pm.check("bash", {"command": "sudo su"})
        self.assertEqual(result["behavior"], "deny")

    def test_unknown_tool_asks(self):
        pm = PermissionManager(mode="default")
        result = pm.check("some_unknown_tool", {})
        self.assertEqual(result["behavior"], "ask")


if __name__ == "__main__":
    unittest.main()
