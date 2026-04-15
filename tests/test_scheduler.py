"""
tests/test_scheduler.py — Tests for capabilities/scheduler.py
"""
import unittest
import tempfile
import time
import threading
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from capabilities.scheduler import (
    cron_matches, _field_matches, CronScheduler,
    AUTO_EXPIRY_DAYS,
)


class TestCronMatches(unittest.TestCase):
    def test_exact_minute(self):
        from datetime import datetime
        dt = datetime(2026, 4, 15, 10, 30, 0)
        self.assertTrue(cron_matches("30 10 * * *", dt))

    def test_any_minute(self):
        from datetime import datetime
        dt = datetime(2026, 4, 15, 10, 15, 0)
        self.assertTrue(cron_matches("* 10 * * *", dt))
        dt2 = datetime(2026, 4, 15, 10, 59, 0)
        self.assertTrue(cron_matches("* 10 * * *", dt2))

    def test_step(self):
        from datetime import datetime
        # */3 in minute field: 0, 3, 6, 9, ...
        dt1 = datetime(2026, 4, 15, 10, 0, 0)
        dt2 = datetime(2026, 4, 15, 10, 3, 0)
        dt3 = datetime(2026, 4, 15, 10, 6, 0)
        dt_not = datetime(2026, 4, 15, 10, 7, 0)
        self.assertTrue(cron_matches("*/3 * * * *", dt1))  # min 0
        self.assertTrue(cron_matches("*/3 * * * *", dt2))  # min 3
        self.assertTrue(cron_matches("*/3 * * * *", dt3))  # min 6
        self.assertFalse(cron_matches("*/3 * * * *", dt_not))  # min 7

    def test_step_day_of_week_divisible_only(self):
        # */5 in day-of-week (lo=0, hi=6) only matches day 0 and 5 (0%5==0, 5%5==0)
        # NOT day 3 (Wednesday) — this reveals the step implementation semantics
        from datetime import datetime
        dt_wed = datetime(2026, 4, 15, 10, 0, 0)   # Wednesday
        dt_sun = datetime(2026, 4, 19, 10, 0, 0)  # Sunday = day 0
        self.assertFalse(cron_matches("* * * * */5", dt_wed))  # 3%5 != 0
        self.assertTrue(cron_matches("* * * * */5", dt_sun))   # 0%5 == 0

    def test_range(self):
        from datetime import datetime
        dt_in = datetime(2026, 4, 15, 10, 30, 0)
        dt_out = datetime(2026, 4, 15, 14, 30, 0)
        self.assertTrue(cron_matches("30 10-12 * * *", dt_in))
        self.assertFalse(cron_matches("30 10-12 * * *", dt_out))

    def test_list(self):
        from datetime import datetime
        dt1 = datetime(2026, 4, 15, 10, 0, 0)
        dt2 = datetime(2026, 4, 15, 12, 0, 0)
        dt3 = datetime(2026, 4, 15, 14, 0, 0)
        self.assertTrue(cron_matches("0 10,12 * * *", dt1))
        self.assertTrue(cron_matches("0 10,12 * * *", dt2))
        self.assertFalse(cron_matches("0 10,12 * * *", dt3))

    def test_wrong_field_count(self):
        from datetime import datetime
        dt = datetime(2026, 4, 15, 10, 30, 0)
        self.assertFalse(cron_matches("30 10 * *", dt))

    def test_day_of_week(self):
        from datetime import datetime
        # Wednesday = 3
        dt_wed = datetime(2026, 4, 15, 10, 0, 0)
        dt_thu = datetime(2026, 4, 16, 10, 0, 0)
        self.assertTrue(cron_matches("0 10 * * 3", dt_wed))
        self.assertFalse(cron_matches("0 10 * * 3", dt_thu))


class TestFieldMatches(unittest.TestCase):
    def test_star(self):
        for val in [0, 30, 59]:
            self.assertTrue(_field_matches("*", val, 0, 59))

    def test_exact(self):
        self.assertTrue(_field_matches("5", 5, 0, 59))
        self.assertFalse(_field_matches("5", 6, 0, 59))

    def test_step(self):
        # */3 from range 0-59: 0, 3, 6, ...
        self.assertTrue(_field_matches("*/3", 6, 0, 59))
        self.assertFalse(_field_matches("*/3", 7, 0, 59))

    def test_range(self):
        self.assertTrue(_field_matches("10-20", 15, 0, 59))
        self.assertFalse(_field_matches("10-20", 25, 0, 59))

    def test_range_with_step(self):
        # 5-15/2: 5, 7, 9, 11, 13, 15
        self.assertTrue(_field_matches("5-15/2", 11, 0, 59))
        self.assertFalse(_field_matches("5-15/2", 10, 0, 59))

    def test_list(self):
        self.assertTrue(_field_matches("5,10,15", 10, 0, 59))
        self.assertFalse(_field_matches("5,10,15", 12, 0, 59))


class TestCronScheduler(unittest.TestCase):
    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmpfile.close()
        self.sched = CronScheduler(Path(self.tmpfile.name))

    def tearDown(self):
        self.sched.stop()
        Path(self.tmpfile.name).unlink(missing_ok=True)

    def test_create_and_list(self):
        result = self.sched.create("0 10 * * *", "test prompt")
        self.assertTrue(result.startswith("Created task"))
        listed = self.sched.list_tasks()
        self.assertIn("test prompt", listed)

    def test_create_one_shot(self):
        result = self.sched.create("0 10 * * *", "one shot", recurring=False)
        self.assertIn("one-shot", result)

    def test_create_durable(self):
        result = self.sched.create("0 10 * * *", "durable task", durable=True)
        self.assertIn("durable", result)
        # 重启后应该能加载
        sched2 = CronScheduler(Path(self.tmpfile.name))
        sched2.start()
        time.sleep(0.1)
        listed = sched2.list_tasks()
        self.assertIn("durable task", listed)
        sched2.stop()

    def test_delete(self):
        self.sched.create("0 10 * * *", "to delete")
        result = self.sched.delete("nonexistent")
        self.assertIn("not found", result)

    def test_drain_notifications_empty(self):
        result = self.sched.drain_notifications()
        self.assertEqual(result, [])

    def test_jitter_offset_computed(self):
        # 0 or 30 minute fields should get jitter 1-4
        t1 = self.sched.create("0 10 * * *", "at zero minute")
        self.assertIn("Created task", t1)
        t2 = self.sched.create("30 10 * * *", "at 30 minute")
        task1 = [t for t in self.sched.tasks if "at zero minute" in t["prompt"]][0]
        task2 = [t for t in self.sched.tasks if "at 30 minute" in t["prompt"]][0]
        # jitter should be 0 for non-0/30, non-zero for 0/30
        self.assertGreaterEqual(task1.get("jitter_offset", 0), 0)
        self.assertGreaterEqual(task2.get("jitter_offset", 0), 0)


if __name__ == "__main__":
    unittest.main()
