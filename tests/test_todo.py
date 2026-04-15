"""
tests/test_todo.py — Tests for capabilities/todo.py
"""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from capabilities.todo import TodoManager, PLAN_REMINDER_INTERVAL


class TestTodoManager(unittest.TestCase):
    def setUp(self):
        self.tm = TodoManager()

    def test_update_empty(self):
        result = self.tm.update([])
        self.assertEqual(result, "No session plan yet.")

    def test_update_single_item(self):
        result = self.tm.update([{"content": "Do something"}])
        self.assertIn("Do something", result)

    def test_update_multiple_items(self):
        self.tm.update([
            {"content": "Task 1", "status": "pending"},
            {"content": "Task 2", "status": "completed"},
        ])
        result = self.tm.render()
        self.assertIn("Task 1", result)
        self.assertIn("Task 2", result)

    def test_in_progress_marker(self):
        self.tm.update([{"content": "In progress task", "status": "in_progress", "activeForm": "working on it"}])
        result = self.tm.render()
        self.assertIn("[>]", result)
        self.assertIn("working on it", result)

    def test_completed_marker(self):
        self.tm.update([{"content": "Done task", "status": "completed"}])
        result = self.tm.render()
        self.assertIn("[x]", result)

    def test_only_one_in_progress_allowed(self):
        with self.assertRaises(ValueError):
            self.tm.update([
                {"content": "Task 1", "status": "in_progress"},
                {"content": "Task 2", "status": "in_progress"},
            ])

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            self.tm.update([{"content": "Bad status", "status": "badstatus"}])

    def test_max_items_limit(self):
        items = [{"content": f"Item {i}"} for i in range(15)]
        with self.assertRaises(ValueError):
            self.tm.update(items)

    def test_reminder_after_rounds(self):
        self.tm.update([{"content": "Task 1", "status": "pending"}])
        # Simulate rounds without update
        for _ in range(PLAN_REMINDER_INTERVAL):
            self.tm.note_round_without_update()
        reminder = self.tm.reminder()
        self.assertIsNotNone(reminder)
        self.assertIn("Refresh", reminder)

    def test_no_reminder_early(self):
        self.tm.update([{"content": "Task 1", "status": "pending"}])
        reminder = self.tm.reminder()
        self.assertIsNone(reminder)


if __name__ == "__main__":
    unittest.main()
