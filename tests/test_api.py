import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from markdown_quiz.api import APIError, QuizAPI, make_handler
from markdown_quiz.backend import QuizBackend
from markdown_quiz.config import Settings
from markdown_quiz.notes.parser import parse_markdown, digest, normalize_code


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.note = self.root / 'note.md'
        self.note.write_text('#quiz #Study\nOne:: First\nTwo:: Second\nThree:: Third\nFour:: Fourth\n'
                             '```python\nprint(1)\n```\n```python\nprint(1)\n```', encoding='utf-8')
        self.api = QuizAPI(QuizBackend(Settings(vault_path=str(self.root), data_path=str(self.root / 'data'))))
        self.call('/sync')

    def call(self, path, data=None):
        return self.api.dispatch('POST', path, data or {})

    def test_library_settings_persist_and_failed_install_keeps_previous_image(self):
        with patch('markdown_quiz.api.install_libraries', return_value=('quiz:test', 'numpy')):
            self.assertEqual(self.call('/libraries', {'packages': 'numpy'}), {'packages': 'numpy'})
        self.assertEqual(self.api.backend.settings.sandbox_image, 'quiz:test')
        self.assertEqual(self.api.dispatch('GET', '/libraries', {}), {'packages': 'numpy'})
        with patch('markdown_quiz.api.install_libraries', side_effect=RuntimeError('No matching distribution')):
            with self.assertRaisesRegex(APIError, 'No matching distribution'):
                self.call('/libraries', {'packages': 'badpackage'})
        self.assertEqual(self.api.backend.settings.sandbox_image, 'quiz:test')
        saved = json.loads((self.root / 'data/settings.json').read_text())
        self.assertEqual(saved['python_libraries'], 'numpy')

    def test_term_session_keys_idempotency_and_completion(self):
        start = self.call('/quiz/term/start', dict(direction='reverse', length=1))
        self.assertNotIn('correct_index', start['question'])
        session = self.api.sessions[start['session_id']]
        payload = dict(session_id=start['session_id'], question_id=start['question']['question_id'],
                       index=session['question']['correct_index'])
        answer = self.call('/quiz/term/answer', payload)
        self.assertTrue(answer['correct'])
        self.assertEqual(answer, self.call('/quiz/term/answer', payload))
        self.assertEqual(self.api.stats()['correct'], 1)
        end = self.call('/quiz/term/next', dict(session_id=start['session_id']))
        self.assertTrue(end['complete'])
        self.assertEqual(end['progress']['percent'], 100)

    def test_no_repeats_and_due_filter(self):
        start = self.call('/quiz/term/start', dict(direction='reverse', length='all'))
        seen = set()
        while not start['complete']:
            question = start['question']
            self.assertNotIn(question['source_id'], seen)
            seen.add(question['source_id'])
            private = self.api.sessions[start['session_id']]['question']
            self.call('/quiz/term/answer', dict(session_id=start['session_id'], question_id=question['question_id'], index=private['correct_index']))
            start = self.call('/quiz/term/next', dict(session_id=start['session_id']))
        self.assertEqual(len(seen), 4)
        with self.assertRaisesRegex(APIError, 'No due'):
            self.call('/quiz/term/start', dict(due_only=True))

    def test_modified_and_deleted_sources_invalidate_question(self):
        start = self.call('/quiz/term/start', dict(direction='reverse'))
        question = start['question']
        self.note.write_text('Unrelated:: New', encoding='utf-8')
        with self.assertRaisesRegex(APIError, 'changed or was deleted'):
            self.call('/quiz/term/answer', dict(session_id=start['session_id'], question_id=question['question_id'], index=0))
        self.note.unlink()
        self.call('/sync/file', dict(source_file='note.md'))
        self.assertEqual(self.api.stats()['total'], 0)

    def test_rename_preserves_mastery_and_duplicate_code_occurrences(self):
        self.api.backend.terms[0]['mastery'] = 4
        self.api.backend.codes[1]['mastery'] = 3
        self.assertEqual(len(self.api.backend.codes), 2)
        self.assertNotEqual(*[r['source_id'] for r in self.api.backend.codes])
        self.note.rename(self.root / 'renamed.md')
        self.call('/sync/file', dict(source_file='renamed.md', old_path='note.md'))
        self.assertEqual(self.api.backend.terms[0]['mastery'], 4)
        self.assertEqual(self.api.backend.codes[1]['mastery'], 3)
        self.assertTrue(all(r['source_file'] == 'renamed.md' for r in self.api.backend.codes))

    def test_paths_and_no_generation_during_sync(self):
        for value in ('../outside.md', '/absolute.md', 'C:/secret.md', 'folder\\note.md'):
            with self.assertRaises(APIError):
                self.call('/sync/file', dict(source_file=value))
        self.note.write_text('One:: Changed', encoding='utf-8')
        with patch('markdown_quiz.backend.generate_wrong_answers') as generate:
            self.call('/sync/file', dict(source_file='note.md'))
            generate.assert_not_called()

    def test_code_cache_and_stale_question(self):
        row = self.api.backend.codes[0]
        row.update(generated_code='print(2)', blank_code='print(<BLANK>)', answer='2',
                   expected_output='2\n', generation_hash='hash', difficulty='medium')
        self.api.backend.save('code')
        with patch('markdown_quiz.quiz.questions.run_in_sandbox', return_value=__import__('markdown_quiz.services.sandbox', fromlist=['RunResult']).RunResult(stdout='2\n', exit_code=0)), patch('markdown_quiz.backend.generate_code_quiz') as generate:
            question = self.call('/quiz/code/get', dict(source_file='note.md', code_hash=digest(normalize_code('print(1)')), occurrence=1))
            generate.assert_not_called()
        self.assertNotIn('answer', question)
        self.note.write_text('No code here.', encoding='utf-8')
        with self.assertRaisesRegex(APIError, 'question changed'):
            self.call('/quiz/code/answer', dict(question_id=question['question_id'], answer='2'))

    def test_quiz_marker_include_exclude_dates_and_auto_tags(self):
        self.note.write_text('#quiz #Python #2026-10-14\nA:: Alpha\n'
                             '#quiz #Other #2026-10-15\nB:: Beta\n'
                             '#Python\nHidden:: Hidden definition\n'
                             'C:: Gamma #quiz #date/2026-10-16\n', encoding='utf-8')
        self.call('/sync')
        self.assertEqual(self.api.stats()['total'], 3)
        self.assertNotIn('quiz', self.api.dispatch('GET', '/tags', {})['tags'])
        self.assertEqual([r['term'] for r in self.api.matching(dict(tags=['Python'], exclude_tags=['Other']))], ['A', 'C'])
        self.assertEqual([r['term'] for r in self.api.matching(dict(date_from='2026-10-14', date_to='2026-10-15'))], ['A', 'B'])
        self.assertEqual([r['term'] for r in self.api.matching(dict(date_from='2026-10-16'))], ['C'])
        self.assertEqual(len(self.api.matching(dict(exclude_tags=['quiz']))), 3)
        with self.assertRaisesRegex(APIError, 'Start date'):
            self.api.matching(dict(date_from='2026-10-16', date_to='2026-10-14'))

    def test_frontmatter_and_label_tags(self):
        terms, _ = parse_markdown('---\ntags:\n  - quiz\n  - date/2026-10-14\n---\nA:: Alpha\n#Other\nB:: Beta', 'tags.md')
        self.assertTrue(all('quiz' in row['tags'] for row in terms))
        self.assertEqual(terms[0]['source_line'], 6)
        terms, _ = parse_markdown('**Term:** A #quiz\n**Definition:** Alpha #Python', 'tags.md')
        self.assertEqual(terms[0]['tags'], ['quiz', 'Python'])
        self.assertEqual(terms[0]['term'], 'A')

    def test_two_connected_vaults_do_not_use_default_folder(self):
        roots = [self.root / 'real-a', self.root / 'real-b']
        ids = []
        for index, root in enumerate(roots):
            root.mkdir()
            (root / 'note.md').write_text(f'#quiz\nReal{index}:: From Obsidian\n```python\nprint({index + 10})\n```', encoding='utf-8')
            connected = self.api.connect_vault(dict(vault_path=str(root)))
            ids.append(connected['vault_id'])
            target = self.api.vaults[ids[-1]]
            target.dispatch('POST', '/sync', {})
            self.assertEqual([r['term'] for r in target.eligible()], [f'Real{index}'])
            self.assertEqual(target.backend.codes[0]['original_code'], f'print({index + 10})')
        self.assertNotEqual(ids[0], ids[1])
        self.assertNotEqual(self.api.vaults[ids[0]].backend.settings.data_path, self.api.vaults[ids[1]].backend.settings.data_path)
        self.assertEqual(self.api.stats()['total'], 4)
        self.assertEqual(self.api.connect_vault(dict(vault_path=str(roots[0])))['vault_id'], ids[0])

    def test_http_vault_context_and_expired_context(self):
        root = self.root / 'actual-vault'
        root.mkdir()
        (root / 'note.md').write_text('#quiz #ActualVault\nActual:: Correct vault', encoding='utf-8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.api))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            request = Request(url + '/vault/connect', data=json.dumps(dict(vault_path=str(root))).encode(), headers={'Content-Type': 'application/json'})
            with urlopen(request) as response:
                identity = json.load(response)['vault_id']
            headers = {'Content-Type': 'application/json', 'X-Quiz-Vault': identity}
            with urlopen(Request(url + '/sync', data=b'{}', headers=headers)) as response:
                self.assertEqual(json.load(response)['stats']['total'], 1)
            with urlopen(Request(url + '/tags', headers=headers)) as response:
                self.assertEqual(json.load(response)['tags'], ['ActualVault'])
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(url + '/tags', headers={'X-Quiz-Vault': 'expired'}))
            self.assertEqual(caught.exception.code, 409)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_http_boundary_and_origin(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.api))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            with urlopen(url + '/tags') as response:
                self.assertEqual(json.load(response)['tags'], ['Study'])
            request = Request(url + '/sync', data=b'{}', headers={'Content-Type': 'application/json', 'Origin': 'https://untrusted.example'})
            with self.assertRaises(HTTPError) as caught:
                urlopen(request)
            self.assertEqual(caught.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    unittest.main()
