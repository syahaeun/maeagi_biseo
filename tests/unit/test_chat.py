"""UI and local settings checks. Real API integration is in test_llm.py."""
import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from maeagi_biseo.ui.chat import SettingsDialog, load_api_key
from maeagi_biseo.app import Pet, PETS
from maeagi_biseo.resources import DEFAULTS, PRESETS, PERSONAS, TEXTS, resource_path, PROJECT_ROOT


class ChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])

    def test_key_file_and_environment_priority(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'OPENAI_API_KEY': ''}), patch('maeagi_biseo.llm.settings.read_key', return_value=''):
            self.assertEqual(load_api_key(directory), '')
            Path(directory, '.env').write_text('OPENAI_API_KEY="test-file-key"\n', encoding='utf-8-sig')
            self.assertEqual(load_api_key(directory), 'test-file-key')
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-env-key'}):
                self.assertEqual(load_api_key(directory), 'test-env-key')

    def test_gemini_only_selection_and_key_is_automatically_saved(self):
        with patch('maeagi_biseo.ui.chat.store_key') as store:
            legacy = {**DEFAULTS, 'provider': 'openai', 'model': 'legacy-openai-model'}
            dialog = SettingsDialog(legacy, 'legacy-openai-key',
                                    keys={'gemini': 'test-gemini-key'},
                                    profiles={'gemini': {'model': 'saved-gemini-model'}})
            self.addCleanup(dialog.close)
            self.assertEqual(dialog.provider.count(), 1)
            self.assertEqual(dialog.provider.currentData(), 'gemini')
            self.assertEqual(dialog.values()['provider'], 'gemini')
            self.assertEqual(dialog.values()['model'], 'saved-gemini-model')
            self.assertEqual(dialog.key.text(), 'test-gemini-key')
            store.assert_not_called()
            with patch.object(dialog, 'accept'), patch('maeagi_biseo.ui.chat.save_profiles'), patch('maeagi_biseo.ui.chat.save_scripts'), patch('maeagi_biseo.ui.chat.set_default'), patch.object(dialog.sol_erda_panel.manual, 'save_settings'), patch.object(dialog.meso_panel.manual, 'save_settings'):
                dialog.save()
                store.assert_not_called()
                dialog.key.setText('test-only-first')
                dialog.save()
                store.assert_called_once_with('gemini', 'test-only-first')
                store.reset_mock()
                dialog.key.clear()
                dialog.save()
                store.assert_called_once_with('gemini', '')

    def test_persona_preset_and_preview(self):
        dialog = SettingsDialog(DEFAULTS, '')
        preset = next(iter(PRESETS))
        dialog.apply_preset(preset)
        self.assertIn(PRESETS[preset][1], dialog.preview.toPlainText())
        self.assertEqual(dialog.values()['personality'], PRESETS[preset][0])
        dialog.close()

    def test_sol_erda_capture_tab_and_missing_dependency(self):
        from PySide6.QtWidgets import QTabWidget
        dialog = SettingsDialog(DEFAULTS, '')
        panel = dialog.sol_erda_panel
        tabs = dialog.findChild(QTabWidget, 'settingsTabs')
        self.assertGreaterEqual(tabs.indexOf(dialog.capture_page), 0)
        self.assertTrue(dialog.capture_page.isAncestorOf(panel))
        process = Mock()
        process.readAllStandardOutput.return_value = b''
        process.readAllStandardError.return_value = b"ModuleNotFoundError: No module named 'cv2'"
        panel.process = process
        panel.finished(1, None)
        self.assertIn('requirements.txt', panel.status.text())
        self.assertTrue(panel.capture_button.isEnabled())
        self.assertFalse(panel.folder_button.isEnabled())
        self.assertIsNone(panel.process)
        dialog.close()

    def test_sol_erda_failed_detection_keeps_source_accessible(self):
        import json
        dialog = SettingsDialog(DEFAULTS, '')
        panel = dialog.sol_erda_panel
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'result.json').write_text(json.dumps({'detected': False, 'score': 0.3}), encoding='utf-8')
            process = Mock()
            process.readAllStandardOutput.return_value = f'Artifacts: {directory}\n'.encode('utf-8')
            process.readAllStandardError.return_value = b''
            panel.process = process
            panel.finished(2, None)
            self.assertEqual(panel.folder, Path(directory))
            self.assertTrue(panel.folder_button.isEnabled())
            self.assertIn('source.png', panel.status.text())
            self.assertTrue(panel.preview.text())
        dialog.close()

    def test_text_resources_and_templates_are_complete(self):
        root = PROJECT_ROOT
        for filename in ('maeagi_biseo/ui/chat.py', 'maeagi_biseo/ui/dialogue.py', 'maeagi_biseo/app.py',
                         'maeagi_biseo/core/sprites.py', 'maeagi_biseo/resources.py', 'maeagi_biseo/platforms/windows.py',
                         'maeagi_biseo/core/movement.py', 'maeagi_biseo/llm/client.py',
                         'maeagi_biseo/llm/settings.py', 'tools/gemini_test.py'):
            tree = ast.parse((root / filename).read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr':
                    if isinstance(node.args[0], ast.Constant):
                        self.assertIn(node.args[0].value, TEXTS, filename)
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertFalse(any('\uac00' <= c <= '\ud7a3' for c in node.value), filename)
        self.assertIn(DEFAULTS['name'], PERSONAS['prompt_template'].format(**DEFAULTS))

    def test_resources_resolve_outside_project_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertTrue(resource_path('texts.ko.json').is_file())
                self.assertTrue(resource_path('theme.qss').is_file())
            finally:
                os.chdir(previous)

    def test_robot_renders_and_moves_in_both_directions(self):
        pet = Pet(x=200, kind='robot')
        pet.timer.stop()
        try:
            images = []
            for state in ('idle', 'walk', 'sleep', 'hop', 'talk'):
                pet.go_to_floor()
                pet.set_state(state)
                pet.direction = 1
                pet.phase = 1
                images.append(pet.grab().toImage())
                self.assertFalse(images[-1].isNull())
            self.assertNotEqual(images[0], images[2])
            self.assertNotEqual(images[0], images[4])
            pet.go_to_floor()
            pet.set_state('walk')
            for direction in (1, -1):
                pet.direction = direction
                before = pet.xpos
                pet.tick()
                self.assertEqual(pet.xpos, before + direction * 1.5)
            pet.set_focus(True)
            pet.choose()
            self.assertEqual(pet.state, 'idle')
        finally:
            PETS.remove(pet)
            pet.close()


if __name__ == '__main__':
    unittest.main()
