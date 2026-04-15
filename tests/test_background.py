"""
tests/test_background.py — Tests for capabilities/background.py
"""
import unittest
import tempfile
import time
import shutil
from pathlib import Path
import os
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from capabilities.background import BackgroundManager


class TestBackgroundManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bm = BackgroundManager(Path(self.tmpdir))
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)  # 确保 cwd 在 temp dir 下

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_run_command(self):
        result = self.bm.run("echo hello from bg")
        self.assertIn("Background task", result)
        self.assertIn("started", result)
        task_id = result.split()[2]
        # 等待后台完成
        time.sleep(1)
        status = self.bm.check(task_id)
        self.assertIn("completed", status)

    def test_run_multiple_commands(self):
        self.bm.run("echo first")
        self.bm.run("echo second")
        self.assertEqual(len(self.bm.tasks), 2)

    def test_check_nonexistent(self):
        result = self.bm.check("nonexistent_id")
        self.assertIn("Unknown task", result)

    def test_drain_notifications(self):
        self.bm.run("echo notification_test")
        time.sleep(1)
        notifs = self.bm.drain_notifications()
        self.assertIsInstance(notifs, list)
        # 清空后再次 drain 应该为空
        notifs2 = self.bm.drain_notifications()
        self.assertEqual(len(notifs2), 0)

    def test_check_all(self):
        self.bm.run("echo task_a")
        result = self.bm.check()
        self.assertIn("task_a", result)


if __name__ == "__main__":
    unittest.main()
