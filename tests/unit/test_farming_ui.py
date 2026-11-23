import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch
from PySide6.QtCore import QSettings, Qt, QTimer, QDate, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QMessageBox
from PySide6.QtGui import QFontDatabase
from maeagi_biseo.core.farming import FarmingStore
from maeagi_biseo.core.farming_tools import FarmingTools, capture_options
from maeagi_biseo.ui.farming_panel import FarmingPanel
from maeagi_biseo.ui.chat import ChatWindow, ReplyWorker, SettingsDialog
from maeagi_biseo.ui.dialogue import DialogueManager
from maeagi_biseo.resources import DEFAULTS, tr
from tests.artifacts import artifact_path


class FarmingUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent)
        self.root = Path(self.temp.name)
        self.settings = QSettings(str(self.root / 'settings.ini'), QSettings.IniFormat)
        self.now = datetime(2026, 11, 15, 9, tzinfo=timezone.utc)
        self.store = FarmingStore(self.root / 'records.sqlite3', clock=lambda: self.now)

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.temp.cleanup()

    def test_history_renders_actual_before_after_and_active_session(self):
        start = self.store.start({'meso': 62_946_114_234, 'fragments': 114}, 'Lucid', note='<b>사냥터</b>')
        self.now += timedelta(hours=2)
        self.store.finish(start['session']['id'], {'meso': 63_246_114_234, 'fragments': 151})
        self.store.start({'meso': 63_246_114_234, 'fragments': 151}, 'Lucid')
        panel = FarmingPanel(self.store)
        panel.calendar.setSelectedDate(QDate(2026, 11, 15))
        panel.resize(860, 450)
        panel.show()
        self.app.processEvents()
        try:
            self.assertIn('+3억', panel.summary.text())
            self.assertIn('진행 중', panel.summary.text())
            self.assertEqual(panel.table.rowCount(), 1)
            self.assertEqual(panel.table.item(0, 4).text(), '+37')
            tooltip = panel.table.item(0, 0).toolTip()
            self.assertIn('629억 4611만 4234', tooltip)
            self.assertIn('632억 4611만 4234', tooltip)
            self.assertIn('2시간 0분 0초', tooltip)
            self.assertIn('114개 → 151개', tooltip)
            self.assertIn('+37개', tooltip)
            self.assertIn('&lt;b&gt;사냥터&lt;/b&gt;', tooltip)
            for column in range(panel.table.columnCount()):
                self.assertEqual(panel.table.item(0, column).toolTip(), tooltip)
            panel.grab().save(str(artifact_path('farming_history_preview.png')))
        finally:
            panel.close()

    def test_ui_receipt_survives_llm_error_and_capture_keeps_windows_visible(self):
        pet = QWidget()
        pet.kind = 'Lucid'
        dialogue = DialogueManager([pet])
        chat = ChatWindow([pet], dialogue, self.settings, self.settings, self.settings, self.store, self.settings)
        pet.show()
        chat.show()
        self.app.processEvents()
        try:
            session = self.store.start({'meso': 100, 'fragments': 10}, 'Lucid')
            chat.farming_tool_event({'event': 'result', 'result': session})
            chat.pending = '재획 시작해'
            chat.failed('Network failed after save')
            self.assertTrue(any('시작 기록 저장 완료' in label.text() for label in chat.findChildren(QLabel)))
            self.assertIsNotNone(self.store.active())
            worker = ReplyWorker(DEFAULTS, '', [], chat)
            chat.worker = worker
            gate = threading.Event()
            with patch('maeagi_biseo.ui.capture_notice.time.monotonic', return_value=100) as clock:
                chat.prepare_farming_capture(gate)
                self.assertIn('5초 남음', chat.capture_notice.text())
                self.assertTrue(chat.capture_notice.isVisible())
                self.assertFalse(gate.is_set())
                clock.return_value = 103
                chat.capture_notice.tick()
                self.assertIn('2초 남음', chat.status.text())
                clock.return_value = 105
                chat.capture_notice.tick()
                self.assertIn('화면 인식 중', chat.capture_notice.text())
            self.assertTrue(pet.isVisible())
            self.assertTrue(dialogue.timer.isActive())
            self.assertTrue(gate.is_set())
            self.assertTrue(chat.isVisible())
            self.assertFalse(chat.isMinimized())
            self.assertTrue(pet.isVisible())
            self.assertTrue(dialogue.timer.isActive())
            chat.finish_farming_capture()
            self.assertFalse(chat.capture_notice.isVisible())
            chat.worker = None
        finally:
            dialogue.timer.stop()
            chat.target_refresh_timer.stop()
            chat.close()
            pet.close()

    def test_legacy_vision_capture_settings_use_local_ocr(self):
        import json
        self.settings.setValue('vision_provider', 'gemini')
        self.settings.setValue('vision_profiles', json.dumps({'gemini': {'model': 'old-model'}}))
        for kind in ('meso', 'sol_erda'):
            self.settings.setValue('method_' + kind, 'vision')
        options = capture_options(self.settings)
        for option in options.values():
            self.assertEqual(option['method'], 'local')
            self.assertEqual(option['key'], '')
            self.assertEqual(option['config'], {})

    def test_select_multiple_records_cancel_then_confirm_deletion(self):
        for gain in (100, 200, 300):
            start = self.store.start({'meso': 1000, 'fragments': 10})
            self.now += timedelta(minutes=10)
            self.store.finish(start['session']['id'], {'meso': 1000 + gain, 'fragments': 15})
        panel = FarmingPanel(self.store)
        panel.calendar.setSelectedDate(QDate(2026, 11, 15))
        panel.resize(860, 450)
        panel.show()
        self.app.processEvents()
        try:
            self.assertFalse(panel.delete_button.isEnabled())
            for row, modifier in ((0, Qt.NoModifier), (2, Qt.ControlModifier)):
                rect = panel.table.visualItemRect(panel.table.item(row, 0))
                QTest.mouseClick(panel.table.viewport(), Qt.LeftButton, modifier, rect.center())
            self.assertEqual(len(panel.selected_ids()), 2)
            def click_confirmation(button):
                dialog = QApplication.activeModalWidget()
                self.assertIsInstance(dialog, QMessageBox)
                QTest.mouseClick(dialog.button(button), Qt.LeftButton)
            QTimer.singleShot(0, lambda: click_confirmation(QMessageBox.No))
            QTest.mouseClick(panel.delete_button, Qt.LeftButton)
            self.assertEqual(self.store.query()['completed_sessions'], 3)
            QTimer.singleShot(0, lambda: click_confirmation(QMessageBox.Yes))
            QTest.mouseClick(panel.delete_button, Qt.LeftButton)
            self.assertEqual(self.store.query()['completed_sessions'], 1)
            self.assertEqual(panel.table.rowCount(), 1)
            self.assertEqual(len(panel.calendar.days['2026-11-15']), 1)
            self.assertFalse(panel.delete_button.isEnabled())
            self.assertIn('+200', panel.summary.text())
            self.assertIn('2', panel.notice.text())
            panel.grab().save(str(artifact_path('farming_deletion_preview.png')))
        finally:
            panel.close()

    def test_calendar_month_navigation_date_selection_and_unlimited_day_records(self):
        for index in range(103):
            start = self.store.start({'meso': 100, 'fragments': 1})
            self.now += timedelta(seconds=1)
            self.store.finish(start['session']['id'], {'meso': 200, 'fragments': 2})
        self.now = datetime(2026, 12, 1, 15, 5, tzinfo=timezone.utc)  # Dec 2 in Korea
        start = self.store.start({'meso': 100, 'fragments': 1})
        self.now += timedelta(minutes=1)
        self.store.finish(start['session']['id'], {'meso': 400, 'fragments': 4})
        panel = FarmingPanel(self.store)
        panel.calendar.setSelectedDate(QDate(2026, 11, 15))
        panel.resize(860, 780)
        panel.show()
        self.app.processEvents()
        try:
            self.assertEqual(panel.table.rowCount(), 103)
            self.assertIn('103', panel.day_summary.text())
            self.assertEqual(len(panel.calendar.days['2026-11-15']), 103)
            calendar_view = panel.calendar.findChild(QWidget, 'qt_calendar_calendarview')
            # Navigate dates with actual keyboard input; moving to an empty day clears details.
            panel.calendar.setFocus()
            QTest.keyClick(calendar_view, Qt.Key_Right)
            self.assertEqual(panel.calendar.selectedDate(), QDate(2026, 11, 16))
            self.assertEqual(panel.table.rowCount(), 0)
            self.assertFalse(panel.delete_button.isEnabled())
            panel.calendar.showNextMonth()
            self.app.processEvents()
            self.assertIn('12월', panel.summary.text())
            self.assertEqual(set(panel.calendar.days), {'2026-12-02'})
            panel.calendar.setSelectedDate(QDate(2026, 12, 2))
            self.assertEqual(panel.table.rowCount(), 1)
            self.assertIn('+300', panel.day_summary.text())
            panel.calendar.showPreviousMonth()
            panel.calendar.setSelectedDate(QDate(2026, 11, 15))
            self.assertEqual(panel.table.rowCount(), 103)
            panel.grab().save(str(artifact_path('farming_calendar_preview.png')))
        finally:
            panel.close()

    def test_calendar_fits_settings_and_scrolls_in_small_windows(self):
        from maeagi_biseo.ui.chat_theme import apply_chat_theme
        start = self.store.start({'meso': 1_000_000_000, 'fragments': 100})
        self.now += timedelta(hours=2)
        self.store.finish(start['session']['id'], {'meso': 1_300_000_000, 'fragments': 135})
        dialog = SettingsDialog(DEFAULTS, '', capture_store=self.settings, character_store=self.settings,
                                catalog_store=self.settings, dialogue_store=self.settings, farming_store=self.store)
        panel = dialog.farming_panel
        panel.calendar.setSelectedDate(QDate(2026, 11, 15))
        dialog.show()
        self.app.processEvents()
        try:
            item = next(dialog.navigation.item(i) for i in range(dialog.navigation.count())
                        if dialog.navigation.item(i).text() == tr('farming.tab'))
            QTest.mouseClick(dialog.navigation.viewport(), Qt.LeftButton,
                             pos=dialog.navigation.visualItemRect(item).center())
            self.app.processEvents()
            self.assertTrue(panel.calendar.isVisible())
            self.assertEqual(panel.table.rowCount(), 1)
            for mode in ('light', 'dark'):
                apply_chat_theme(dialog, mode)
                self.app.processEvents()
                self.assertEqual(panel.scroll.horizontalScrollBar().maximum(), 0)
                dialog.grab().save(str(artifact_path('farming_calendar_settings_' + mode + '.png')))
            dialog.resize(820, 620)
            self.app.processEvents()
            self.assertEqual(panel.scroll.horizontalScrollBar().maximum(), 0)
            self.assertGreater(panel.scroll.verticalScrollBar().maximum(), 0)
            panel.scroll.ensureWidgetVisible(panel.delete_button)
            self.app.processEvents()
            self.assertTrue(panel.scroll.viewport().rect().contains(
                panel.delete_button.mapTo(panel.scroll.viewport(), panel.delete_button.rect().center())))
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_clean_month_picker_sunday_first_and_top_today_button(self):
        from maeagi_biseo.ui.chat_theme import apply_chat_theme
        with patch('maeagi_biseo.ui.farming_panel.korea_today', return_value=QDate(2026, 11, 15)):
            panel = FarmingPanel(self.store)
            panel.resize(860, 780)
            panel.show()
            self.app.processEvents()
            try:
                self.assertEqual(panel.calendar.firstDayOfWeek(), Qt.Sunday)
                self.assertFalse(panel.calendar.isNavigationBarVisible())
                self.assertLess(panel.today_button.mapTo(panel, panel.today_button.rect().center()).y(),
                                panel.calendar.mapTo(panel, panel.calendar.rect().topLeft()).y())
                QTest.mouseClick(panel.month_button, Qt.LeftButton)
                self.app.processEvents()
                picker = panel.month_picker
                self.assertTrue(picker.isVisible())
                self.assertEqual(len(picker.month_buttons), 12)
                self.assertTrue(picker.month_buttons[10].isChecked())
                QTest.mouseClick(picker.next_year, Qt.LeftButton)
                self.assertEqual(picker.year, 2027)
                QTest.mouseClick(picker.month_buttons[0], Qt.LeftButton)
                self.assertFalse(picker.isVisible())
                self.assertEqual(panel.calendar.selectedDate(), QDate(2027, 1, 1))
                self.assertIn('2027년 1월', panel.month_button.text())
                QTest.mouseClick(panel.today_button, Qt.LeftButton)
                self.assertEqual(panel.calendar.selectedDate(), QDate(2026, 11, 15))
                QTest.mouseClick(panel.previous_month, Qt.LeftButton)
                self.assertEqual(panel.calendar.monthShown(), 10)
                QTest.mouseClick(panel.next_month, Qt.LeftButton)
                self.assertEqual(panel.calendar.monthShown(), 11)
                for mode in ('light', 'dark'):
                    apply_chat_theme(panel, mode)
                    QTest.mouseClick(panel.month_button, Qt.LeftButton)
                    self.app.processEvents()
                    self.assertTrue(picker.isVisible())
                    picker.grab().save(str(artifact_path('farming_month_picker_' + mode + '.png')))
                    panel.grab().save(str(artifact_path('farming_calendar_toolbar_' + mode + '.png')))
                    QTest.keyClick(picker, Qt.Key_Escape)
                    self.assertFalse(picker.isVisible())
            finally:
                panel.close()
                panel.deleteLater()
                self.app.processEvents()

    def test_record_table_shows_three_complete_rows(self):
        from maeagi_biseo.ui.chat_theme import apply_chat_theme
        for _ in range(3):
            start = self.store.start({'meso': 1000, 'fragments': 10})
            self.now += timedelta(minutes=10)
            self.store.finish(start['session']['id'], {'meso': 1200, 'fragments': 15})
        dialog = SettingsDialog(DEFAULTS, '', capture_store=self.settings, character_store=self.settings,
                                catalog_store=self.settings, dialogue_store=self.settings, farming_store=self.store)
        panel = dialog.farming_panel
        panel.calendar.setSelectedDate(QDate(2026, 11, 15))
        dialog.show()
        self.app.processEvents()
        try:
            item = next(dialog.navigation.item(i) for i in range(dialog.navigation.count())
                        if dialog.navigation.item(i).text() == tr('farming.tab'))
            QTest.mouseClick(dialog.navigation.viewport(), Qt.LeftButton,
                             pos=dialog.navigation.visualItemRect(item).center())
            for mode in ('light', 'dark'):
                apply_chat_theme(dialog, mode)
                self.app.processEvents()
                panel.resize_record_table()
                panel.scroll.ensureWidgetVisible(panel.table)
                self.app.processEvents()
                self.assertEqual(panel.table.rowCount(), 3)
                self.assertGreaterEqual(panel.table.viewport().height(), panel.table.rowHeight(0) * 3)
                self.assertTrue(panel.table.viewport().rect().contains(
                    panel.table.visualItemRect(panel.table.item(2, 0)).bottomLeft()))
                dialog.grab().save(str(artifact_path('farming_three_records_' + mode + '.png')))
        finally:
            dialog.close()

    def test_calendar_cell_respects_dark_theme(self):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QPixmap, QPainter, QColor
        from maeagi_biseo.ui.chat_theme import apply_chat_theme, COLORS
        panel = FarmingPanel(self.store)
        try:
            apply_chat_theme(panel, 'dark')
            panel.calendar.setSelectedDate(QDate(2026, 11, 15))
            image = QPixmap(150, 70)
            painter = QPainter(image)
            panel.calendar.paintCell(painter, QRect(0, 0, 150, 70), QDate(2026, 11, 10))
            painter.end()
            self.assertEqual(image.toImage().pixelColor(100, 40), QColor(COLORS['dark']['surface']))
        finally:
            panel.close()

    def test_start_confirmation_shows_readable_amount_and_waits_for_click(self):
        chat = ChatWindow([], DialogueManager([]), self.settings, self.settings, self.settings, self.store, self.settings)
        request = {'snapshot': {'meso': 41231234, 'fragments': 114}, 'intro': '선생님, 수량이 맞는지 봐주실래요?',
                   'choice': 'cancel', 'ready': threading.Event()}
        chat.show()
        try:
            chat.confirm_farming_start(request)
            self.app.processEvents()
            dialog = chat.farming_confirmation_dialog
            self.assertIn('4123만 1234 메소', dialog.text())
            self.assertIn('114개', dialog.text())
            self.assertTrue(dialog.text().startswith(request['intro']))
            self.assertFalse(request['ready'].is_set())
            self.assertIsNone(self.store.active())
            self.assertFalse(chat.farming_reminder.isActive())
            dialog.grab().save(str(artifact_path('farming_start_confirmation.png')))
            start_button = next(button for button in dialog.buttons() if button.text() == tr('farming.confirm_yes'))
            QTest.mouseClick(start_button, Qt.LeftButton)
            self.assertTrue(request['ready'].is_set())
            self.assertEqual(request['choice'], 'start')
            for choice, label in (('retry', 'farming.confirm_retry'), ('cancel', 'common.cancel')):
                next_request = {'snapshot': request['snapshot'], 'choice': 'cancel', 'ready': threading.Event()}
                chat.confirm_farming_start(next_request)
                self.app.processEvents()
                dialog = chat.farming_confirmation_dialog
                button = next(button for button in dialog.buttons() if button.text() == tr(label))
                QTest.mouseClick(button, Qt.LeftButton)
                self.assertTrue(next_request['ready'].is_set())
                self.assertEqual(next_request['choice'], choice)
        finally:
            chat.dialogue.timer.stop()
            chat.target_refresh_timer.stop()
            chat.close()

    def test_farming_reminder_stays_in_original_chat_and_keeps_session_active(self):
        chat = ChatWindow([], DialogueManager([]), self.settings, self.settings, self.settings, self.store, self.settings)
        chat.key = ''
        identifier = chat.thread_id
        snapshot = {'meso': 100, 'fragments': 10}
        tool = FarmingTools(self.store, lambda: snapshot, identifier, chat.farming_tool_event,
                            confirm_start=lambda _: 'start')
        result = tool('start_farming_session', {})
        self.assertEqual(result['status'], 'started')
        self.assertEqual(chat.farming_reminder.interval(), 30 * 60 * 1000)
        self.assertTrue(chat.farming_reminder.isActive())

        chat.thread_id = 'other-character'
        chat.farming_reminder.start(1)
        QTest.qWait(30)
        self.assertFalse(chat.farming_reminder.isActive())
        self.assertEqual(chat.transcripts[identifier][-1]['text'], tr('farming.end_reminder'))
        self.assertNotIn(chat.thread_id, chat.transcripts)
        self.assertEqual(self.store.active()['id'], result['session']['id'])

    def test_farming_reminder_uses_original_persona_and_falls_back_on_error(self):
        chat = ChatWindow([], DialogueManager([]), self.settings, self.settings, self.settings, self.store, self.settings)
        chat.key = 'fixture-key'
        chat.thread_id = 'other-character'
        config = {**DEFAULTS, 'name': 'Original Pet', 'tone': 'Original voice',
                  'model': 'fixture-model', 'base_url': 'https://example.com'}
        phrase = '선생님, 벌써 30분이에요! 재획이 끝났는지 봐주실래요?'
        for response, error, expected in ((phrase, None, phrase), ('', None, tr('farming.end_reminder')),
                                          (None, ValueError('offline'), tr('farming.end_reminder'))):
            with self.subTest(response=response, error=error):
                chat.farming_reminder_thread = 'original-character'
                with patch.object(chat, 'config_for', return_value=config) as persona, \
                     patch('maeagi_biseo.ui.chat.generate_reply', return_value=response, side_effect=error) as generate:
                    chat.remind_farming_end()
                    self.assertTrue(chat.farming_reminder_worker.wait(2000))
                    self.app.processEvents()
                    persona.assert_called_with('original-character')
                    self.assertIn('Original voice', generate.call_args.args[3])
                    self.assertEqual(generate.call_args.args[2][0]['content'], tr('farming.reminder_persona_request'))
                entry = chat.transcripts['original-character'][-1]
                self.assertEqual(entry['speaker'], 'Original Pet')
                self.assertEqual(entry['text'], expected)

    def test_farming_reminder_stops_after_early_finish_or_cancel(self):
        chat = ChatWindow([], DialogueManager([]), self.settings, self.settings, self.settings, self.store, self.settings)
        snapshot = {'meso': 100, 'fragments': 10}
        for action, status in (('finish_farming_session', 'completed'), ('cancel_farming_session', 'cancelled')):
            with self.subTest(action=action):
                start = FarmingTools(self.store, lambda: snapshot, report=chat.farming_tool_event,
                                     confirm_start=lambda _: 'start')
                start('start_farming_session', {})
                self.assertTrue(chat.farming_reminder.isActive())
                stop = FarmingTools(self.store, lambda: snapshot, report=chat.farming_tool_event)
                self.assertEqual(stop(action, {})['status'], status)
                self.assertFalse(chat.farming_reminder.isActive())

    def test_farming_confirmation_uses_persona_without_sending_snapshot(self):
        worker = ReplyWorker({**DEFAULTS, 'name': 'Test Pet', 'tone': 'Custom voice'}, 'fixture-key', [])
        captured = []

        def confirm(request):
            captured.append(request)
            request['choice'] = 'start'
            request['ready'].set()

        worker.confirmation_requested.connect(confirm)
        snapshot = {'meso': 41231234, 'fragments': 114}
        with patch('maeagi_biseo.ui.chat.generate_reply', return_value='선생님, 맞는지 확인해 주실래요?') as generate:
            self.assertEqual(worker.confirm_farming_start(snapshot), 'start')
            self.assertIn('Custom voice', generate.call_args.args[3])
            self.assertNotIn(str(snapshot['meso']), str(generate.call_args))
            self.assertEqual(captured[-1]['intro'], '선생님, 맞는지 확인해 주실래요?')
        with patch('maeagi_biseo.ui.chat.generate_reply', side_effect=ValueError('offline')):
            self.assertEqual(worker.confirm_farming_start(snapshot), 'start')
            self.assertEqual(captured[-1]['intro'], tr('farming.confirm_intro'))
        worker.deleteLater()


if __name__ == '__main__':
    unittest.main()
