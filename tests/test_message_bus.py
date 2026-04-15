"""
tests/test_message_bus.py — Tests for multiagent/message_bus.py
"""
import unittest
import tempfile
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from multiagent.message_bus import MessageBus, VALID_MSG_TYPES


class TestMessageBus(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bus = MessageBus(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_send_and_read_inbox(self):
        self.bus.send("alice", "bob", "Hello Bob!", "message")
        messages = self.bus.read_inbox("bob")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "Hello Bob!")
        self.assertEqual(messages[0]["from"], "alice")

    def test_read_inbox_clears(self):
        self.bus.send("alice", "bob", "Hello")
        msgs1 = self.bus.read_inbox("bob")
        msgs2 = self.bus.read_inbox("bob")
        self.assertEqual(len(msgs2), 0)

    def test_broadcast(self):
        # alice sends one direct message, then a broadcast
        self.bus.send("alice", "bob", "Hello Bob")
        self.bus.send("alice", "carol", "Hello Carol")
        self.bus.broadcast("alice", "Broadcast content", ["bob", "carol"])
        bob_msgs = self.bus.read_inbox("bob")
        carol_msgs = self.bus.read_inbox("carol")
        # bob: 1 direct + 1 broadcast = 2; carol: 1 direct + 1 broadcast = 2
        self.assertEqual(len(bob_msgs), 2)
        self.assertEqual(carol_msgs[1]["content"], "Broadcast content")

    def test_invalid_msg_type(self):
        result = self.bus.send("alice", "bob", "text", "invalid_type")
        self.assertTrue(result.startswith("Error"))

    def test_valid_msg_types(self):
        for t in ["message", "broadcast", "shutdown_request", "shutdown_response",
                  "plan_approval", "plan_approval_response"]:
            self.assertIn(t, VALID_MSG_TYPES)


if __name__ == "__main__":
    unittest.main()
