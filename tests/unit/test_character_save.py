"""Offscreen widget checks for asynchronous saving and its busy dialog."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox
import shiboken6

from tests.artifacts import artifact_path
from maeagi_biseo.ui.character_editor import CharacterEditor
from maeagi_biseo.core.character_store import save_character
from maeagi_biseo.core.sprites import SpritePack, CharacterInfo


class CharacterSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_editor(self):
        with patch('maeagi_biseo.ui.character_editor.registered_characters', return_value={}):
            editor = CharacterEditor()
        editor.name.setText('저장 검사')
        source = Path(__file__).resolve().parents[1] / 'fixtures/xbrz/yoshi-transparent.png'
        editor.animations = {'idle': {'frames': [str(source)], 'frame_ms': 210}}
        editor.smoothing_box.setCurrentIndex(editor.smoothing_box.findData(3))
        editor.show()
        self.app.processEvents()
        return editor

    def wait_for(self, condition):
        deadline = time.monotonic() + 8
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(condition(), 'Async save did not finish')

    def destroy(self, editor):
        if editor.save_worker is not None:
            self.wait_for(lambda: editor.save_worker is None)
        editor.close()
        shiboken6.delete(editor)

    def test_spinner_animates_during_real_worker_save_and_blocks_close(self):
        editor = self.make_editor()
        release = threading.Event()
        entered = threading.Event()
        thread_ids = []
        root = artifact_path('character_save/characters')

        def delayed(*args, **kwargs):
            thread_ids.append(threading.get_ident())
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test save gate timed out')
            return save_character(*args, **kwargs)

        try:
            with patch('maeagi_biseo.ui.character_editor.save_character', side_effect=delayed) as save, \
                    patch('maeagi_biseo.core.character_store.user_character_root', return_value=root):
                QTest.mouseClick(editor.footer.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.wait_for(entered.is_set)
                loading = editor.saving_dialog
                self.assertTrue(loading.isVisible())
                angle = loading.spinner.angle
                QTest.qWait(100)
                self.assertNotEqual(loading.spinner.angle, angle)
                self.assertNotEqual(thread_ids[0], threading.get_ident())
                self.assertFalse(editor.footer.isEnabled())
                QTest.keyClick(loading, Qt.Key_Escape)
                editor.close()
                self.assertTrue(editor.isVisible())
                self.assertTrue(loading.isVisible())
                QTest.mouseClick(editor.footer.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.assertEqual(save.call_count, 1)
                evidence = artifact_path('character_save/saving_dialog.png')
                loading.grab().save(str(evidence))
                release.set()
                self.wait_for(lambda: editor.save_worker is None)
                self.assertIsNone(editor.saving_dialog)
                self.assertEqual(editor.result(), QDialog.Accepted)
                pack = SpritePack(CharacterInfo(editor.identifier, 'test', root / editor.identifier))
                self.assertEqual(pack.animations['idle'][1], 210)
        finally:
            release.set()
            self.destroy(editor)

    def test_failure_restores_editor_and_allows_retry(self):
        editor = self.make_editor()
        try:
            with patch('maeagi_biseo.ui.character_editor.save_character', side_effect=OSError('test failure')), \
                    patch('maeagi_biseo.ui.character_editor.QMessageBox.warning') as warning:
                QTest.mouseClick(editor.footer.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.wait_for(lambda: editor.save_worker is None)
                warning.assert_called_once()
                self.assertIsNone(editor.saving_dialog)
                self.assertTrue(editor.isVisible())
                self.assertTrue(editor.footer.isEnabled())
                self.assertTrue(editor.timer.isActive())
            with patch('maeagi_biseo.ui.character_editor.save_character', return_value='saved'):
                QTest.mouseClick(editor.footer.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.wait_for(lambda: editor.save_worker is None)
                self.assertEqual(editor.identifier, 'saved')
                self.assertEqual(editor.result(), QDialog.Accepted)
        finally:
            self.destroy(editor)
