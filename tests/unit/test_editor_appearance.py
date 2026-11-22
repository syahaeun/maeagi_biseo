from maeagi_biseo.resources import read_json
"""Bundled character appearance and menu rendering without user writes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import Mock, patch
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget
from maeagi_biseo.ui.character_editor import CharacterEditor
from maeagi_biseo.ui.chat_theme import apply_chat_theme
from maeagi_biseo.app import Pet
from tests.artifacts import artifact_path


class EditorAppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_character_editor_and_menu_follow_dark_theme(self):
        parent = QWidget()
        apply_chat_theme(parent, 'dark')
        editor = CharacterEditor(parent, selected_identifier=read_json('characters.json')['default'])
        try:
            self.assertEqual(editor.characters.currentData(), read_json('characters.json')['default'])
            self.assertEqual(editor.property('appearance'), 'dark')
            editor.show()
            self.app.processEvents()
            editor.grab().save(str(artifact_path('character_editor_default_character_dark.png')))
            apply_chat_theme(editor, 'light')
            self.app.processEvents()
            editor.grab().save(str(artifact_path('character_editor_default_character_light.png')))
            chat = Mock()
            chat.theme_selector.currentData.return_value = 'dark'
            with patch('maeagi_biseo.app.CHAT', chat):
                pet = Pet(kind=read_json('characters.json')['default'])
                pet.timer.stop()
                pet.topmost_timer.stop()
                try:
                    menu = pet.action_menu()
                    self.assertEqual(menu.property('appearance'), 'dark')
                    menu.show()
                    self.app.processEvents()
                    menu.grab().save(str(artifact_path('pet_menu_dark.png')))
                    apply_chat_theme(menu, 'light')
                    self.app.processEvents()
                    menu.grab().save(str(artifact_path('pet_menu_light.png')))
                    menu.close()
                    menu.deleteLater()
                finally:
                    pet.close_pet()
        finally:
            editor.reject()
            self.assertFalse(editor.timer.isActive())
            editor.deleteLater()
            parent.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
