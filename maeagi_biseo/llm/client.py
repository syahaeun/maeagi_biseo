"""Text-only Gemini, OpenAI-compatible and Claude REST adapters (no Qt dependency)."""
import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse, quote, urlencode

from maeagi_biseo.resources import tr
from maeagi_biseo.llm.settings import normalize_config, PROVIDERS


class ApiError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate(config, key, need_model=True):
    config = normalize_config(config)
    if '\n' in key or '\r' in key:
        raise ApiError(tr('api.invalid_key'))
    base = config['base_url'].strip().rstrip('/')
    parsed = urlparse(base)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ApiError(tr('api.invalid_url'))
    local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
    if parsed.scheme != 'https' and not local:
        raise ApiError(tr('api.https_required'))
    if config['provider'] in ('gemini', 'openai', 'claude') and not key.strip():
        raise ApiError(tr('api.key_required'))
    if config['api_format'] not in ('gemini', 'openai', 'claude'):
        raise ApiError(tr('api.unsupported_format'))
    if need_model and not config['model'].strip():
        raise ApiError(tr('api.model_required'))
    try:
        timeout = int(config.get('timeout_seconds', 45))
        if not 5 <= timeout <= 180:
            raise ValueError()
    except (TypeError, ValueError):
        raise ApiError(tr('api.invalid_timeout')) from None
    config['timeout_seconds'] = timeout
    config['base_url'] = base
    return config


def auth_headers(config, key):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if config['api_format'] == 'gemini':
        if key.strip():
            headers['x-goog-api-key'] = key.strip()
    elif config['api_format'] == 'claude':
        headers['anthropic-version'] = '2023-06-01'
        if key.strip():
            headers['x-api-key'] = key.strip()
    elif key.strip():
        headers['Authorization'] = 'Bearer ' + key.strip()
    return headers


def clean_detail(detail, key):
    text = str(detail)
    if key:
        text = text.replace(key, '[REDACTED]').replace(quote(key, safe=''), '[REDACTED]')
    text = re.sub(r'(?i)([?&]key=)[^\s&"\']+', r'\1[REDACTED]', text)
    return text[:800]


def json_request(url, headers, key, payload=None, timeout=45):
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method='POST' if data is not None else 'GET')
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            result = json.loads(response.read())
        if not isinstance(result, dict):
            raise ApiError(tr('api.invalid_response'))
        return result
    except urllib.error.HTTPError as exc:
        hints = {400: 'api.bad_request', 401: 'api.unauthorized', 403: 'api.forbidden',
                 404: 'api.not_found', 429: 'api.rate_limit', 502: 'api.busy',
                 503: 'api.busy', 504: 'api.busy'}
        detail = ''
        try:
            body = json.loads(exc.read(65536))
            error = body.get('error', {})
            if isinstance(error, dict):
                detail = error.get('message', '')
        except (ValueError, OSError, AttributeError):
            pass
        message = tr('api.http_error', code=exc.code) + tr(hints.get(exc.code, 'api.server_error'))
        if detail:
            message += tr('api.provider_detail', detail=clean_detail(detail, key))
        raise ApiError(message) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ApiError(tr('api.connection_failed', timeout=timeout)) from None
    except (json.JSONDecodeError, UnicodeError):
        raise ApiError(tr('api.invalid_json')) from None


def generate_reply(config, key, messages, system_prompt, tool_executor=None):
    if tool_executor is not None:
        from maeagi_biseo.llm.tool_chat import generate_with_tools
        return generate_with_tools(config, key, messages, system_prompt, tool_executor)
    config = validate(config, key)
    protocol = config['api_format']
    model = config['model'].strip()
    base = config['base_url']
    try:
        limit = int(config.get('max_tokens', 4096))
        if not 64 <= limit <= 65536:
            raise ValueError()
    except (ValueError, TypeError):
        raise ApiError(tr('api.invalid_token_limit')) from None
    if protocol == 'gemini':
        model = model.removeprefix('models/')
        payload = {'systemInstruction': {'parts': [{'text': system_prompt}]},
                   'contents': [{'role': 'model' if message['role'] == 'assistant' else 'user',
                                 'parts': [{'text': message['content']}]} for message in messages],
                   'generationConfig': {'maxOutputTokens': limit}}
        url = base + '/models/' + quote(model, safe='-._') + ':generateContent'
    elif protocol == 'claude':
        payload = dict(model=model, system=system_prompt, messages=messages, max_tokens=limit, stream=False)
        url = base + '/messages'
    else:
        payload = dict(model=model, messages=[dict(role='system', content=system_prompt), *messages], stream=False)
        # Compatible servers and OpenAI use different parameter names for output limits.
        payload['max_completion_tokens' if config['provider'] == 'openai' else 'max_tokens'] = limit
        url = base + '/chat/completions'
    result = json_request(url, auth_headers(config, key), key, payload, timeout=config['timeout_seconds'])
    try:
        if protocol == 'gemini':
            if result.get('promptFeedback', {}).get('blockReason'):
                raise ApiError(tr('api.gemini_blocked', reason=result['promptFeedback']['blockReason']))
            candidate = result.get('candidates', [{}])[0]
            reason = candidate.get('finishReason', '')
            if reason in ('SAFETY', 'RECITATION', 'BLOCKLIST', 'PROHIBITED_CONTENT', 'SPII'):
                raise ApiError(tr('api.gemini_blocked', reason=reason))
            answer = ''.join(part['text'] for part in candidate.get('content', {}).get('parts', [])
                             if isinstance(part.get('text'), str) and not part.get('thought', False))
            if not answer.strip() and reason == 'MAX_TOKENS':
                raise ApiError(tr('api.token_exhausted'))
        elif protocol == 'claude':
            answer = ''.join(part['text'] for part in result.get('content', [])
                             if part.get('type') == 'text' and isinstance(part.get('text'), str))
        else:
            answer = result['choices'][0]['message']['content']
        if not isinstance(answer, str) or not answer.strip():
            raise ApiError(tr('api.empty_response'))
        return answer.strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise ApiError(tr('api.invalid_response')) from None


def list_models(config, key):
    config = validate(config, key, need_model=False)
    protocol = config['api_format']
    models = []
    token = None
    seen = set()
    for _ in range(10):
        params = {}
        if protocol == 'gemini':
            params['pageSize'] = 1000
            if token:
                params['pageToken'] = token
        elif protocol == 'claude' and token:
            params['after_id'] = token
        url = config['base_url'] + '/models' + ('?' + urlencode(params) if params else '')
        result = json_request(url, auth_headers(config, key), key, timeout=config['timeout_seconds'])
        try:
            items = result['models' if protocol == 'gemini' else 'data']
            for item in items:
                if protocol == 'gemini':
                    name = item['name'].removeprefix('models/')
                    excluded = PROVIDERS['gemini']['non_chat_model_fragments']
                    if ('generateContent' in item.get('supportedGenerationMethods', [])
                            and not any(fragment in name.casefold() for fragment in excluded)):
                        models.append(name)
                else:
                    models.append(item['id'])
            token = result.get('nextPageToken') if protocol == 'gemini' else (
                result.get('last_id') if protocol == 'claude' and result.get('has_more') else None)
        except (KeyError, TypeError, AttributeError):
            raise ApiError(tr('api.invalid_response')) from None
        if not token:
            break
        if not isinstance(token, str):
            raise ApiError(tr('api.invalid_response'))
        if token in seen:
            raise ApiError(tr('api.model_pagination'))
        seen.add(token)
    else:
        raise ApiError(tr('api.model_pagination'))
    models = sorted(set(item for item in models if isinstance(item, str) and item))
    if not models:
        raise ApiError(tr('api.no_models'))
    return models


def choose_chat_model(models):
    """Prefer the server's Flash alias, then newer stable Flash versions."""
    if 'gemini-flash-latest' in models:
        return 'gemini-flash-latest'

    def rank(name):
        version = re.match(r'gemini-(\d+)(?:\.(\d+))?', name)
        major, minor = (int(version[1]), int(version[2] or 0)) if version else (0, 0)
        return ('flash' not in name, 'preview' in name, not name.startswith('gemini-'),
                -major, -minor, 'lite' in name, name)

    return min(models, key=rank)
