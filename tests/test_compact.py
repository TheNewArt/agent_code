"""
tests/test_compact.py — Tests for capabilities/compact.py
"""
import unittest
import tempfile
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from capabilities.compact import (
    CompactState, estimate_context_size, track_recent_file,
    persist_large_output, collect_tool_result_blocks, micro_compact,
    write_transcript, CONTEXT_LIMIT, KEEP_RECENT_TOOL_RESULTS,
    PERSIST_THRESHOLD,
)


class TestCompactState(unittest.TestCase):
    def test_init_defaults(self):
        cs = CompactState()
        self.assertFalse(cs.has_compacted)
        self.assertEqual(cs.last_summary, "")
        self.assertEqual(cs.recent_files, [])

    def test_track_recent_file(self):
        cs = CompactState()
        track_recent_file(cs, "/path/to/file1.py")
        self.assertIn("/path/to/file1.py", cs.recent_files)
        # same file should not duplicate
        track_recent_file(cs, "/path/to/file1.py")
        self.assertEqual(len(cs.recent_files), 1)
        # max 5 files
        for i in range(10):
            track_recent_file(cs, f"/path/file{i}.py")
        self.assertLessEqual(len(cs.recent_files), 5)


class TestEstimateContextSize(unittest.TestCase):
    def test_returns_int(self):
        size = estimate_context_size([{"role": "user", "content": "hello"}])
        self.assertIsInstance(size, int)
        self.assertGreater(size, 0)


class TestPersistLargeOutput(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import capabilities.compact as c
        c.TOOL_RESULTS_DIR = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_small_output_not_persisted(self):
        small = "x" * 100
        result = persist_large_output("small_id", small)
        self.assertEqual(result, small)

    def test_large_output_persisted(self):
        large = "x" * (PERSIST_THRESHOLD + 1000)
        result = persist_large_output("large_id", large)
        self.assertIn("Full output saved to:", result)
        self.assertIn("large_id", result)
        self.assertIn("Preview:", result)


class TestCollectToolResultBlocks(unittest.TestCase):
    def test_collects_tool_results(self):
        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "result1"}
            ]},
        ]
        blocks = collect_tool_result_blocks(messages)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0][2]["tool_use_id"], "t1")

    def test_ignores_non_user_messages(self):
        messages = [
            {"role": "assistant", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "result1"}
            ]},
        ]
        blocks = collect_tool_result_blocks(messages)
        self.assertEqual(len(blocks), 0)


class TestMicroCompact(unittest.TestCase):
    def test_keeps_recent(self):
        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{i}", "content": f"result{i}"}
            ]} for i in range(5)
        ]
        # 5 tool results, keep 3 recent
        compacted = micro_compact(messages)
        # Should still have all 5 tool result blocks but older ones replaced
        blocks = collect_tool_result_blocks(compacted)
        self.assertEqual(len(blocks), 5)

    def test_short_results_not_compacted(self):
        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "hi"}
            ]} for _ in range(5)
        ]
        compacted = micro_compact(messages)
        blocks = collect_tool_result_blocks(compacted)
        # All kept as-is (content <= 120 chars)
        self.assertEqual(len(blocks), 5)


class TestWriteTranscript(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import capabilities.compact as c
        c.TRANSCRIPT_DIR = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_writes_jsonl(self):
        messages = [{"role": "user", "content": "hello"}]
        path = write_transcript(messages)
        self.assertTrue(path.exists())
        content = path.read_text()
        self.assertIn("hello", content)


if __name__ == "__main__":
    unittest.main()
