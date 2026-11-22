import copy
import unittest
from unittest.mock import Mock, patch
from maeagi_biseo.llm.client import generate_reply, ApiError
from maeagi_biseo.resources import DEFAULTS
from maeagi_biseo.llm.settings import provider_defaults


class ToolChatTests(unittest.TestCase):
    def executor(self):
        executor = Mock(return_value={'status': 'ok', 'meso_change': 300000000})
        executor.system_context.return_value = 'Use local farming records.'
        executor.definitions = [{'name': 'get_farming_records', 'description': 'Read records',
                                 'parameters': {'type': 'object', 'properties': {}}}]
        return executor

    def run_protocol(self, protocol):
        executor = self.executor()
        config = {**DEFAULTS, **provider_defaults(protocol), 'model': 'test-model'}
        if protocol == 'gemini':
            call = {'candidates': [{'content': {'role': 'model', 'parts': [{'functionCall': {'name': 'get_farming_records', 'args': {}}, 'thoughtSignature': 'keep-me'}]}, 'finishReason': 'STOP'}]}
            final = {'candidates': [{'content': {'role': 'model', 'parts': [{'text': '수익은 3억 메소입니다.'}]}, 'finishReason': 'STOP'}]}
        elif protocol == 'claude':
            call = {'content': [{'type': 'tool_use', 'id': 'use_1', 'name': 'get_farming_records', 'input': {}}], 'stop_reason': 'tool_use'}
            final = {'content': [{'type': 'text', 'text': '수익은 3억 메소입니다.'}], 'stop_reason': 'end_turn'}
        else:
            call = {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {'name': 'get_farming_records', 'arguments': '{}'}}]}, 'finish_reason': 'tool_calls'}]}
            final = {'choices': [{'message': {'role': 'assistant', 'content': '수익은 3억 메소입니다.'}, 'finish_reason': 'stop'}]}
        payloads = []
        def transport(url, headers, key, payload, timeout):
            payloads.append(copy.deepcopy(payload))
            return [call, final][len(payloads) - 1]
        with patch('maeagi_biseo.llm.client.json_request', side_effect=transport):
            answer = generate_reply(config, 'test-key', [{'role': 'user', 'content': '어제 수익은?'}], 'Persona', executor)
        self.assertEqual(answer, '수익은 3억 메소입니다.')
        executor.assert_called_once_with('get_farming_records', {})
        if protocol == 'gemini':
            self.assertEqual(payloads[1]['contents'][-2]['parts'][0]['thoughtSignature'], 'keep-me')
            self.assertEqual(payloads[1]['contents'][-1]['parts'][0]['functionResponse']['response']['meso_change'], 300000000)
        elif protocol == 'claude':
            self.assertEqual(payloads[1]['messages'][-1]['content'][0]['tool_use_id'], 'use_1')
        else:
            self.assertEqual(payloads[1]['messages'][-1]['tool_call_id'], 'call_1')
        self.assertIn('tools', payloads[0])

    def test_gemini_native_function_call_and_thought_signature(self):
        self.run_protocol('gemini')

    def test_openai_function_call_result_round_trip(self):
        self.run_protocol('openai')

    def test_claude_tool_use_result_round_trip(self):
        self.run_protocol('claude')

    def test_truncated_calls_are_not_executed(self):
        executor = self.executor()
        config = {**DEFAULTS, **provider_defaults('openai'), 'model': 'test'}
        truncated = {'choices': [{'message': {'tool_calls': []}, 'finish_reason': 'length'}]}
        with patch('maeagi_biseo.llm.client.json_request', return_value=truncated):
            with self.assertRaises(ApiError):
                generate_reply(config, 'key', [], 'Persona', executor)
        executor.assert_not_called()

    def test_call_loop_is_bounded(self):
        executor = self.executor()
        config = {**DEFAULTS, **provider_defaults('claude'), 'model': 'test'}
        response = {'content': [{'type': 'tool_use', 'id': 'id1', 'name': 'get_farming_records', 'input': {}}], 'stop_reason': 'tool_use'}
        with patch('maeagi_biseo.llm.client.json_request', return_value=response) as transport:
            with self.assertRaises(ApiError):
                generate_reply(config, 'key', [], 'Persona', executor)
        self.assertEqual(transport.call_count, 6)


if __name__ == '__main__':
    unittest.main()
