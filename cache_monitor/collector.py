from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

from .store import Store, now

COUNTERS = ("input_tokens", "cached_input_tokens", "output_tokens")
COLLECTOR_VERSION = 2


def session_kind(payload: dict) -> str:
    source = payload.get("source")
    subagent = source.get("subagent") if isinstance(source, dict) else None
    if payload.get("thread_source") == "guardian_review" or (
        isinstance(subagent, dict) and subagent.get("other") == "guardian"
    ):
        return "internal_review"
    return "subagent" if subagent is not None else "chat"


def usage_counts(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    result = {key: value.get(key) for key in COUNTERS}
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in result.values()):
        return None
    if result["cached_input_tokens"] > result["input_tokens"]:
        return None
    return result


class Collector:
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
                self.last_error = (f"{unavailable} log files could not be read." if unavailable else None) if self.root.is_dir() else "Session log directory is unavailable."
                self.last_scan_at = now()
            except (OSError, sqlite3.Error) as exc:
                self.last_error = f"Collector could not complete a scan ({type(exc).__name__})."

    def run(self):
        while not self.stop_event.is_set():
            self.scan()
            self.stop_event.wait(1)

    def issue(self, state: dict, message: str):
        issues = state.setdefault("issues", [])
        if message not in issues:
            issues.append(message)

    def ingest(self, path: Path):
        with self.store.lock, self.store.db:
            db = self.store.db
            # Acquire the write reservation before reading cursors; concurrent MCP
            # processes must not upgrade an obsolete WAL read snapshot to a writer.
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("SELECT * FROM files WHERE path=?", (str(path),)).fetchone()
            with path.open("rb") as handle:
                stat = path.stat()
                signature = f"{stat.st_dev}:{stat.st_ino}"
                position = cursor["position"] if cursor else 0
                state = json.loads(cursor["state"]) if cursor else {}
                handle.seek(max(0, position - 64))
                anchor = hashlib.sha256(handle.read(min(64, position))).hexdigest()
                if cursor and (signature != cursor["signature"] or stat.st_size < position or anchor != cursor["anchor"]):
                    state = {"issues": ["A log was truncated or replaced; retained records may represent partial history."]}
                    position = 0
                if cursor and (position == 0 or state.get("collector_version") != COLLECTOR_VERSION
                               or state.get("checked_position") != position):
                    # Replay old cursors to restore the real file owner and counter provenance.
                    position, state = 0, {"issues": state.get("issues", [])}
                    db.execute("DELETE FROM response_checks WHERE path=?", (str(path),))
                    db.execute("DELETE FROM rollout_checks WHERE path=?", (str(path),))
                state["collector_version"] = COLLECTOR_VERSION
                if cursor and state.get("session_id"):
                    session = db.execute("SELECT session_kind FROM sessions WHERE id=?", (state["session_id"],)).fetchone()
                    if session and session[0] is None:
                        # Backfill classification from metadata without replaying usage/counters.
                        handle.seek(0)
                        try:
                            metadata = json.loads(handle.readline())
                            if isinstance(metadata, dict) and metadata.get("type") == "session_meta":
                                self.process(metadata, state)
                        except (ValueError, TypeError, AttributeError):
                            self.issue(state, "Session metadata could not be classified.")
                handle.seek(position)
                for _ in range(20000):
                    start = handle.tell()
                    line = handle.readline()
                    if not line or not line.endswith(b"\n"):
                        handle.seek(start)
                        break
                    ordinal = state.get("ordinal", 0)
                    state["ordinal"] = ordinal + 1
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            # Forked logs can contain inherited context before their own events.
                            if ordinal == 0 or ordinal >= state.get("history_start", 0):
                                self.process(event, state, str(path), handle.tell(), ordinal)
                    except (ValueError, TypeError, AttributeError):
                        self.issue(state, "One or more log records could not be parsed.")
                position = handle.tell()
                handle.seek(max(0, position - 64))
                anchor = hashlib.sha256(handle.read(min(64, position))).hexdigest()
                state["checked_position"] = position
                db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)",
                           (str(path), position, signature, anchor, json.dumps(state)))
                if state.get("session_id"):
                    db.execute("INSERT OR REPLACE INTO rollout_checks VALUES(?,?,?,?)",
                               (str(path), state["session_id"], json.dumps(state["history_base"]) if state.get("history_base") else None,
                                json.dumps(state.get("issues", []))))

    def process(self, event: dict, state: dict, path: str = "", position: int = 0, ordinal: int = 0):
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return
        db = self.store.db
        kind, timestamp = event.get("type"), event.get("timestamp") or now()
        if kind == "session_meta":
            sid = payload.get("id") or payload.get("session_id")
            if not isinstance(sid, str) or not sid:
                return
            if state.get("session_id") and state["session_id"] != sid:
                # The first metadata entry owns the log; subsequent parent entries are context.
                return
            state["session_id"] = sid
            state["parent_ids"] = [p for p in (payload.get("forked_from_id"), payload.get("parent_thread_id")) if isinstance(p, str)]
            boundary = payload.get("subagent_history_start_ordinal")
            if isinstance(boundary, int) and not isinstance(boundary, bool) and boundary >= 0:
                state["history_start"] = boundary
            base = payload.get("history_base")
            if isinstance(base, dict):
                state["history_base"] = {k: base.get(k) for k in ("thread_id", "end_byte_offset", "end_ordinal_exclusive")}
            source = payload.get("source")
            source = source if isinstance(source, str) else "subagent" if isinstance(source, dict) else "unknown"
            db.execute("INSERT INTO sessions(id,project,source,version,updated_at,session_kind) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET project=excluded.project,source=excluded.source,version=excluded.version,session_kind=excluded.session_kind",
                       (sid, payload.get("cwd"), source, payload.get("cli_version"), timestamp, session_kind(payload)))
            return
        if kind == "turn_context":
            state["model"] = payload.get("model") if isinstance(payload.get("model"), str) else None
            state["turn_id"] = payload.get("turn_id") if isinstance(payload.get("turn_id"), str) else None
            return
        if kind == "event_msg" and payload.get("type") == "task_started":
            state["turn_id"] = payload.get("turn_id")
        sid = state.get("session_id")
        if not sid:
            return
        if kind == "token_usage_record":
            response = payload.get("response_id")
            counts = usage_counts(payload.get("usage"))
            if not isinstance(response, str) or not counts:
                self.issue(state, "A response record has missing or invalid token counts or response ID.")
                return
            if payload.get("thread_id", sid) != sid:
                if payload.get("thread_id") not in state.get("parent_ids", []):
                    self.issue(state, "A response record belongs to a different chat and was excluded.")
                return
            self.insert(sid, response, payload.get("turn_id"), timestamp, state.get("model"), "response", counts)
            expected = usage_counts(payload.get("thread_token_usage"))
            db.execute("INSERT OR IGNORE INTO response_checks VALUES(?,?,?,?,?,?)",
                       (path, sid, response, position, ordinal, json.dumps(expected) if expected else None))
            if expected:
                db.execute("UPDATE sessions SET expected=?,expected_at=? WHERE id=? AND (expected_at IS NULL OR expected_at<=?)", (json.dumps(expected), timestamp, sid, timestamp))
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            total = usage_counts(info.get("total_token_usage"))
            if not total:
                return
            previous = state.get("cumulative")
            state["cumulative"] = total
            if previous:
                delta = {k: total[k] - previous[k] for k in COUNTERS}
                if any(v < 0 for v in delta.values()):
                    self.issue(state, "Cumulative token counters reset; snapshot history is partial.")
                elif delta["input_tokens"] or delta["output_tokens"]:
                    if usage_counts(delta):
                        identity = hashlib.sha256(json.dumps([timestamp, total], sort_keys=True).encode()).hexdigest()
                        self.insert(sid, "snapshot:" + identity, state.get("turn_id"), timestamp, state.get("model"), "snapshot", delta)
                    else:
                        self.issue(state, "A cumulative token delta is inconsistent and was excluded.")

    def insert(self, sid, response, turn, timestamp, model, source, counts):
        db = self.store.db
        db.execute("INSERT OR IGNORE INTO usage(session_id,response_id,turn_id,timestamp,model,source,"
                   "input_tokens,cached_input_tokens,output_tokens) VALUES(?,?,?,?,?,?,?,?,?)",
                   (sid, response, turn, timestamp, model, source, *[counts[k] for k in COUNTERS]))
        db.execute("UPDATE sessions SET updated_at=MAX(updated_at,?) WHERE id=?", (timestamp, sid))
