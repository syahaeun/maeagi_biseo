import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QTabWidget
from maeagi_biseo.app import Pet, PETS
from maeagi_biseo.core.character_profiles import load_profiles, save_profiles, persona_for, allowed_for
from maeagi_biseo.core.sprites import STATES
from maeagi_biseo.resources import DEFAULTS, tr
from maeagi_biseo.ui.chat import SettingsDialog, ChatWindow
from tests.artifacts import artifact_path


class CharacterProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])
        from PySide6.QtGui import QFontDatabase
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent)
        self.store = QSettings(str(Path(self.temp.name) / 'profiles.ini'), QSettings.IniFormat)

    def tearDown(self):
        self.temp.cleanup()

    def test_profile_switch_save_and_cancel_are_independent(self):
        dialog = SettingsDialog(DEFAULTS, '', character_store=self.store, capture_store=self.store, catalog_store=self.store)
        try:
            for identifier, name, disabled in (('robot', '로봇 이름', 'walk'), ('bunny', '토끼 이름', 'sleep')):
                dialog.character_selector.setCurrentIndex(dialog.character_selector.findData(identifier))
                dialog.fields['name'].setText(name)
                dialog.action_checks[disabled].setChecked(False)
            dialog.character_selector.setCurrentIndex(dialog.character_selector.findData('robot'))
            self.assertEqual(dialog.fields['name'].text(), '로봇 이름')
            self.assertFalse(dialog.action_checks['walk'].isChecked())
            self.assertTrue(dialog.action_checks['sleep'].isChecked())
            self.assertNotIn('robot', load_profiles(self.store))
            self.assertNotIn('bunny', load_profiles(self.store))
            dialog.save()
            self.assertEqual(persona_for('bunny', store=self.store)['name'], '토끼 이름')
            self.assertNotIn('walk', allowed_for('robot', self.store))
            self.assertIn('walk', allowed_for('bunny', self.store))
            self.assertEqual(dialog.findChild(QTabWidget, 'settingsTabs').tabText(0), tr('settings.persona_tab'))
            dialog.show()
            self.app.processEvents()
            dialog.grab().save(str(artifact_path('character_settings_preview.png')))
        finally:
            dialog.close()
        saved = load_profiles(self.store)
        cancelled = SettingsDialog(DEFAULTS, '', character_store=self.store, capture_store=self.store, catalog_store=self.store)
        cancelled.fields['name'].setText('취소할 이름')
        cancelled.reject()
        self.assertEqual(load_profiles(self.store), saved)

    def test_persona_limits_and_multiline_fields(self):
        from PySide6.QtWidgets import QLabel
        dialog = SettingsDialog(DEFAULTS, '', character_store=self.store, capture_store=self.store, catalog_store=self.store)
        try:
            for field in ('name', 'personality', 'tone', 'interests'):
                dialog.fields[field].setText('가' * 501)
                self.assertEqual(len(dialog.fields[field].text()), 20 if field == 'name' else 500)
                if field == 'name':
                    self.assertEqual(dialog.fields[field].maxLength(), 20)
                else:
                    self.assertGreaterEqual(dialog.fields[field].minimumHeight(), dialog.fields[field].fontMetrics().lineSpacing() * 4)
            dialog.extra.setPlainText('나' * 501)
            self.assertEqual(len(dialog.extra.toPlainText()), 500)
            dialog.extra.setPlainText('가\n' * 250 + '초과')
            self.assertEqual(len(dialog.extra.toPlainText()), 500)
            labels = [label.text() for label in dialog.findChildren(QLabel)]
            self.assertIn(tr('settings.limit_label', label=tr('settings.name'), limit=20), labels)
            for key in ('settings.personality', 'settings.tone', 'settings.interests'):
                self.assertIn(tr('settings.field_count', label=tr(key), count=500, limit=500), labels)
        finally:
            dialog.close()

    def test_restricted_actions_keep_physics_and_stop_autonomous_actions(self):
        pet = Pet(kind='robot')
        pet.timer.stop()
        pet.topmost_timer.stop()
        try:
            pet.set_allowed_actions({'idle', 'sleep'})
            for _ in range(30):
                pet.choose()
                self.assertIn(pet.state, ('idle', 'sleep'))
            pet.start_jump()
            self.assertEqual(pet.motion, 'ground')
            pet.request_climb()
            self.assertFalse(pet.climb_requested)
            self.assertFalse(pet.can_talk())
            pet.ypos -= 100
            pet.begin_fall()
            before = pet.ypos
            pet.tick()
            self.assertGreater(pet.ypos, before)
            self.assertFalse(pet.action_allowed('fall'))
        finally:
            PETS.remove(pet)
            pet.close()

    def test_chat_uses_target_persona_and_separate_histories(self):
        save_profiles({'robot': {'persona': {'name': '알파', 'tone': '존댓말'}},
                       'bunny': {'persona': {'name': '베타', 'tone': '반말'}}}, self.store)
        robot, bunny = Mock(kind='robot'), Mock(kind='bunny')
        chat_store = QSettings(str(Path(self.temp.name) / 'chat.ini'), QSettings.IniFormat)
        chat = ChatWindow([robot, bunny], Mock(), chat_store, self.store, self.store)
        try:
            chat.open_for(robot)
            self.assertEqual(chat.current_config()['name'], '알파')
            self.assertEqual(chat.current_config()['tone'], '존댓말')
            chat.history.append({'role': 'user', 'content': '로봇에게만'})
            chat.open_for(bunny)
            self.assertEqual(chat.current_config()['name'], '베타')
            self.assertEqual(chat.history, [])
            chat.open_for(robot)
            self.assertEqual(chat.history[0]['content'], '로봇에게만')
        finally:
            chat.close()


if __name__ == '__main__':
    unittest.main()
