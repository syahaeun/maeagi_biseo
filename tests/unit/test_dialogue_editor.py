import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from maeagi_biseo.core.dialogue_store import load_scripts, save_scripts
from maeagi_biseo.ui.dialogue_editor import DialogueEditor
from maeagi_biseo.ui.dialogue import DialogueManager
from tests.artifacts import artifact_path


class DialogueEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_drafts_save_delete_reset_and_invalid_text(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            store = QSettings(str(Path(temp) / 'dialogue.ini'), QSettings.IniFormat)
            original = load_scripts(store)
            editor = DialogueEditor(store)
            self.addCleanup(editor.deleteLater)
            editor.editor.setPlainText('first\nsecond')
            self.assertEqual(load_scripts(store), original)
            editor.selector.setCurrentIndex(1)
            self.assertEqual(editor.scripts[0], ['first', 'second'])
            save_scripts(editor.values(), store)
            self.assertEqual(load_scripts(store)[0], ['first', 'second'])
            editor.add_script()
            with self.assertRaises(ValueError):
                editor.values()
            editor.delete_script()
            editor.reset_scripts()
            self.assertEqual(editor.values(), original)
            save_scripts([], store)
            self.assertEqual(load_scripts(store), [])

    def test_manager_uses_saved_lines_and_empty_list_disables_dialogue(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            store = QSettings(str(Path(temp) / 'dialogue.ini'), QSettings.IniFormat)
            a, b = Mock(), Mock()
            a.x.return_value, b.x.return_value = 0, 100
            manager = DialogueManager([a, b], settings_store=store)
            self.addCleanup(manager.timer.stop)
            save_scripts([['one', 'two']], store)
            with patch.object(manager, 'bubble', return_value=Mock()) as bubble:
                manager.start(a, b)
                self.assertEqual(manager.active[2], ['one', 'two'])
                bubble.return_value.say.assert_called_with('one')
                manager.finish()
                save_scripts([], store)
                manager.start(a, b)
                self.assertIsNone(manager.active)
