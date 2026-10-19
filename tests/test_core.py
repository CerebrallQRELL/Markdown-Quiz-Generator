import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from markdown_quiz.notes.parser import parse_markdown, scan_vault, normalize_code
from markdown_quiz.notes.storage import sync_terms, read_json, write_json, reset_quiz_data
from markdown_quiz.quiz.spaced_repetition import record_answer, review_time


class CoreTests(unittest.TestCase):
    def test_reset_backs_up_corrupt_data_and_preserves_other_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'terms.json').write_bytes(b'{broken')
            (root / 'code_quizzes.json').write_bytes(b'[]')
            (root / 'settings.json').write_bytes(b'{"ollama_model":"local"}')
            backup = reset_quiz_data(root, 'terms')
            self.assertEqual((backup / 'terms.json').read_bytes(), b'{broken')
            self.assertEqual(read_json(root / 'terms.json'), [])
            self.assertEqual((root / 'code_quizzes.json').read_bytes(), b'[]')
            self.assertEqual((root / 'settings.json').read_bytes(), b'{"ollama_model":"local"}')

    def test_parse_and_tag_replacement(self):
        terms, blocks = parse_markdown('#Biology\n#Notes\n\nCell:: **Living unit**\n\n'
            '**Term:** Ribosome\n**Definition:** Makes proteins\n#Chemistry #Notes\nAtom:: Matter\n'
            '```python\nprint(1)\n```\n```js\nFake:: Nope\n```', 'notes.md')
        self.assertEqual([r['term'] for r in terms], ['Cell', 'Ribosome', 'Atom'])
        self.assertEqual(terms[0]['tags'], ['Biology', 'Notes'])
        self.assertEqual(terms[1]['tags'], ['Biology', 'Notes'])
        self.assertEqual(terms[2]['tags'], ['Chemistry', 'Notes'])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['original_code'], 'print(1)')

    def test_sync_change_delete_restore(self):
        parse = lambda text: parse_markdown(text, 'x.md')[0]
        rows = sync_terms([], parse('#A\nCell:: **Living unit**'))
        rows[0].update(mastery=4, wrong_answers=['a', 'b', 'c'], correct_count=3)
        rows = sync_terms(rows, parse('#B\nCell:: Living  unit'))
        self.assertEqual(rows[0]['mastery'], 4)
        self.assertEqual(rows[0]['tags'], ['B'])
        rows = sync_terms(rows, parse('Cell:: New meaning'))
        self.assertEqual(rows[0]['mastery'], 2)
        self.assertEqual(rows[0]['wrong_answers'], [])
        rows = sync_terms(rows, [])
        self.assertFalse(rows[0]['active'])
        rows = sync_terms(rows, parse('Cell:: New meaning'))
        self.assertTrue(rows[0]['active'])
        self.assertEqual(rows[0]['correct_count'], 3)
        self.assertEqual(len(rows), 1)

    def test_partial_scan_and_failed_file_preserve_records(self):
        rows = sync_terms([], parse_markdown('Cell:: Unit', 'x.md')[0])
        self.assertTrue(sync_terms(rows, [], scanned_files={'y.md'})[0]['active'])
        self.assertTrue(sync_terms(rows, [], failed_files={'x.md'})[0]['active'])

    def test_schedule(self):
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        record = dict(source_id='a', mastery=0)
        record_answer(record, True, now)
        self.assertEqual(record['mastery'], 1)
        self.assertEqual(record['next_review'], (now + timedelta(days=1)).isoformat())
        record_answer(record, False, now)
        self.assertEqual(record['mastery'], 0)
        self.assertEqual(record['incorrect_count'], 1)
        self.assertEqual(review_time(7, now), now + timedelta(days=60))

    def test_code_normalization_and_identity(self):
        self.assertEqual(normalize_code('\nprint(1)  \n'), 'print(1)')
        a = parse_markdown('```python\nprint(1)  \n```', 'x.md')[1]
        b = parse_markdown('~~~python\nprint(1)\n~~~', 'x.md')[1]
        self.assertEqual(a[0]['source_id'], b[0]['source_id'])

    def test_files_and_corruption(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / 'a.md'
            note.write_text('Cell:: Unit', encoding='utf-8')
            before = note.read_bytes()
            self.assertEqual(scan_vault(root)[0][0]['source_file'], 'a.md')
            self.assertEqual(note.read_bytes(), before)
            target = root / 'terms.json'
            self.assertEqual(read_json(target), [])
            write_json(target, scan_vault(root)[0])
            self.assertEqual(len(read_json(target)), 1)
            target.write_text('{broken', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_json(target)
            self.assertEqual(target.read_text(), '{broken')

    def test_malformed_and_empty_markdown(self):
        self.assertEqual(parse_markdown('**Definition:** orphan\n:: missing\n```python\nunclosed', 'x.md'), ([], []))
        self.assertEqual(parse_markdown('', 'x.md'), ([], []))


if __name__ == '__main__':
    unittest.main()
