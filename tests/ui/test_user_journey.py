"""Native Qt mouse/keyboard journey against the real Gemini API.

Run in a separate process: python -m tools.run_tests --suite ui
No mock responses and no direct calls to send()/test_connection() in the scenario.
"""
import unittest
import time
from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QTabWidget
from maeagi_biseo.app import Pet, PETS
from maeagi_biseo.ui.chat import ChatWindow, SettingsDialog
from maeagi_biseo.ui.dialogue import DialogueManager
from maeagi_biseo.llm.settings import key_with_source
from maeagi_biseo.resources import read_json, tr
from tests.artifacts import artifact_path
from tests.evidence import Evidence


class UserJourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        if cls.app.platformName() != 'windows':
            raise unittest.SkipTest('Native desktop required; run --suite ui in a separate process')
        if not key_with_source('gemini')[0]:
            raise unittest.SkipTest(tr('api.key_required'))

    def wait_until(self, condition, timeout=105):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                self.fail('Timed out waiting for the real UI/API operation')
            QTest.qWait(100)

    def click(self, widget, scroll=None):
        def in_view():
            return widget.isVisible() and (scroll is None or scroll.viewport().rect().contains(
                widget.mapTo(scroll.viewport(), widget.rect().center())))
        if scroll is not None and not in_view():
            QTest.keyClick(scroll.verticalScrollBar(), Qt.Key_Home)
            for _ in range(12):
                if in_view():
                    break
                QTest.keyClick(scroll.verticalScrollBar(), Qt.Key_PageDown)
                QTest.qWait(80)
        self.assertTrue(in_view(), f'Target {widget.objectName()} visible={widget.isVisible()} '
            f'center={widget.mapTo(scroll.viewport(), widget.rect().center()) if scroll else widget.rect().center()} '
            f'viewport={scroll.viewport().rect() if scroll else None} '
            f'scroll={scroll.verticalScrollBar().value() if scroll else None}')
        QTest.mouseClick(widget, Qt.LeftButton, pos=widget.rect().center(), delay=60)
        QTest.qWait(120)

    def configure_through_ui(self):
        dialog = QApplication.activeModalWidget()
        try:
            self.assertIsInstance(dialog, SettingsDialog)
            tabs = dialog.findChild(QTabWidget, 'settingsTabs')
            nav = dialog.navigation
            api_index = tabs.indexOf(dialog.api_scroll)
            QTest.mouseClick(nav.viewport(), Qt.LeftButton, pos=nav.visualItemRect(nav.item(api_index)).center())
            QTest.qWait(150)
            self.assertIs(tabs.currentWidget(), dialog.api_scroll)
            self.click(dialog.provider)
            view = dialog.provider.view()
            first_item = view.model().index(0, 0)
            QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.visualRect(first_item).center())
            QTest.qWait(150)
            self.assertTrue(dialog.isVisible())
            self.evidence.action('choose_provider', provider='gemini')
            self.click(dialog.load_key_button, dialog.api_scroll)
            self.assertTrue(dialog.key.text())
            self.evidence.screenshot(dialog, '02_settings.png')
            self.click(dialog.models_button, dialog.api_scroll)
            self.wait_until(lambda: dialog.test_worker is None)
            self.assertGreater(dialog.model_combo.count(), 0, dialog.test_output.toPlainText())
            self.evidence.action('load_real_models', model=dialog.fields['model'].text(), count=dialog.model_combo.count())
            self.click(dialog.test_button, dialog.api_scroll)
            self.wait_until(lambda: dialog.test_worker is None)
            self.assertTrue(dialog.test_output.toPlainText().startswith(
                tr('settings.test_success', answer='').strip()), dialog.test_output.toPlainText())
            self.evidence.action('real_connection_test', result='success')
            self.evidence.screenshot(dialog, '03_connection_success.png')
            buttons = dialog.findChild(QDialogButtonBox, 'settingsActions')
            self.click(buttons.button(QDialogButtonBox.Save))
            self.evidence.action('save_settings')
        except BaseException as exc:
            self.dialog_error = exc
            if dialog:
                self.evidence.screenshot(dialog, 'failure_settings.png')
                if dialog.test_worker:
                    dialog.test_worker.wait()
                # Test-only cleanup after failure; not counted as a user action.
                dialog.reject()

    def test_settings_real_api_chat_and_bubble_by_mouse_and_keyboard(self):
        self.evidence = Evidence()
        self.dialog_error = None
        scenario = read_json('test_journey.json')
        pet = Pet(kind='robot')
        manager = DialogueManager(PETS)
        store = QSettings(str(artifact_path('ui/settings.ini')), QSettings.IniFormat)
        chat = ChatWindow(PETS, manager, settings_store=store)
        chat.open_for(pet)
        QTest.qWait(300)
        passed = False
        error = None
        try:
            self.evidence.screenshot(chat, '01_start.png')
            QTimer.singleShot(150, self.configure_through_ui)
            self.click(chat.settings_button)
            if self.dialog_error:
                raise self.dialog_error
            for index, prompt in enumerate((scenario['first_message'], scenario['followup_message']), 1):
                self.click(chat.input)
                QTest.keyClicks(chat.input, prompt, delay=12)
                self.assertEqual(chat.input.toPlainText(), prompt)
                self.evidence.action('type_message', turn=index, method='mouse_click_and_keyboard')
                self.evidence.screenshot(chat, f'04_typed_{index}.png')
                if index == 1:
                    QTest.keyClick(chat.input, Qt.Key_Return)
                    QTest.qWait(150)
                    self.evidence.action('press_enter_to_send', turn=index)
                else:
                    self.click(chat.send_button)
                self.wait_until(lambda: chat.worker is None)
                self.assertEqual(len(chat.history), index * 2, chat.status.text())
                answer = chat.history[-1]['content']
                bubble = manager.bubble(pet)
                self.assertTrue(answer.strip())
                self.assertTrue(bubble.isVisible())
                self.assertEqual(''.join(bubble.pages), answer)
                self.evidence.action('send_real_message', turn=index, answer_characters=len(answer))
                self.evidence.screenshot(chat, f'05_reply_{index}.png')
                self.evidence.screenshot(bubble, f'06_bubble_{index}.png')
            passed = True
        except BaseException as exc:
            error = exc
            self.evidence.screenshot(chat, 'failure_chat.png')
            raise
        finally:
            self.evidence.finish(passed, error)
            chat.shutdown()
            manager.timer.stop()
            for bubble in manager.bubbles.values():
                bubble.page_timer.stop()
                bubble.close()
            pet.timer.stop()
            chat.close()
            PETS.remove(pet)
            pet.close()


if __name__ == '__main__':
    unittest.main()
