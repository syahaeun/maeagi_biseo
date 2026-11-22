import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QPlainTextEdit
from maeagi_biseo.ui.message_input import MessageInput
from maeagi_biseo.resources import tr
from tests.artifacts import artifact_path


class MessageInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = MessageInput()
        self.editor.resize(460, 100)
        self.editor.setPlaceholderText(tr('chat.input_placeholder'))
        self.editor.show()
        self.editor.setFocus()
        self.sent = QSignalSpy(self.editor.sendRequested)

    def tearDown(self):
        self.editor.close()

    def test_enter_sends_without_inserting_a_newline(self):
        QTest.keyClicks(self.editor, 'hello')
        QTest.keyClick(self.editor, Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.sent.count(), 1)
        self.assertEqual(self.editor.toPlainText(), 'hello')

    def test_shift_enter_inserts_newline_without_sending(self):
        QTest.keyClicks(self.editor, 'hello')
        QTest.keyClick(self.editor, Qt.Key_Return, Qt.ShiftModifier)
        QTest.keyClicks(self.editor, 'world')
        self.assertEqual(self.editor.toPlainText(), 'hello\nworld')
        self.assertEqual(self.sent.count(), 0)

    def test_empty_enter_does_not_send_or_insert_newline(self):
        QTest.keyClick(self.editor, Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.sent.count(), 0)
        self.assertEqual(self.editor.toPlainText(), '')

    def test_insert_key_does_not_enable_overwrite(self):
        QTest.keyClicks(self.editor, 'ac')
        QTest.keyClick(self.editor, Qt.Key_Left)
        QTest.keyClick(self.editor, Qt.Key_Insert)
        QTest.keyClicks(self.editor, 'b')
        self.assertFalse(self.editor.overwriteMode())
        self.assertEqual(self.editor.toPlainText(), 'abc')

    def test_hangul_preedit_hides_placeholder_and_cancel_restores_it(self):
        event = QInputMethodEvent('\u3141', [])
        QApplication.sendEvent(self.editor, event)
        self.assertEqual(self.editor.toPlainText(), '')
        self.assertEqual(self.editor.placeholderText(), '')
        self.assertTrue(self.editor.grab().save(str(artifact_path('input_hangul_preedit.png'))))
        QApplication.sendEvent(self.editor, QInputMethodEvent('', []))
        self.assertEqual(self.editor.placeholderText(), tr('chat.input_placeholder'))

    def test_committed_hangul_can_be_sent(self):
        QApplication.sendEvent(self.editor, QInputMethodEvent('\u3141', []))
        committed = QInputMethodEvent('', [])
        committed.setCommitString('\ub9c8')
        QApplication.sendEvent(self.editor, committed)
        QTest.keyClick(self.editor, Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.editor.toPlainText(), '\ub9c8')
        self.assertEqual(self.sent.count(), 1)

    def test_hint_changes_do_not_touch_native_placeholder_or_document_cursor(self):
        self.assertEqual(QPlainTextEdit.placeholderText(self.editor), '')
        cursor = self.editor.textCursor().position()
        QApplication.sendEvent(self.editor, QInputMethodEvent('가', []))
        self.assertFalse(self.editor._hint_label.isVisible())
        self.assertEqual(QPlainTextEdit.placeholderText(self.editor), '')
        self.assertEqual(self.editor.textCursor().position(), cursor)
        QApplication.sendEvent(self.editor, QInputMethodEvent('', []))
        self.assertTrue(self.editor._hint_label.isVisible())
        self.assertEqual(QPlainTextEdit.placeholderText(self.editor), '')
        self.assertEqual(self.editor.toPlainText(), '')


if __name__ == '__main__':
    unittest.main()
