"""Create installable GitHub downloads, excluding user data and credentials."""
import json
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'obsidian_plugin'


def package():
    manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8'))
    version, plugin_id = manifest['version'], manifest['id']
    if plugin_id != 'markdown-quiz-generator':
        raise ValueError('Unexpected plugin ID')
    install = ROOT / 'plugin' / plugin_id
    install.mkdir(parents=True, exist_ok=True)
    for name in ('main.js', 'manifest.json', 'styles.css'):
        shutil.copy2(SOURCE / name, install / name)
    python_files = sorted((ROOT / 'quiz_backend').rglob('*.py'))
    bundled = [ROOT / 'backend.py', *python_files]
    # Remove files shipped by the old flat layout, while preserving runtime data.
    package_root = install / 'backend' / 'quiz_backend'
    expected = {path.relative_to(ROOT / 'quiz_backend') for path in python_files}
    if package_root.exists():
        for previous in package_root.rglob('*.py'):
            if previous.relative_to(package_root) not in expected:
                previous.unlink()
    for path in bundled:
        target = install / 'backend' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    with ZipFile(output / f'{plugin_id}-{version}.zip', 'w', ZIP_DEFLATED) as archive:
        for name in ('main.js', 'manifest.json', 'styles.css'):
            archive.write(install / name, f'{plugin_id}/{name}')
        for path in bundled:
            archive.write(path, f'{plugin_id}/backend/' + path.relative_to(ROOT).as_posix())
    backend_files = [*python_files,
                     ROOT / 'backend.py', ROOT / 'run_backend.py', ROOT / 'requirements.txt', ROOT / 'Dockerfile',
                     ROOT / '.dockerignore', ROOT / 'main.py', ROOT / 'docs' / 'OBSIDIAN_SETUP.md', ROOT / 'LICENSE',
                     ROOT / 'vault' / 'example.md']
    with ZipFile(output / f'markdown-quiz-backend-{version}.zip', 'w', ZIP_DEFLATED) as archive:
        for path in backend_files:
            archive.write(path, 'markdown-quiz-backend/' + path.relative_to(ROOT).as_posix())
    backend_files += sorted(p for p in (ROOT / 'deployment').iterdir() if p.is_file() and p.name != '.env')
    source_files = [*backend_files, ROOT / 'docs' / 'ARCHITECTURE.md', ROOT / 'docs' / 'REFACTOR_NOTES.md',
                    ROOT / 'docs' / 'PROJECT_MAP.json', ROOT / 'README.md', ROOT / '.gitignore',
                    ROOT / 'run_multiple_choice.py', ROOT / 'run_code_quiz.py', ROOT / 'scripts/reset_json.py',
                    *sorted((ROOT / 'tests').glob('*.py')), *sorted((ROOT / 'scripts').glob('*.py')),
                    *sorted((ROOT / '.github' / 'workflows').glob('*.yml'))]
    source_files += [p for p in SOURCE.iterdir() if p.is_file() and p.suffix in ('.json', '.yaml', '.mjs', '.css', '.md')]
    source_files += [SOURCE / '.gitignore', *sorted((SOURCE / 'src').rglob('*.ts')),
                     *sorted((SOURCE / 'tests').glob('*.ts')), *sorted((SOURCE / 'tests').glob('*.mjs'))]
    with ZipFile(output / f'markdown-quiz-source-{version}.zip', 'w', ZIP_DEFLATED) as archive:
        for path in sorted(set(source_files)):
            archive.write(path, path.relative_to(ROOT).as_posix())
    deployment_files = sorted(p for p in (ROOT / 'deployment').iterdir() if p.is_file() and p.name != '.env')
    with ZipFile(output / f'markdown-quiz-local-{version}.zip', 'w', ZIP_DEFLATED) as archive:
        for name in ('main.js', 'manifest.json', 'styles.css'):
            archive.write(install / name, f'{plugin_id}/{name}')
        for path in bundled:
            archive.write(path, f'{plugin_id}/backend/' + path.relative_to(ROOT).as_posix())
        for name in ('install-local.ps1', 'DEPLOYMENT.md'):
            archive.write(ROOT / 'deployment' / name, 'deployment/' + name)
    with ZipFile(output / f'markdown-quiz-server-{version}.zip', 'w', ZIP_DEFLATED) as archive:
        for path in [*bundled, *deployment_files, ROOT / '.dockerignore', ROOT / 'LICENSE']:
            archive.write(path, path.relative_to(ROOT).as_posix())
    print(f'Installable plugin: {install}')
    for path in sorted(output.glob(f'*-{version}.zip')):
        print(path)


if __name__ == '__main__':
    package()
