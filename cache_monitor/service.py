from __future__ import annotations

import os
import threading
from pathlib import Path

from .collector import Collector
from .store import Store


class Monitor:
    def __init__(self, logs: Path, database: Path):
        self.store = Store(database)
        self.collector = Collector(logs, self.store)
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


def default_database() -> Path:
    # Installed plugin/package directories can be replaced during upgrades or
    # be read-only. Keep data in the user's Codex home, outside the package.
    override = os.environ.get("GAUGE_DATABASE")
    if override:
        return Path(override).expanduser()
    return codex_home() / "gauge" / "usage.sqlite3"
