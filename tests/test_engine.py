import ast
import os
from pathlib import Path
import random
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from quiz_backend.backend import QuizBackend
from quiz_backend.config import Settings
from quiz_backend.quiz.engine import QuizEngine
from quiz_backend.quiz import questions
from quiz_backend.services.sandbox import RunResult, hidden_process_options


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.note = self.root / 'lesson.md'
        self.note.write_text('#quiz #Python #2026-10-14\nOne:: First\nTwo:: Second\nThree:: Third\nFour:: Fourth\n'
                             '```python\ndef add(x, y):\n    return x + y\nprint(add(5, 4))\n```\n'
                             '#Other #2026-10-15\nNotEligible:: Ignore\n```py\nprint(7)\n```', encoding='utf-8')
        self.settings = Settings(vault_path=str(self.root), data_path=str(self.root / 'data'))
        self.backend = QuizBackend(self.settings)
        self.backend.rescan(regenerate_changed=False)
        for row in self.backend.terms:
            row['wrong_answers'] = ['Wrong A', 'Wrong B', 'Wrong C']
        self.backend.save('term')
        self.engine = QuizEngine(self.backend)
        self.runner = patch('quiz_backend.quiz.questions.run_in_sandbox', return_value=RunResult(stdout='9\n', exit_code=0))
        self.runner.start(); self.addCleanup(self.runner.stop)

    def start(self, **extra):
        return self.engine.start(dict(direction='forward', length=1, **extra))

    def answer(self, state, answer_id, request='attempt'):
        return self.engine.operate('answer', dict(session_id=state['session_id'], question_id=state['question']['question_id'],
                                               answer_id=answer_id, request_id=request))

    def test_silent_code_skipped_and_requested_count_backfilled(self):
        self.note.write_text('```python\nx = 1\n```\n```python\nprint(2)\n```\n```python\ny = 3\n```\n```python\nprint(4)\n```', encoding='utf-8')
        self.backend.rescan(regenerate_changed=False)
        def execute(code, settings):
            return RunResult(stdout='2\n' if 'print' in code else '', exit_code=0)
        with patch('quiz_backend.quiz.questions.run_in_sandbox', side_effect=execute):
            state = self.engine.start(dict(quiz_type='coding', direction='source', length=2))
            self.assertEqual(state['index'], 0)
            self.assertEqual(state['total'], 2)
            self.assertIn('Skipped 1', state['notice'])
            # Skip an actual presented question; silence itself receives no mastery attempt.
            state = self.engine.operate('skip', dict(session_id=state['session_id']))
            self.assertEqual(state['index'], 1)
            self.assertEqual(state['total'], 2)
            self.assertIn('Skipped 2', state['notice'])
            self.assertEqual(state['progress']['answered'], 1)
            self.assertEqual(self.backend.codes[0]['mastery'], 0)
            self.assertEqual(self.backend.codes[2]['mastery'], 0)
            resumed = QuizEngine(self.backend).operate('resume', dict(session_id=state['session_id']))
            self.assertEqual(resumed['notice'], state['notice'])

    def test_all_silent_code_completes_without_attempt_or_loop(self):
        with patch('quiz_backend.quiz.questions.run_in_sandbox', return_value=RunResult(exit_code=0)):
            for length in (1, 'all', 'until'):
                state = self.engine.start(dict(quiz_type='coding', direction='source', length=length))
                self.assertTrue(state['complete'])
                self.assertEqual(state['progress']['answered'], 0)
                self.assertIn('Skipped 2', state['notice'])
                if length != 'until': self.assertEqual(state['total'], 0)

    def test_invalid_sources_are_skipped_at_start_and_next(self):
        self.note.write_text('```py\nprint(\n```\n```py\nprint(1)\n```\n```py\nraise ValueError("broken")\n```\n```py\nprint(2)\n```', encoding='utf-8')
        self.backend.rescan(regenerate_changed=False)
        def execute(code, settings):
            return RunResult(stderr='ValueError: broken', exit_code=1) if 'raise' in code else RunResult(stdout='1\n', exit_code=0)
        with patch('quiz_backend.quiz.questions.run_in_sandbox', side_effect=execute):
            state = self.engine.start(dict(quiz_type='coding', direction='source', length=2))
            self.assertIn('Skipped 1 invalid', state['notice'])
            state = self.engine.operate('skip', dict(session_id=state['session_id']))
            self.assertIn('Skipped 2 invalid', state['notice'])
            self.assertEqual(state['total'], 2)
            self.assertIsNotNone(state['question'])
            self.assertEqual(state['progress']['answered'], 1)

    def test_all_errors_complete_without_attempts(self):
        with patch('quiz_backend.quiz.questions.run_in_sandbox', return_value=RunResult(stderr='ValueError: broken', exit_code=1)):
            state = self.engine.start(dict(quiz_type='coding', direction='source', length='until'))
            self.assertTrue(state['complete'])
            self.assertEqual(state['progress']['answered'], 0)

    def test_input_requested_after_start_and_not_carried_to_next(self):
        self.note.write_text('```py\nprint(input())\n```\n```py\nprint(2)\n```', encoding='utf-8')
        self.backend.rescan(regenerate_changed=False)
        def execute(code, settings, stdin_text=''):
            if 'input()' in code and not stdin_text:
                return RunResult(stderr='EOFError: EOF when reading a line', exit_code=1)
            return RunResult(stdout=stdin_text or '2\n', exit_code=0)
        with patch('quiz_backend.quiz.questions.run_in_sandbox', side_effect=execute):
            state = self.engine.start(dict(quiz_type='coding', direction='source', length=2, stdin_text='stale'))
            q = state['question']
            self.assertTrue(q['needs_input'])
            self.assertEqual(q['stdin_text'], '')
            state = self.engine.operate('input', dict(session_id=state['session_id'], question_id=q['question_id'], stdin_text='hello\n'))
            self.assertFalse(state['question']['needs_input'])
            self.assertEqual(state['question']['expected_output'], 'hello\n')
            state = self.engine.operate('skip', dict(session_id=state['session_id']))
            self.assertEqual(state['question']['stdin_text'], '')
            self.assertFalse(state['question']['needs_input'])

    def test_difficulty_changes_current_unattempted_question_and_future_questions(self):
        state = self.engine.start(dict(quiz_type='coding', direction='source', length=2))
        identity = state['question']['question_id']
        state = self.engine.operate('difficulty', dict(session_id=state['session_id'], question_id=identity, difficulty='easy'))
        self.assertEqual(state['question']['difficulty'], 'easy')
        self.assertEqual(len(state['question']['blanks']), 1)
        self.assertEqual(state['question']['question_id'], identity)
        state = self.engine.operate('skip', dict(session_id=state['session_id']))
        self.assertEqual(state['question']['difficulty'], 'easy')

    def test_failed_generation_can_be_skipped_or_retried_after_resume(self):
        with patch('quiz_backend.quiz.questions.run_in_sandbox', side_effect=RuntimeError('Docker unavailable')):
            state = self.engine.start(dict(quiz_type='coding', direction='source', length=2))
        self.assertFalse(state['complete'])
        self.assertIsNone(state['question'])
        self.assertIn('Docker unavailable', state['preparation_error'])
        resumed = QuizEngine(self.backend)
        state = resumed.operate('resume', dict(session_id=state['session_id']))
        self.assertIn('Docker unavailable', state['preparation_error'])
        state = resumed.operate('skip', dict(session_id=state['session_id']))
        self.assertEqual(state['index'], 1)
        self.assertIsNotNone(state['question'])
        self.assertFalse(state['preparation_error'])
        self.assertEqual(state['progress']['answered'], 0)

        with patch('quiz_backend.quiz.questions.run_in_sandbox', side_effect=RuntimeError('Docker unavailable')):
            state = self.engine.start(dict(quiz_type='coding', direction='source', length=1))
        state = self.engine.operate('retry', dict(session_id=state['session_id']))
        self.assertEqual(state['index'], 0)
        self.assertIsNotNone(state['question'])

    def test_consecutive_preparation_errors_can_be_skipped_to_completion(self):
        with patch('quiz_backend.quiz.questions.run_in_sandbox', side_effect=RuntimeError('Docker unavailable')):
            state = self.engine.start(dict(quiz_type='coding', direction='source', length=2))
            state = self.engine.operate('skip', dict(session_id=state['session_id']))
            self.assertFalse(state['complete'])
            self.assertEqual(state['index'], 1)
            state = self.engine.operate('skip', dict(session_id=state['session_id']))
            self.assertTrue(state['complete'])
            self.assertFalse(state['preparation_error'])

    def test_skip_legacy_failed_second_question_advances_to_third_once(self):
        self.note.write_text('```py\nprint(1)\n```\n```py\nprint(“bad”)\n```\n```py\nprint(3)\n```', encoding='utf-8')
        self.backend.rescan(regenerate_changed=False)
        state = self.engine.start(dict(quiz_type='coding', direction='source', length=3))
        session = self.engine.sessions[state['session_id']]
        third = session['queue'][2]
        # Older backends could advance to a failed source without saving error metadata.
        session.update(index=1, question=None)
        payload = dict(session_id=state['session_id'], question_id=state['question']['question_id'], index=1)
        state = self.engine.operate('skip', payload)
        self.assertEqual(state['index'], 2)
        self.assertEqual(state['question']['source_id'], third)
        self.assertEqual(state, self.engine.operate('skip', payload))
        self.assertEqual(state['progress']['answered'], 0)

    def test_session_models_remain_separate_across_next_and_regenerate(self):
        mc = self.engine.start(dict(quiz_type='multiple-choice', direction='forward', length=2, model='mc-model'))
        self.engine.start(dict(quiz_type='coding', direction='source', length=1, model='code-model'))
        self.assertEqual(self.backend.settings.ollama_model, 'code-model')
        self.engine.operate('skip', dict(session_id=mc['session_id']))
        self.assertEqual(self.backend.settings.ollama_model, 'mc-model')
        observed = []
        with patch.object(self.backend, 'regenerate_term', side_effect=lambda row: observed.append(self.backend.settings.ollama_model)):
            self.engine.operate('regenerate', dict(session_id=mc['session_id'], model='new-mc-model'))
        self.assertEqual(observed, ['new-mc-model'])
        restored = QuizEngine(self.backend)
        session = restored.sessions[mc['session_id']]
        self.assertEqual(session['filters']['model'], 'new-mc-model')
        self.backend.settings.ollama_model = 'another-code-model'
        restored.apply_session_model(session)
        self.assertEqual(self.backend.settings.ollama_model, 'new-mc-model')

    def test_retry_order_no_leaked_key_and_durable_resume(self):
        state = self.start()
        q = state['question']
        private = self.engine.sessions[state['session_id']]['question']
        correct = private['correct_answer_id']
        wrong = next(a['id'] for a in q['answers'] if a['id'] != correct)
        first = self.answer(state, wrong)
        self.assertFalse(first['question']['completed'])
        for hidden in ('correct_answer_id', 'correct_index', 'explanation'):
            self.assertNotIn(hidden, first['question'])
            self.assertNotIn(hidden, first['result'])
        self.assertEqual(q['answers'], first['question']['answers'])
        self.assertEqual(first, self.answer(state, wrong))
        resumed_engine = QuizEngine(QuizBackend(self.settings))
        resumed = resumed_engine.operate('resume', {'session_id': state['session_id']})
        self.assertEqual(first['question'], resumed['question'])
        second = resumed_engine.operate('answer', dict(session_id=state['session_id'], question_id=q['question_id'],
                                                     answer_id=correct, request_id='second'))
        self.assertTrue(second['result']['correct'])
        self.assertEqual(second['result']['attempts'], 2)
        self.assertEqual(second['result']['mastery'], 1)
        self.assertEqual(second['progress']['retry_correct'], 1)
        self.assertEqual(resumed_engine.operate('next', dict(session_id=state['session_id']))['complete'], True)

    def test_random_answer_positions_and_credit(self):
        positions = set()
        for _ in range(20):
            state = self.start()
            q = state['question']; private = self.engine.sessions[state['session_id']]['question']
            positions.add(next(i for i, answer in enumerate(q['answers']) if answer['id'] == private['correct_answer_id']))
        self.assertGreater(len(positions), 1)
        before = private['mastery']
        result = self.answer(state, private['correct_answer_id'])['result']
        self.assertEqual(result['mastery'], before + 2)
        self.assertTrue(result['first_attempt_correct'])
        row = next(r for r in self.backend.terms if r['source_id'] == q['source_id'])
        for key in ('question_id', 'question_type', 'attempts', 'response_time_ms', 'mastery_before', 'mastery_after', 'next_review'):
            self.assertIn(key, row['history'][-1])

    def test_two_failures_reveal_and_block_further_input(self):
        state = self.start()
        private = self.engine.sessions[state['session_id']]['question']
        wrong = [a['id'] for a in private['answers'] if a['id'] != private['correct_answer_id']]
        self.answer(state, wrong[0])
        result = self.answer(state, wrong[1], 'second')
        self.assertTrue(result['question']['completed'])
        self.assertEqual(result['result']['correct_answer_id'], private['correct_answer_id'])
        self.assertFalse(result['result']['correct'])
        self.assertEqual(self.answer(state, private['correct_answer_id'], 'third'), result)

    def test_same_filter_pipeline_counts_and_code_length(self):
        for kind in ('multiple-choice', 'coding'):
            filters = dict(quiz_type=kind, tags=['Python'], exclude_tags=['Other'], date_from='2026-10-14', date_to='2026-10-14')
            rows = questions.matching(self.backend, filters)
            self.assertEqual(len(rows), 4 if kind == 'multiple-choice' else 1)
            self.assertEqual(self.engine.catalog(filters)['count'], len(rows))
            self.assertFalse(questions.matching(self.backend, dict(filters, date_from='2026-10-16', date_to='2026-10-17')))
        with self.assertRaisesRegex(ValueError, 'both included'):
            self.engine.catalog(dict(tags=['Python'], exclude_tags=['python']))
        state = self.engine.start(dict(quiz_type='coding', direction='random', length=10))
        self.assertEqual(state['total'], 2)
        self.assertEqual(state['question']['type'], 'coding')
        self.assertNotIn('solutions', state['question'])
        state = self.engine.operate('skip', dict(session_id=state['session_id']))
        self.assertEqual(state['index'], 1)
        state = self.engine.operate('skip', dict(session_id=state['session_id']))
        self.assertTrue(state['complete'])
        self.assertEqual(state['progress']['skipped'], 2)

    def test_code_retry_draft_mastery_identity_and_no_source_write(self):
        before = self.note.read_bytes()
        state = self.engine.start(dict(quiz_type='coding', direction='random', length=1, tags=['Python']))
        q = self.engine.sessions[state['session_id']]['question']
        self.assertGreaterEqual(len(q['blanks']), 2)
        draft = dict(q['solutions'])
        draft[q['blanks'][0]['id']] = ')'
        self.engine.operate('draft', dict(session_id=state['session_id'], question_id=q['question_id'], answers=draft))
        self.assertEqual(QuizEngine(self.backend).operate('resume', dict(session_id=state['session_id']))['question']['draft'], draft)
        failed = self.engine.operate('answer', dict(session_id=state['session_id'], question_id=q['question_id'], answers=draft, request_id='bad'))
        self.assertEqual(failed['result']['status'], 'syntax_error')
        self.assertFalse(failed['question']['completed'])
        passed = self.engine.operate('answer', dict(session_id=state['session_id'], question_id=q['question_id'], answers=q['solutions'], request_id='good'))
        self.assertEqual(passed['result']['mastery'], 1)
        self.assertEqual(passed['result']['run_count'], 2)
        self.assertEqual(passed['progress']['failed_runs'], 1)
        another = self.engine.start(dict(quiz_type='coding', direction='random', length=1, tags=['Python']))
        self.assertEqual(another['question']['source_id'], q['source_id'])
        self.assertEqual(another['question']['mastery'], 1)
        self.assertNotEqual(another['question']['question_id'], q['question_id'])
        self.assertEqual(len(self.backend.codes), 2)
        self.assertEqual(self.note.read_bytes(), before)

    def test_source_change_does_not_grade_old_snapshot(self):
        state = self.start(); q = self.engine.sessions[state['session_id']]['question']
        self.note.write_text('Removed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed or was deleted'):
            self.answer(state, q['correct_answer_id'])

    def test_random_question_order(self):
        orders = set()
        for _ in range(8):
            state = self.engine.start(dict(length='all', direction='forward'))
            queue = self.engine.sessions[state['session_id']]['queue']
            self.assertEqual(len(set(queue)), 4)
            orders.add(tuple(queue))
        self.assertGreater(len(orders), 1)


class CodingModelTests(unittest.TestCase):
    def test_safe_inputs_and_protected_algorithm_values(self):
        source = 'def add(x, y):\n    return x + y + 100\nprint(add(5, 4))'
        varied, changes = questions.varied_code(source, random.Random(1))
        tree = ast.parse(varied)
        self.assertEqual(tree.body[0].body[0].value.right.value, 100)
        self.assertEqual(len(changes), 2)
        self.assertTrue(all(c['before'] != c['after'] for c in changes))
        for unsafe in ('for i in range(10):\n    print(i)', 'def divide(x):\n    return 10 / x\nprint(divide(2))',
                       'values = [1, 2]\nprint(values[0])', 'def stop(x):\n    return x == -1\nprint(stop(1))'):
            self.assertEqual(questions.varied_code(unsafe), (unsafe, []))

    def test_multiple_blanks_reconstruct_unicode_and_reject_protected_edits(self):
        source = 'def café(x, y):\n    return x * y\nprint(café(5, 4))'
        q = questions.make_blanks(source, 'hard', random.Random(4))
        self.assertGreater(len(q['blanks']), 1)
        self.assertEqual(questions.reconstruct(q, q['solutions']), source)
        with self.assertRaises(ValueError):
            questions.reconstruct(q, dict(q['solutions'], protected='evil'))
        answers = dict(q['solutions']); answers[q['blanks'][0]['id']] = '<BLANK_2>'
        self.assertIn('<BLANK_2>', questions.reconstruct(q, answers))

    def test_result_categories_and_hidden_windows(self):
        q = dict(questions.make_blanks('print(1)', 'easy'), expected_output='1\n')
        for expected, result in [('correct', RunResult(stdout='1\n', exit_code=0)),
                ('incorrect_output', RunResult(stdout='2\n', exit_code=0)), ('runtime_error', RunResult(stderr='ValueError: bad', exit_code=1)),
                ('timeout', RunResult(timed_out=True)), ('output_limit', RunResult(output_limited=True))]:
            self.assertEqual(questions.grade_coding(q, q['solutions'], Settings(), lambda *_: result)['status'], expected)
        def broken(*_): raise RuntimeError('Docker failed')
        self.assertEqual(questions.grade_coding(q, q['solutions'], Settings(), broken)['status'], 'sandbox_failure')
        self.assertEqual(questions.grade_coding(q, {'blank_1': ')'}, Settings())['status'], 'syntax_error')
        if os.name == 'nt':
            import subprocess
            self.assertEqual(hidden_process_options()['creationflags'], subprocess.CREATE_NO_WINDOW)

    @unittest.skipUnless(os.getenv('RUN_DOCKER_TESTS') == '1', 'Requires Docker')
    def test_real_randomized_output_and_multiple_blanks(self):
        source = 'def add(x, y):\n    return x + y\nprint(add(5, 4))'
        q = questions.coding_instance(dict(original_code=source), Settings(), 'medium')
        args = ast.parse(q['generated_code']).body[1].value.args[0].args
        self.assertEqual(q['expected_output'], f'{sum(a.value for a in args)}\n')
        self.assertEqual(questions.grade_coding(q, q['solutions'], Settings())['status'], 'correct')
