"""Pet context menus reflect allowed actions and keep management in settings."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import Mock, patch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from maeagi_biseo.app import Pet
from maeagi_biseo.resources import tr


class PetMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])

    def test_only_enabled_actions_and_close_commands_are_visible(self):
        pet = Pet(kind='robot')
        pet.timer.stop()
        pet.topmost_timer.stop()
        try:
            pet.set_allowed_actions({'idle', 'sleep'})
            menu = pet.action_menu()
            labels = [a.text() for a in menu.actions() if not a.isSeparator()]
            self.assertEqual(labels, [tr('action.idle'), tr('action.sleep'), tr('menu.pause'), tr('menu.focus'), tr('menu.close_pet'), tr('menu.quit')])
            pause = next(a for a in menu.actions() if a.text() == tr('menu.pause'))
            pause.trigger()
            self.assertTrue(pet.paused)
            pause.trigger()
            self.assertFalse(pet.paused)
            self.assertFalse(any(a.menu() is not None for a in menu.actions()))
            next(a for a in menu.actions() if a.text() == tr('action.sleep')).trigger()
            self.assertEqual(pet.state, 'sleep')
            menu.deleteLater()
            pet.set_allowed_actions({'idle', 'walk', 'hop', 'climb', 'talk'})
            menu = pet.action_menu()
            labels = [a.text() for a in menu.actions()]
            self.assertNotIn(tr('action.sleep'), labels)
            self.assertIn(tr('action.hop'), labels)
            self.assertIn(tr('menu.climb'), labels)
            self.assertIn(tr('menu.friend_chat'), labels)
            menu.deleteLater()
        finally:
            pet.close_pet()

    def test_double_click_opens_chat_with_this_pet(self):
        pet = Pet(kind='robot')
        pet.timer.stop()
        pet.topmost_timer.stop()
        chat = Mock()
        try:
            pet.show()
            QTest.qWaitForWindowExposed(pet)
            centre = pet.rect().center()
            with patch('maeagi_biseo.app.CHAT', chat):
                QTest.mouseClick(pet, Qt.LeftButton, pos=centre)
                chat.open_for.assert_not_called()
                QTest.mouseDClick(pet, Qt.LeftButton, pos=centre)
                chat.open_for.assert_called_once_with(pet)
                QTest.mouseRelease(pet, Qt.LeftButton, pos=centre)
                QTest.mouseDClick(pet, Qt.RightButton, pos=centre)
            chat.open_for.assert_called_once_with(pet)
            self.assertIsNone(pet.drag_offset)
            self.assertFalse(pet.drag_active)
            self.assertNotEqual(pet.state, 'drag')
        finally:
            pet.close_pet()
