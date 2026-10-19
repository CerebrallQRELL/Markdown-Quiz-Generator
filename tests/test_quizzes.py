from copy import deepcopy
from pathlib import Path
import random
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from markdown_quiz.backend import QuizBackend
from markdown_quiz.quiz.code_quiz import create_blank, generate_code_quiz, generation_hash, grade_answer, validate_candidate
from markdown_quiz.config import Settings, load_settings
from markdown_quiz.notes.parser import parse_markdown
from markdown_quiz.services.sandbox import RunResult, run_in_sandbox
from markdown_quiz.notes.storage import sync_terms, sync_records
from markdown_quiz.quiz.term_quiz import build_question, filter_tags, generate_wrong_answers


class TermTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.rows = sync_terms([], parse_markdown('#A #B\nOne:: First\nTwo:: Second\nThree:: Third\nFour:: Fourth', 'x.md')[0])

    def test_or_filter_and_inactive(self):
        self.rows[-1]['active'] = False
        self.assertEqual(len(filter_tags(self.rows, ['A', 'Other'])), 3)
        self.assertEqual(len(filter_tags(self.rows, ['a', 'b'], 'all')), 3)
        self.assertEqual(filter_tags(self.rows, ['Other']), [])

    def test_cache_and_reverse_no_llm(self):
        request = Mock(return_value={'wrong_answers': ['a', 'b', 'c']})
        record = self.rows[0]
        build_question(record, self.rows, self.settings, 'forward', request=request)
        build_question(record, self.rows, self.settings, 'forward', request=request)
        question = build_question(record, self.rows, self.settings, 'reverse', rng=random.Random(1), request=request)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(question['choices'][question['correct_index']], 'One')
        self.assertEqual(len(set(question['choices'])), 4)

    def test_retry_and_manual_regeneration_preserves_mastery(self):
        self.rows[0]['mastery'] = 5
        request = Mock(side_effect=[{'wrong_answers': ['a', 'a', 'b']},
            {'wrong_answers': ['**First**', 'b', 'c']}, {'wrong_answers': ['a', 'b', 'c']}])
        generate_wrong_answers(self.rows[0], self.settings, request)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(self.rows[0]['mastery'], 5)
        request = Mock(return_value={})
        with self.assertRaises(ValueError):
            generate_wrong_answers(self.rows[0], self.settings, request)
        self.assertEqual(request.call_count, 3)

    def test_insufficient_reverse_terms(self):
        with self.assertRaisesRegex(ValueError, 'three other'):
            build_question(self.rows[0], self.rows[:1], self.settings, 'reverse')


class CodeTests(unittest.TestCase):
    def test_local_blank_reconstructs_unicode_program_at_every_difficulty(self):
        code = 'word = "café"\nif len(word) > 2:\n    print(word + "!")\n'
        for difficulty in ('easy', 'medium', 'hard'):
            candidate = create_blank(code, difficulty)
            self.assertEqual(candidate['blank_code'].count('<BLANK>'), 1)
            self.assertEqual(candidate['blank_code'].replace('<BLANK>', candidate['answer']), code)

    def test_generation_accepts_program_without_model_blank(self):
        request = Mock(return_value={'generated_code': 'print(2)'})
        generate_code_quiz(self.row, self.settings, request=request, runner=self.runner)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.row['blank_code'].count('<BLANK>'), 1)

    def setUp(self):
        self.settings = Settings()
        self.row = dict(source_id='code1', original_code='print(1)', mastery=4,
                        previous_generation_hashes=[])
        self.candidate = dict(generated_code='print(2)', blank_code='print(<BLANK>)', answer='2')
        self.runner = Mock(return_value=RunResult(stdout='2\n', exit_code=0))

    def test_validate_and_regenerate(self):
        generate_code_quiz(self.row, self.settings, request=Mock(return_value=self.candidate), runner=self.runner)
        self.assertEqual(self.runner.call_count, 2)
        old_hash = self.row['generation_hash']
        candidate = dict(generated_code='print(3)', blank_code='print(<BLANK>)', answer='3')
        self.runner.return_value = RunResult(stdout='3\n', exit_code=0)
        generate_code_quiz(self.row, self.settings, request=Mock(return_value=candidate), runner=self.runner)
        self.assertIn(old_hash, self.row['previous_generation_hashes'])
        self.assertEqual(self.row['mastery'], 4)

    def test_duplicate_code_and_three_attempts(self):
        self.row['previous_generation_hashes'] = [generation_hash('print(2)  \n')]
        request = Mock(return_value=self.candidate)
        before = deepcopy(self.row)
        with self.assertRaisesRegex(ValueError, '3 attempts'):
            generate_code_quiz(self.row, self.settings, request=request, runner=self.runner)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(self.row, before)
        self.runner.assert_not_called()

    def test_source_duplicate_syntax_and_blank_validation(self):
        for candidate in [dict(generated_code='print(1)', blank_code='print(<BLANK>)', answer='1'),
                          dict(generated_code='print(', blank_code='print(<BLANK>', answer=' '),
                          dict(generated_code='print(2)', blank_code='<BLANK><BLANK>', answer='2'),
                          dict(generated_code='print(2)', blank_code='print(<BLANK>)', answer='3')]:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                validate_candidate(candidate, self.row, self.settings, self.runner)
        self.runner.assert_not_called()

    def test_runtime_timeout_and_unstable_output(self):
        for result in [RunResult(exit_code=1), RunResult(timed_out=True), RunResult(output_limited=True), RunResult(exit_code=0)]:
            self.runner.return_value = result
            with self.assertRaises(ValueError):
                validate_candidate(self.candidate, self.row, self.settings, self.runner)
        self.runner.side_effect = [RunResult(stdout='2\n', exit_code=0), RunResult(stdout='3\n', exit_code=0)]
        with self.assertRaisesRegex(ValueError, 'stable'):
            validate_candidate(self.candidate, self.row, self.settings, self.runner)

    def test_behavioral_answer(self):
        record = {**self.candidate, 'expected_output': '2\n'}
        correct, _ = grade_answer(record, '1 + 1', self.settings, self.runner)
        self.assertTrue(correct)
        self.runner.assert_called_once_with('print(1 + 1)', self.settings)
        self.runner.return_value = RunResult(stdout='3\n', exit_code=0)
        self.assertFalse(grade_answer(record, '3', self.settings, self.runner)[0])

    def test_code_change_deactivates_old_cache(self):
        old = parse_markdown('```python\nprint(1)\n```', 'x.md')[1]
        rows = sync_records([], old, kind='code')
        rows[0]['mastery'] = 3
        new = parse_markdown('```python\nprint(2)\n```', 'x.md')[1]
        changed = sync_records(rows, new, kind='code')
        self.assertFalse(changed[0]['active'])
        self.assertEqual(changed[0]['mastery'], 3)
        self.assertTrue(changed[1]['active'])
        self.assertNotIn('generated_code', changed[1])


class BackendTests(unittest.TestCase):
    def test_rescan_persistence_and_automatic_regeneration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / 'notes.md'
            note.write_text('Cell:: Unit', encoding='utf-8')
            settings = Settings(vault_path=directory, data_path=str(root / 'data'))
            backend = QuizBackend(settings)
            backend.rescan()
            backend.terms[0]['mastery'] = 5
            backend.save('term')
            note.write_text('Cell:: Changed', encoding='utf-8')
            with patch('markdown_quiz.backend.generate_wrong_answers') as generate:
                backend.rescan()
                generate.assert_called_once()
            restored = QuizBackend(settings)
            self.assertEqual(restored.terms[0]['mastery'], 3)
            note.unlink()
            backend.rescan()
            self.assertFalse(QuizBackend(settings).terms[0]['active'])

    def test_code_cache(self):
        with TemporaryDirectory() as directory:
            backend = QuizBackend(Settings(data_path=directory))
            row = dict(generation_hash='cached', difficulty='easy')
            with patch('markdown_quiz.backend.generate_code_quiz') as generate:
                self.assertIs(backend.code_question(row, 'easy'), row)
                generate.assert_not_called()

    def test_settings_environment(self):
        with TemporaryDirectory() as directory, patch.dict('os.environ', {'DATA_PATH': directory, 'OLLAMA_MODEL': 'local-test'}):
            settings = load_settings()
            self.assertEqual(settings.ollama_model, 'local-test')
            self.assertEqual(settings.data_path, directory)

    def test_missing_docker(self):
        with patch('markdown_quiz.services.sandbox.shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'Docker not installed'):
                run_in_sandbox('print(2)', Settings())


if __name__ == '__main__':
    unittest.main()
