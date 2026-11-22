import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QLabel
from maeagi_biseo.core.character_catalog import registered_characters, set_default, preferences
from maeagi_biseo.core.sprites import CharacterInfo, default_character
from maeagi_biseo.ui.chat import ChatWindow
from tests.artifacts import artifact_path


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent)
        self.store = QSettings(str(Path(self.temp.name) / 'catalog.ini'), QSettings.IniFormat)
        self.characters = {key: CharacterInfo(key, label, Path(self.temp.name) / key)
                           for key, label in [('robot', 'Robot'), ('bunny', 'Bunny'), ('user_lucid', 'Lucid')]}

    def tearDown(self):
        self.temp.cleanup()

    def test_lucid_default_and_builtin_exclusion_persist(self):
        with patch('maeagi_biseo.core.sprites.available_characters', return_value=self.characters), patch('maeagi_biseo.core.character_catalog.catalog_store', return_value=self.store):
            set_default('user_lucid', hidden={'robot', 'bunny'})
            self.assertEqual(list(registered_characters()), ['user_lucid'])
            self.assertEqual(default_character(), 'user_lucid')
            reopened = QSettings(self.store.fileName(), QSettings.IniFormat)
            self.assertEqual(preferences(reopened), ('user_lucid', {'robot', 'bunny'}))

    def test_chat_opens_unsummoned_character_without_spawning(self):
        robot = Mock(kind='robot')
        lucid = Mock(kind='user_lucid')
        fixture = Path(__file__).resolve().parents[1] / 'fixtures' / 'characters' / 'robot'
        catalog = {'robot': CharacterInfo('robot', 'Robot', fixture)}
        with patch('maeagi_biseo.ui.chat.registered_characters', side_effect=lambda *args: dict(catalog)):
            chat = ChatWindow([robot], Mock(), self.store, self.store, self.store,
                              avatar_root=Path(self.temp.name) / 'avatars')
            try:
                chat.open_for(robot)
                self.assertEqual(chat.target_selector.count(), 1)
                self.assertEqual(chat.contacts.count(), 1)
                self.assertTrue(chat.profile_button.isEnabled())
                with patch('maeagi_biseo.ui.chat.ChatAvatarDialog') as dialog:
                    dialog.return_value.exec.return_value = QDialog.Accepted
                    dialog.return_value.crop.return_value = (150, 10, -5)
                    dialog.return_value.image_choice = None
                    chat.profile_button.click()
                self.assertEqual(json.loads(str(self.store.value('chat_avatar_crops')))['robot'], [150, 10, -5])
                chat.add_message('Robot', 'previous reply')
                chat.add_message('Record', 'saved farming details', kind='record')
                chat.input.setPlainText('robot draft')
                catalog['user_lucid'] = self.characters['user_lucid']
                chat.refresh_targets()
                self.assertGreaterEqual(chat.target_selector.findData('user_lucid'), 0)
                with patch('maeagi_biseo.app.spawn_pet', return_value=lucid) as spawn:
                    chat.contacts.setCurrentItem(chat.contact_items['user_lucid'])
                    self.assertIsNone(chat.target)
                    self.assertEqual(chat.current_config()['name'], 'Lucid')
                    chat.open_for(identifier='user_lucid')
                    spawn.assert_not_called()
                    chat.pending = 'hello'
                    chat.receive('reply from the unsummoned character')
                    chat.dialogue.say_to_user.assert_not_called()
                    self.assertTrue(chat.summon_button.isEnabled())
                    chat.summon_button.click()
                    spawn.assert_called_once_with(kind='user_lucid')
                    self.assertFalse(chat.summon_button.isEnabled())
                self.assertIs(chat.target, lucid)
                self.assertEqual(chat.current_config()['name'], 'Lucid')
                self.assertFalse(chat.input.toPlainText())
                chat.contacts.setCurrentItem(chat.contact_items['robot'])
                self.assertEqual(chat.input.toPlainText(), 'robot draft')
                self.assertEqual(chat.findChild(QLabel, 'chatRecord').text(), 'saved farming details')
            finally:
                chat.target_refresh_timer.stop()
                chat.close()


if __name__ == '__main__':
    unittest.main()
