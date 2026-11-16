from __future__ import annotations

import argparse
import asyncio
import json
import sys

from pathlib import Path
from . import __version__
from .service import Monitor, default_database, default_logs


def main():
    parser = argparse.ArgumentParser(description="Gauge: local Codex token, prompt-cache and estimated-credit monitor")
    parser.add_argument("--version", action="version", version=f"Gauge {__version__}")
    parser.add_argument("command", choices=["mcp", "scan", "config"])
    parser.add_argument("--logs", type=Path, default=default_logs())
    parser.add_argument("--database", type=Path, default=default_database())
    args = parser.parse_args()
    if args.command == "config":
        print(json.dumps({"mcpServers": {"cache-monitor": {
            "command": sys.executable,
            "args": ["-m", "cache_monitor", "mcp", "--logs", str(args.logs.resolve()), "--database", str(args.database.resolve())],
            "cwd": str(Path(__file__).resolve().parents[1]),
        }}}, indent=2))
        return
    monitor = Monitor(args.logs.resolve(), args.database.resolve())
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
