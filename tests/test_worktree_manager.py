"""
tests/test_worktree_manager.py — Tests for multiagent/worktree_manager.py
"""
import unittest
import tempfile
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from multiagent.worktree_manager import WorktreeManager, EventBus


class TestEventBus(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.event_file = Path(self.tmpdir) / "events.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_emit_and_list_recent(self):
        bus = EventBus(self.event_file)
        bus.emit("test.event", key="value")
        result = bus.list_recent(10)
        parsed = eval(result)  # json decoded
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["event"], "test.event")

    def test_event_file_created(self):
        bus = EventBus(self.event_file)
        self.assertTrue(self.event_file.exists())


class TestWorktreeManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # 创建一个真实的 git 仓库用于测试
        self.repo_dir = Path(self.tmpdir) / "repo"
        self.repo_dir.mkdir()
        import subprocess
        subprocess.run(["git", "init"], cwd=self.repo_dir, capture_output=True)
        # 创建初始提交（需要至少一个 commit 才能 worktree add）
        (self.repo_dir / "README").write_text("test")
        subprocess.run(["git", "add", "."], cwd=self.repo_dir, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=test@test.com", "-c", "user.name=test",
             "commit", "-m", "initial"],
            cwd=self.repo_dir, capture_output=True
        )
        self.wtm = WorktreeManager(self.repo_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_git_available(self):
        self.assertTrue(self.wtm.git_available)

    def test_create_and_list(self):
        result = self.wtm.create("feature-test", base_ref="HEAD")
        self.assertIn("feature-test", result)
        listed = self.wtm.list_all()
        self.assertIn("feature-test", listed)

    def test_create_invalid_name(self):
        with self.assertRaises(ValueError):
            self.wtm.create("invalid/name!")

    def test_create_duplicate(self):
        self.wtm.create("dup-test", base_ref="HEAD")
        with self.assertRaises(ValueError):
            self.wtm.create("dup-test", base_ref="HEAD")

    def test_status(self):
        self.wtm.create("status-test", base_ref="HEAD")
        result = self.wtm.status("status-test")
        # should contain git status output
        self.assertIsInstance(result, str)

    def test_closeout_keep(self):
        self.wtm.create("closeout-test", base_ref="HEAD")
        result = self.wtm.keep("closeout-test")
        self.assertIn("kept", result)
        listed = self.wtm.list_all()
        self.assertIn("kept", listed)

    def test_closeout_remove(self):
        self.wtm.create("remove-test", base_ref="HEAD")
        result = self.wtm.remove("remove-test", reason="test done")
        self.assertIn("Removed", result)
        listed = self.wtm.list_all()
        self.assertIn("remove-test", listed)  # still in index, status=removed

    def test_worktree_not_in_git_repo(self):
        other_dir = Path(tempfile.mkdtemp())
        try:
            wtm = WorktreeManager(other_dir)
            self.assertFalse(wtm.git_available)
        finally:
            shutil.rmtree(other_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
