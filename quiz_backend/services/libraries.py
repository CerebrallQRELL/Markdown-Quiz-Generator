"""Prepare optional third-party libraries in a dedicated quiz image."""
import hashlib
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

from .sandbox import hidden_process_options


def package_names(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError('Enter package names separated by spaces, commas, or new lines.')
    packages = sorted(set(filter(None, re.split(r'[\s,]+', value))))
    if len(packages) > 20 or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:==[A-Za-z0-9][A-Za-z0-9_.+-]*)?', p) for p in packages):
        raise ValueError('Use up to 20 package names, optionally with ==version (for example numpy==2.3.0).')
    return packages


def install_libraries(value):
    packages = package_names(value)
    if not packages:
        return 'python:3.13-alpine', ''
    executable = shutil.which('docker')
    if not executable:
        raise RuntimeError('Start Docker Desktop before installing Python libraries.')
    base = 'python:3.13-slim'
    identity = hashlib.sha256((base + '\n' + '\n'.join(packages)).encode()).hexdigest()[:24]
    image = 'markdown-quiz-libraries:' + identity
    # Only wheel distributions; package build scripts never run on the host.
    dockerfile = (f'FROM {base}\n' +
                  'RUN python -m pip install --no-cache-dir --only-binary=:all: -- ' + ' '.join(packages) + '\n')
    try:
        with TemporaryDirectory(prefix='quiz-libraries-') as context:
            result = subprocess.run([executable, 'build', '--tag', image, '--file', '-', context],
                                    input=dockerfile, capture_output=True, text=True, timeout=300,
                                    **hidden_process_options())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Library installation failed or timed out. Check Docker and your connection, then retry.') from exc
    if result.returncode:
        raise RuntimeError('Could not install libraries. Check package names and Python 3.13 wheel availability. ' + result.stderr[-2000:])
    try:
        inspected = subprocess.run([executable, 'image', 'inspect', '--format', '{{.Id}}', image],
                                   capture_output=True, text=True, timeout=15, **hidden_process_options())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Could not verify the installed library image. Retry installation.') from exc
    image_id = inspected.stdout.strip()
    if inspected.returncode or not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        raise RuntimeError('Could not verify the installed library image. Retry installation.')
    return image_id, ' '.join(packages)
