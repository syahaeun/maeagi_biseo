"""Real Gemini integration checks. No simulated HTTP server or canned replies."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer
from maeagi_biseo.ui.chat import SettingsDialog, ChatWindow
from maeagi_biseo.ui.dialogue import DialogueManager
from maeagi_biseo.llm.settings import provider_defaults, key_with_source
from maeagi_biseo.app import Pet, PETS
from maeagi_biseo.resources import DEFAULTS, tr


class GeminiLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])
        cls.key, cls.source = key_with_source('gemini')
        if not cls.key:
            raise unittest.SkipTest(tr('api.key_required'))
        cls.config = {**DEFAULTS, **provider_defaults('gemini')}

    def wait_worker(self, owner, attribute):
        worker = getattr(owner, attribute)
        self.assertIsNotNone(worker)
        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        QTimer.singleShot((int(self.config['timeout_seconds']) + 10) * 1000, loop.quit)
        loop.exec()
        self.app.processEvents()
        self.assertIsNone(getattr(owner, attribute))

    def test_real_model_listing_and_settings_reply(self):
        dialog = SettingsDialog(self.config, self.key)
        try:
            dialog.load_models()
            self.wait_worker(dialog, 'test_worker')
            self.assertGreater(dialog.model_combo.count(), 0, dialog.test_output.toPlainText())
            self.assertTrue(dialog.fields['model'].text().strip())
            dialog.test_connection()
            self.wait_worker(dialog, 'test_worker')
            self.assertTrue(dialog.test_output.toPlainText().startswith(
                tr('settings.test_success', answer='').strip()), dialog.test_output.toPlainText())
        finally:
            if dialog.test_worker:
                dialog.test_worker.wait()
            dialog.close()

    def test_real_chat_followup_and_pet_bubble(self):
        pet = Pet(kind='robot')
        pet.timer.stop()
        manager = DialogueManager(PETS)
        manager.timer.stop()
        chat = ChatWindow(PETS, manager)
        chat.config = dict(self.config)
        chat.key = self.key
        chat.target = pet
        try:
            for prompt in (tr('settings.test_prompt'), tr('cli.followup_prompt')):
                chat.input.setPlainText(prompt)
                chat.send()
                self.wait_worker(chat, 'worker')
                self.assertTrue(chat.history, chat.status.text())
                self.assertEqual(chat.history[-2]['content'], prompt, chat.status.text())
                answer = chat.history[-1]['content']
                self.assertTrue(answer.strip())
                self.assertEqual(''.join(manager.bubble(pet).pages), answer)
            self.assertEqual(len(chat.history), 4)
        finally:
            chat.shutdown()
            for bubble in manager.bubbles.values():
                bubble.page_timer.stop()
                bubble.close()
                bubble.deleteLater()
            chat.close()
            PETS.remove(pet)
            pet.close()


if __name__ == '__main__':
    unittest.main()
