"""Exercise an extracted plugin's real launch command using synthetic logs only."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def record(kind, payload, second):
    return {'type': kind, 'timestamp': f'2026-11-16T12:00:{second:02d}Z', 'payload': payload}


def append(path, records):
    with path.open('ab') as handle:
        for item in records:
            handle.write(json.dumps(item).encode() + b'\n')


def call(rid, inputs, cached, output, total, second, sid='release-chat'):
    return record('token_usage_record', {
        'thread_id': sid, 'response_id': rid, 'turn_id': 'release-turn',
        'usage': {'input_tokens': inputs, 'cached_input_tokens': cached, 'output_tokens': output},
        'thread_token_usage': dict(zip(('input_tokens', 'cached_input_tokens', 'output_tokens'), total)),
    }, second)


async def smoke(archive: Path):
    uv = shutil.which('uv') or str(Path(sys.executable).with_name('uv.exe' if os.name == 'nt' else 'uv'))
    if not Path(uv).is_file():
        raise RuntimeError('Install uv before testing the release')
    with tempfile.TemporaryDirectory(prefix='gauge-release-') as temporary:
        base = Path(temporary)
        plugin = base / 'plugin'
        plugin.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read('release-manifest.json'))
            assert set(bundle.namelist()) == set(manifest['files']) | {'release-manifest.json'}
            for name, digest in manifest['files'].items():
                assert (plugin / name).resolve().is_relative_to(plugin.resolve())
                assert hashlib.sha256(bundle.read(name)).hexdigest() == digest
            bundle.extractall(plugin)
        env = {**os.environ, 'CODEX_HOME': str(base / 'codex')}
        env.pop('GAUGE_DATABASE', None)
        # Pin this check to the selected CI interpreter, not an unrelated system Python.
        subprocess.run([uv, 'sync', '--locked', '--no-dev', '--project', str(plugin),
                        '--python', sys.executable], env=env, check=True, capture_output=True, text=True)
        logs = base / 'codex' / 'sessions'
        logs.mkdir(parents=True)
        log = logs / 'synthetic.jsonl'
        append(log, [record('session_meta', {'id': 'release-chat', 'cwd': 'synthetic-project', 'source': 'test'}, 0),
                     record('turn_context', {'model': 'gpt-6.1-sol', 'turn_id': 'release-turn'}, 0),
                     call('first-call', 1000, 900, 20, (1000, 900, 20), 1)])
        server, = json.loads((plugin / 'mcp.json').read_text())['mcpServers'].values()
        args = [arg.replace('${PLUGIN_ROOT}', str(plugin)) for arg in server['args']]
        cwd = server['cwd'].replace('${PLUGIN_ROOT}', str(plugin))
        params = StdioServerParameters(command=uv, args=args, cwd=cwd, env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert 'show_cache_dashboard' in {tool.name for tool in tools.tools}
                resource = await client.read_resource('ui://cache-monitor/dashboard.html')
                assert '<title>Gauge</title>' in resource.contents[0].text
                for _ in range(40):
                    shown = await client.call_tool('show_cache_dashboard', {'session_id': 'release-chat'})
                    detail = shown.meta['dashboard']['detail']
                    if detail:
                        break
                    await asyncio.sleep(.1)
                assert detail['summary']['input_tokens'] == 1000
                assert detail['quality']['status'] == 'verified'
                assert [s['id'] for s in shown.meta['dashboard']['sessions']] == ['release-chat']
                missing = await client.call_tool('show_cache_dashboard', {'session_id': 'missing-chat'})
                assert missing.meta['dashboard']['detail'] is None
                append(log, [call('next-call', 100, 50, 5, (1100, 950, 25), 2)])
                for _ in range(40):
                    updated = await client.call_tool('refresh_cache_dashboard', {'session_id': 'release-chat'})
                    detail = updated.structuredContent['detail']
                    if detail['summary']['calls'] == 2:
                        break
                    await asyncio.sleep(.1)
                assert detail['summary']['input_tokens'] == 1100
                assert detail['quality']['status'] == 'verified'
        assert (base / 'codex' / 'gauge' / 'usage.sqlite3').is_file()
        assert not list(plugin.glob('**/*.sqlite3'))
    print('Extracted plugin passed: locked install, manifest launch, MCP UI resource, verified usage and live refresh.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    parser.add_argument('archive', type=Path, nargs='?', default=root / 'dist' / f'gauge-{version}-plugin.zip')
    args = parser.parse_args()
    try:
        asyncio.run(smoke(args.archive.resolve()))
    except subprocess.CalledProcessError as exc:
        print(exc.stderr, file=sys.stderr)
        raise
