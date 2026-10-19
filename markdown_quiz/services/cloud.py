"""Request-scoped OpenAI-compatible generation. Credentials are never persisted."""
import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_endpoint(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment):
        raise ValueError('API base URL must use HTTPS without credentials, query, or fragment.')
    return url.rstrip('/')


def request_json(settings, prompt, schema):
    key = getattr(settings, 'api_key', '')
    if not key:
        raise ValueError('Enter an API key in settings or the quiz API controls.')
    model = getattr(settings, 'api_model', '').strip()
    if not model:
        raise ValueError('Enter an API model name.')
    endpoint = validate_endpoint(settings.api_url)
    if endpoint != getattr(settings, 'api_key_url', '').rstrip('/'):
        raise ValueError('This quiz uses a different API provider. Restore its API URL and key, or start a new quiz.')
    payload = dict(model=model, messages=[
        dict(role='system', content='Return only a JSON object matching this schema: ' + json.dumps(schema)),
        dict(role='user', content=prompt)], response_format={'type': 'json_object'})
    request = Request(endpoint + '/chat/completions', data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    try:
        with build_opener(NoRedirect()).open(request, timeout=settings.ollama_timeout) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('API response exceeds the size limit.')
        envelope = json.loads(raw)
        result = json.loads(envelope['choices'][0]['message']['content'])
        if not isinstance(result, dict):
            raise ValueError('Expected a JSON object.')
        return result
    except HTTPError as exc:
        # Provider bodies can echo credentials or prompts; never surface them.
        raise RuntimeError(f'API request failed (HTTP {exc.code}). Check your key, model, quota, and API URL.') from None
    except (URLError, OSError, TimeoutError):
        raise RuntimeError('API unavailable or timed out. Check the provider and retry.') from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise ValueError('API returned invalid JSON content. Use a model supporting JSON output.') from None
