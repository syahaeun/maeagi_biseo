"""Real Gemini function call against an isolated SQLite fixture, no screen capture."""
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
import unittest
from maeagi_biseo.core.farming import FarmingStore
from maeagi_biseo.core.farming_tools import FarmingTools
from maeagi_biseo.llm.client import generate_reply, list_models, choose_chat_model
from maeagi_biseo.llm.settings import provider_defaults, load_api_key
from tests.artifacts import artifact_path


class LiveFarmingToolTests(unittest.TestCase):
    def test_gemini_looks_up_persistent_records_with_native_function_call(self):
        key = load_api_key(provider='gemini')
        if not key:
            self.skipTest('No Gemini API key')
        config = provider_defaults('gemini')
        if not config['model']:
            config['model'] = choose_chat_model(list_models(config, key))
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            now = [datetime(2026, 11, 15, 9, tzinfo=timezone.utc)]
            store = FarmingStore(Path(temp) / 'records.sqlite3', clock=lambda: now[0])
            start = store.start({'meso': 1000000000, 'fragments': 100})
            now[0] += timedelta(hours=2)
            store.finish(start['session']['id'], {'meso': 1300000000, 'fragments': 137})
            tools = FarmingTools(store)
            answer = generate_reply(config, key, [{'role': 'user', 'content': '반드시 get_farming_records 도구로 저장된 전체 재획 기록을 조회하고 총 메소 증감과 조각 증감을 숫자로 알려줘.'}],
                                    'You are a desktop companion. Use the provided tools for stored data.', tools)
            self.assertTrue(any('get_farming_records' in cache_key for cache_key in tools.cache))
            self.assertTrue(answer.strip())
            import json
            artifact_path('farming_live_evidence.json').write_text(json.dumps({'provider': 'gemini', 'model': config['model'],
                'answer': answer, 'tool_results': list(tools.cache.values())}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
