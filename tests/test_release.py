import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from cache_monitor.service import default_database, default_logs
from scripts.build_release import create_release, release_files

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTest(unittest.TestCase):
    def test_user_data_is_outside_installed_package_and_overrides_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {'CODEX_HOME': temp}, clear=True):
                self.assertEqual(default_database(), Path(temp) / 'gauge' / 'usage.sqlite3')
                self.assertEqual(default_logs(), Path(temp) / 'sessions')
            custom = str(Path(temp) / 'custom.sqlite3')
            with patch.dict(os.environ, {'GAUGE_DATABASE': custom}, clear=True):
                self.assertEqual(default_database(), Path(custom))
        home = Path.home()
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'home', return_value=home):
            self.assertEqual(default_database(), home / '.codex' / 'gauge' / 'usage.sqlite3')

    def test_marketplace_and_portable_manifest_resolve_inside_release(self):
        marketplace = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text())
        entry, = marketplace['plugins']
        plugin_root = (ROOT / entry['source']['path']).resolve()
        self.assertEqual(plugin_root, ROOT)
        plugin = json.loads((plugin_root / 'plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(entry['name'], plugin['name'])
        server, = json.loads((plugin_root / 'mcp.json').read_text())['mcpServers'].values()
        self.assertEqual(server['type'], 'stdio')
        self.assertEqual(server['command'], 'uv')
        self.assertIn('${PLUGIN_ROOT}', server['args'])
        for field in ('logo', 'composerIcon'):
            asset = (plugin_root / plugin['extensions']['com.openai']['interface'][field]).resolve()
            self.assertTrue(asset.is_relative_to(plugin_root) and asset.is_file())
        onboarding = (plugin_root / plugin['extensions']['com.openai']['onboardingSkill']).resolve()
        self.assertTrue(onboarding.is_relative_to(plugin_root / 'skills') and onboarding.is_file())

    def test_claude_code_marketplace_and_manifest_resolve_inside_release(self):
        marketplace = json.loads((ROOT / '.claude-plugin/marketplace.json').read_text(encoding='utf-8'))
        entry, = marketplace['plugins']
        self.assertEqual((ROOT / entry['source']).resolve(), ROOT)
        plugin = json.loads((ROOT / '.claude-plugin/plugin.json').read_text(encoding='utf-8'))
        codex_plugin = json.loads((ROOT / 'plugin.json').read_text(encoding='utf-8'))
        self.assertEqual((entry['name'], entry['version']), (plugin['name'], plugin['version']))
        self.assertEqual((plugin['name'], plugin['version']), (codex_plugin['name'], codex_plugin['version']))
        server, = plugin['mcpServers'].values()
        self.assertEqual(server['command'], 'uv')
        self.assertIn('${CLAUDE_PLUGIN_ROOT}', server['args'])
        # Claude Code discovers bundled skills under skills/ at the plugin root.
        self.assertTrue((ROOT / 'skills/gauge/SKILL.md').is_file())

    def test_archive_excludes_private_data_and_verifies_each_file(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = create_release(ROOT, Path(temp))
            original_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
                self.assertTrue({'plugin.json', 'mcp.json', 'uv.lock', 'LICENSE',
                                 '.agents/plugins/marketplace.json', '.claude-plugin/plugin.json',
                                 '.claude-plugin/marketplace.json', 'cache_monitor/web/mcp-app.html',
                                 'docs/screenshots/gauge-dark.png', 'docs/screenshots/gauge-light.png',
                                 'scripts/screenshot_preview.mjs'} <= names)
                plugin = json.loads(bundle.read('plugin.json'))
                onboarding = plugin['extensions']['com.openai']['onboardingSkill'].removeprefix('./')
                self.assertIn(onboarding, names)
                for name in names:
                    self.assertFalse(Path(name).is_absolute())
                    self.assertFalse(set(Path(name).parts) & {'.monitor', '.codex', '.venv', 'node_modules', '__pycache__', '.git'})
                    self.assertNotIn('..', Path(name).parts)
                    self.assertFalse(name.endswith(('.sqlite3', '.jsonl', '.pyc')))
                manifest = json.loads(bundle.read('release-manifest.json'))
                self.assertEqual(set(manifest['files']), names - {'release-manifest.json'})
                for name, digest in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(bundle.read(name)).hexdigest(), digest)
            create_release(ROOT, Path(temp))
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), original_hash)

    def test_release_allowlist_ignores_unexpected_root_files(self):
        selected = {p.relative_to(ROOT).as_posix() for p in release_files(ROOT)}
        self.assertNotIn('AGENTS.md', selected)
        self.assertNotIn('.codex/config.toml', selected)
        self.assertNotIn('.monitor/usage.sqlite3', selected)
