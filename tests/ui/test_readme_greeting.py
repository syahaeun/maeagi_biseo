from maeagi_biseo.resources import read_json
"""Capture a short real Gemini greeting for the README using native Qt input."""
import time
import unittest

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from maeagi_biseo.app import PETS, Pet
from maeagi_biseo.llm.settings import key_with_source
from maeagi_biseo.ui.chat import ChatWindow
from maeagi_biseo.ui.dialogue import DialogueManager
from tests.artifacts import artifact_path
from tests.evidence import Evidence


class ReadmeGreetingTests(unittest.TestCase):
    def test_real_greeting(self):
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        if app.platformName() != 'windows':
            self.skipTest('Run with QT_QPA_PLATFORM=windows')
        if not key_with_source('gemini')[0]:
            self.skipTest('Gemini API key is required')

        def store(name):
            return QSettings(str(artifact_path(f'readme/{name}.ini')), QSettings.IniFormat)

        settings = store('chat')
        settings.clear()
        settings.setValue('provider', 'gemini')
        settings.setValue('model', 'gemini-3.5-flash-lite')
        settings.setValue('appearance', 'dark')
        pet = Pet(kind=read_json('characters.json')['default'])
        manager = DialogueManager(PETS)
        manager.timer.stop()
        chat = ChatWindow(PETS, manager, settings_store=settings,
                          character_store=store('profiles'), catalog_store=store('catalog'),
                          capture_store=store('capture'))
        evidence = Evidence('readme/evidence.json')
        previous_clipboard = app.clipboard().text()
        backdrop = QWidget()
        backdrop.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        backdrop.setStyleSheet('background: #202124;')
        backdrop.resize(460, 340)
        passed = False
        try:
            chat.open_for(pet)
            QTest.qWait(400)
            prompt = '안녕, 루시드! 만나서 반가워. 짧게 인사해 줘.'
            QTest.mouseClick(chat.input, Qt.LeftButton)
            app.clipboard().setText(prompt)
            QTest.keyClick(chat.input, Qt.Key_V, Qt.ControlModifier)
            self.assertEqual(chat.input.toPlainText(), prompt)
            evidence.action('paste_greeting', model=chat.config['model'])
            QTest.keyClick(chat.input, Qt.Key_Return)
            QTest.qWait(150)
            evidence.action('press_enter_to_send')
            deadline = time.monotonic() + 110
            while chat.worker is not None and time.monotonic() < deadline:
                QTest.qWait(100)
            self.assertIsNone(chat.worker, 'Timed out waiting for Gemini')
            self.assertEqual(len(chat.history), 2, chat.status.text())
            answer = chat.history[-1]['content']
            self.assertTrue(answer.strip())
            self.assertEqual(chat.history[0]['content'], prompt)
            bubble = manager.bubble(pet)
            self.assertTrue(bubble.isVisible())
            self.assertEqual(''.join(bubble.pages), answer)
            QTest.qWait(250)
            evidence.screenshot(chat, 'readme-greeting.png')
            # Stage a plain background so the desktop crop contains no unrelated
            # windows or private desktop content. Capture actual on-screen pixels.
            pet.timer.stop()
            bubble.page_timer.stop()
            area = pet.screen().availableGeometry()
            backdrop.move(area.center().x() - backdrop.width() // 2,
                          area.center().y() - backdrop.height() // 2)
            backdrop.show()
            backdrop.raise_()
            pet.move(backdrop.x() + (backdrop.width() - pet.width()) // 2,
                     backdrop.y() + 150)
            pet.raise_()
            bubble.follow()
            bubble.raise_()
            QTest.qWait(350)
            rect = backdrop.geometry()
            shot = backdrop.screen().grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
            self.assertFalse(shot.isNull())
            path = artifact_path('ui/readme-greeting-bubble.png')
            self.assertTrue(shot.save(str(path)))
            evidence.data['screenshots'].append({
                'path': str(path), 'capture_method': 'native_desktop_region',
                'staging': 'plain background behind real pet and reply bubble'})
            evidence.action('received_real_greeting', answer_characters=len(answer))
            passed = True
        finally:
            evidence.finish(passed)
            app.clipboard().setText(previous_clipboard)
            chat.shutdown()
            chat.close()
            for bubble in manager.bubbles.values():
                bubble.page_timer.stop()
                bubble.close()
            pet.timer.stop()
            if pet in PETS:
                PETS.remove(pet)
            pet.close()
            backdrop.close()


if __name__ == '__main__':
    unittest.main()
