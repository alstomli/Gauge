from __future__ import annotations

import os
import threading
from pathlib import Path

from .claude_collector import ClaudeCollector
from .collector import Collector
from .store import Store


class Sources:
    """Scan Codex logs and, when configured, Claude Code transcripts as one collector."""

    def __init__(self, collectors: list):
        self.collectors = collectors
        self.stop_event = threading.Event()

    def scan(self):
        for collector in self.collectors:
            collector.scan()

    def run(self):
        while not self.stop_event.is_set():
            self.scan()
            self.stop_event.wait(1)

    def status(self):
        statuses = [c.status() for c in self.collectors]
        available = [s for s in statuses if s["logs_available"]]
        scans = [s["last_scan_at"] for s in statuses]
        if not available:
            error = statuses[0]["error"] if len(statuses) == 1 else (
                "No Codex session log or Claude Code transcript directory is available." if all(scans) else None)
        else:
            # A missing directory for a host the user does not run is not an error.
            error = " ".join(s["error"] for s in available if s["error"]) or None
        return {"last_scan_at": min(scans) if all(scans) else None, "error": error,
                "logs_available": bool(available), "refresh_seconds": 1}


class Monitor:
    def __init__(self, logs: Path, database: Path, claude_logs: Path | None = None):
        self.store = Store(database)
        collectors = [Collector(logs, self.store)]
        if claude_logs is not None:
            collectors.append(ClaudeCollector(claude_logs, self.store))
        self.collector = collectors[0] if len(collectors) == 1 else Sources(collectors)
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.collector.run, name="usage-collector", daemon=True)
        self.thread.start()

    def close(self):
        self.collector.stop_event.set()
        if self.thread:
            self.thread.join()
        self.store.close()

    def dashboard(self, session_id: str | None = None, limit: int = 500, include_internal: bool = False) -> dict:
        detail = None
        # Selection is explicit and stable, including while a new session is loading.
        if session_id:
            try:
                detail = self.store.history(session_id, limit)
            except KeyError:
                pass
        # An explicit internal-session deep link is an intentional request to show it.
        if detail and detail["session"]["session_kind"] == "internal_review":
            include_internal = True
        sessions = self.store.sessions(include_internal=include_internal)
        return {"sessions": sessions, "detail": detail, "selected_session_id": session_id,
                "include_internal": include_internal, "collector": self.collector.status()}


def default_logs() -> Path:
    return codex_home() / "sessions"


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    return Path(override).expanduser() if override else Path.home() / ".codex"


def claude_home() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override).expanduser() if override else Path.home() / ".claude"


def default_claude_logs() -> Path:
    return claude_home() / "projects"


def default_database() -> Path:
    # Installed plugin/package directories can be replaced during upgrades or
    # be read-only. Keep data in the user's Codex home, outside the package.
    # Claude Code-only users (no Codex home) keep it in the Claude home instead.
    override = os.environ.get("GAUGE_DATABASE")
    if override:
        return Path(override).expanduser()
    if not codex_home().is_dir() and claude_home().is_dir():
        return claude_home() / "gauge" / "usage.sqlite3"
    return codex_home() / "gauge" / "usage.sqlite3"
