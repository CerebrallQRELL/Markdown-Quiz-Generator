"""Release archives must follow the source folders without deleting study data."""
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import package_release


class PackagingTests(unittest.TestCase):
    def test_nested_sources_replace_old_copies_and_preserve_data(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            frontend = root / 'obsidian-markdown-quiz'
            files = {
                'backend.py': '# launcher', 'run_backend.py': '# launcher',
                'main.py': '# launcher', 'run_multiple_choice.py': '# launcher',
                'run_code_quiz.py': '# launcher', 'reset_json.py': '# launcher',
                'requirements.txt': '', 'Dockerfile': '', '.dockerignore': '',
                'LICENSE': '', 'README.md': '', '.gitignore': '',
                'docs/OBSIDIAN_SETUP.md': '', 'docs/ARCHITECTURE.md': '',
                'docs/REFACTOR_NOTES.md': '', 'docs/PROJECT_MAP.json': '{}',
                'vault/example.md': '#quiz',
                'deployment/install-local.ps1': '', 'deployment/DEPLOYMENT.md': '',
                'markdown_quiz/__init__.py': '', 'markdown_quiz/api.py': '# API',
                'markdown_quiz/notes/__init__.py': '',
                'markdown_quiz/notes/parser.py': '# nested parser',
                'markdown_quiz/quiz/__init__.py': '',
                'markdown_quiz/quiz/engine.py': '# nested engine',
                'markdown_quiz/services/__init__.py': '',
                'markdown_quiz/services/sandbox.py': '# nested sandbox',
                'obsidian-markdown-quiz/main.js': '// generated',
                'obsidian-markdown-quiz/styles.css': '',
                'obsidian-markdown-quiz/.gitignore': '',
                'obsidian-markdown-quiz/src/views/QuizView.ts': '// nested frontend',
                'obsidian-markdown-quiz/manifest.json': json.dumps({
                    'id': 'markdown-quiz-generator', 'version': '1.3.9'}),
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')

            installed = root / 'plugin/markdown-quiz-generator/backend'
            obsolete = installed / 'markdown_quiz/engine.py'
            obsolete.parent.mkdir(parents=True)
            obsolete.write_text('# previous flat layout')
            saved = installed / 'data/vaults/example/sessions.json'
            saved.parent.mkdir(parents=True)
            saved.write_bytes(b'{"study_progress":"preserve"}')

            with patch.object(package_release, 'ROOT', root), patch.object(package_release, 'SOURCE', frontend), patch('sys.stdout', new_callable=io.StringIO):
                package_release.package()

            self.assertFalse(obsolete.exists())
            self.assertEqual(saved.read_bytes(), b'{"study_progress":"preserve"}')
            self.assertEqual((installed / 'markdown_quiz/quiz/engine.py').read_text(), '# nested engine')
            for path in (root / 'dist').glob('*.zip'):
                with self.subTest(archive=path.name), ZipFile(path) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertTrue(any(name.endswith('markdown_quiz/quiz/engine.py') for name in archive.namelist()))
                    self.assertFalse(any('/data/' in name for name in archive.namelist()))
            with ZipFile(root / 'dist/markdown-quiz-source-1.3.9.zip') as archive:
                self.assertIn('obsidian-markdown-quiz/src/views/QuizView.ts', archive.namelist())
                self.assertIn('docs/ARCHITECTURE.md', archive.namelist())


if __name__ == '__main__':
    unittest.main()
