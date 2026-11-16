from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def aggregate(rows) -> dict:
    rows = list(rows)
    inputs = sum(r["input_tokens"] for r in rows)
    cached = sum(r["cached_input_tokens"] for r in rows)
    return {
        "input_tokens": inputs,
        "cached_input_tokens": cached,
        "uncached_input_tokens": inputs - cached,
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "cache_reuse": cached / inputs if inputs else None,
        "calls": len(rows),
    }


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, project TEXT, source TEXT, version TEXT,
                updated_at TEXT, expected TEXT, issues TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY, position INTEGER NOT NULL, signature TEXT NOT NULL,
                anchor TEXT NOT NULL, state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage (
                session_id TEXT NOT NULL, response_id TEXT NOT NULL, turn_id TEXT,
                timestamp TEXT NOT NULL, model TEXT, source TEXT NOT NULL,
                input_tokens INTEGER NOT NULL, cached_input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                PRIMARY KEY(session_id, response_id)
            );
            CREATE INDEX IF NOT EXISTS usage_session_time ON usage(session_id,timestamp);
            CREATE TABLE IF NOT EXISTS rollout_checks (
                path TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                history_base TEXT, issues TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS response_checks (
                path TEXT NOT NULL, session_id TEXT NOT NULL, response_id TEXT NOT NULL,
                position INTEGER NOT NULL, ordinal INTEGER NOT NULL, expected TEXT,
                PRIMARY KEY(path,response_id)
            );
            CREATE INDEX IF NOT EXISTS response_checks_session ON response_checks(session_id);
        """)
        if "expected_at" not in {r[1] for r in self.db.execute("PRAGMA table_info(sessions)")}:
            self.db.execute("ALTER TABLE sessions ADD COLUMN expected_at TEXT")
        if "session_kind" not in {r[1] for r in self.db.execute("PRAGMA table_info(sessions)")}:
            self.db.execute("ALTER TABLE sessions ADD COLUMN session_kind TEXT")
        self.db.commit()

    def close(self):
        with self.lock:
            self.db.close()

    def rows(self, session_id: str) -> list[dict]:
        # Response records supersede snapshots for the entire session.
        primary = self.db.execute(
            "SELECT 1 FROM usage WHERE session_id=? AND source='response' LIMIT 1", (session_id,)
        ).fetchone()
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM usage WHERE session_id=? AND source=? ORDER BY timestamp,response_id",
            (session_id, "response" if primary else "snapshot"),
        )]

    def quality(self, session: dict, rows: list[dict]) -> dict:
        issues = json.loads(session["issues"])
        primary = bool(rows and rows[0]["source"] == "response")
        reconciled = None
        rollouts = [dict(r) for r in self.db.execute("SELECT * FROM rollout_checks WHERE session_id=?", (session["id"],))]
        legacy_files = any(json.loads(r[0]).get("collector_version", 0) < 2 for r in self.db.execute(
            "SELECT state FROM files WHERE json_extract(state,'$.session_id')=?", (session["id"],)))
        # The former collector overwrote child ownership with inherited parent metadata.
        # Once all files have been replayed, actual exclusions come from per-file checks.
        if rollouts and not legacy_files:
            issues = [issue for issue in issues if issue != "A response record belongs to a different chat and was excluded."]
        for rollout in rollouts:
            issues.extend(json.loads(rollout["issues"]))
        notes = []
        if primary:
            reconciled, resumed = self.reconcile_rollouts(session["id"], rows, rollouts)
            if reconciled is False:
                issues.append("Recorded response totals do not match their log/checkpoint counters.")
            elif reconciled is None:
                notes.append("Counter verification is pending: some log/checkpoint records are unavailable or still being indexed.")
            if resumed:
                notes.append("Counters are checked per log and resume checkpoint. Whole-chat totals include every distinct recorded call, including completed attempts replaced by an edit or omitted from a resumed checkpoint.")
        if not primary:
            issues.append("Snapshot fallback: first cumulative record is a baseline; earlier calls are excluded.")
        return {
            "status": "degraded" if issues else "verified" if reconciled else "unreconciled",
            "source": "response" if primary else "snapshot" if rows else "unavailable",
            "reconciled": reconciled,
            "issues": list(dict.fromkeys(issues)),
            "notes": notes,
            "counter_scope": "log/checkpoint" if primary else None,
        }

    def reconcile_rollouts(self, session_id: str, rows: list[dict], rollouts: list[dict]) -> tuple[bool | None, bool]:
        """Verify recorded calls against each log's own counter lineage, not a global sum."""
        fields = ("input_tokens", "cached_input_tokens", "output_tokens")
        usage = {row["response_id"]: row for row in rows}
        files = {r["path"]: r["position"] for r in self.db.execute("SELECT path,position FROM files")}
        logs = {r["path"]: r for r in rollouts}
        checks = {path: [] for path in logs}
        for record in self.db.execute("SELECT * FROM response_checks WHERE session_id=? ORDER BY path,position", (session_id,)):
            if record["path"] in checks and record["response_id"] in usage:
                checks[record["path"]].append(dict(record))
        cache = {}

        def totals(ids):
            return {field: sum(usage[rid][field] for rid in ids) for field in fields}

        def verify(path, end=None, stack=()):
            key = (path, end)
            if path in stack:
                return set(), None
            if key in cache:
                return cache[key]
            records = [r for r in checks[path] if end is None or r["position"] <= end]
            ids, status, baseline_known = set(), True, True
            base = json.loads(logs[path]["history_base"]) if logs[path]["history_base"] else None
            if base and records:
                # Paginated history can reference a prior rollout segment ID,
                # rather than the stable chat ID, after editing/resuming again.
                # Accept only independently verified prefixes owned by this chat
                # whose token totals exactly prove the required baseline.
                offset = base.get("end_byte_offset")
                first = records[0]
                expected = json.loads(first["expected"]) if first["expected"] else None
                baseline = {field: expected[field] - usage[first["response_id"]][field] for field in fields} if expected else None
                candidates = []
                if isinstance(offset, int) and not isinstance(offset, bool) and offset >= 0:
                    for other in logs:
                        if other == path or other in stack or files.get(other, -1) < offset:
                            continue
                        inherited, verified = verify(other, offset, (*stack, path))
                        if verified is True and baseline == totals(inherited):
                            candidates.append(inherited)
                if candidates:
                    ids = set(candidates[0])
                    if any(candidate != ids for candidate in candidates[1:]):
                        status = None
                        baseline_known = False
                else:
                    status = None
                    baseline_known = False
            running = totals(ids)
            for record in records:
                rid = record["response_id"]
                if rid not in ids:
                    ids.add(rid)
                    for field in fields:
                        running[field] += usage[rid][field]
                expected = json.loads(record["expected"]) if record["expected"] else None
                if expected is None:
                    if status is True:
                        status = None
                elif baseline_known and running != expected:
                    status = False
            cache[key] = (ids, status)
            return ids, status

        covered, statuses = set(), []
        for path in logs:
            ids, status = verify(path)
            covered.update(ids)
            if checks[path]:
                statuses.append(status)
        resumed = any(r["history_base"] for r in rollouts)
        if any(status is False for status in statuses):
            return False, resumed
        if not statuses or any(status is None for status in statuses) or covered != set(usage):
            return None, resumed
        return True, resumed

    def sessions(self, include_internal: bool = False) -> list[dict]:
        with self.lock:
            result = []
            for record in self.db.execute("SELECT * FROM sessions ORDER BY updated_at DESC,id"):
                session = dict(record)
                if session["session_kind"] == "internal_review" and not include_internal:
                    continue
                rows = self.rows(session["id"])
                result.append({
                    "id": session["id"], "project": session["project"],
                    "source": session["source"], "version": session["version"],
                    "session_kind": session["session_kind"] or "unknown",
                    "last_record_at": rows[-1]["timestamp"] if rows else None,
                    "summary": aggregate(rows), "quality": self.quality(session, rows),
                    "model": rows[-1]["model"] if rows else None,
                })
            return result

    def history(self, session_id: str, limit: int = 500) -> dict:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 2000:
            raise ValueError("limit must be an integer between 1 and 2000")
        with self.lock:
            record = self.db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not record:
                raise KeyError("Unknown session")
            session = dict(record)
            rows = self.rows(session_id)
            visible = rows[-limit:]
            visible_ids = {r["response_id"] for r in visible}
            turns = {}
            models = {}
            for row in rows:
                # Missing turn IDs are explicit separate groups, never guessed prompts.
                key = row["turn_id"] or "unattributed:" + row["response_id"]
                turns.setdefault(key, []).append(row)
                models.setdefault(row["model"], []).append(row)
            return {
                "session": {"id": session_id, "project": session["project"], "source": session["source"],
                            "session_kind": session["session_kind"] or "unknown"},
                "summary": aggregate(rows), "visible_summary": aggregate(visible),
                "usage_by_model": [{"model": model, **aggregate(group)} for model, group in models.items()],
                "latest": rows[-1] if rows else None,
                "history": visible, "history_truncated": len(visible) < len(rows),
                "turns": [{"id": key, "attributed": not key.startswith("unattributed:"),
                           "timestamp": group[0]["timestamp"], "summary": aggregate(group),
                           "calls": group} for key, group in turns.items()
                          if any(r["response_id"] in visible_ids for r in group)],
                "quality": self.quality(session, rows),
                "last_record_at": rows[-1]["timestamp"] if rows else None,
                "read_at": now(),
            }
