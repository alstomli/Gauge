"""Index Claude Code transcripts (``~/.claude/projects/**/*.jsonl``).

Claude Code writes one JSON record per line. Each assistant record carries the
Anthropic Messages API ``usage`` object of the model call that produced it. One
call can be split across several records (one per content block) that share
``message.id``, so calls are deduplicated by that ID.

Anthropic reports input in three disjoint parts: ``input_tokens`` (uncached),
``cache_read_input_tokens`` and ``cache_creation_input_tokens``. Gauge stores
``input_tokens`` as their sum and ``cached_input_tokens`` as the cache reads, so
cache reuse keeps the same meaning as for Codex: cached input / all input.
Cache writes are kept separately because they are billed above the input rate.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

from .store import Store, now

COLLECTOR_VERSION = 1
PROVIDER = "claude"


def _count(value) -> int | None:
    if value is None:
        return 0
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def claude_usage(usage) -> dict | None:
    """Map an Anthropic usage object onto Gauge counters, or None when invalid."""
    if not isinstance(usage, dict):
        return None
    fresh, read, write, output = (_count(usage.get(k)) for k in (
        "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"))
    if None in (fresh, read, write, output) or "input_tokens" not in usage or "output_tokens" not in usage:
        return None
    write_5m, write_1h = write, 0
    split = usage.get("cache_creation")
    if isinstance(split, dict):
        five, hour = _count(split.get("ephemeral_5m_input_tokens")), _count(split.get("ephemeral_1h_input_tokens"))
        if five is not None and hour is not None and five + hour == write:
            write_5m, write_1h = five, hour
    return {"input_tokens": fresh + read + write, "cached_input_tokens": read, "output_tokens": output,
            "cache_write_5m_tokens": write_5m, "cache_write_1h_tokens": write_1h}


class ClaudeCollector:
    def __init__(self, root: Path, store: Store):
        self.root, self.store = root, store
        self.lock = threading.RLock()
        self.last_scan_at = None
        self.last_error = None
        self.stop_event = threading.Event()

    def status(self):
        return {"last_scan_at": self.last_scan_at, "error": self.last_error,
                "logs_available": self.root.is_dir(), "refresh_seconds": 1}

    def scan(self):
        with self.lock:
            try:
                unavailable = 0
                for path in sorted(self.root.rglob("*.jsonl")):
                    try:
                        self.ingest(path)
                    except OSError:
                        unavailable += 1
                self.last_error = (f"{unavailable} Claude Code transcripts could not be read." if unavailable else None) \
                    if self.root.is_dir() else "Claude Code transcript directory is unavailable."
                self.last_scan_at = now()
            except (OSError, sqlite3.Error) as exc:
                self.last_error = f"Claude Code collector could not complete a scan ({type(exc).__name__})."

    def run(self):
        while not self.stop_event.is_set():
            self.scan()
            self.stop_event.wait(1)

    @staticmethod
    def issue(state: dict, message: str):
        issues = state.setdefault("issues", [])
        if message not in issues:
            issues.append(message)

    def ingest(self, path: Path):
        with self.store.lock, self.store.db:
            db = self.store.db
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("SELECT * FROM files WHERE path=?", (str(path),)).fetchone()
            with path.open("rb") as handle:
                stat = path.stat()
                signature = f"{stat.st_dev}:{stat.st_ino}"
                position = cursor["position"] if cursor else 0
                state = json.loads(cursor["state"]) if cursor else {}
                if cursor and position == stat.st_size and signature == cursor["signature"]:
                    return
                handle.seek(max(0, position - 64))
                anchor = hashlib.sha256(handle.read(min(64, position))).hexdigest()
                if cursor and (signature != cursor["signature"] or stat.st_size < position or anchor != cursor["anchor"]
                               or state.get("claude_collector_version") != COLLECTOR_VERSION):
                    # Usage rows are keyed by message ID, so a replay never double counts.
                    position, state = 0, {"issues": ["A transcript was truncated or replaced; retained records may represent partial history."]
                                          if state.get("claude_collector_version") == COLLECTOR_VERSION else []}
                state["claude_collector_version"] = COLLECTOR_VERSION
                handle.seek(position)
                for _ in range(20000):
                    start = handle.tell()
                    line = handle.readline()
                    if not line or not line.endswith(b"\n"):
                        handle.seek(start)
                        break
                    try:
                        record = json.loads(line)
                        if isinstance(record, dict):
                            self.process(record, state, path)
                    except (ValueError, TypeError, AttributeError):
                        self.issue(state, "One or more transcript records could not be parsed.")
                position = handle.tell()
                handle.seek(max(0, position - 64))
                anchor = hashlib.sha256(handle.read(min(64, position))).hexdigest()
                db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)",
                           (str(path), position, signature, anchor, json.dumps(state)))
                if state.get("session_id"):
                    db.execute("UPDATE sessions SET issues=? WHERE id=?", (json.dumps(state.get("issues", [])), state["session_id"]))

    def session_for(self, record: dict, path: Path) -> tuple[str, str] | None:
        sid = record.get("sessionId")
        if not isinstance(sid, str) or not sid:
            return None
        if record.get("isSidechain") is True:
            # Subagent calls are a separate agent chat, as for Codex subagents.
            agent = record.get("agentId") if isinstance(record.get("agentId"), str) else path.stem
            return f"{sid}:{agent}", "subagent"
        return sid, "chat"

    def process(self, record: dict, state: dict, path: Path):
        kind = record.get("type")
        if kind not in ("user", "assistant"):
            return
        owner = self.session_for(record, path)
        if not owner:
            return
        sid, session_kind = owner
        db = self.store.db
        timestamp = record.get("timestamp") if isinstance(record.get("timestamp"), str) else now()
        project = record.get("cwd") if isinstance(record.get("cwd"), str) else None
        version = record.get("version") if isinstance(record.get("version"), str) else None
        if session_kind == "chat" and not state.get("session_id"):
            state["session_id"] = sid
        db.execute("INSERT INTO sessions(id,project,source,version,updated_at,session_kind,provider) VALUES(?,?,?,?,?,?,?) "
                   "ON CONFLICT(id) DO UPDATE SET project=COALESCE(excluded.project,project),version=COALESCE(excluded.version,version),"
                   "session_kind=excluded.session_kind,provider=excluded.provider",
                   (sid, project, "claude-code", version, timestamp, session_kind, PROVIDER))
        if kind == "user":
            prompt = record.get("promptId")
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            content = message.get("content")
            is_prompt = isinstance(content, str) or (isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") != "tool_result" for b in content))
            if isinstance(prompt, str) and prompt:
                state.setdefault("turns", {})[sid] = prompt
            elif is_prompt and not record.get("isMeta"):
                # Older transcripts lack promptId: a typed prompt starts a new turn.
                state.setdefault("turns", {})[sid] = "prompt:" + str(record.get("uuid") or timestamp)
            return
        message = record.get("message")
        if not isinstance(message, dict):
            return
        model = message.get("model")
        if model == "<synthetic>":
            return  # Locally generated placeholder, not a model call.
        response = message.get("id") or record.get("requestId")
        counts = claude_usage(message.get("usage"))
        if not isinstance(response, str) or not response or not counts:
            self.issue(state, "A model-call record has missing or invalid token counts or message ID.")
            return
        turn = state.get("turns", {}).get(sid)
        db.execute(
            "INSERT INTO usage(session_id,response_id,turn_id,timestamp,model,source,input_tokens,cached_input_tokens,"
            "output_tokens,cache_write_5m_tokens,cache_write_1h_tokens) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(session_id,response_id) DO UPDATE SET "
            # Split records repeat the call's usage; streaming can only grow output.
            "output_tokens=MAX(output_tokens,excluded.output_tokens)",
            (sid, response, turn, timestamp, model if isinstance(model, str) else None, "response",
             counts["input_tokens"], counts["cached_input_tokens"], counts["output_tokens"],
             counts["cache_write_5m_tokens"], counts["cache_write_1h_tokens"]))
        db.execute("UPDATE sessions SET updated_at=MAX(updated_at,?) WHERE id=?", (timestamp, sid))
