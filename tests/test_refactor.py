"""Compatibility checks for the consolidated parser, selection and storage paths."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from quiz_backend.backend import QuizBackend
from quiz_backend.config import Settings
from quiz_backend.quiz.engine import QuizEngine
from quiz_backend.notes.parser import parse_markdown
from quiz_backend.quiz.questions import InvalidQuestionError, NoOutputError, coding_instance
from quiz_backend.services.sandbox import RunResult
from quiz_backend.quiz.selection import eligible, filter_questions, filter_tags
from quiz_backend.notes.storage import load_records, read_json, sync_terms, write_json
from quiz_backend.quiz.term_quiz import build_question


class RefactorTests(unittest.TestCase):
    def test_parser_keeps_saved_ids_and_physical_lines(self):
        # IDs captured from the original parser, not calculated by the new code.
        text = ('---\ntags: [quiz, Python]\n---\n**Term:** [[Cell|Unit]] #Extra\n\n'
                '**Definition:** **Living** unit\n~~~py\nprint("café")  \n~~~\n'
                '```python\nprint("café")\n```')
        terms, blocks = parse_markdown(text, 'folder/lesson.md')
        self.assertEqual(terms[0]['source_id'], '3d4503187bc1d8ffe72ae5a7e02196ed81f1601c83a00c500ffba632490d6ff8')
        self.assertEqual([row['source_id'] for row in blocks], [
            '9c71888a7ca1e68519def39c2d2a9d1018387c2cf6c731f8b1f9a2fc5cd5551a',
            '8fe5e90330aec31522ce253a6566db09ed6a04e7081115bd325972ba449fdc0a'])
        self.assertEqual(terms[0]['tags'], ['quiz', 'Python', 'Extra'])
        self.assertEqual([row['source_line'] for row in terms + blocks], [6, 7, 10])
        self.assertEqual([row['occurrence'] for row in blocks], [1, 2])
        self.assertEqual(blocks[0]['original_code'], 'print("café")')

    def test_old_filter_imports_are_the_same_functions(self):
        from quiz_backend.quiz import questions, term_quiz
        self.assertIs(questions.matching, filter_questions)
        self.assertIs(questions.eligible, eligible)
        self.assertIs(term_quiz.filter_tags, filter_tags)

    def test_filters_do_not_mutate_saved_records_or_request(self):
        with TemporaryDirectory() as directory:
            backend = QuizBackend(Settings(data_path=directory))
            backend.terms = sync_terms([], parse_markdown(
                '#quiz #Python #date/2026-10-14\nA:: Alpha\n'
                '#quiz #Other #2026-10-15\nB:: Beta', 'lesson.md')[0])
            filters = dict(tags=['#PYTHON'], exclude_tags=['Other'], date_from='2026-10-14',
                           date_to='2026-10-14', source_file='lesson.md', due_only=True)
            before = deepcopy((backend.terms, filters))
            self.assertEqual([row['term'] for row in filter_questions(backend, filters)], ['A'])
            self.assertEqual((backend.terms, filters), before)

    def test_term_cache_can_be_outside_reverse_choice_pool(self):
        cached = sync_terms([], parse_markdown('A:: Alpha', 'cache.md')[0])[0]
        cached['wrong_answers'] = ['Wrong one', 'Wrong two', 'Wrong three']
        record = sync_terms([], parse_markdown('A:: Alpha', 'lesson.md')[0])[0]
        request = Mock(side_effect=AssertionError('A valid cached answer must not call a model.'))
        result = build_question(record, [record], Settings(), 'forward', request=request, cache=[cached])
        self.assertEqual(set(result['choices']), {'Alpha', *cached['wrong_answers']})
        request.assert_not_called()
        self.assertEqual(cached['mastery'], 0)

    def test_engine_uses_cache_and_follows_each_queued_source(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'lesson.md').write_text('#quiz\nA:: Alpha\nB:: Beta\nC:: Gamma\nD:: Delta')
            settings = Settings(vault_path=directory, data_path=str(root / 'data'))
            backend = QuizBackend(settings)
            backend.rescan(regenerate_changed=False)
            for row in backend.terms:
                row['wrong_answers'] = ['Wrong one', 'Wrong two', 'Wrong three']
            backend.save('term')
            engine = QuizEngine(backend)
            with patch('quiz_backend.quiz.term_quiz.generate_wrong_answers', side_effect=AssertionError('Cached quiz')):
                state = engine.start(dict(direction='forward', length='all'))
                queue = engine.sessions[state['session_id']]['queue'].copy()
                for identity in queue:
                    self.assertEqual(state['question']['source_id'], identity)
                    state = engine.operate('skip', dict(session_id=state['session_id']))
            self.assertTrue(state['complete'])
            self.assertEqual(state['progress']['skipped'], 4)
            self.assertEqual(QuizEngine(QuizBackend(settings)).operate(
                'resume', dict(session_id=state['session_id'])), state)

    def test_record_validation_refuses_to_rewrite_damaged_data(self):
        for changes, message in [({'term': None}, 'source fields'),
                                 ({'tags': [1]}, 'tags'),
                                 ({'history': [{'correct': 'yes'}]}, 'history'),
                                 ({'generation_hash': 'incomplete'}, 'incomplete')]:
            with self.subTest(changes=changes), TemporaryDirectory() as directory:
                row = sync_terms([], parse_markdown('A:: Alpha', 'lesson.md')[0])[0]
                row.update(changes)
                path = Path(directory) / 'terms.json'
                write_json(path, [row])
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, message):
                    load_records(directory, 'term')
                self.assertEqual(path.read_bytes(), before)

    def test_loaded_progress_keeps_its_existing_shape(self):
        with TemporaryDirectory() as directory:
            row = sync_terms([], parse_markdown('A:: Alpha', 'lesson.md')[0])[0]
            row.update(mastery=5, history=[{'correct': True}], extra_legacy_field='preserve')
            path = Path(directory) / 'terms.json'
            write_json(path, [row])
            self.assertEqual(load_records(directory, 'term'), read_json(path))

    def test_silent_program_without_blank_is_classified_before_blank_creation(self):
        runner = Mock(return_value=RunResult(exit_code=0))
        with self.assertRaises(NoOutputError):
            coding_instance({'original_code': 'pass'}, Settings(), 'easy', runner=runner)
        self.assertTrue(all(call.args[0] == 'pass' for call in runner.call_args_list))

    def test_reconstructed_solution_is_still_checked_in_sandbox(self):
        def runner(code, settings):
            return RunResult(stdout='1\n' if code == 'print(1)' else '2\n', exit_code=0)
        damaged_blank = dict(blank_code='print(<BLANK_1>)', blanks=[{'id': 'blank_1', 'marker': '<BLANK_1>'}],
                             solutions={'blank_1': '2'})
        with patch('quiz_backend.quiz.questions.make_blanks', return_value=damaged_blank):
            with self.assertRaisesRegex(InvalidQuestionError, 'different output'):
                coding_instance({'original_code': 'print(1)'}, Settings(), 'easy', runner=runner)


if __name__ == '__main__':
    unittest.main()
