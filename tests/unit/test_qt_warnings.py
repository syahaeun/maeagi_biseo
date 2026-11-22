from maeagi_biseo.resources import read_json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtCore import Qt, QMimeData, qInstallMessageHandler
from PySide6.QtGui import QInputMethodEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from maeagi_biseo.ui.chat import PersonaTextEdit, STYLE
from maeagi_biseo.ui.message_input import MessageInput


class QtWarningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.warnings = []
        self.handler = lambda kind, context, message: self.warnings.append(message)
        self.old_handler = qInstallMessageHandler(self.handler)
        self.host = QWidget()
        self.host.setStyleSheet(STYLE)
        self.layout = QVBoxLayout(self.host)

    def tearDown(self):
        self.host.close()
        qInstallMessageHandler(self.old_handler)

    def assert_no_cursor_or_font_warnings(self):
        relevant = [message for message in self.warnings if 'QTextCursor::setPosition' in message or 'QFont::setPointSize' in message]
        self.assertEqual(relevant, [])

    def test_persona_limit_paste_undo_replacement_and_hangul_commit(self):
        editor = PersonaTextEdit('')
        self.layout.addWidget(editor)
        self.host.show()
        editor.setFocus()
        for text in ('a' * 501, '가' * 600, '😀' * 510, '가\n' * 300):
            editor.setPlainText(text)
            self.app.processEvents()
            self.assertLessEqual(len(editor.toPlainText()), 500)
            editor.undo()
            editor.clear()
            editor.insertPlainText('a' * 499)
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.End)
            editor.setTextCursor(cursor)
            preedit = QInputMethodEvent('가', [])
            QApplication.sendEvent(editor, preedit)
            commit = QInputMethodEvent('', [])
            commit.setCommitString('가나')
            QApplication.sendEvent(editor, commit)
            self.app.processEvents()
            self.assertLessEqual(len(editor.toPlainText()), 500)
            editor.selectAll()
            paste = QMimeData()
            paste.setText('b' * 700)
            editor.insertFromMimeData(paste)
            self.app.processEvents()
            self.assertLessEqual(len(editor.toPlainText()), 500)
        self.assert_no_cursor_or_font_warnings()

    def test_chat_hangul_send_clear_and_next_composition(self):
        editor = MessageInput()
        self.layout.addWidget(editor)
        editor.sendRequested.connect(editor.clear)
        self.host.show()
        editor.setFocus()
        for _ in range(5):
            QApplication.sendEvent(editor, QInputMethodEvent('ㄱ', []))
            commit = QInputMethodEvent('', [])
            commit.setCommitString('가')
            QApplication.sendEvent(editor, commit)
            QTest.keyClick(editor, Qt.Key_Return)
            self.app.processEvents()
            self.assertEqual(editor.toPlainText(), '')
        self.assert_no_cursor_or_font_warnings()

    def test_styled_widgets_use_positive_point_font_sizes(self):
        editor = MessageInput()
        self.layout.addWidget(editor)
        self.host.show()
        self.app.processEvents()
        self.assertGreater(editor.font().pointSizeF(), 0)
        self.assert_no_cursor_or_font_warnings()

    def test_clear_during_preedit_resets_composition_and_accepts_new_input(self):
        editor = MessageInput()
        editor.setPlaceholderText('Message')
        self.layout.addWidget(editor)
        self.host.show()
        QApplication.sendEvent(editor, QInputMethodEvent('가', []))
        editor.clear()
        self.assertEqual(editor._preedit, '')
        self.assertEqual(editor.placeholderText(), 'Message')
        commit = QInputMethodEvent('', [])
        commit.setCommitString('나')
        QApplication.sendEvent(editor, commit)
        self.assertEqual(editor.toPlainText(), '나')
        self.assert_no_cursor_or_font_warnings()

    def test_hangul_composition_while_pet_climbs_wall(self):
        from maeagi_biseo.app import Pet, PETS
        pet = Pet(kind=read_json('characters.json')['default'])
        pet.allowed_actions = None
        pet.attach_wall(1)
        editor = MessageInput()
        editor.setPlaceholderText('Message')
        self.layout.addWidget(editor)
        self.host.show()
        editor.setFocus()
        try:
            before = pet.ypos
            for _ in range(5):
                QApplication.sendEvent(editor, QInputMethodEvent('가', []))
                QTest.qWait(40)
                commit = QInputMethodEvent('', [])
                commit.setCommitString('가')
                QApplication.sendEvent(editor, commit)
            self.assertEqual(editor.toPlainText(), '가' * 5)
            self.assertLess(pet.ypos, before)
            self.assert_no_cursor_or_font_warnings()
        finally:
            pet.timer.stop()
            pet.topmost_timer.stop()
            PETS.remove(pet)
            pet.close()


if __name__ == '__main__':
    unittest.main()
