"""
tests/test_tasks.py — Tests for capabilities/tasks.py
"""
import unittest
import tempfile
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from capabilities.tasks import TaskManager


class TestTaskManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tm = TaskManager(Path(self.tmpdir))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_task(self):
        result = self.tm.create("Test task", "description here")
        data = json.loads(result)
        self.assertEqual(data["subject"], "Test task")
        self.assertEqual(data["status"], "pending")
        self.assertIn("id", data)

    def test_get_task(self):
        created = self.tm.create("Test task")
        task_id = json.loads(created)["id"]
        retrieved = json.loads(self.tm.get(task_id))
        self.assertEqual(retrieved["subject"], "Test task")

    def test_get_nonexistent(self):
        with self.assertRaises(ValueError):
            self.tm.get(9999)

    def test_update_status(self):
        created = self.tm.create("Test task")
        task_id = json.loads(created)["id"]
        result = self.tm.update(task_id, status="in_progress")
        self.assertEqual(json.loads(result)["status"], "in_progress")

    def test_update_invalid_status(self):
        created = self.tm.create("Test task")
        task_id = json.loads(created)["id"]
        with self.assertRaises(ValueError):
            self.tm.update(task_id, status="invalid_status")

    def test_update_owner(self):
        created = self.tm.create("Test task")
        task_id = json.loads(created)["id"]
        result = self.tm.update(task_id, owner="agent-1")
        self.assertEqual(json.loads(result)["owner"], "agent-1")

    def test_blockedby_dependency(self):
        t1 = json.loads(self.tm.create("Task 1"))
        t2 = json.loads(self.tm.create("Task 2"))
        self.tm.update(t2["id"], add_blocked_by=[t1["id"]])
        updated = json.loads(self.tm.get(t2["id"]))
        self.assertIn(t1["id"], updated["blockedBy"])

    def test_complete_clears_blockedby(self):
        t1 = json.loads(self.tm.create("Task 1"))
        t2 = json.loads(self.tm.create("Task 2"))
        self.tm.update(t2["id"], add_blocked_by=[t1["id"]])
        self.tm.update(t1["id"], status="completed")
        updated = json.loads(self.tm.get(t2["id"]))
        self.assertNotIn(t1["id"], updated["blockedBy"])

    def test_list_all_empty(self):
        result = self.tm.list_all()
        self.assertEqual(result, "No tasks.")

    def test_list_all_shows_tasks(self):
        self.tm.create("Task A")
        self.tm.create("Task B")
        result = self.tm.list_all()
        self.assertIn("Task A", result)
        self.assertIn("Task B", result)


if __name__ == "__main__":
    unittest.main()
