from __future__ import annotations

import argparse
import asyncio
import json
import sys

from pathlib import Path
from . import __version__
from .service import Monitor, default_claude_logs, default_database, default_logs


def main():
    parser = argparse.ArgumentParser(description="Gauge: local Codex and Claude Code token, prompt-cache and estimated-cost monitor")
    parser.add_argument("--version", action="version", version=f"Gauge {__version__}")
    parser.add_argument("command", choices=["mcp", "scan", "config"])
    parser.add_argument("--logs", type=Path, default=default_logs(), help="Codex session log directory")
    parser.add_argument("--claude-logs", type=Path, default=default_claude_logs(), help="Claude Code transcript directory")
    parser.add_argument("--no-claude", action="store_true", help="Do not index Claude Code transcripts")
    parser.add_argument("--database", type=Path, default=default_database())
    args = parser.parse_args()
    if args.command == "config":
        print(json.dumps({"mcpServers": {"cache-monitor": {
            "command": sys.executable,
            "args": ["-m", "cache_monitor", "mcp", "--logs", str(args.logs.resolve()), "--database", str(args.database.resolve()),
                     *(["--no-claude"] if args.no_claude else ["--claude-logs", str(args.claude_logs.resolve())])],
            "cwd": str(Path(__file__).resolve().parents[1]),
        }}}, indent=2))
        return
    monitor = Monitor(args.logs.resolve(), args.database.resolve(),
                      None if args.no_claude else args.claude_logs.resolve())
    try:
        if args.command == "scan":
            monitor.collector.scan()
            print(json.dumps({"collector": monitor.collector.status(), "sessions": monitor.store.sessions()}, indent=2))
        else:
            monitor.start()
            from .mcp_server import run
            asyncio.run(run(monitor))
    except KeyboardInterrupt:
        pass
    finally:
        monitor.close()


if __name__ == "__main__":
    main()
