"""Build a Windows x64 portable release from an audited public-only snapshot."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_release import check_release, private_values
from scripts.export_github import export_source
from scripts.release_files import public_files


def digest_file(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def third_party_files():
    files = {}
    packages = {}
    notices = ['Bundled third-party components retain their respective licenses.',
               'PyQt6 is distributed under GPL-3.0-only; see its included license.',
               'AEGIS application source: https://github.com/iLrs9935/AEGIS',
               'Exact dependency versions and upstream source distributions follow.\n']
    for distribution in sorted(importlib.metadata.distributions(), key=lambda item: item.metadata['Name'].lower()):
        name = distribution.metadata['Name']
        version = distribution.version
        packages[name] = version
        notices.append(f'{name} {version}: https://pypi.org/project/{name}/{version}/')
        for item in distribution.files or []:
            relative = Path(str(item))
            if relative.is_absolute() or '..' in relative.parts:
                continue
            if not relative.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
                continue
            source = Path(distribution.locate_file(item))
            if source.is_file():
                destination = Path('THIRD_PARTY_LICENSES') / name / relative
                files[destination.as_posix()] = source.read_bytes()
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        files['THIRD_PARTY_LICENSES/Python/LICENSE.txt'] = python_license.read_bytes()
    files['THIRD_PARTY_NOTICES.txt'] = ('\n'.join(notices) + '\n').encode('utf-8')
    return files, packages


def build(version, output):
    if os.name != 'nt' or struct.calcsize('P') != 8 or platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise SystemExit('This builder requires Windows x64 Python')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise SystemExit('Version must be MAJOR.MINOR.PATCH')
    if output.exists():
        raise SystemExit('Output already exists; choose a fresh build directory')
    if output.is_relative_to(ROOT) and output.relative_to(ROOT).parts[0] != 'release':
        raise SystemExit('Build inside the ignored release directory or outside the checkout')
    installed = {item.metadata['Name'].lower().replace('_', '-') for item in importlib.metadata.distributions()}
    if installed & {'llama-cpp-python', 'dxcam'}:
        raise SystemExit('Use a clean requirements-build.txt environment for the standard portable edition')
    if check_release(ROOT):
        raise SystemExit('Source privacy audit failed')
    inputs = public_files(ROOT)
    secrets = private_values(ROOT)
    source = output / 'source'
    source.mkdir(parents=True)
    source_hashes = {}
    for path in inputs:
        relative = path.relative_to(ROOT)
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        source_hashes[relative.as_posix()] = digest_file(path)
    revision = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    commit = revision.stdout.strip() if revision.returncode == 0 else None
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith('AEGIS_') and key not in {'PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'}}
    environment['AEGIS_BUILD_VERSION'] = version
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                    '--distpath', str(output / 'dist'), '--workpath', str(output / 'build'),
                    str(source / 'AEGIS Command Terminal.spec')], cwd=source, env=environment, check=True)
    bundle = output / 'dist' / 'AEGIS Command Terminal'
    if not (bundle / 'AEGIS Command Terminal.exe').is_file():
        raise RuntimeError('Expected executable is missing')
    expected_examples = {path.name for path in (source / 'examples/workflows').glob('*.json')}
    actual_examples = {path.name for path in (bundle / '_internal/workflows').glob('*.json')}
    if len(expected_examples) != 5 or actual_examples != expected_examples:
        raise RuntimeError('Bundled examples differ from the public examples')
    files = {}
    forbidden = {'config.local.json', 'aegis_settings.json', 'ui_config.json', '.env', 'daily.json'}
    for path in sorted(bundle.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(bundle)
        if path.name.lower() in forbidden or path.suffix.lower() in {'.db', '.sqlite', '.log', '.bak'}:
            raise RuntimeError('Private/runtime file in bundle: ' + relative.as_posix())
        if any(part.lower() in {'logs', 'outbox', 'backups', 'models'} for part in relative.parts):
            raise RuntimeError('Private/runtime directory in bundle: ' + relative.as_posix())
        data = path.read_bytes()
        if any(value.encode('utf-8') in data or value.encode('utf-16-le') in data for value in secrets):
            raise RuntimeError('Known private value found in bundle: ' + relative.as_posix())
        files[relative.as_posix()] = path
    extra, packages = third_party_files()
    extra['LICENSE.txt'] = (source / 'LICENSE').read_bytes()
    extra['START_HERE.md'] = (source / 'docs/PORTABLE.md').read_bytes()
    extra['config.local.example.json'] = (source / 'config.local.example.json').read_bytes()
    for path in (source / 'examples/workflows').glob('*.json'):
        extra['workflows/' + path.name] = path.read_bytes()
    extra['BUILD_INFO.json'] = (json.dumps({
        'application': 'AEGIS', 'version': version, 'platform': 'windows-x64',
        'python': platform.python_version(), 'source_commit': commit,
        'source_files_sha256': source_hashes, 'build_environment_packages': packages,
        'optional_backends_bundled': {'llama_cpp': False, 'dxcam': False},
    }, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if set(files) & set(extra):
        raise RuntimeError('Duplicate portable package paths')
    manifest = {name: digest_file(path) for name, path in files.items()}
    manifest.update({name: hashlib.sha256(data).hexdigest() for name, data in extra.items()})
    extra['FILE_MANIFEST.sha256'] = ''.join(f'{digest}  {name}\n' for name, digest in sorted(manifest.items())).encode('utf-8')
    destination = output / f'AEGIS-v{version}-windows-x64.zip'
    folder = destination.stem
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in files.items():
            archive.write(path, f'{folder}/{name}')
        for name, data in extra.items():
            archive.writestr(f'{folder}/{name}', data)
    source_archive = output / f'AEGIS-v{version}-source.zip'
    export_source(source, source_archive)
    sums = output / 'SHA256SUMS.txt'
    sums.write_text(''.join(f'{digest_file(path)}  {path.name}\n' for path in (destination, source_archive)), encoding='utf-8')
    print(f'Portable release: {destination}', flush=True)
    print(f'Bundled files: {len(manifest) + 1}; public examples: 5; local configuration excluded', flush=True)
    print(sums.read_text(), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='3.0.0')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.version, args.output.resolve())
