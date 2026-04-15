"""
tests/test_base.py — Tests for infra/base.py
"""
import unittest
import tempfile
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from infra.base import (
    safe_path, is_dangerous, run_bash, read_file,
    write_file, edit_file, normalize_messages, extract_text,
)


class TestSafePath(unittest.TestCase):
    def test_resolves_relative_to_workdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = safe_path("foo/bar.txt", Path(tmpdir))
            self.assertEqual(result.parts[-3:-1], (Path(tmpdir).name, "foo"))

    def test_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError) as ctx:
                safe_path("../../../etc/passwd", Path(tmpdir))
            self.assertIn("escapes workspace", str(ctx.exception))


class TestIsDangerous(unittest.TestCase):
    def test_dangerous_patterns(self):
        for cmd in ["rm -rf /", "sudo su", "shutdown -h now", "reboot"]:
            self.assertTrue(is_dangerous(cmd), f"Should flag: {cmd}")

    def test_safe_patterns(self):
        for cmd in ["ls", "dir", "echo hello", "python script.py"]:
            self.assertFalse(is_dangerous(cmd), f"Should allow: {cmd}")


class TestRunBash(unittest.TestCase):
    def test_simple_echo(self):
        result = run_bash("echo hello world")
        self.assertIn("hello world", result)

    def test_dir_command(self):
        result = run_bash("cd /", timeout=5)
        self.assertNotIn("Error", result)

    def test_blocked_dangerous(self):
        result = run_bash("rm -rf /")
        self.assertIn("Dangerous", result)


class TestReadWriteFile(unittest.TestCase):
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            write_file("test.txt", "line1\nline2\nline3", workdir=td)
            content = read_file("test.txt", workdir=td)
            self.assertEqual(content, "line1\nline2\nline3")

    def test_read_nonexistent(self):
        result = read_file("does_not_exist_12345.txt")
        self.assertTrue(result.startswith("Error"))

    def test_write_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            path = td / "a" / "b" / "c" / "test.txt"
            result = write_file(str(path), "nested content", workdir=td)
            self.assertTrue(result.startswith("Wrote"))
            self.assertTrue(Path(path).exists())


class TestEditFile(unittest.TestCase):
    def test_edit_exact_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            fname = td / "test_edit.txt"
            fname.write_text("hello world")
            result = edit_file(str(fname), "world", "openclaw", workdir=td)
            self.assertTrue(result.startswith("Edited"))
            content = fname.read_text()
            self.assertEqual(content, "hello openclaw")

    def test_edit_text_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            fname = td / "test_edit2.txt"
            fname.write_text("hello world")
            result = edit_file(str(fname), "not present", "replacement", workdir=td)
            self.assertTrue(result.startswith("Error"))


class TestNormalizeMessages(unittest.TestCase):
    def test_strips_internal_fields(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hi", "_extra": 123}]}
        ]
        normalized = normalize_messages(messages)
        self.assertNotIn("_extra", str(normalized))

    def test_merges_consecutive_same_role(self):
        # Only plain string content is merged; block-based content is never merged
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "user", "content": "there"},
        ]
        normalized = normalize_messages(messages)
        # 两轮纯字符串 user 应该合并
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["content"], "hi\nthere")

    def test_inserts_placeholder_for_orphaned_tool_use(self):
        messages = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tool1", "name": "bash", "input": {}}
            ]}
        ]
        normalized = normalize_messages(messages)
        # 应该有追加的 tool_result
        self.assertGreater(len(normalized), 1)


class TestExtractText(unittest.TestCase):
    def test_extracts_text_blocks(self):
        class FakeBlock:
            def __init__(self, text):
                self.text = text
        blocks = [FakeBlock("hello"), FakeBlock("world")]
        result = extract_text(blocks)
        self.assertEqual(result, "hello\nworld")

    def test_empty_content(self):
        result = extract_text([])
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
