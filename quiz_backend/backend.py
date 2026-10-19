"""Saved collections, Markdown synchronization and the compatible CLI operations."""
from pathlib import Path
import logging

from .quiz.code_quiz import generate_code_quiz, grade_answer
from .notes.parser import scan_vault, code_identity, digest, normalize_text
from .quiz.spaced_repetition import record_answer, reset_mastery
from .notes.storage import load_records, write_json, sync_records
from .quiz.term_quiz import build_question, generate_wrong_answers


class QuizBackend:
    """One shared settings object and two collections; no terminal dependencies."""

    def __init__(self, settings):
        self.settings = settings
        self.terms = load_records(settings.data_path, 'term')
        self.codes = load_records(settings.data_path, 'code')

    def save(self, kind):
        filename, rows = ('terms.json', self.terms) if kind == 'term' else ('code_quizzes.json', self.codes)
        write_json(Path(self.settings.data_path) / filename, rows)

    def rescan(self, files=None, regenerate_changed=True):
        terms, codes, scope, failed = scan_vault(self.settings.vault_path, files)
        options = dict(scanned_files=scope, failed_files=failed)
        self.terms = sync_records(self.terms, terms, kind='term', **options)
        self.codes = sync_records(self.codes, codes, kind='code', **options)
        self.save('term')
        self.save('code')
        errors = [f'Unreadable Markdown: {path}' for path in sorted(failed)]
        # Save the invalidation before requesting the local model. A failed request
        # remains pending and is retried on rescan or when this term is questioned.
        for row in self.terms:
            if regenerate_changed and row.get('active') and row.get('needs_regeneration'):
                try:
                    self.regenerate_term(row)
                except (ValueError, RuntimeError) as exc:
                    errors.append(f"{row['term']}: {exc}")
        return errors

    def rename_source(self, old_path, new_path):
        """Move stable identities with a note, preserving caches and study progress."""
        for kind, rows in (('term', self.terms), ('code', self.codes)):
            updates = []
            for row in rows:
                if row['source_file'] != old_path:
                    continue
                identity = (digest(f"{new_path}:{normalize_text(row['term'])}") if kind == 'term'
                            else code_identity(new_path, row['original_code'], row.get('occurrence', 1)))
                updates.append((row, identity))
            # A previous inactive incarnation of the destination must not shadow this rename.
            moving = {id(row) for row, _ in updates}
            targets = {identity for _, identity in updates}
            rows[:] = [row for row in rows if row['source_id'] not in targets or id(row) in moving]
            for row, identity in updates:
                row.update(source_file=new_path, source_id=identity)
            self.save(kind)
        return self.rescan([new_path], regenerate_changed=False)

    def regenerate_term(self, record):
        generate_wrong_answers(record, self.settings)
        self.save('term')

    def term_question(self, record, direction='random', pool=None):
        question = build_question(record, self.terms if pool is None else pool, self.settings,
                                  direction, cache=self.terms)
        self.save('term')
        return question

    def answer_term(self, question, index):
        if type(index) is not int or not 0 <= index < len(question['choices']):
            raise ValueError('Answer index is out of range.')
        record = next(r for r in self.terms if r['source_id'] == question['source_id'])
        correct = index == question['correct_index']
        record_answer(record, correct, direction=question['direction'])
        self.save('term')
        return correct

    def code_question(self, record, difficulty, regenerate=False):
        if regenerate or not record.get('generation_hash') or record.get('difficulty') != difficulty:
            generate_code_quiz(record, self.settings, difficulty)
            self.save('code')
        return record

    def answer_code(self, record, answer):
        correct, result = grade_answer(record, answer, self.settings)
        record_answer(record, correct, generation_hash=record['generation_hash'])
        self.save('code')
        return correct, result

    def reset(self, record, kind='term'):
        reset_mastery(record)
        self.save(kind)
        logging.getLogger(__name__).info('Reset mastery: %s', record['source_id'])
