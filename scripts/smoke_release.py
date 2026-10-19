"""Exercise the packaged HTTP backend with Docker and an isolated temporary vault."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    with TemporaryDirectory(prefix='quiz packaged API ') as temporary:
        root = Path(temporary)
        vault = root / 'Actual Obsidian Vault'
        vault.mkdir()
        note = vault / 'lesson.md'
        note.write_text('#quiz #Python #2026-10-14\nA:: Alpha\nB:: Beta\nC:: Gamma\nD:: Delta\n'
                        '```python\nprint(1)\n```', encoding='utf-8')
        original = note.read_bytes()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        folder = ROOT / 'plugin/markdown-quiz-generator/backend'

        def launch():
            return subprocess.Popen([sys.executable, '-B', str(folder / 'backend.py'), '--vault', str(vault),
                '--data', str(root / 'data'), '--port', str(port)], cwd=folder, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))

        def call(path, data, identity=None):
            headers = {'Content-Type': 'application/json'}
            if identity:
                headers['X-Quiz-Vault'] = identity
            request = Request(f'http://127.0.0.1:{port}' + path, data=json.dumps(data).encode(), headers=headers)
            with urlopen(request, timeout=30) as response:
                return json.load(response)

        def connect():
            for _ in range(30):
                try:
                    return call('/vault/connect', {'vault_path': str(vault)})['vault_id']
                except OSError:
                    time.sleep(.1)
            raise AssertionError('Packaged backend did not start')

        child = launch()
        try:
            identity = connect()
            call('/sync', {}, identity)
            assert call('/quiz/catalog', {'quiz_type': 'coding', 'tags': ['Python']}, identity)['count'] == 1
            mc = call('/quiz/start', {'quiz_type': 'multiple-choice', 'direction': 'reverse', 'length': 1}, identity)
            q = mc['question']
            correct = {'Alpha': 'A', 'Beta': 'B', 'Gamma': 'C', 'Delta': 'D'}[q['prompt'].split('\n')[-1]]
            wrong = next(a for a in q['answers'] if a['text'] != correct)
            first = call('/quiz/answer', dict(session_id=mc['session_id'], question_id=q['question_id'],
                         request_id='first', answer_id=wrong['id']), identity)
            assert not first['question']['completed'] and 'correct_answer_id' not in first['result']
            assert first['question']['answers'] == q['answers']
            coding = call('/quiz/start', dict(quiz_type='coding', direction='random', length=1, difficulty='easy'), identity)
            q = coding['question']
            blank = q['blanks'][0]
            solution = next(value for value in ('print', '1') if q['blank_code'].replace(blank['marker'], value) == 'print(1)')
            result = call('/quiz/answer', dict(session_id=coding['session_id'], question_id=q['question_id'],
                          request_id='run', answers={blank['id']: solution}), identity)
            assert result['result']['status'] == 'correct', result['result']
            assert result['result']['stdout'] == '1\n'
            child.terminate()
            child.wait(timeout=10)
            child = launch()
            identity = connect()
            resumed = call('/quiz/resume', dict(session_id=mc['session_id']), identity)
            assert resumed['question'] == first['question']
            assert note.read_bytes() == original
            print('Packaged API passed: MC retry, coding execution, filters, restart/resume, unchanged Markdown.')
        finally:
            child.terminate()
            child.wait(timeout=10)


if __name__ == '__main__':
    main()
