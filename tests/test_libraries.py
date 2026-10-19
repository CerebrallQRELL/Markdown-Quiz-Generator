import subprocess
import unittest
from unittest.mock import patch

from markdown_quiz.services.libraries import package_names, install_libraries
from markdown_quiz.quiz.questions import validate_imports, coding_instance, grade_coding
from markdown_quiz.config import Settings
from markdown_quiz.services.sandbox import RunResult


class LibraryTests(unittest.TestCase):
    def test_package_validation(self):
        self.assertEqual(package_names('numpy, pandas\nnumpy'), ['numpy', 'pandas'])
        self.assertEqual(package_names('numpy==2.3.0'), ['numpy==2.3.0'])
        for value in ('--index-url evil', 'https://example.com/pkg.whl', 'numpy;touch', 'a @ file:/tmp/a', 'x$(cmd)', 'a>=1', 'a\nRUN echo nope', None):
            if value == 'a\nRUN echo nope':
                # These remain ordinary pip package arguments, never Dockerfile instructions.
                self.assertEqual(package_names(value), ['RUN', 'a', 'echo', 'nope'])
            else:
                with self.assertRaises(ValueError): package_names(value)

    @patch('markdown_quiz.services.libraries.shutil.which', return_value='docker')
    @patch('markdown_quiz.services.libraries.subprocess.run')
    def test_install_builds_separate_image_and_reports_failure(self, run, which):
        run.side_effect = [subprocess.CompletedProcess([], 0, '', ''), subprocess.CompletedProcess([], 0, 'sha256:' + 'a' * 64, '')]
        image, packages = install_libraries('numpy, pandas')
        self.assertEqual(image, 'sha256:' + 'a' * 64)
        self.assertEqual(packages, 'numpy pandas')
        call = run.call_args_list[0]
        self.assertEqual(call.args[0][1], 'build')
        self.assertIn('--only-binary=:all: -- numpy pandas', call.kwargs['input'])
        self.assertNotIn('shell', call.kwargs)
        run.side_effect = None
        run.return_value = subprocess.CompletedProcess([], 1, '', 'No matching distribution')
        with self.assertRaisesRegex(RuntimeError, 'No matching distribution'):
            install_libraries('nonexistent')

    @patch('markdown_quiz.services.libraries.subprocess.run')
    def test_empty_packages_uses_default_without_install(self, run):
        self.assertEqual(install_libraries(''), ('python:3.13-alpine', ''))
        run.assert_not_called()

    def test_imports_validate_and_apply_to_generation_and_grading(self):
        for value in ('print(1)', 'import math; open("file")', 'from .local import x', 'import ???'):
            with self.assertRaises(ValueError): validate_imports(value)
        executions = []
        def execute(code, settings):
            executions.append(code)
            return RunResult(stdout='3.0\n', exit_code=0)
        q = coding_instance({'original_code': 'print(sqrt(9))'}, Settings(), 'easy',
                            runner=execute, imports='from math import sqrt')
        self.assertTrue(q['generated_code'].startswith('from math import sqrt\n'))
        self.assertTrue(grade_coding(q, q['solutions'], Settings(), runner=execute)['correct'])
        self.assertTrue(all(code.startswith('from math import sqrt\n') for code in executions))
