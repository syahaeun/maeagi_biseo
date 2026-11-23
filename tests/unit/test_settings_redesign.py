"""Settings layout, sequential capture and appearance regression checks."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
from datetime import datetime, timezone, timedelta
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QDate, QSettings
from PySide6.QtGui import QCursor, QFontDatabase, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QTabWidget
from maeagi_biseo.resources import DEFAULTS, tr
from maeagi_biseo.ui.chat import ChatWindow, SettingsDialog
from maeagi_biseo.ui.chat_theme import apply_chat_theme
from maeagi_biseo.core.farming import FarmingStore
from maeagi_biseo.ui.settings_widgets import Disclosure
from tests.artifacts import artifact_path


class SettingsRedesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/malgun.ttf'
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))

    def test_layout_and_sequential_capture(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            store = QSettings(str(Path(temp) / 'settings.ini'), QSettings.IniFormat)
            farming = FarmingStore(Path(temp) / 'records.sqlite3')
            dialog = SettingsDialog(DEFAULTS, '', capture_store=store, character_store=store, catalog_store=store, farming_store=farming)
            self.addCleanup(dialog.close)
            tabs = dialog.findChild(QTabWidget, 'settingsTabs')
            self.assertEqual(tabs.count(), 8)
            self.assertEqual(tabs.tabText(tabs.indexOf(dialog.obs_scroll)), tr('obs.settings_tab'))
            self.assertIs(tabs.widget(1), dialog.management_page)
            self.assertGreaterEqual(dialog.preview.minimumHeight(), dialog.preview.fontMetrics().lineSpacing() * 10)
            dialog.show()
            self.app.processEvents()
            dialog.grab().save(str(artifact_path('settings_redesign_light.png')))
            tabs.setCurrentWidget(dialog.obs_scroll)
            self.app.processEvents()
            self.assertEqual(dialog.obs_scroll.horizontalScrollBar().maximum(), 0)
            dialog.grab().save(str(artifact_path('obs/settings-dialog.png')))
            dialog.obs_page.show_placement()
            self.app.processEvents()
            dialog.grab().save(str(artifact_path('obs/settings-placement-dialog.png')))
            tabs.setCurrentWidget(dialog.api_scroll)
            self.app.processEvents()
            dialog.grab().save(str(artifact_path('settings_connection_light.png')))
            tabs.setCurrentWidget(dialog.capture_page)
            self.assertIs(tabs.currentWidget(), dialog.capture_page)
            self.app.processEvents()
            self.assertEqual(dialog.capture_page.horizontalScrollBar().maximum(), 0)
            dialog.grab().save(str(artifact_path('settings_capture_light.png')))
            apply_chat_theme(dialog, 'dark')
            self.app.processEvents()
            dialog.grab().save(str(artifact_path('settings_capture_dark.png')))
            a, b = dialog.sol_erda_panel.manual, dialog.meso_panel.manual
            with patch.object(a, 'schedule', side_effect=lambda action, **kwargs: setattr(a, 'busy', True)) as first, \
                 patch.object(b, 'schedule', side_effect=lambda action, **kwargs: setattr(b, 'busy', True)) as second:
                dialog.read_all_capture()
                first.assert_called_once_with('read', delay_ms=5000, restore_after=False)
                second.assert_not_called()
                dialog.advance_capture_queue()
                second.assert_not_called()
                a.busy = False
                dialog.advance_capture_queue()
                second.assert_called_once_with('read', delay_ms=0, restore_after=True)
                b.busy = False
                dialog.advance_capture_queue()
                self.assertTrue(dialog.read_all_button.isEnabled())
            with patch('maeagi_biseo.ui.capture_notice.time.monotonic', return_value=100) as clock, \
                 patch.object(a, 'launch') as launch:
                dialog.read_all_button.click()
                self.app.processEvents()
                self.assertTrue(dialog.isMinimized())
                self.assertTrue(a.capture_notice.isVisible())
                self.assertIn('5초 남음', a.capture_notice.text())
                screen = self.app.screenAt(QCursor.pos()) or dialog.screen()
                self.assertEqual(a.capture_notice.geometry().center(), screen.availableGeometry().center())
                clock.return_value = 103
                a.capture_notice.tick()
                self.assertIn('2초 남음', a.capture_notice.text())
                launch.assert_not_called()
                clock.return_value = 105
                a.capture_notice.tick()
                launch.assert_called_once_with('read')
                self.assertIn('화면 인식 중', a.capture_notice.text())
                dialog.reject()
                self.assertFalse(a.capture_notice.isVisible())
            self.assertFalse(dialog.capture_sequence_timer.isActive())

    def test_lab_saves_and_schedules_chatter_from_one_topic(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            store = QSettings(str(Path(temp) / 'settings.ini'), QSettings.IniFormat)
            farming = FarmingStore(Path(temp) / 'records.sqlite3')
            pet = Mock(kind='fixture-pet', broadcast_window=None, paused=False, focus=False)
            pet.isVisible.return_value = True
            pet.can_talk.return_value = False
            dialogue = Mock(store=store, active=None, user_until=0)
            with patch('maeagi_biseo.ui.chat.load_api_key', return_value=''):
                chat = ChatWindow([pet], dialogue, store, store, store, farming, store)
            pet.kind = chat.thread_id
            try:
                self.assertFalse(chat.chatter_timer.isActive())
                chat.settings()
                dialog = chat._settings_dialog
                tabs = dialog.findChild(QTabWidget, 'settingsTabs')
                tabs.setCurrentWidget(dialog.lab_scroll)
                self.assertEqual(tabs.tabText(tabs.currentIndex()), tr('lab.tab'))
                self.assertFalse(dialog.chatter_enabled.isChecked())
                self.assertFalse(dialog.chatter_in_focus.isChecked())
                self.assertFalse(dialog.chatter_in_focus.isEnabled())
                self.assertEqual(dialog.chatter_minutes.value(), 30)
                dialog.chatter_enabled.setChecked(True)
                self.assertTrue(dialog.chatter_in_focus.isEnabled())
                dialog.chatter_minutes.setValue(12)
                dialog.chatter_topics.setText(' 달팽이 퇴근 ; ; 우주 고양이 ;')
                buttons = dialog.findChild(QDialogButtonBox, 'settingsActions')
                self.app.processEvents()
                QTest.mouseClick(buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.assertIsNone(chat._settings_dialog)
                self.assertEqual(store.value('chatter_topics'), ' 달팽이 퇴근 ; ; 우주 고양이 ;')
                self.assertTrue(chat.chatter_timer.isActive())
                self.assertEqual(chat.chatter_timer.interval(), 12 * 60 * 1000)

                pet.focus = True
                chat.chatter_timer.timeout.emit()
                dialogue.say_to_user.assert_not_called()
                chat.settings()
                dialog = chat._settings_dialog
                dialog.findChild(QTabWidget, 'settingsTabs').setCurrentWidget(dialog.lab_scroll)
                dialog.chatter_in_focus.setChecked(True)
                buttons = dialog.findChild(QDialogButtonBox, 'settingsActions')
                self.app.processEvents()
                QTest.mouseClick(buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.assertTrue(store.value('chatter_in_focus', False, type=bool))

                with patch('maeagi_biseo.ui.chat.random.choice', side_effect=lambda choices: choices[-1]) as choose:
                    chat.chatter_timer.timeout.emit()
                    self.assertEqual(choose.call_args_list[0].args[0], ('달팽이 퇴근', '우주 고양이'))
                dialogue.say_to_user.assert_called_once_with(
                    pet, tr('lab.chatter_fallback_question', topic='우주 고양이'))
                fallback = tr('lab.chatter_fallback_question', topic='우주 고양이')
                self.assertEqual([entry['text'] for entry in chat.transcripts[pet.kind]], [fallback])
                self.assertEqual(chat.history[-1], {'role': 'assistant', 'content': fallback})
                dialogue.say_to_user.reset_mock()

                chat.key = 'fixture-key'
                config = {**DEFAULTS, 'model': 'fixture-model', 'base_url': 'https://example.com', 'tone': 'Fixture voice'}
                phrase = '선생님, 우주 고양이한테 달 한 조각만 빌려올까요?'
                notice = tr('lab.chatter_api_check')
                for responses, expected in (([phrase], phrase), ([ValueError('offline'), phrase], phrase),
                                            (['', ValueError('offline')], notice)):
                    with patch.object(chat, 'config_for', return_value=config) as persona, \
                         patch('maeagi_biseo.ui.chat.random.choice', side_effect=lambda choices: choices[-1]), \
                         patch('maeagi_biseo.ui.chat.generate_reply', side_effect=responses) as generate:
                        chat.chatter_timer.timeout.emit()
                        for _ in responses:
                            self.assertTrue(chat.chatter_request[0].wait(2000))
                            self.app.processEvents()
                        self.assertIsNone(chat.chatter_request)
                        self.assertEqual(generate.call_count, len(responses))
                        persona.assert_called_once_with(pet.kind)
                        for call in generate.call_args_list:
                            self.assertIn('Fixture voice', call.args[3])
                            self.assertIn('우주 고양이', call.args[2][0]['content'])
                    dialogue.say_to_user.assert_called_once_with(pet, expected)
                    self.assertEqual(chat.history[-1], {'role': 'assistant', 'content': phrase})
                    if expected == notice:
                        self.assertEqual(chat.transcripts[pet.kind][-1]['kind'], 'notice')
                    dialogue.say_to_user.reset_mock()

                question = '그 고양이는 왜 달에 갔어?'
                chat.config.update(model=config['model'], base_url=config['base_url'])
                chat.input.setPlainText(question)
                with patch('maeagi_biseo.ui.chat.generate_reply', return_value='달에서 낮잠을 자려고요.') as generate:
                    chat.send_button.click()
                    self.assertTrue(chat.worker.wait(2000))
                    self.app.processEvents()
                    self.assertEqual(generate.call_args.args[2][-2:], [
                        {'role': 'assistant', 'content': phrase},
                        {'role': 'user', 'content': question},
                    ])
                dialogue.say_to_user.reset_mock()

                dialogue.active = object()
                chat.chatter_timer.timeout.emit()
                self.assertIsNone(chat.chatter_request)
                dialogue.say_to_user.assert_not_called()
                store.setValue('chatter_topics', ' ; ; ')
                chat.refresh_idle_chatter()
                self.assertFalse(chat.chatter_timer.isActive())
            finally:
                chat.shutdown()
                chat.close()

    def test_fit_images_reveal_actions_and_history_dates(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            store = QSettings(str(Path(temp) / 'settings.ini'), QSettings.IniFormat)
            now = [datetime(2026, 11, 15, 1, 5, tzinfo=timezone.utc)]
            farming = FarmingStore(Path(temp) / 'records.sqlite3', clock=lambda: now[0])
            session = farming.start({'meso': 1000000, 'fragments': 10}, 'Lucid')
            now[0] += timedelta(hours=2)
            farming.finish(session['session']['id'], {'meso': 2300000, 'fragments': 17})
            dialog = SettingsDialog(DEFAULTS, '', capture_store=store, character_store=store, catalog_store=store, farming_store=farming)
            self.addCleanup(dialog.close)
            dialog.show()
            self.app.processEvents()
            dialog.fields['name'].setText('Test Name')
            self.assertIn('Test Name', dialog.preview_section.toggle.text())
            action = next(d for d in dialog.findChildren(Disclosure) if d.content.isAncestorOf(dialog.action_checks['walk']))
            action.toggle.setChecked(True)
            QTest.qWait(30)
            tabs = dialog.findChild(QTabWidget, 'settingsTabs')
            scroll = tabs.widget(0)
            rect = action.content.rect()
            point = action.content.mapTo(scroll.viewport(), rect.center())
            self.assertTrue(scroll.viewport().rect().contains(point))
            tabs.setCurrentWidget(dialog.capture_page)
            self.app.processEvents()
            for panel in (dialog.sol_erda_panel, dialog.meso_panel):
                pixmap = QPixmap(2400, 240)
                pixmap.fill(Qt.darkGray)
                panel.preview.setPixmap(pixmap)
                panel.status.setText('C:/' + 'long_capture_folder_' * 30 + '/result.json')
            dialog.resize(820, 740)
            self.app.processEvents()
            for panel in (dialog.sol_erda_panel, dialog.meso_panel):
                self.assertLessEqual(panel.preview.pixmap().width(), panel.preview.width())
                self.assertLessEqual(panel.preview.pixmap().height(), panel.preview.height())
            self.assertEqual(dialog.capture_page.horizontalScrollBar().maximum(), 0)
            tabs.setCurrentWidget(dialog.farming_panel)
            dialog.farming_panel.calendar.setSelectedDate(QDate(2026, 11, 15))
            apply_chat_theme(dialog, 'dark')
            self.app.processEvents()
            self.assertEqual(dialog.farming_panel.table.item(0, 0).text(), '2026.11.15\n10:05:00')
            self.assertEqual(dialog.farming_panel.table.item(0, 1).text(), '2026.11.15\n12:05:00')
            dialog.grab().save(str(artifact_path('settings_history_dark.png')))
