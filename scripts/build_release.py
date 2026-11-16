"""Build a reproducible plugin ZIP from an explicit public-file allowlist."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    '.gitignore', 'LICENSE', 'README.md', 'CHANGELOG.md', 'PRIVACY.md',
    'SECURITY.md', 'CONTRIBUTING.md', 'THIRD_PARTY_NOTICES.md', 'MANIFEST.in',
    'pyproject.toml', 'requirements.lock', 'uv.lock', 'plugin.json', 'mcp.json',
    'package.json', 'package-lock.json', '.agents/plugins/marketplace.json',
)
DIRECTORIES = {
    'cache_monitor': {'*.py'}, 'cache_monitor/web': {'*.html'},
    'ui': {'*.js', '*.css', '*.html'}, 'assets': {'*.svg'},
    'tests': {'*.py', '*.mjs'}, 'scripts': {'*.py', '*.mjs', '*.ps1', '*.sh'},
    'docs': {'*.md'}, '.github/workflows': {'*.yml'},
}


def release_files(root: Path) -> list[Path]:
    root = root.resolve()
    selected = {root / name for name in ROOT_FILES}
    for directory, patterns in DIRECTORIES.items():
        for pattern in patterns:
            selected.update((root / directory).glob(pattern))
    for path in selected:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f'Release input escapes the project: {path.name}')
        if not path.is_file():
            raise ValueError(f'Missing release input: {path.relative_to(root)}')
    return sorted(selected, key=lambda path: path.relative_to(root).as_posix())


def create_release(root: Path = ROOT, output: Path | None = None) -> Path:
    root = root.resolve()
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    plugin = json.loads((root / 'plugin.json').read_text(encoding='utf-8'))
    package = json.loads((root / 'package.json').read_text(encoding='utf-8'))
    version = project['version']
    module = ast.parse((root / 'cache_monitor/__init__.py').read_text(encoding='utf-8'))
    runtime_version = next(ast.literal_eval(node.value) for node in module.body
                           if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == '__version__' for target in node.targets))
    if any(value != version for value in (plugin['version'], package['version'], runtime_version)):
        raise ValueError('Python metadata, runtime, UI and plugin versions must match')
    files = release_files(root)
    contents = {path.relative_to(root).as_posix(): path.read_bytes() for path in files}
    manifest = {'name': plugin['name'], 'version': version,
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    contents['release-manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    output = (output or root / 'dist').resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f'gauge-{version}-plugin.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
            bundle.writestr(info, data)
    artifacts = sorted(path for path in output.iterdir()
                       if path.is_file() and version in path.name
                       and (path.suffix in {'.zip', '.whl'} or path.name.endswith('.tar.gz')))
    checksums = ''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in artifacts)
    (output / 'SHA256SUMS').write_text(checksums, encoding='utf-8')
    print(f'Built {archive.name}: {len(files)} public files, {archive.stat().st_size:,} bytes')
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    create_release(output=args.output)
