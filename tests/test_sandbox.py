import io
import os
import subprocess
import unittest
from unittest.mock import Mock, patch

from markdown_quiz.config import Settings
from markdown_quiz.services.sandbox import run_in_sandbox


class SandboxPolicyTests(unittest.TestCase):
    @patch('markdown_quiz.services.sandbox.shutil.which', return_value='docker')
    @patch('markdown_quiz.services.sandbox.subprocess.run')
    @patch('markdown_quiz.services.sandbox.subprocess.Popen')
    def test_policy_and_cleanup(self, popen, run, which):
        run.side_effect = [subprocess.CompletedProcess([], 0, 'id', ''),
                           subprocess.CompletedProcess([], 0, 'exited 0', ''),
                           subprocess.CompletedProcess([], 0, '', '')]
        process = Mock(stdin=io.BytesIO(), stdout=io.BytesIO(b'2\n'), stderr=io.BytesIO())
        process.poll.return_value = 0
        popen.return_value = process
        self.assertEqual(run_in_sandbox('print(2)', Settings()).stdout, '2\n')
        args = run.call_args_list[0].args[0]
        for flag, value in [('--network', 'none'), ('--cap-drop', 'ALL'), ('--user', '10001:10001'),
                            ('--pids-limit', '32'), ('--memory', '128m'), ('--memory-swap', '128m')]:
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertIn('OPENBLAS_NUM_THREADS=1', args)
        self.assertIn('--read-only', args)
        self.assertNotIn('--privileged', args)
        self.assertNotIn('-v', args)
        if os.name == 'nt':
            self.assertEqual(popen.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
            self.assertTrue(all(call.kwargs['creationflags'] == subprocess.CREATE_NO_WINDOW for call in run.call_args_list))
        self.assertEqual(run.call_args_list[-1].args[0][1:3], ['rm', '--force'])

    @patch('markdown_quiz.services.sandbox.shutil.which', return_value='docker')
    @patch('markdown_quiz.services.sandbox.subprocess.run')
    @patch('markdown_quiz.services.sandbox.subprocess.Popen')
    def test_timeout_removes_container(self, popen, run, which):
        run.return_value = subprocess.CompletedProcess([], 0, '', '')
        process = Mock(stdin=io.BytesIO(), stdout=io.BytesIO(), stderr=io.BytesIO())
        process.poll.return_value = None
        popen.return_value = process
        result = run_in_sandbox('while True: pass', Settings(sandbox_timeout=0.01))
        self.assertTrue(result.timed_out)
        process.kill.assert_called_once()
        self.assertEqual(run.call_args_list[-1].args[0][1:3], ['rm', '--force'])


@unittest.skipUnless(os.getenv('RUN_DOCKER_TESTS') == '1', 'Requires running Docker and sandbox image')
class DockerIntegrationTests(unittest.TestCase):
    def test_real_execution_alternative_and_runtime_error(self):
        settings = Settings()
        self.assertEqual(run_in_sandbox('print(1 + 1)', settings).stdout, '2\n')
        result = run_in_sandbox('raise ValueError("bad")', settings)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('ValueError', result.stderr)

    def test_infinite_loop_and_output_cap(self):
        self.assertTrue(run_in_sandbox('while True: pass', Settings(sandbox_timeout=2)).timed_out)
        result = run_in_sandbox('print("x" * 100000)', Settings())
        self.assertTrue(result.output_limited)

    def test_nonroot_readonly_and_network_policy(self):
        result = run_in_sandbox('import os\nprint(os.getuid())\nopen("/blocked", "w")', Settings())
        self.assertEqual(result.stdout, '10001\n')
        self.assertFalse(result.successful)


if __name__ == '__main__':
    unittest.main()
