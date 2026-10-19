"""One persisted session/attempt engine for sidebar quizzes and inline practice."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import random
import time
import uuid
from typing import NotRequired, TypedDict

from . import questions
from .selection import eligible, filter_questions, QuizFilters
from .term_quiz import build_question
from .spaced_repetition import record_answer, priority
from ..notes.storage import read_json, write_json
from ..notes.parser import digest


class SessionState(TypedDict):
    """Private sessions.json shape; public responses omit question solutions."""
    session_id: str
    quiz_type: str
    filters: QuizFilters
    queue: list[str]  # Persistent source IDs, not generated question IDs.
    index: int
    total: int | None
    question: dict | None
    answers: dict[str, dict]
    requests: dict[str, dict]  # Request ID → original response for safe retries.
    updated: float
    no_output_ids: list[str]
    invalid_ids: NotRequired[list[str]]
    preparation_error: NotRequired[str]


class QuizEngine:
    def __init__(self, backend):
        self.backend = backend
        self.file = Path(backend.settings.data_path) / 'sessions.json'
        self.sessions: dict[str, SessionState] = read_json(self.file, dict)

    def save(self):
        # Preserve recent completed sessions and bounded abandoned inline practices.
        ordered = sorted(self.sessions, key=lambda k: self.sessions[k]['updated'], reverse=True)
        self.sessions = {k: self.sessions[k] for k in ordered[:256]}
        write_json(self.file, self.sessions)

    def catalog(self, filters):
        rows = filter_questions(self.backend, filters)
        tags = {}
        for row in eligible(self.backend, filters.get('quiz_type', 'multiple-choice')):
            for tag in set(row['tags']):
                if tag.casefold() != 'quiz':
                    tags[tag] = tags.get(tag, 0) + 1
        return dict(count=len(rows), tags=sorted(tags, key=lambda t: (-tags[t], t.casefold())),
                    stats=self.statistics(rows))

    @staticmethod
    def statistics(rows):
        return dict(total=len(rows), due=sum(priority(row) <= 1 for row in rows),
                    mastered=sum(row['mastery'] >= 4 for row in rows),
                    learning=sum(bool(row.get('last_seen')) and row['mastery'] < 4 for row in rows),
                    new=sum(not row.get('last_seen') for row in rows),
                    correct=sum(row.get('correct_count', 0) for row in rows),
                    incorrect=sum(row.get('incorrect_count', 0) for row in rows))

    def start(self, filters: QuizFilters):
        kind = filters.get('quiz_type', 'multiple-choice')
        length = filters.get('length', 10)
        if length not in ('all', 'until') and (type(length) is not int or not 1 <= length <= 10000):
            raise ValueError('Invalid quiz length.')
        direction = filters.get('direction', 'random')
        if direction not in (('random', 'forward', 'reverse') if kind == 'multiple-choice' else ('random', 'source')):
            raise ValueError('Unsupported direction for this quiz type.')
        if kind == 'coding':
            questions.validate_imports(filters.get('python_imports', ''))
        rows = filter_questions(self.backend, filters)
        if not rows:
            raise ValueError('No due questions match these filters.' if filters.get('due_only') else 'No questions match these filters.')
        if direction == 'source':
            rows.sort(key=lambda row: (row['source_file'], row.get('source_line', 0)))
        else:
            random.shuffle(rows)
        ids = [row['source_id'] for row in rows]
        if type(length) is int and kind != 'coding':
            ids = ids[:length]
        identity = uuid.uuid4().hex
        if length == 'until':
            total = None
        elif type(length) is int:
            total = min(length, len(ids))
        else:
            total = len(ids)
        session: SessionState = dict(session_id=identity, quiz_type=kind, filters=deepcopy(filters), queue=ids,
                                    index=0, total=total, question=None, no_output_ids=[],
                                    answers={}, requests={}, updated=time.time())
        self.sessions[identity] = session
        try:
            self.prepare_question(session)
        except Exception:
            del self.sessions[identity]
            raise
        self.save()
        return self.public_session(session)

    def find_source_record(self, session, identity):
        return next((row for row in eligible(self.backend, session['quiz_type']) if row['source_id'] == identity), None)

    def apply_session_model(self, session):
        self.backend.settings.generation_provider = session['filters'].get('provider', 'ollama')
        self.backend.settings.api_url = session['filters'].get('api_url', '')
        self.backend.settings.api_model = session['filters'].get('api_model', '')
        model = session['filters'].get('model')
        if isinstance(model, str) and model.strip():
            self.backend.settings.ollama_model = model

    def prepare_question(self, session):
        session.pop('preparation_error', None)
        try:
            self._prepare_question(session)
        except (ValueError, RuntimeError, OSError) as exc:
            # Keep the failed queue position available for explicit skip or retry.
            session['question'] = None
            session['preparation_error'] = str(exc)

    def _prepare_question(self, session):
        self.apply_session_model(session)
        while session['index'] < len(session['queue']) and (session['total'] is None or session['index'] < session['total']):
            row = self.find_source_record(session, session['queue'][session['index']])
            if row:
                source_id = row['source_id']
                self.backend.rescan([row['source_file']], regenerate_changed=False)
                row = next((candidate for candidate in filter_questions(self.backend, session['filters'])
                            if candidate['source_id'] == source_id), None)
            if not row:
                session['index'] += 1
                continue
            kind = session['quiz_type']
            if kind == 'multiple-choice':
                data = build_question(row, eligible(self.backend), self.backend.settings,
                                      session['filters'].get('direction', 'random'), cache=self.backend.terms)
                self.backend.save('term')
                answers = [dict(id=uuid.uuid4().hex, text=t) for t in data['choices']]
                correct_id = answers[data['correct_index']]['id']
                data.update(answers=answers, correct_answer_id=correct_id, explanation=row['definition'])
                fingerprint = row['definition_hash']
            else:
                try:
                    data = questions.coding_instance(row, self.backend.settings, session['filters'].get('difficulty', 'medium'), defer_input=True, imports=session['filters'].get('python_imports', ''))
                except questions.InvalidQuestionError as exc:
                    self.discard_invalid_source(session, row['source_id'], exc)
                    continue
                data['sandbox_image'] = self.backend.settings.sandbox_image
                fingerprint = row['code_hash']
            session['question'] = dict(data, type=kind, question_id=uuid.uuid4().hex,
                source_id=row['source_id'], source_file=row['source_file'], source_line=row.get('source_line', 1),
                tags=row['tags'], mastery=row['mastery'], next_review=row.get('next_review'),
                fingerprint=fingerprint, started=time.time(), attempts=[], draft={}, result=None, completed=False)
            return
        session['question'] = None

    def discard_invalid_source(self, session, source_id, error):
        """Backfill a rejected coding source without counting a student attempt."""
        reason = 'no_output_ids' if isinstance(error, questions.NoOutputError) else 'invalid_ids'
        session.setdefault(reason, []).append(source_id)
        session['queue'].pop(session['index'])
        if session['total'] is not None:
            session['total'] = min(session['total'], len(session['queue']))

    def current_question(self, session):
        question = session.get('question')
        if not question:
            raise ValueError('No active question. Start another quiz.')
        self.backend.rescan([question['source_file']], regenerate_changed=False)
        row = self.find_source_record(session, question['source_id'])
        key = 'definition_hash' if session['quiz_type'] == 'multiple-choice' else 'code_hash'
        if not row or row[key] != question['fingerprint']:
            raise ValueError('This question changed or was deleted. Skip it or start over.')
        return question, row

    def public_session(self, session):
        question = session.get('question')
        public = None
        if question:
            hidden = {'solutions', 'generated_code', 'correct_answer_id', 'correct_index', 'fingerprint', 'started', 'explanation', 'sandbox_image'}
            public = {k: deepcopy(v) for k, v in question.items() if k not in hidden}
        results = list(session['answers'].values())
        correct = sum(row['correct'] for row in results)
        summary = dict(answered=len(results), correct=correct, incorrect=len(results) - correct,
            first_correct=sum(row['correct'] and row['attempts'] == 1 for row in results),
            retry_correct=sum(row['correct'] and row['attempts'] > 1 for row in results),
            failed_runs=sum(row.get('failed_runs', 0) for row in results),
            skipped=sum(row['status'] == 'skipped' for row in results),
            percent=round(100 * correct / len(results)) if results else 0,
            improved=len({row['source_id'] for row in results if row['correct']}),
            missed=list(dict.fromkeys(row['source_id'] for row in results if not row['correct'])))
        return dict(session_id=session['session_id'], quiz_type=session['quiz_type'], question=public,
                    complete=question is None and not session.get('preparation_error'), preparation_error=session.get('preparation_error', ''), difficulty=session['filters'].get('difficulty', 'medium'), index=session['index'], total=session['total'], progress=summary,
                    notice=' '.join(filter(None, [
                        f"Skipped {len(session['no_output_ids'])} code block(s) that produce no output." if session.get('no_output_ids') else '',
                        f"Skipped {len(session['invalid_ids'])} invalid code block(s)." if session.get('invalid_ids') else ''])),
                    result=deepcopy(question['result']) if question else None)

    def get_session(self, data):
        session = self.sessions.get(data.get('session_id'))
        if not session:
            raise ValueError('Session not found. Start another quiz.')
        session['updated'] = time.time()
        return session

    def record_attempt(self, session, question, row, result, payload):
        final = result['completed']
        count = len(question['attempts']) + 1
        result.update(question_id=question['question_id'], source_id=question['source_id'], question_type=question['type'],
                      attempts=count, response_time_ms=max(0, round((time.time() - question['started']) * 1000)),
                      timestamp=datetime.now(timezone.utc).isoformat(), first_attempt_correct=result['correct'] and count == 1,
                      difficulty=question.get('difficulty'), mastery_before=row['mastery'],
                      run_count=(len(question['attempts']) + (result['status'] != 'skipped')) if question['type'] == 'coding' else 0,
                      failed_runs=sum(not a['correct'] and a['status'] != 'skipped' for a in question['attempts']) + (not result['correct'] and result['status'] != 'skipped'),
                      response=deepcopy(payload))
        execution = {key: result[key] for key in ('stdout', 'stderr', 'expected_output') if key in result}
        instance_hash = digest(question.get('generated_code', question.get('prompt', '')))
        details = dict(question_id=question['question_id'], question_type=question['type'], attempts=count,
                       response=deepcopy(payload), run_count=result['run_count'], execution=execution,
                       generation_hash=instance_hash, status=result['status'],
                       response_time_ms=result['response_time_ms'], difficulty=question.get('difficulty'))
        if final:
            record_answer(row, result['correct'], **details, failed_runs=result['failed_runs'],
                          selected_answer_ids=[attempt.get('selected_answer_id') for attempt in question['attempts']]
                                              + [result.get('selected_answer_id')])
        else:
            row.setdefault('history', []).append(dict(at=result['timestamp'], correct=False, completed=False,
                source_id=question['source_id'], **details,
                mastery_before=row['mastery'], mastery_after=row['mastery'], next_review=row.get('next_review')))
        result.update(mastery=row['mastery'], mastery_after=row['mastery'], next_review=row.get('next_review'))
        question['attempts'].append(deepcopy(result))
        question.update(result=result, completed=final, mastery=row['mastery'], next_review=row.get('next_review'))
        if final:
            session['answers'][question['question_id']] = deepcopy(result)
        self.backend.save('term' if question['type'] == 'multiple-choice' else 'code')

    def answer(self, session, data):
        request_id = data.get('request_id')
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
            raise ValueError('An attempt request ID is required.')
        if request_id in session['requests']:
            return deepcopy(session['requests'][request_id])
        question, row = self.current_question(session)
        if question['question_id'] != data.get('question_id'):
            raise ValueError('This question is no longer current.')
        if question['completed']:
            return self.public_session(session)
        if question['type'] == 'multiple-choice':
            answer_id = data.get('answer_id')
            if answer_id not in {a['id'] for a in question['answers']}:
                raise ValueError('Choose one of the displayed answers.')
            if answer_id in {a.get('selected_answer_id') for a in question['attempts']}:
                return self.public_session(session)
            correct = answer_id == question['correct_answer_id']
            final = correct or len(question['attempts']) >= 1
            result = dict(correct=correct, completed=final, status='correct' if correct else 'incorrect', selected_answer_id=answer_id)
            if final:
                result.update(correct_answer_id=question['correct_answer_id'], explanation=question['explanation'],
                    correct_answer=next(a['text'] for a in question['answers'] if a['id'] == question['correct_answer_id']))
            payload = {'answer_id': answer_id}
        else:
            if question.get('needs_input'):
                raise ValueError('Apply program input before answering.')
            payload = data.get('answers')
            result = questions.grade_coding(question, payload, replace(self.backend.settings, sandbox_image=question.get('sandbox_image', self.backend.settings.sandbox_image)))
            result['completed'] = result['correct']
            question['draft'] = deepcopy(payload)
            if result['status'] == 'sandbox_failure':
                # Infrastructure failures do not count as student mistakes.
                result.update(attempts=len(question['attempts']), mastery=row['mastery'], next_review=row.get('next_review'))
                question['result'] = result
                self.save()
                return self.public_session(session)
        self.record_attempt(session, question, row, result, payload)
        response = self.public_session(session)
        session['requests'][request_id] = deepcopy(response)
        self.save()
        return response

    def skip(self, session):
        question = session.get('question')
        if not question or question['completed']:
            return
        row = self.find_source_record(session, question['source_id'])
        if row and row.get('definition_hash' if question['type'] == 'multiple-choice' else 'code_hash') == question['fingerprint']:
            self.record_attempt(session, question, row, dict(correct=False, completed=True, status='skipped'), question.get('draft', {}))

    def advance(self, session, data, *, skip=False):
        """Finish or skip one queue position, then prepare the next question."""
        question = session.get('question')
        # A repeated click must not advance a position the client has not seen.
        if 'index' in data and data['index'] != session['index']:
            return False
        if question and data.get('question_id') and question['question_id'] != data['question_id']:
            return False
        if question and not question['completed']:
            if not skip:
                raise ValueError('Finish this question or choose Skip.')
            self.skip(session)
        within_queue = session['index'] < len(session['queue'])
        within_length = session['total'] is None or session['index'] < session['total']
        if question or (skip and within_queue and within_length):
            session['index'] += 1
            session['question'] = None
        if session['index'] >= len(session['queue']) and session['total'] is None:
            rows = filter_questions(self.backend, session['filters'])
            random.shuffle(rows)
            rejected = session.get('no_output_ids', []) + session.get('invalid_ids', [])
            session['queue'].extend(row['source_id'] for row in rows if row['source_id'] not in rejected)
        self.prepare_question(session)
        return True

    def configure_coding_question(self, session, action, data):
        question = session.get('question')
        if not question or question['type'] != 'coding' or question['question_id'] != data.get('question_id'):
            raise ValueError('This coding question is no longer current.')
        if action == 'difficulty':
            difficulty = data.get('difficulty')
            if difficulty not in ('easy', 'medium', 'hard'):
                raise ValueError('Difficulty must be easy, medium, or hard.')
            session['filters']['difficulty'] = difficulty
            if not question['attempts'] and not question['completed']:
                question.update(questions.make_blanks(question['generated_code'], difficulty),
                                difficulty=difficulty, draft={})
            return
        if question['attempts'] or question['completed']:
            raise ValueError('Program input is fixed after the first answer.')
        settings = replace(self.backend.settings,
                           sandbox_image=question.get('sandbox_image', self.backend.settings.sandbox_image))
        try:
            question.update(questions.prepare_output(question, settings, data.get('stdin_text', '')))
        except questions.InvalidQuestionError as exc:
            self.discard_invalid_source(session, question['source_id'], exc)
            session['question'] = None
            self.prepare_question(session)

    def regenerate_question(self, session, data):
        question = session.get('question')
        if not question or question['attempts']:
            raise ValueError('Start over to regenerate an attempted question.')
        for key in ('provider', 'api_url', 'api_model'):
            if key in data:
                session['filters'][key] = data[key]
        if data.get('model'):
            session['filters']['model'] = data['model']
        self.apply_session_model(session)
        if question['type'] == 'multiple-choice':
            _, row = self.current_question(session)
            self.backend.regenerate_term(row)
        self.prepare_question(session)

    def operate(self, action, data):
        """Translate a quiz action to the shared session lifecycle."""
        if action == 'catalog':
            return self.catalog(data)
        if action == 'start':
            return self.start(data)
        session = self.get_session(data)
        if action == 'answer':
            return self.answer(session, data)
        question = session.get('question')
        if action == 'resume':
            pass
        elif action == 'draft':
            if question and question['question_id'] == data.get('question_id') and question['type'] == 'coding' and not question['completed']:
                questions.reconstruct(question, data.get('answers'))
                question['draft'] = deepcopy(data['answers'])
        elif action == 'abandon':
            self.skip(session)
            session['question'] = None
        elif action in ('skip', 'next'):
            if not self.advance(session, data, skip=action == 'skip'):
                return self.public_session(session)
        elif action in ('input', 'difficulty'):
            self.configure_coding_question(session, action, data)
        elif action == 'retry':
            if session.get('preparation_error'):
                self.prepare_question(session)
        elif action == 'regenerate':
            self.regenerate_question(session, data)
        else:
            raise ValueError('Unknown quiz operation.')
        self.save()
        return self.public_session(session)
