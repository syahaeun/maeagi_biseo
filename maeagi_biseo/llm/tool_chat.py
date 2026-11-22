"""Native function-call round trips for the three supported chat protocols."""
from copy import deepcopy
import json
from urllib.parse import quote
from maeagi_biseo.llm import client
from maeagi_biseo.resources import tr


def generate_with_tools(config, key, messages, system_prompt, executor):
    config = client.validate(config, key)
    try:
        limit = int(config.get('max_tokens', 4096))
        if not 64 <= limit <= 65536:
            raise ValueError()
    except (ValueError, TypeError):
        raise client.ApiError(tr('api.invalid_token_limit')) from None
    protocol, model, base = config['api_format'], config['model'], config['base_url']
    system_prompt += '\n\n' + executor.system_context()
    definitions = deepcopy(executor.definitions)
    if protocol == 'gemini':
        payload = {'systemInstruction': {'parts': [{'text': system_prompt}]},
                   'contents': [{'role': 'model' if message['role'] == 'assistant' else 'user', 'parts': [{'text': message['content']}]} for message in messages],
                   'generationConfig': {'maxOutputTokens': limit}, 'tools': [{'functionDeclarations': definitions}]}
        url = base + '/models/' + quote(model.removeprefix('models/'), safe='-._') + ':generateContent'
    elif protocol == 'claude':
        payload = {'model': model, 'system': system_prompt, 'messages': deepcopy(messages), 'max_tokens': limit,
                   'tools': [{'name': tool['name'], 'description': tool['description'], 'input_schema': tool['parameters']} for tool in definitions]}
        url = base + '/messages'
    else:
        payload = {'model': model, 'messages': [{'role': 'system', 'content': system_prompt}, *deepcopy(messages)],
                   'tools': [{'type': 'function', 'function': tool} for tool in definitions], 'stream': False}
        payload['max_completion_tokens' if config['provider'] == 'openai' else 'max_tokens'] = limit
        url = base + '/chat/completions'
    executed = 0
    for _ in range(6):
        result = client.json_request(url, client.auth_headers(config, key), key, payload, timeout=config['timeout_seconds'])
        try:
            if protocol == 'gemini':
                if result.get('promptFeedback', {}).get('blockReason'):
                    raise client.ApiError(tr('api.gemini_blocked', reason=result['promptFeedback']['blockReason']))
                candidate = result['candidates'][0]
                reason = candidate.get('finishReason')
                if reason not in (None, 'STOP', 'MAX_TOKENS'):
                    raise client.ApiError(tr('api.gemini_blocked', reason=reason))
                content = candidate['content']
                parts = content['parts']
                calls = [part['functionCall'] for part in parts if 'functionCall' in part]
                answer = ''.join(part.get('text', '') for part in parts if not part.get('thought'))
                if calls:
                    if reason == 'MAX_TOKENS':
                        raise client.ApiError(tr('api.token_exhausted'))
                    # Echo the entire model content: includes Gemini thoughtSignature.
                    payload['contents'].append(content)
            elif protocol == 'claude':
                content = result['content']
                if result.get('stop_reason') == 'max_tokens':
                    raise client.ApiError(tr('api.token_exhausted'))
                calls = [part for part in content if part.get('type') == 'tool_use']
                answer = ''.join(part.get('text', '') for part in content if part.get('type') == 'text')
                if calls:
                    payload['messages'].append({'role': 'assistant', 'content': content})
            else:
                choice = result['choices'][0]
                if choice.get('finish_reason') in ('length', 'content_filter'):
                    raise client.ApiError(tr('api.token_exhausted'))
                content = choice['message']
                calls = content.get('tool_calls') or []
                answer = content.get('content') or ''
                if calls:
                    payload['messages'].append(content)
            if not calls:
                if not isinstance(answer, str) or not answer.strip():
                    raise client.ApiError(tr('api.empty_response'))
                return answer.strip()
            if len(calls) + executed > 8:
                raise client.ApiError(tr('farming.tool_limit'))
            responses = []
            for call in calls:
                executed += 1
                name = call['name'] if protocol != 'openai' else call['function']['name']
                if protocol == 'gemini':
                    arguments = call.get('args', {})
                elif protocol == 'claude':
                    arguments = call.get('input', {})
                else:
                    try:
                        arguments = json.loads(call['function']['arguments'])
                    except (ValueError, TypeError):
                        arguments = None
                output = executor(name, arguments)
                if protocol == 'gemini':
                    response = {'name': name, 'response': output}
                    if call.get('id'):
                        response['id'] = call['id']
                    responses.append({'functionResponse': response})
                elif protocol == 'claude':
                    responses.append({'type': 'tool_result', 'tool_use_id': call['id'],
                                      'content': json.dumps(output, ensure_ascii=False), 'is_error': output.get('status') == 'error'})
                else:
                    payload['messages'].append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(output, ensure_ascii=False)})
            if protocol == 'gemini':
                payload['contents'].append({'role': 'user', 'parts': responses})
            elif protocol == 'claude':
                payload['messages'].append({'role': 'user', 'content': responses})
        except (KeyError, IndexError, TypeError, AttributeError):
            raise client.ApiError(tr('api.invalid_response')) from None
    raise client.ApiError(tr('farming.tool_limit'))
