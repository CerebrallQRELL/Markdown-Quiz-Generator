"""Local HTTP bridge. All study logic stays in the existing Python modules.

One lock serializes database mutations. Question keys stay on the server, with
bounded, persisted sessions and idempotent answer submission within a session.
"""
import argparse
from copy import deepcopy
from dataclasses import replace
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path, PurePosixPath
import threading
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener, Request

from .backend import QuizBackend
from .quiz.engine import QuizEngine
from .quiz.selection import eligible, filter_questions
from .config import load_settings, save_settings
from .notes.parser import digest
from .services.sandbox import check_sandbox_available, run_in_sandbox
from .services.libraries import install_libraries
from .notes.storage import read_json

VERSION = '1.3.9'
log = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def string(data, key, default=None, limit=10000):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value) > limit:
        raise APIError(f'Invalid {key}.')
    return value


class QuizAPI:
    def __init__(self, backend, managed=False):
        self.backend = backend
        self.managed = managed
        self.vaults = {}
        self.lock = threading.RLock()
        self.engine = QuizEngine(backend)
        self.health_cache = None
        self.health_at = 0

    def connect_vault(self, data):
        if self.managed:
            key = string(data, 'vault_key', limit=200)
            if not key.strip():
                raise APIError('A stable vault key is required.')
            identity = digest(key)
            root = Path(self.backend.settings.data_path) / 'notes' / identity
            root.mkdir(parents=True, exist_ok=True)
        else:
            root = Path(string(data, 'vault_path')).expanduser()
            if not root.is_absolute() or not root.is_dir():
                raise APIError('The active Obsidian vault must be an existing absolute folder.')
            root = root.resolve()
            identity = digest(os.path.normcase(str(root)))
        with self.lock:
            if identity not in self.vaults:
                data_path = Path(self.backend.settings.data_path) / 'vaults' / identity
                saved = read_json(data_path / 'settings.json', dict)
                settings = replace(self.backend.settings, vault_path=str(root), data_path=str(data_path),
                    ollama_model=saved.get('ollama_model', self.backend.settings.ollama_model),
                    sandbox_image=saved.get('sandbox_image', self.backend.settings.sandbox_image),
                    python_libraries=saved.get('python_libraries', self.backend.settings.python_libraries))
                self.vaults[identity] = QuizAPI(QuizBackend(settings), managed=self.managed)
        return dict(vault_id=identity, vault_path=str(root))

    @property
    def sessions(self):
        return self.engine.sessions

    def eligible(self):
        return eligible(self.backend)

    def path(self, value):
        if not isinstance(value, str) or not value or '\\' in value or ':' in value:
            raise APIError('Use a vault-relative Markdown path.')
        relative = PurePosixPath(value)
        root = Path(self.backend.settings.vault_path).resolve()
        if self.managed and any(part.startswith('.') for part in relative.parts):
            raise APIError('Hidden folders cannot be uploaded.')
        if relative.is_absolute() or '..' in relative.parts or relative.suffix.lower() != '.md':
            raise APIError('Use a vault-relative Markdown path.')
        if not (root / value).resolve().is_relative_to(root):
            raise APIError('Source path is outside the configured vault.')
        return relative.as_posix()

    def health(self):
        if self.health_cache and time.monotonic() - self.health_at < 30:
            return self.health_cache
        settings = self.backend.settings
        ollama = sandbox = False
        try:
            with build_opener(ProxyHandler({})).open(settings.ollama_url.rstrip('/') + '/api/tags', timeout=3) as response:
                models = json.loads(response.read(1_000_000)).get('models', [])
            model = settings.ollama_model
            ollama = any(row.get('name') in (model, model + ':latest') for row in models)
        except (OSError, ValueError, AttributeError):
            pass
        try:
            check_sandbox_available(settings)
            sandbox = True
        except RuntimeError:
            pass
        self.health_cache = dict(status='ok', version=VERSION, api_version=1, capabilities=['shared-sessions-v2', 'managed-vault-sync', 'local-restart', 'stdin-v1', 'skip-no-output', 'quiz-model-selection', 'session-models', 'python-libraries'], service='markdown-quiz-generator', managed=self.managed, ollama=ollama, sandbox=sandbox)
        self.health_at = time.monotonic()
        return self.health_cache

    def stats(self):
        return self.engine.statistics(self.eligible())

    def matching(self, filters):
        try:
            return filter_questions(self.backend, filters)
        except ValueError as exc:
            raise APIError(str(exc)) from exc

    def quiz(self, path, data):
        """Old endpoints are adapters into the same session engine."""
        payload = deepcopy(data)
        api_key = string(payload, 'api_key', '', limit=4096)
        key_url = string(payload, 'api_key_url', '', limit=2000)
        payload.pop('api_key', None)
        payload.pop('api_key_url', None)
        if payload.get('provider', 'ollama') not in ('ollama', 'api'):
            raise APIError('Choose Ollama or API.')
        if payload.get('provider') == 'api':
            from .services.cloud import validate_endpoint
            try:
                validate_endpoint(string(payload, 'api_url', limit=2000))
            except ValueError as exc:
                raise APIError(str(exc)) from exc
            if not string(payload, 'api_model', limit=200).strip():
                raise APIError('Enter an API model name.')
        legacy = path.startswith('/quiz/term/') or path.startswith('/quiz/code/')
        action = path.rsplit('/', 1)[-1]
        code = path.startswith('/quiz/code/')
        if payload.get('source_file'):
            payload['source_file'] = self.path(payload['source_file'])
        if action in ('start', 'get'):
            self.backend.rescan(regenerate_changed=False)
        if path.startswith('/quiz/term/'):
            payload['quiz_type'] = 'multiple-choice'
        if code:
            payload['quiz_type'] = 'coding'
            if action == 'get':
                action = 'start'
                payload.update(length=1, direction='random')
            elif not payload.get('session_id'):
                session = next((s for s in self.sessions.values() if s.get('question') and
                    s['question']['question_id'] == payload.get('question_id')), None)
                if not session:
                    raise APIError('Question expired. Start again.', 409)
                payload['session_id'] = session['session_id']
        if legacy and action == 'answer':
            session = self.engine.get_session(payload)
            q = session['question']
            if q['type'] == 'multiple-choice' and 'answer_id' not in payload:
                index = payload.get('index')
                if type(index) is not int or not 0 <= index < len(q['answers']):
                    raise APIError('Choose an answer from 0 to 3.')
                payload['answer_id'] = q['answers'][index]['id']
            if q['type'] == 'coding' and 'answers' not in payload:
                if len(q['blanks']) != 1:
                    raise APIError('Update the plugin to answer multiple blanks.')
                payload['answers'] = {q['blanks'][0]['id']: string(payload, 'answer')}
            payload.setdefault('request_id', digest(json.dumps(payload, sort_keys=True)))
        if action in ('start', 'regenerate') and 'model' in payload:
            model = string(payload, 'model', limit=200).strip()
            if not model:
                raise APIError('Choose an Ollama model.')
            self.backend.settings.ollama_model = model
            save_settings(self.backend.settings)
            self.health_cache = None
        try:
            self.backend.settings.api_key = api_key
            self.backend.settings.api_key_url = key_url
            response = self.engine.operate(action, payload)
        except ValueError as exc:
            raise APIError(str(exc), 409 if 'changed' in str(exc) else 400) from exc
        finally:
            self.backend.settings.api_key = ''
            self.backend.settings.api_key_url = ''
        if legacy and action == 'answer':
            return response['result']
        if code and action in ('start', 'regenerate'):
            return dict(response['question'], session_id=response['session_id'])
        return response

    def reset_service(self, data):
        target = string(data, 'target', limit=20)
        if target == 'server':
            self.backend = QuizBackend(self.backend.settings)
            self.engine = QuizEngine(self.backend)
            message = 'Server vault state reloaded. Study progress preserved.'
        elif target == 'sandbox':
            image, _ = install_libraries(self.backend.settings.python_libraries)
            settings = replace(self.backend.settings, sandbox_image=image)
            check_sandbox_available(settings)
            result = run_in_sandbox('print("sandbox-ready")', settings)
            if not result.successful or result.stdout.strip() != 'sandbox-ready':
                raise APIError('Sandbox test failed. Check Docker and retry.', 503)
            self.backend.settings.sandbox_image = image
            save_settings(self.backend.settings)
            message = 'Sandbox reset and fresh execution verified.'
        elif target == 'ollama':
            model = string(data, 'model', self.backend.settings.ollama_model, limit=200)
            request = Request(self.backend.settings.ollama_url.rstrip('/') + '/api/generate',
                data=json.dumps(dict(model=model, keep_alive=0, stream=False)).encode(),
                headers={'Content-Type': 'application/json'})
            with build_opener(ProxyHandler({})).open(request, timeout=30) as response:
                response.read(100000)
            message = 'Ollama model unloaded. It will reload on the next generation.'
        else:
            raise APIError('Unknown reset target.')
        self.health_cache = None
        return dict(ok=True, message=message)

    def sync_manifest(self, data):
        if not self.managed:
            raise APIError('Uploads require managed server mode.', 403)
        files = data.get('files')
        if not isinstance(files, list) or len(files) > 20000:
            raise APIError('Invalid Markdown manifest.')
        keep = {self.path(value) for value in files}
        root = Path(self.backend.settings.vault_path)
        for note in root.rglob('*'):
            if note.is_file() and note.suffix.lower() == '.md' and note.relative_to(root).as_posix() not in keep:
                note.unlink()
        self.backend.rescan(regenerate_changed=False)
        return dict(ok=True)

    def sync_file(self, data):
        source = self.path(data.get('source_file'))
        old = self.path(data['old_path']) if data.get('old_path') else None
        if old:
            if old == source:
                raise APIError('Rename source and destination must differ.')
        if self.managed:
            destination = Path(self.backend.settings.vault_path) / source
            content = data.get('content')
            if content is None:
                destination.unlink(missing_ok=True)
            else:
                if not isinstance(content, str) or len(content.encode('utf-8')) > 800000:
                    raise APIError('Note exceeds the 800 KB upload limit.')
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding='utf-8')
            if old:
                (Path(self.backend.settings.vault_path) / old).unlink(missing_ok=True)
        if old:
            root = Path(self.backend.settings.vault_path).resolve()
            if (root / old).exists() or not (root / source).is_file():
                raise APIError('Rename has not reached the backend vault yet. Retry syncing.', 409)
            self.backend.rename_source(old, source)
        else:
            self.backend.rescan([source], regenerate_changed=False)
        return dict(ok=True)

    def dispatch(self, method, path, data):
        # Health checks do not read or mutate quiz collections.
        if method == 'GET' and path == '/health':
            return self.health()
        with self.lock:
            if method == 'GET' and path == '/tags':
                return dict(tags=self.engine.catalog({})['tags'])
            if method == 'GET' and path == '/stats':
                return self.stats()
            if method == 'GET' and path == '/models':
                with build_opener(ProxyHandler({})).open(self.backend.settings.ollama_url.rstrip('/') + '/api/tags', timeout=5) as response:
                    models = json.loads(response.read(1_000_000)).get('models', [])
                return dict(models=[m['name'] for m in models if isinstance(m.get('name'), str)])
            if method == 'POST' and path == '/model':
                self.backend.settings.ollama_model = string(data, 'model', limit=200)
                save_settings(self.backend.settings)
                self.health_cache = None
                return dict(ok=True)
            if method == 'GET' and path == '/libraries':
                return dict(packages=self.backend.settings.python_libraries)
            if method == 'POST' and path == '/libraries':
                try:
                    image, packages = install_libraries(string(data, 'packages', limit=2000))
                except ValueError as exc:
                    raise APIError(str(exc)) from exc
                except RuntimeError as exc:
                    raise APIError(str(exc), 503) from exc
                self.backend.settings.sandbox_image = image
                self.backend.settings.python_libraries = packages
                save_settings(self.backend.settings)
                self.health_cache = None
                return dict(packages=packages)
            if method != 'POST':
                raise APIError('Endpoint not found.', 404)
            if path == '/admin/reset':
                return self.reset_service(data)
            if path == '/sync/manifest':
                return self.sync_manifest(data)
            if path == '/sync':
                errors = self.backend.rescan(regenerate_changed=False)
                return dict(ok=True, skipped=len(errors), stats=self.stats())
            if path == '/sync/file':
                return self.sync_file(data)
            if path.startswith('/quiz/'):
                return self.quiz(path, data)
            raise APIError('Endpoint not found.', 404)


def make_handler(api, token=''):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def do_GET(self):
            self.respond('GET')

        def do_POST(self):
            self.respond('POST')

        def respond(self, method):
            status = 200
            try:
                if token and not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                    raise APIError('Backend authentication failed.', 401)
                if self.headers.get('Origin') not in (None, 'app://obsidian.md'):
                    raise APIError('Browser origin is not allowed.', 403)
                if not token:
                    host = self.headers.get('Host', '').split(':')[0]
                    if host not in ('127.0.0.1', 'localhost'):
                        raise APIError('Only local requests are allowed.', 403)
                data = {}
                if method == 'POST':
                    if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                        raise APIError('Expected application/json.', 415)
                    try:
                        length = int(self.headers.get('Content-Length', '0'))
                    except ValueError:
                        raise APIError('Invalid request length.')
                    if not 0 < length <= 1_000_000:
                        raise APIError('Request is empty or too large.', 413)
                    try:
                        data = json.loads(self.rfile.read(length))
                    except (ValueError, UnicodeError):
                        raise APIError('Invalid JSON.')
                    if not isinstance(data, dict):
                        raise APIError('Expected a JSON object.')
                route = urlsplit(self.path).path
                if method == 'POST' and route == '/vault/connect':
                    result = api.connect_vault(data)
                elif method == 'POST' and route == '/admin/restart':
                    if api.managed or self.client_address[0] not in ('127.0.0.1', '::1'):
                        raise APIError('Restart is local-only.', 403)
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    result = dict(ok=True)
                else:
                    vault_id = self.headers.get('X-Quiz-Vault')
                    target = api.vaults.get(vault_id) if vault_id else api
                    if target is None:
                        raise APIError('Vault connection expired. Reconnect the plugin.', 409)
                    if api.managed and not vault_id and route != '/health':
                        raise APIError('Connect a managed vault first.', 403)
                    result = target.dispatch(method, route, data)
            except APIError as exc:
                status, result = exc.status, dict(error=str(exc))
            except (ValueError, RuntimeError, OSError) as exc:
                log.exception('Backend operation failed')
                text = str(exc)
                if 'Docker' in text or 'sandbox' in text.lower():
                    message = 'Sandbox unavailable. Start Docker Desktop and prepare the Python sandbox image.'
                elif 'Ollama' in text or 'wrong answers' in text:
                    message = 'Ollama could not generate a question. Check the local model and retry.'
                else:
                    message = 'The operation could not finish. Retry or check the backend terminal.'
                status, result = 503, dict(error=message)
            except Exception:
                log.exception('Unexpected API failure')
                status, result = 500, dict(error='Backend error. Check the backend terminal.')
            payload = json.dumps(result, ensure_ascii=False).encode('utf-8')
            try:
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, fmt, *args):
            log.info(fmt, *args)
    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description='Markdown Quiz HTTP backend for Obsidian')
    parser.add_argument('--vault', help='The same vault opened in Obsidian')
    parser.add_argument('--data', help='Separate quiz JSON directory')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--managed', action='store_true', help='Accept uploaded notes, never client filesystem paths')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    if args.data:
        os.environ['DATA_PATH'] = args.data
    token = os.getenv('QUIZ_API_TOKEN', '')
    if args.host not in ('127.0.0.1', 'localhost') and not token:
        parser.error('Non-loopback binding requires QUIZ_API_TOKEN.')
    settings = load_settings()
    if args.vault:
        settings.vault_path = args.vault
    if args.managed:
        if not token:
            parser.error('Managed mode requires QUIZ_API_TOKEN.')
        settings.vault_path = str(Path(settings.data_path) / 'empty')
        Path(settings.vault_path).mkdir(parents=True, exist_ok=True)
    if not Path(settings.vault_path).is_dir():
        parser.error('The configured Markdown vault does not exist.')
    api = QuizAPI(QuizBackend(settings), managed=args.managed)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(api, token))
    print(f'Quiz backend {VERSION}: http://{args.host}:{args.port}', flush=True)
    print(f'Vault: {Path(settings.vault_path).resolve()}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
