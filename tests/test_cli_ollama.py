import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from markdown_quiz.config import Settings
from markdown_quiz.main import main
from markdown_quiz.services.ollama import request_json


class CLITests(unittest.TestCase):
    def test_scan_tags_and_reverse_quiz_progress(self):
        with TemporaryDirectory() as directory, patch.dict('os.environ', {}, clear=True):
            root = Path(directory)
            note = root / 'notes.md'
            note.write_text('#Study\nOne:: First\nTwo:: Second\nThree:: Third\nFour:: Fourth', encoding='utf-8')
            args = ['--vault', str(root), '--data', str(root / 'data')]
            with patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(main([*args, 'rescan']), 0)
                self.assertIn('4 active terms', output.getvalue())
            with patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(main([*args, 'tags']), 0)
                self.assertIn('Study', output.getvalue())
            # Term quiz, all tags, reverse mode, one question, answer A, exit.
            with patch('builtins.input', side_effect=['1', '', '3', '1', 'A', '6']), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(args), 0)
            rows = json.loads((root / 'data' / 'terms.json').read_text())
            self.assertEqual(sum(r['correct_count'] + r['incorrect_count'] for r in rows), 1)
            self.assertEqual(sum(len(r['history']) for r in rows), 1)

    def test_missing_vault_and_corrupt_json(self):
        with TemporaryDirectory() as directory, patch.dict('os.environ', {}, clear=True), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(main(['--data', directory, '--vault', directory + '/missing', 'rescan']), 1)
            path = Path(directory) / 'terms.json'
            path.write_text('{bad')
            self.assertEqual(main(['--data', directory, 'terms']), 1)
            self.assertEqual(path.read_text(), '{bad')


class OllamaTests(unittest.TestCase):
    def test_structured_local_request(self):
        response = Mock()
        response.read.return_value = json.dumps({'response': '{"wrong_answers": ["a", "b", "c"]}'}).encode()
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch('markdown_quiz.services.ollama.build_opener', return_value=opener):
            result = request_json(Settings(ollama_model='local-model'), 'prompt', {'type': 'object'})
        self.assertEqual(result['wrong_answers'], ['a', 'b', 'c'])
        request = opener.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload['model'], 'local-model')
        self.assertEqual(payload['format'], {'type': 'object'})
        self.assertFalse(payload['stream'])

    def test_unavailable(self):
        with patch('markdown_quiz.services.ollama.build_opener') as opener:
            opener.return_value.open.side_effect = URLError('offline')
            with self.assertRaisesRegex(RuntimeError, 'Ollama unavailable'):
                request_json(Settings(), 'prompt', {})

    def test_missing_model_shows_server_error_and_recovery(self):
        with patch('markdown_quiz.services.ollama.build_opener') as opener:
            opener.return_value.open.side_effect = HTTPError('http://localhost:11434', 404,
                'Not Found', {}, io.BytesIO(b'{"error":"model qwen3 not found"}'))
            with self.assertRaisesRegex(RuntimeError, 'model qwen3 not found.*ollama pull qwen3'):
                request_json(Settings(), 'prompt', {})


if __name__ == '__main__':
    unittest.main()
