"""Exercise the actual server image with ephemeral notes and Docker execution."""
import json
import secrets
import subprocess
import time
import uuid
from urllib.request import Request, urlopen

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quiz_backend.services.sandbox import hidden_process_options

name = 'markdown-quiz-server-test-' + uuid.uuid4().hex
secret = secrets.token_hex(32)

def docker(*args):
    return subprocess.run(['docker', *args], capture_output=True, text=True, check=True, timeout=120, **hidden_process_options()).stdout.strip()

try:
    docker('run', '-d', '--name', name, '-p', '127.0.0.1::8765', '-e', 'QUIZ_API_TOKEN=' + secret,
           '-e', 'DATA_PATH=/data', '-v', '/var/run/docker.sock:/var/run/docker.sock', 'markdown-quiz-server:1.3.0')
    address = docker('port', name, '8765/tcp').splitlines()[0]
    vault_id = ''
    def call(path, body=None):
        request = Request('http://' + address + path, data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + secret, 'X-Quiz-Vault': vault_id})
        with urlopen(request, timeout=45) as response: return json.load(response)
    for attempt in range(30):
        try:
            health = call('/health'); break
        except OSError: time.sleep(.5)
    else: raise RuntimeError('Server did not start')
    assert health['sandbox'], health
    vault_id = call('/vault/connect', {'vault_key': 'smoke-only'})['vault_id']
    content = '#quiz\nOne:: First\nTwo:: Second\nThree:: Third\nFour:: Fourth\n```python\nprint(1 + 2)\n```'
    call('/sync/file', {'source_file': 'Active vault.md', 'content': content})
    call('/sync/manifest', {'files': ['Active vault.md']})
    assert call('/quiz/catalog', {'quiz_type': 'multiple-choice'})['count'] == 4
    mc = call('/quiz/start', {'quiz_type': 'multiple-choice', 'length': 1, 'direction': 'reverse'})
    assert mc['question']['type'] == 'multiple-choice'
    code = call('/quiz/start', {'quiz_type': 'coding', 'length': 1, 'difficulty': 'easy'})
    assert code['question']['expected_output'] == '3\n'
    assert call('/quiz/resume', {'session_id': code['session_id']})['question'] == code['question']
    print('Server container passed: authentication, uploaded active-vault notes, MC, coding output, real Docker sandbox, resume.')
finally:
    subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30, **hidden_process_options())
