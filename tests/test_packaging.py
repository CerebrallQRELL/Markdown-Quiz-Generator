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
            frontend = root / 'obsidian_plugin'
            files = {
                'backend.py': '# launcher', 'scripts/run_backend.py': '# launcher',
                'main.py': '# launcher', 'scripts/run_multiple_choice.py': '# launcher',
                'scripts/run_code_quiz.py': '# launcher', 'scripts/reset_json.py': '# launcher',
                'requirements.txt': '', 'Dockerfile': '', '.dockerignore': '',
                'LICENSE': '', 'README.md': '', '.gitignore': '',
                'docs/OBSIDIAN_SETUP.md': '', 'docs/ARCHITECTURE.md': '',
                'docs/REFACTOR_NOTES.md': '', 'docs/PROJECT_MAP.json': '{}',
                'vault/example.md': '#quiz',
                'deployment/install-local.ps1': '', 'deployment/DEPLOYMENT.md': '',
                'quiz_backend/__init__.py': '', 'quiz_backend/api.py': '# API',
                'quiz_backend/notes/__init__.py': '',
                'quiz_backend/notes/parser.py': '# nested parser',
                'quiz_backend/quiz/__init__.py': '',
                'quiz_backend/quiz/engine.py': '# nested engine',
                'quiz_backend/services/__init__.py': '',
                'quiz_backend/services/sandbox.py': '# nested sandbox',
                'obsidian_plugin/main.js': '// generated',
                'obsidian_plugin/styles.css': '',
                'obsidian_plugin/.gitignore': '',
                'obsidian_plugin/src/views/QuizView.ts': '// nested frontend',
                'obsidian_plugin/manifest.json': json.dumps({
                    'id': 'markdown-quiz-generator', 'version': '1.3.9'}),
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')

            installed = root / 'plugin/markdown-quiz-generator/backend'
            obsolete = installed / 'quiz_backend/engine.py'
            obsolete.parent.mkdir(parents=True)
            obsolete.write_text('# previous flat layout')
            saved = installed / 'data/vaults/example/sessions.json'
            saved.parent.mkdir(parents=True)
            saved.write_bytes(b'{"study_progress":"preserve"}')

            with patch.object(package_release, 'ROOT', root), patch.object(package_release, 'SOURCE', frontend), patch('sys.stdout', new_callable=io.StringIO):
                package_release.package()

            self.assertFalse(obsolete.exists())
            self.assertEqual(saved.read_bytes(), b'{"study_progress":"preserve"}')
            self.assertEqual((installed / 'quiz_backend/quiz/engine.py').read_text(), '# nested engine')
            for path in (root / 'dist').glob('*.zip'):
                with self.subTest(archive=path.name), ZipFile(path) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertTrue(any(name.endswith('quiz_backend/quiz/engine.py') for name in archive.namelist()))
                    self.assertFalse(any('/data/' in name for name in archive.namelist()))
            with ZipFile(root / 'dist/markdown-quiz-source-1.3.9.zip') as archive:
                self.assertIn('obsidian_plugin/src/views/QuizView.ts', archive.namelist())
                self.assertIn('docs/ARCHITECTURE.md', archive.namelist())


if __name__ == '__main__':
    unittest.main()
