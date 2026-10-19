import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from quiz_backend.api import APIError, QuizAPI, make_handler
from quiz_backend.backend import QuizBackend
from quiz_backend.config import Settings
from quiz_backend.quiz import questions
from quiz_backend.services.sandbox import RunResult


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = Settings(vault_path=str(self.root), data_path=str(self.root / 'data'))
        self.api = QuizAPI(QuizBackend(self.settings), managed=True)
        self.connection = self.api.connect_vault({'vault_key': 'my-private-key'})
        self.vault = self.api.vaults[self.connection['vault_id']]

    def upload(self, path='note.md', content='#quiz\nOne:: First', **extra):
        return self.vault.dispatch('POST', '/sync/file', dict(source_file=path, content=content, **extra))

    def test_vault_libraries_restore_without_affecting_other_vaults(self):
        with patch('quiz_backend.api.install_libraries', return_value=('quiz:custom', 'numpy')):
            self.vault.dispatch('POST', '/libraries', {'packages': 'numpy'})
        restored = QuizAPI(QuizBackend(self.settings), managed=True)
        connection = restored.connect_vault({'vault_key': 'my-private-key'})
        self.assertEqual(restored.vaults[connection['vault_id']].backend.settings.sandbox_image, 'quiz:custom')
        other = restored.connect_vault({'vault_key': 'another-vault'})
        self.assertEqual(restored.vaults[other['vault_id']].backend.settings.python_libraries, '')

    def test_remote_uses_uploaded_notes_and_stable_identity(self):
        with self.assertRaises(APIError):
            self.api.connect_vault({'vault_path': str(self.root)})
        self.upload()
        self.assertEqual(self.vault.stats()['total'], 1)
        self.assertFalse((self.root / 'note.md').exists())
        self.assertEqual(self.connection, self.api.connect_vault({'vault_key': 'my-private-key'}))
        other = self.api.connect_vault({'vault_key': 'other'})
        self.assertEqual(self.api.vaults[other['vault_id']].stats()['total'], 0)

    def test_upload_paths_manifest_and_rename(self):
        for path in ('../outside.md', 'C:/note.md', '/tmp/a.md', '.obsidian/config.md'):
            with self.assertRaises(APIError): self.upload(path)
        self.upload()
        self.vault.backend.terms[0]['mastery'] = 4
        self.upload('renamed.md', old_path='note.md')
        self.assertEqual(self.vault.backend.terms[0]['mastery'], 4)
        with self.assertRaises(APIError): self.upload('renamed.md', old_path='renamed.md')
        self.upload('folder/second.md', '#quiz\nTwo:: Second')
        self.vault.dispatch('POST', '/sync/manifest', {'files': ['renamed.md']})
        self.assertEqual(self.vault.stats()['total'], 1)
        self.upload('renamed.md', None)
        self.assertEqual(self.vault.stats()['total'], 0)

    def test_model_survives_reconnect(self):
        self.vault.dispatch('POST', '/model', {'model': 'example:model'})
        restarted = QuizAPI(QuizBackend(self.settings), managed=True)
        connected = restarted.connect_vault({'vault_key': 'my-private-key'})
        self.assertEqual(restarted.vaults[connected['vault_id']].backend.settings.ollama_model, 'example:model')

    def test_http_auth_and_server_restart_protection(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.api, 'secret'))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        for route, token, expected in [('/vault/connect', '', 401), ('/admin/restart', 'secret', 403), ('/sync', 'secret', 403)]:
            req = Request(base + route, data=b'{}', headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
            with self.assertRaises(HTTPError) as error: urlopen(req)
            self.assertEqual(error.exception.code, expected)

    def test_cached_json_avoids_ollama(self):
        self.upload()
        row = self.vault.backend.terms[0]
        row['wrong_answers'] = ['Wrong one', 'Wrong two', 'Wrong three']
        self.vault.backend.save('term')
        reloaded = QuizBackend(self.vault.backend.settings)
        with patch('quiz_backend.quiz.term_quiz.generate_wrong_answers', side_effect=AssertionError('Should use JSON')):
            question = reloaded.term_question(reloaded.terms[0], 'forward')
        self.assertEqual(len(question['choices']), 4)

    def test_expression_output_and_actionable_errors(self):
        observed = []
        def runner(code, settings):
            observed.append(code)
            return RunResult(stdout='3\n', exit_code=0)
        q = questions.coding_instance({'original_code': '1 + 2'}, self.settings, 'easy', runner=runner)
        self.assertEqual('1 + 2', observed[0])
        self.assertEqual(q['expected_output'], '3\n')
        for result, message in [(RunResult(exit_code=0), 'produces no output'),
                (RunResult(timed_out=True), 'time limit'),
                (RunResult(stderr='NameError: missing', exit_code=1), 'NameError: missing')]:
            with self.assertRaisesRegex(ValueError, message):
                questions.coding_instance({'original_code': 'print(1)'}, self.settings, 'easy', runner=lambda *_: result)

    @unittest.skipUnless(os.getenv('RUN_DOCKER_TESTS') == '1', 'Requires Docker')
    def test_expression_real_sandbox(self):
        q = questions.coding_instance({'original_code': 'print(1 + 2)'}, self.settings, 'easy')
        self.assertEqual(q['expected_output'], '3\n')
        self.assertTrue(questions.grade_coding(q, q['solutions'], self.settings)['correct'])

    def test_local_restart_stops_only_http_service(self):
        local = QuizAPI(QuizBackend(self.settings))
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(local))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        req = Request(f'http://127.0.0.1:{server.server_port}/admin/restart', data=b'{}', headers={'Content-Type': 'application/json'})
        with urlopen(req) as response: self.assertTrue(json.load(response)['ok'])
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())

    @unittest.skipUnless(os.getenv('RUN_DOCKER_TESTS') == '1', 'Requires Docker')
    def test_program_input_real_sandbox_and_retries(self):
        source = 'x = int(input("First: "))\ny = int(input("Second: "))\nprint(x + y)'
        q = questions.coding_instance({'original_code': source}, self.settings, 'medium', stdin_text='5\n4\n')
        self.assertEqual(q['expected_output'], 'First: Second: 9\n')
        self.assertEqual(q['stdin_text'], '5\n4\n')
        for _ in range(2):
            self.assertTrue(questions.grade_coding(q, q['solutions'], self.settings)['correct'])
        with self.assertRaisesRegex(ValueError, 'Program input'):
            questions.coding_instance({'original_code': source}, self.settings, 'easy', stdin_text='5\n')
        from quiz_backend.services.sandbox import run_in_sandbox
        result = run_in_sandbox('import sys\nprint(sys.stdin.buffer.read().decode())', self.settings, stdin_text='café')
        self.assertEqual(result.stdout, 'café\n')

    def test_program_input_validation_and_eof_message(self):
        for invalid in (['5'], 'x' * 65537):
            with self.assertRaisesRegex(ValueError, '64 KB'):
                questions.coding_instance({'original_code': 'input()'}, self.settings, 'easy', stdin_text=invalid)
        with self.assertRaisesRegex(ValueError, 'one response per line'):
            questions.coding_instance({'original_code': 'input()'}, self.settings, 'easy',
                runner=lambda *_: RunResult(stderr='EOFError: EOF when reading a line', exit_code=1))

    @unittest.skipUnless(os.getenv('RUN_DOCKER_TESTS') == '1', 'Requires Docker')
    def test_silent_programs_not_converted_to_print(self):
        for source in ('1 + 2', 'pass', 'def example():\n    return 7', 'print("   ")'):
            with self.assertRaises(questions.NoOutputError):
                questions.coding_instance({'original_code': source}, self.settings, 'easy')

    def test_quiz_model_applied_before_generation_and_saved(self):
        self.upload()
        with patch.object(self.vault.engine, 'operate', side_effect=lambda action, data: {'model': self.vault.backend.settings.ollama_model}) as operate:
            for action in ('start', 'regenerate'):
                result = self.vault.quiz('/quiz/' + action, {'model': 'installed:test'})
                self.assertEqual(result['model'], 'installed:test')
            with self.assertRaises(APIError):
                self.vault.quiz('/quiz/start', {'model': ' '})
        saved = json.loads((Path(self.vault.backend.settings.data_path) / 'settings.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['ollama_model'], 'installed:test')
