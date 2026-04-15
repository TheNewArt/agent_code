"""
tests/test_memory.py — Tests for capabilities/memory.py
"""
import unittest
import tempfile
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from capabilities.memory import MemoryManager


class TestMemoryManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mm = MemoryManager(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        self.mm.save_memory("test_mem", "A test memory", "project", "content here")
        self.mm.memories.clear()
        self.mm.load_all()
        self.assertIn("test_mem", self.mm.memories)
        self.assertEqual(self.mm.memories["test_mem"]["type"], "project")

    def test_save_invalid_type(self):
        result = self.mm.save_memory("bad", "desc", "invalid_type", "content")
        self.assertTrue(result.startswith("Error"))

    def test_load_memory_prompt_empty(self):
        result = self.mm.load_memory_prompt()
        self.assertEqual(result, "")

    def test_load_memory_prompt_with_data(self):
        self.mm.save_memory("proj1", "Project 1", "project", "Some content")
        result = self.mm.load_memory_prompt()
        self.assertIn("proj1", result)
        self.assertIn("Some content", result)

    def test_duplicate_name_safe(self):
        self.mm.save_memory("dup", "First", "project", "Content 1")
        result = self.mm.save_memory("dup", "Second", "project", "Content 2")
        # 应该覆盖
        self.assertTrue(result.startswith("Saved"))

    def test_rebuild_index(self):
        self.mm.save_memory("mem1", "Mem 1", "user", "c1")
        self.mm.save_memory("mem2", "Mem 2", "feedback", "c2")
        idx_path = Path(self.tmpdir) / "MEMORY.md"
        self.assertTrue(idx_path.exists())
        content = idx_path.read_text()
        self.assertIn("mem1", content)
        self.assertIn("mem2", content)


if __name__ == "__main__":
    unittest.main()
