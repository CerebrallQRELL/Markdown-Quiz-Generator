"""Execute only in restricted Docker containers; cap output and enforce cleanup."""
from dataclasses import dataclass
import logging
import json
import os
import shutil
import subprocess
import threading
import time
import uuid


def hidden_process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


@dataclass
class RunResult:
    stdout: str = ''
    stderr: str = ''
    exit_code: int = -1
    timed_out: bool = False
    output_limited: bool = False

    @property
    def successful(self):
        return self.exit_code == 0 and not self.timed_out and not self.output_limited


def check_sandbox_available(settings):
    """Fail before model generation when Docker or the sandbox image is missing."""
    executable = shutil.which('docker')
    if not executable:
        raise RuntimeError('Docker is not installed or is not on PATH.')
    try:
        engine = subprocess.run([executable, 'info', '--format', '{{.OSType}}'],
                                capture_output=True, text=True, timeout=15, **hidden_process_options())
        if engine.returncode or engine.stdout.strip() != 'linux':
            raise RuntimeError('Code quizzes need Docker Desktop running with Linux containers. '
                               'Docker is currently unavailable; open Docker Desktop and resolve its startup error.')
        image = subprocess.run([executable, 'image', 'inspect', settings.sandbox_image],
                               capture_output=True, text=True, timeout=15, **hidden_process_options())
        if image.returncode:
            raise RuntimeError(f'Sandbox image is missing. Run: docker pull {settings.sandbox_image}')
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Docker did not respond. Check Docker Desktop before starting a code quiz.') from exc


def run_in_sandbox(code, settings, stdin_text=""):
    if not isinstance(stdin_text, str) or len(stdin_text.encode("utf-8")) > 65536:
        raise ValueError("Program input must be text up to 64 KB.")
    if len(code.encode('utf-8')) > 100_000:
        raise ValueError('Code exceeds 100 KB.')
    if stdin_text:
        # Python reads its script from the transport pipe. Give the executed program
        # a separate text/binary stdin so input() never consumes the script itself.
        payload = json.dumps([code, stdin_text], ensure_ascii=True)
        code = ('import io, sys, json\n'
                + '_source, _input = json.loads(' + repr(payload) + ')\n'
                + 'sys.stdin = io.TextIOWrapper(io.BytesIO(_input.encode("utf-8")), encoding="utf-8")\n'
                + 'exec(compile(_source, "<quiz>", "exec"), {"__name__": "__main__"})\n')
    executable = shutil.which('docker')
    if not executable:
        raise RuntimeError('Docker not installed or not on PATH. Install Docker with Linux containers.')
    name = 'markdown-quiz-' + uuid.uuid4().hex
    process = None
    threads = []
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()
    limit = 65536

    def command(args):
        try:
            return subprocess.run([executable, *args], capture_output=True, text=True, timeout=15, **hidden_process_options())
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError('Docker command failed or timed out. Check the Docker engine.') from exc

    def drain(pipe, buffer):
        try:
            while chunk := pipe.read(4096):
                remaining = max(0, limit - len(buffer))
                buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()
        except (OSError, ValueError):
            pass

    def feed():
        try:
            process.stdin.write(code.encode('utf-8'))
            process.stdin.close()
        except (OSError, ValueError):
            pass

    try:
        created = command(['create', '-i', '--pull', 'never', '--name', name,
            '--network', 'none', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--pids-limit', '32',
            '--memory', settings.sandbox_memory, '--memory-swap', settings.sandbox_memory,
            '--cpus', str(settings.sandbox_cpus), '--user', '10001:10001',
            '--env', 'OPENBLAS_NUM_THREADS=1', '--env', 'OMP_NUM_THREADS=1', '--env', 'MKL_NUM_THREADS=1',
            '--log-driver', 'none', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=8m',
            '--entrypoint', 'python', settings.sandbox_image, '-I', '-B', '-u', '-'])
        if created.returncode:
            raise RuntimeError('Cannot create sandbox. Start Docker and pull the configured image. ' + created.stderr[:500])
        process = subprocess.Popen([executable, 'start', '--attach', '--interactive', name],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_process_options())
        threads = [threading.Thread(target=drain, args=(pipe, buffer), daemon=True)
                   for pipe, buffer in zip((process.stdout, process.stderr), buffers)]
        threads.append(threading.Thread(target=feed, daemon=True))
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + settings.sandbox_timeout
        timed_out = False
        while process.poll() is None:
            if overflow.is_set():
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            overflow.wait(0.02)
        if timed_out or overflow.is_set():
            logging.getLogger(__name__).warning('Sandbox limit exceeded: %s', name)
            return RunResult(stdout=buffers[0].decode('utf-8', errors='replace'),
                stderr=buffers[1].decode('utf-8', errors='replace'),
                timed_out=timed_out, output_limited=overflow.is_set())
        for thread in threads:
            thread.join(timeout=1)
        # Inspect the container, since attach's own exit status can describe a client failure.
        inspected = command(['inspect', '--format', '{{.State.Status}} {{.State.ExitCode}}', name])
        state = inspected.stdout.strip().split()
        if inspected.returncode or len(state) != 2 or state[0] != 'exited':
            raise RuntimeError('Docker could not confirm sandbox completion.')
        return RunResult(buffers[0].decode('utf-8', errors='replace'),
            buffers[1].decode('utf-8', errors='replace'), int(state[1]), output_limited=overflow.is_set())
    except OSError as exc:
        raise RuntimeError(f'Cannot start Docker sandbox: {exc}') from exc
    finally:
        # Removing the named container kills the workload, not just the Docker client.
        try:
            cleanup = command(['rm', '--force', name])
            if cleanup.returncode and 'No such container' not in cleanup.stderr:
                raise RuntimeError(f'Could not confirm cleanup of {name}. Check Docker.')
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                for thread in threads:
                    thread.join(timeout=1)
                for pipe in (process.stdin, process.stdout, process.stderr):
                    pipe.close()
