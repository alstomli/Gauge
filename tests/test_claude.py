import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cache_monitor.claude_collector import ClaudeCollector, claude_usage
from cache_monitor.collector import Collector
from cache_monitor.service import Monitor, Sources, default_claude_logs, default_database
from cache_monitor.store import Store

SID = "11111111-2222-3333-4444-555555555555"


def usage(fresh=10, read=900, write=90, output=20, hour=None):
    value = {"input_tokens": fresh, "cache_read_input_tokens": read, "cache_creation_input_tokens": write, "output_tokens": output}
    if hour is not None:
        value["cache_creation"] = {"ephemeral_5m_input_tokens": write - hour, "ephemeral_1h_input_tokens": hour}
    return value


def base(second, sid=SID, **extra):
    return {"sessionId": sid, "cwd": "D:/Project", "version": "2.1.0", "isSidechain": False,
            "timestamp": f"2026-11-16T12:00:{second:02d}.000Z", **extra}


def prompt(prompt_id, second=0, **extra):
    return {**base(second, **extra), "type": "user", "promptId": prompt_id, "message": {"role": "user", "content": "secret prompt text"}}


def tool_result(prompt_id, second=0):
    return {**base(second), "type": "user", "promptId": prompt_id,
            "message": {"role": "user", "content": [{"type": "tool_result", "content": "secret output"}]}}


def assistant(message_id, second=1, model="claude-opus-5-5", block="text", **kwargs):
    extra = {k: kwargs.pop(k) for k in ("isSidechain", "agentId", "sid") if k in kwargs}
    sid = extra.pop("sid", SID)
    return {**base(second, sid=sid, **extra), "type": "assistant", "requestId": "req-" + message_id,
            "message": {"id": message_id, "model": model, "role": "assistant",
                        "content": [{"type": block, "text": "secret answer"}], "usage": usage(**kwargs)}}


def append(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        for row in records:
            handle.write(json.dumps(row).encode() + b"\n")


class ClaudeCollectorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "projects"
        self.log = self.root / "D--Project" / f"{SID}.jsonl"
        self.database = self.base / "usage.sqlite3"
        self.store = Store(self.database)
        self.collector = ClaudeCollector(self.root, self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_usage_mapping_keeps_cache_reuse_meaning(self):
        mapped = claude_usage(usage(hour=60))
        self.assertEqual(mapped, {"input_tokens": 1000, "cached_input_tokens": 900, "output_tokens": 20,
                                  "cache_write_5m_tokens": 30, "cache_write_1h_tokens": 60})
        # Without a TTL breakdown, writes are attributed to the default 5-minute TTL.
        self.assertEqual(claude_usage(usage())["cache_write_5m_tokens"], 90)
        self.assertIsNone(claude_usage({"input_tokens": -1, "output_tokens": 1}))
        self.assertIsNone(claude_usage({"output_tokens": 1}))
        self.assertIsNone(claude_usage(None))

    def test_split_records_count_once_and_turns_follow_prompts(self):
        append(self.log, [prompt("p1"), assistant("m1", block="thinking"), assistant("m1", block="tool_use"),
                          tool_result("p1", 2), assistant("m2", 3, read=1000, write=0),
                          prompt("p2", 4), assistant("m3", 5, model="claude-sonnet-5-5", read=0, write=500)])
        self.collector.scan(); self.collector.scan()
        history = self.store.history(SID)
        self.assertEqual(history["summary"]["calls"], 3)
        self.assertEqual(history["summary"]["input_tokens"], 1000 + 1010 + 510)
        self.assertEqual(history["summary"]["cached_input_tokens"], 1900)
        self.assertEqual(history["summary"]["cache_write_5m_tokens"], 590)
        self.assertEqual([t["id"] for t in history["turns"]], ["p1", "p2"])
        self.assertEqual(history["turns"][0]["summary"]["calls"], 2)
        self.assertEqual(history["latest"]["model"], "claude-sonnet-5-5")
        self.assertEqual(history["session"]["provider"], "claude")
        self.assertEqual(history["session"]["project"], "D:/Project")
        self.assertEqual(history["quality"]["status"], "unreconciled")
        self.assertEqual({m["model"] for m in history["usage_by_model"]}, {"claude-opus-5-5", "claude-sonnet-5-5"})
        stored = b"".join(line for line in self.database.read_bytes().splitlines())
        self.assertNotIn(b"secret", stored)

    def test_partial_lines_streaming_growth_and_synthetic_records(self):
        append(self.log, [prompt("p1"), assistant("m1", output=5)])
        tail = json.dumps(assistant("m1", output=40)).encode()
        with self.log.open("ab") as handle:
            handle.write(tail[:30])
        self.collector.scan()
        self.assertEqual(self.store.history(SID)["summary"]["output_tokens"], 5)
        with self.log.open("ab") as handle:
            handle.write(tail[30:] + b"\n")
        append(self.log, [assistant("m-local", model="<synthetic>", fresh=0, read=0, write=0, output=0)])
        self.collector.scan()
        summary = self.store.history(SID)["summary"]
        self.assertEqual((summary["calls"], summary["output_tokens"]), (1, 40))

    def test_sidechains_are_separate_subagent_sessions_and_invalid_usage_is_flagged(self):
        append(self.log, [prompt("p1"), assistant("m1"),
                          assistant("m2", isSidechain=True, agentId="agent-a"),
                          {**assistant("m3"), "message": {"id": "m3", "model": "claude-opus-5-5", "usage": {"output_tokens": "x"}}}])
        self.collector.scan()
        sessions = {s["id"]: s for s in self.store.sessions()}
        self.assertEqual(sessions[SID]["summary"]["calls"], 1)
        self.assertEqual(sessions[f"{SID}:agent-a"]["session_kind"], "subagent")
        self.assertEqual(sessions[SID]["quality"]["status"], "degraded")

    def test_replaced_transcript_does_not_double_count(self):
        append(self.log, [prompt("p1"), assistant("m1")])
        self.collector.scan()
        self.log.unlink()
        append(self.log, [prompt("p1"), assistant("m1"), assistant("m2", 2)])
        self.collector.scan()
        self.assertEqual(self.store.history(SID)["summary"]["calls"], 2)

    def test_monitor_combines_codex_and_claude_sources(self):
        append(self.log, [prompt("p1"), assistant("m1")])
        missing_codex = self.base / "codex-sessions"
        monitor = Monitor(missing_codex, self.base / "combined.sqlite3", self.root)
        try:
            self.assertIsInstance(monitor.collector, Sources)
            monitor.collector.scan()
            status = monitor.collector.status()
            # A host the user does not run is not an error.
            self.assertIsNone(status["error"])
            self.assertTrue(status["logs_available"])
            self.assertEqual(monitor.dashboard(SID)["detail"]["session"]["provider"], "claude")
        finally:
            monitor.close()
        monitor = Monitor(missing_codex, self.base / "none.sqlite3", self.base / "missing-claude")
        try:
            monitor.collector.scan()
            self.assertIn("No Codex", monitor.collector.status()["error"])
        finally:
            monitor.close()
        codex_only = Monitor(missing_codex, self.base / "codex.sqlite3")
        try:
            self.assertIsInstance(codex_only.collector, Collector)
        finally:
            codex_only.close()

    def test_default_locations(self):
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.base / "claude"), "CODEX_HOME": str(self.base / "codex")}, clear=True):
            self.assertEqual(default_claude_logs(), self.base / "claude" / "projects")
            (self.base / "claude").mkdir()
            self.assertEqual(default_database(), self.base / "claude" / "gauge" / "usage.sqlite3")
            (self.base / "codex").mkdir()
            self.assertEqual(default_database(), self.base / "codex" / "gauge" / "usage.sqlite3")


if __name__ == "__main__":
    unittest.main()
