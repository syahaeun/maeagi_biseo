"""Allowlisted farming actions; no arbitrary code or model-supplied balances."""
from datetime import datetime
import json
import sqlite3
import uuid
from maeagi_biseo.core.farming import FarmingStore, farming_root, KST
from maeagi_biseo.resources import read_json
from maeagi_biseo.core.amounts import with_amount_text


def capture_options(store):
    options = {}
    for kind in ('meso', 'sol_erda'):
        try:
            region = json.loads(str(store.value('region_' + kind, 'null')))
        except ValueError:
            region = None
        options[kind] = {'region': region if isinstance(region, dict) else None,
                         'method': 'local', 'config': {}, 'key': ''}
    return options


class BalanceCapture:
    def __init__(self, options, before=None, after=None, output=None, capture=None):
        self.options = options
        self.before, self.after = before, after
        self.output = output
        self.capture = capture

    def __call__(self):
        from maeagi_biseo.core.capture_region import capture_manual
        capture = self.capture or capture_manual
        if self.before:
            self.before()
        try:
            snapshot = {'captured_at': datetime.now(KST).isoformat(), 'evidence': {}}
            output = self.output or farming_root() / 'captures' / uuid.uuid4().hex
            for kind, field in (('meso', 'meso'), ('sol_erda', 'fragments')):
                option = self.options[kind]
                folder, result = capture(kind, option['region'], 'local', {}, '', output / kind)
                reading = result.get('reading', {})
                if reading.get('status') != 'ok' or type(reading.get('value')) is not int or reading['value'] < 0:
                    label = '메소' if kind == 'meso' else '솔 에르다 조각'
                    raise ValueError(f'{label} 판독이 확정되지 않아 기록하지 않았습니다. 게임 UI와 인식 설정을 확인해주세요.')
                snapshot[field] = reading['value']
                snapshot['evidence'][kind] = {'folder': str(folder), 'method': 'local', 'mode': result.get('mode')}
            return snapshot
        finally:
            if self.after:
                self.after()


class FarmingTools:
    def __init__(self, store=None, reader=None, character_id='', report=None, confirm_start=None):
        self.store = store or FarmingStore()
        self.reader = reader
        self.character_id = character_id
        self.report = report or (lambda event: None)
        self.cache = {}
        self.mutated = None
        self.snapshot = None
        self.confirm_start = confirm_start
        self.definitions = read_json('farming_tools.json')['tools']

    def system_context(self):
        content = read_json('farming_tools.json')
        return content['instructions'] + '\n' + content['confirmation_instructions'] + '\n현재 한국 시각: ' + datetime.now(KST).isoformat()

    def read(self):
        if self.snapshot is None:
            if self.reader is None:
                raise ValueError('화면 판독 기능이 연결되지 않았습니다.')
            self.snapshot = self.reader()
            self.store.validate_snapshot(self.snapshot)
        return self.snapshot

    def start_confirmed(self, note):
        for _ in range(3):
            snapshot = self.read()
            if self.confirm_start is None:
                return {'status': 'confirmation_required', 'meso': snapshot['meso'], 'fragments': snapshot['fragments']}
            choice = self.confirm_start(dict(snapshot))
            if choice == 'start':
                return self.store.start(snapshot, self.character_id, note)
            if choice != 'retry':
                return {'status': 'start_cancelled'}
            self.snapshot = None
        return {'status': 'error', 'error': '재판독 횟수를 초과했습니다. 다시 시작을 요청해주세요.'}

    def __call__(self, name, arguments):
        definitions = {definition['name']: definition for definition in self.definitions}
        if name not in definitions or not isinstance(arguments, dict):
            return {'status': 'error', 'error': '지원하지 않는 도구 호출입니다.'}
        allowed = definitions[name]['parameters']['properties']
        if set(arguments) - set(allowed):
            return {'status': 'error', 'error': '지원하지 않는 도구 인자입니다.'}
        cache_key = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)
        if cache_key in self.cache:
            return self.cache[cache_key]
        try:
            for key in ('since', 'until', 'note'):
                if key in arguments and not isinstance(arguments[key], str):
                    raise ValueError('날짜와 메모는 문자열이어야 합니다.')
            if len(arguments.get('note', '')) > 300:
                raise ValueError('메모는 300자 이내로 입력해주세요.')
            mutation = name in ('start_farming_session', 'finish_farming_session', 'cancel_farming_session')
            if mutation and self.mutated:
                raise ValueError('이 메시지에서는 이미 재획 상태를 변경했습니다. 다음 작업은 새 메시지로 요청해주세요.')
            self.report({'event': 'running', 'tool': name})
            if name == 'read_farming_balances':
                snapshot = self.read()
                result = {'status': 'ok', 'meso': snapshot['meso'], 'fragments': snapshot['fragments'], 'captured_at': snapshot.get('captured_at')}
            elif name == 'get_farming_records':
                result = self.store.query(**arguments)
            else:
                active = self.store.active()
                if name == 'start_farming_session':
                    result = {'status': 'already_active', 'session': active} if active else self.start_confirmed(arguments.get('note', ''))
                elif not active:
                    result = {'status': 'no_active_session'}
                elif name == 'finish_farming_session':
                    result = self.store.finish(active['id'], self.read())
                else:
                    result = self.store.cancel(active['id'])
                if result['status'] in ('started', 'completed', 'cancelled'):
                    self.mutated = name
        except ImportError:
            result = {'status': 'error', 'error': '화면 판독 의존성이 없습니다. requirements.txt 설치 상태를 확인해주세요.'}
        except (ValueError, OSError, sqlite3.Error) as exc:
            result = {'status': 'error', 'error': str(exc)}
        result = with_amount_text(result)
        self.cache[cache_key] = result
        self.report({'event': 'result', 'tool': name, 'result': result})
        return result
