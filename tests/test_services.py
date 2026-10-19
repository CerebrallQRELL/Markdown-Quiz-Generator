import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from markdown_quiz.api import QuizAPI, APIError
from markdown_quiz.backend import QuizBackend
from markdown_quiz.config import Settings, save_settings
from markdown_quiz.services.cloud import request_json, validate_endpoint
from markdown_quiz.services.sandbox import RunResult


class ServiceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.settings = Settings(vault_path=temp.name, data_path=str(self.root / 'data'))
        self.settings.api_key = 'test-secret'
        self.settings.api_url = 'https://provider.test/v1'
        self.settings.api_key_url = self.settings.api_url
        self.settings.api_model = 'test-model'
        (self.root / 'note.md').write_text('#quiz\nOne:: First\nTwo:: Second\nThree:: Third\nFour:: Fourth\n')
        self.api = QuizAPI(QuizBackend(self.settings))
        self.api.dispatch('POST', '/sync', {})

    @patch('markdown_quiz.services.cloud.build_opener')
    def test_api_request_and_safe_errors(self, opener):
        opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            {'choices': [{'message': {'content': '{"wrong_answers": ["a", "b", "c"]}'}}]}).encode()
        self.assertEqual(request_json(self.settings, 'quiz', {})['wrong_answers'], ['a', 'b', 'c'])
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://provider.test/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-secret')
        opener.return_value.open.side_effect = HTTPError(request.full_url, 401, 'test-secret', {}, None)
        with self.assertRaisesRegex(RuntimeError, 'HTTP 401') as caught:
            request_json(self.settings, 'quiz', {})
        self.assertNotIn('test-secret', str(caught.exception))

    def test_endpoint_and_credential_binding(self):
        for url in ('http://provider.test', 'https://user:pass@provider.test', 'https://provider.test?key=abc'):
            with self.assertRaises(ValueError):
                validate_endpoint(url)
        self.settings.api_key_url = 'https://different.test/v1'
        with self.assertRaisesRegex(ValueError, 'different API provider'):
            request_json(self.settings, 'quiz', {})

    def test_keys_not_persisted_and_cleared_on_failure(self):
        body = dict(direction='reverse', length=1, provider='api', api_url=self.settings.api_url,
                    api_model='test-model', api_key='test-secret', api_key_url=self.settings.api_url)
        state = self.api.dispatch('POST', '/quiz/start', body)
        save_settings(self.settings)
        for path in (self.root / 'data').glob('*.json'):
            self.assertNotIn('test-secret', path.read_text())
            self.assertNotIn('api_key', path.read_text())
        self.assertEqual(self.settings.api_key, '')
        session = self.api.sessions[state['session_id']]
        self.assertEqual(session['filters']['provider'], 'api')
        with patch.object(self.api.engine, 'operate', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                self.api.dispatch('POST', '/quiz/next', dict(session_id=state['session_id'], api_key='test-secret'))
        self.assertEqual(self.settings.api_key, '')

    def test_provider_is_session_specific(self):
        self.api.engine.apply_session_model({'filters': {'provider': 'api', 'api_model': 'cloud'}})
        self.assertEqual(self.settings.generation_provider, 'api')
        self.api.engine.apply_session_model({'filters': {'model': 'local'}})
        self.assertEqual(self.settings.generation_provider, 'ollama')

    def test_server_reset_keeps_sessions(self):
        state = self.api.dispatch('POST', '/quiz/start', dict(direction='reverse', length=1))
        self.api.dispatch('POST', '/admin/reset', dict(target='server'))
        self.assertIn(state['session_id'], self.api.sessions)
        self.assertEqual(len(self.api.backend.terms), 4)
        with self.assertRaises(APIError):
            self.api.dispatch('POST', '/admin/reset', dict(target='unknown'))

    @patch('markdown_quiz.api.run_in_sandbox')
    @patch('markdown_quiz.api.check_sandbox_available')
    @patch('markdown_quiz.api.install_libraries', return_value=('new-image', 'numpy'))
    def test_sandbox_reset_commits_only_after_verification(self, install, check, run):
        original = self.settings.sandbox_image
        run.return_value = RunResult(exit_code=1)
        with self.assertRaises(APIError):
            self.api.dispatch('POST', '/admin/reset', dict(target='sandbox'))
        self.assertEqual(self.settings.sandbox_image, original)
        run.return_value = RunResult(stdout='sandbox-ready\n', exit_code=0)
        self.api.dispatch('POST', '/admin/reset', dict(target='sandbox'))
        self.assertEqual(self.settings.sandbox_image, 'new-image')

    @patch('markdown_quiz.api.build_opener')
    def test_ollama_reset_only_unloads_requested_model(self, opener):
        self.api.dispatch('POST', '/admin/reset', dict(target='ollama', model='local-model'))
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(json.loads(request.data), dict(model='local-model', keep_alive=0, stream=False))
