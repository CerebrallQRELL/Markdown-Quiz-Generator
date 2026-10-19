"""JSON generation through local Ollama or the configured cloud provider."""
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener


def request_json(settings, prompt, schema):
    if getattr(settings, 'generation_provider', 'ollama') == 'api':
        from .cloud import request_json as cloud_request
        return cloud_request(settings, prompt, schema)
    payload = dict(model=settings.ollama_model, prompt=prompt, stream=False,
                   format=schema, think=False, options={"num_predict": 2048})
    request = Request(settings.ollama_url.rstrip('/') + '/api/generate',
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    logging.getLogger(__name__).info('Ollama request: %s', settings.ollama_model)
    try:
        # Keep local requests off environment-configured HTTP proxies.
        with build_opener(ProxyHandler({})).open(request, timeout=settings.ollama_timeout) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('Ollama response is too large.')
        envelope = json.loads(raw)
        if not isinstance(envelope, dict) or not isinstance(envelope.get('response'), str):
            raise ValueError('Ollama response envelope is invalid.')
        result = json.loads(envelope['response'])
        if not isinstance(result, dict):
            raise ValueError('Ollama must return a JSON object.')
        return result
    except HTTPError as exc:
        try:
            error = json.loads(exc.read(4096))
            detail = error.get('error', '') if isinstance(error, dict) else ''
        except (ValueError, OSError):
            detail = ''
        hint = f' Check the installed model: ollama pull {settings.ollama_model}' if exc.code == 404 else ''
        raise RuntimeError(f'Ollama HTTP {exc.code}: {str(detail)[:500] or exc.reason}.{hint}') from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise RuntimeError('Ollama unavailable or timed out. Check OLLAMA_URL, OLLAMA_MODEL, and the local server.') from exc
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f'Invalid Ollama JSON: {exc}') from exc
