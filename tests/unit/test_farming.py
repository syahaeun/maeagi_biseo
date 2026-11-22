import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock
from maeagi_biseo.core.farming import FarmingStore
from maeagi_biseo.core.farming_tools import FarmingTools, BalanceCapture
from tests.artifacts import artifact_path


class FarmingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent)
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 11, 15, 9, tzinfo=timezone.utc)
        self.store = FarmingStore(self.root / 'records.sqlite3', clock=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def test_before_after_survives_restart_and_calculates_real_elapsed(self):
        start = self.store.start({'meso': 62_946_114_234, 'fragments': 114}, 'Lucid')
        self.now += timedelta(minutes=120)
        restarted = FarmingStore(self.store.path, clock=lambda: self.now)
        self.assertEqual(restarted.active()['id'], start['session']['id'])
        result = restarted.finish(start['session']['id'], {'meso': 63_246_114_234, 'fragments': 151})
        self.assertEqual(result['session']['duration_seconds'], 7200)
        self.assertEqual(result['session']['meso_change'], 300_000_000)
        self.assertEqual(result['session']['fragment_change'], 37)
        self.assertEqual(result['session']['meso_per_hour'], 150_000_000)
        query = FarmingStore(self.store.path, clock=lambda: self.now).query('2026-11-15', '2026-11-15')
        self.assertEqual(query['completed_sessions'], 1)
        self.assertEqual(query['total_seconds'], 7200)
        self.assertIsNone(query['active'])
        self.assertEqual(self.store.query('2026-11-16')['completed_sessions'], 0)

    def test_negative_changes_preserved_duplicate_start_and_finish_not_double_counted(self):
        start = self.store.start({'meso': 1000, 'fragments': 50})
        self.assertEqual(self.store.start({'meso': 9999, 'fragments': 999})['status'], 'already_active')
        self.now += timedelta(minutes=30)
        end = self.store.finish(start['session']['id'], {'meso': 500, 'fragments': 40})
        self.assertEqual(end['session']['meso_change'], -500)
        self.assertEqual(end['session']['fragment_change'], -10)
        self.assertEqual(self.store.finish(start['session']['id'], {'meso': 0, 'fragments': 0})['status'], 'not_active')
        self.assertEqual(self.store.query()['completed_sessions'], 1)

    def test_invalid_readings_do_not_overwrite_active_and_cancel_excludes_totals(self):
        for snapshot in ({'meso': None, 'fragments': 1}, {'meso': True, 'fragments': 1}, {'meso': -1, 'fragments': 1}):
            with self.assertRaises(ValueError):
                self.store.start(snapshot)
        self.assertIsNone(self.store.active())
        session = self.store.start({'meso': 100, 'fragments': 1})['session']
        with self.assertRaises(ValueError):
            self.store.finish(session['id'], {'meso': 110, 'fragments': None})
        self.assertEqual(self.store.active()['start_meso'], 100)
        self.assertEqual(self.store.cancel(session['id'])['status'], 'cancelled')
        self.assertIsNone(self.store.active())
        self.assertEqual(self.store.query()['completed_sessions'], 0)

    def test_date_filter_uses_korea_end_date_and_totals_ignore_page_limit(self):
        for _ in range(2):
            start = self.store.start({'meso': 100, 'fragments': 1})
            self.now += timedelta(minutes=10)
            self.store.finish(start['session']['id'], {'meso': 150, 'fragments': 4})
        result = self.store.query(limit=1)
        self.assertEqual(len(result['sessions']), 1)
        self.assertEqual(result['completed_sessions'], 2)
        self.assertEqual(result['meso_change'], 100)
        self.now = datetime(2026, 11, 15, 15, 5, tzinfo=timezone.utc)  # 16th in Korea
        start = self.store.start({'meso': 100, 'fragments': 1})
        self.now += timedelta(minutes=10)
        self.store.finish(start['session']['id'], {'meso': 200, 'fragments': 2})
        self.assertEqual(self.store.query('2026-11-16', '2026-11-16')['completed_sessions'], 1)

    def test_more_than_one_hundred_records_are_returned_without_truncation(self):
        for _ in range(105):
            start = self.store.start({'meso': 100, 'fragments': 1})
            self.now += timedelta(minutes=1)
            self.store.finish(start['session']['id'], {'meso': 150, 'fragments': 2})
        result = self.store.query()
        self.assertEqual(len(result['sessions']), 105)
        self.assertEqual(result['meso_change'], 5250)
        self.assertFalse(result['has_more'])
        self.assertEqual(len(self.store.query(limit=101)['sessions']), 101)
        self.assertTrue(self.store.query(limit=101)['has_more'])
        self.assertEqual(len(FarmingTools(self.store)('get_farming_records', {})['sessions']), 105)

    def test_tool_allowlist_cache_and_failed_capture_leave_no_records(self):
        reader = Mock(return_value={'meso': 100, 'fragments': 5})
        tools = FarmingTools(self.store, reader, 'Lucid', confirm_start=lambda snapshot: 'start')
        self.assertEqual(tools('__import__', {})['status'], 'error')
        self.assertEqual(tools('start_farming_session', {'meso': 123})['status'], 'error')
        first = tools('start_farming_session', {})
        self.assertEqual(first['status'], 'started')
        self.assertEqual(tools('start_farming_session', {}), first)
        reader.assert_called_once()
        self.assertEqual(tools('finish_farming_session', {})['status'], 'error')
        failed = FarmingTools(self.store, Mock(side_effect=ValueError('Uncertain OCR')))
        self.assertEqual(failed('finish_farming_session', {})['status'], 'error')
        self.assertIsNotNone(self.store.active())
        reader.reset_mock()
        duplicate = FarmingTools(self.store, reader)
        self.assertEqual(duplicate('start_farming_session', {})['status'], 'already_active')
        reader.assert_not_called()

    def test_capture_requires_both_readings_and_always_restores_ui(self):
        options = {kind: {'region': None, 'method': 'local', 'config': {}, 'key': ''} for kind in ('meso', 'sol_erda')}
        before, after = Mock(), Mock()
        capture = Mock(side_effect=[(self.root, {'reading': {'status': 'ok', 'value': 100}}),
                                    (self.root, {'reading': {'status': 'uncertain', 'value': None}})])
        reader = BalanceCapture(options, before, after, self.root, capture)
        with self.assertRaises(ValueError):
            reader()
        before.assert_called_once()
        after.assert_called_once()

    def test_capture_ignores_legacy_remote_options(self):
        options = {kind: {'region': None, 'method': 'vision', 'config': {'model': 'old'}, 'key': 'unused'}
                   for kind in ('meso', 'sol_erda')}
        capture = Mock(return_value=(self.root, {'reading': {'status': 'ok', 'value': 100}}))
        result = BalanceCapture(options, output=self.root, capture=capture)()
        self.assertEqual(result['meso'], 100)
        self.assertEqual(result['fragments'], 100)
        for call in capture.call_args_list:
            self.assertEqual(call.args[2:5], ('local', {}, ''))
        self.assertTrue(all(item['method'] == 'local' for item in result['evidence'].values()))

    def test_missing_capture_dependency_reports_error_without_starting(self):
        tools = FarmingTools(self.store, Mock(side_effect=ImportError('capture module')))
        result = tools('start_farming_session', {})
        self.assertEqual(result['status'], 'error')
        self.assertIn('requirements.txt', result['error'])
        self.assertIsNone(self.store.active())

    def test_delete_only_selected_completed_records_and_recompute_totals(self):
        identifiers = []
        for gain in (100, 200, 300):
            start = self.store.start({'meso': 1000, 'fragments': 10})
            self.now += timedelta(minutes=10)
            self.store.finish(start['session']['id'], {'meso': 1000 + gain, 'fragments': 15})
            identifiers.append(start['session']['id'])
        active = self.store.start({'meso': 2000, 'fragments': 20})['session']
        deleted = self.store.delete_completed([identifiers[0], identifiers[2], identifiers[0], active['id'], 'unknown'])
        self.assertEqual(deleted, 2)
        result = FarmingStore(self.store.path, clock=lambda: self.now).query()
        self.assertEqual(result['completed_sessions'], 1)
        self.assertEqual(result['meso_change'], 200)
        self.assertEqual(result['total_seconds'], 600)
        self.assertEqual(result['sessions'][0]['id'], identifiers[1])
        self.assertEqual(result['active']['id'], active['id'])

    def test_start_requires_human_confirmation_and_uses_confirmation_time(self):
        reader = Mock(return_value={'meso': 41231234, 'fragments': 114})
        unconfirmed = FarmingTools(self.store, reader)
        result = unconfirmed('start_farming_session', {})
        self.assertEqual(result['status'], 'confirmation_required')
        self.assertEqual(result['meso_text'], '4123만 1234 메소')
        self.assertIsNone(self.store.active())
        def confirm(snapshot):
            self.assertIsNone(self.store.active())
            self.assertEqual(snapshot['meso'], 41231234)
            self.now += timedelta(minutes=2)
            return 'start'
        confirmed = FarmingTools(self.store, reader, confirm_start=confirm)
        result = confirmed('start_farming_session', {})
        self.assertEqual(result['status'], 'started')
        self.assertEqual(result['session']['duration_seconds'], 0)
        self.assertEqual(result['session']['start_meso_text'], '4123만 1234 메소')

    def test_retry_reads_fresh_values_and_cancel_does_not_start(self):
        reader = Mock(side_effect=[{'meso': 100, 'fragments': 10}, {'meso': 200, 'fragments': 20}])
        confirm = Mock(side_effect=['retry', 'start'])
        result = FarmingTools(self.store, reader, confirm_start=confirm)('start_farming_session', {})
        self.assertEqual(result['session']['start_meso'], 200)
        self.assertEqual(result['session']['start_fragments'], 20)
        self.assertEqual(reader.call_count, 2)
        self.store.cancel(result['session']['id'])
        cancelled = FarmingTools(self.store, Mock(return_value={'meso': 100, 'fragments': 10}), confirm_start=lambda snapshot: 'cancel')
        self.assertEqual(cancelled('start_farming_session', {})['status'], 'start_cancelled')
        self.assertIsNone(self.store.active())

    def test_meso_format_preserves_exact_digits_and_sign(self):
        from maeagi_biseo.core.amounts import format_meso
        for value, text in ((0, '0'), (1234, '1234'), (10000, '1만'), (41231234, '4123만 1234'),
                            (300000000, '3억'), (62946114234, '629억 4611만 4234'), (-10001, '-1만 1')):
            self.assertEqual(format_meso(value), text)
        self.assertEqual(format_meso(300000000, signed=True), '+3억')


if __name__ == '__main__':
    unittest.main()
