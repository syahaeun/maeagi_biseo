import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor, QPainter
from PySide6.QtWidgets import QApplication

from maeagi_biseo.core.sprites import STATES, SpriteError, available_characters, load_character, default_character
from maeagi_biseo.app import Pet, PETS, character_menu
from PySide6.QtWidgets import QMenu
from tests.artifacts import artifact_path
from maeagi_biseo.resources import PROJECT_ROOT


class SpriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sprites_', dir=artifact_path('scratch').parent)
        self.root = Path(self.temp.name)
        load_character.cache_clear()

    def tearDown(self):
        load_character.cache_clear()
        self.temp.cleanup()

    def png(self, path, color='#4488bb'):
        image = QPixmap(130, 155)
        image.fill(QColor(color))
        self.assertTrue(image.save(str(path)))

    def test_builtin_packs_have_all_states_and_transparent_frames(self):
        for identifier in ('robot', 'bunny'):
            pack = load_character(identifier)
            self.assertEqual(set(pack.animations), set(STATES))
            for state in STATES:
                frame = pack.frame(state, 0)
                self.assertFalse(frame.isNull())
                self.assertEqual(frame.size(), pack.canvas)
                self.assertEqual(frame.toImage().pixelColor(0, 0).alpha(), 0)
            self.assertNotEqual(pack.frame('walk', 0).toImage(), pack.frame('walk', 100).toImage())

    def test_single_png_can_be_added_without_a_manifest(self):
        self.png(self.root / 'custom.png')
        with patch('maeagi_biseo.core.sprites.sprite_roots', return_value=[self.root]):
            self.assertIn('custom', available_characters())
            self.assertEqual(default_character(), 'custom')
            pack = load_character('custom')
            self.assertEqual(pack.frame('sleep', 0).toImage(), pack.frame('idle', 0).toImage())

    def test_folder_discovers_animation_files_without_a_manifest(self):
        folder = self.root / 'custom'
        folder.mkdir()
        self.png(folder / 'idle.png')
        self.png(folder / 'walk_01.png', '#ff0000')
        self.png(folder / 'walk_02.png', '#00ff00')
        with patch('maeagi_biseo.core.sprites.sprite_roots', return_value=[self.root]):
            pack = load_character('custom')
            self.assertNotEqual(pack.frame('walk', 0).toImage(), pack.frame('walk', 120).toImage())

    def test_manifest_controls_canvas_and_foot_anchor(self):
        folder = self.root / 'custom'
        folder.mkdir()
        self.png(folder / 'idle.png')
        (folder / 'character.json').write_text(json.dumps({
            'name': 'Custom', 'canvas': [96, 120], 'foot_offset': 110,
            'animations': {'idle': {'frames': ['idle.png'], 'frame_ms': 100}}}), encoding='utf-8')
        with patch('maeagi_biseo.core.sprites.sprite_roots', return_value=[self.root]):
            pet = Pet(kind='custom')
            pet.timer.stop()
            self.assertEqual((pet.width(), pet.height(), pet.foot_offset), (96, 120, 110))
            self.assertEqual(pet.ypos + pet.foot_offset, pet.area.bottom() + 1)
            PETS.remove(pet)
            pet.close()

    def test_invalid_or_missing_images_never_fall_back_to_code_drawing(self):
        folder = self.root / 'custom'
        folder.mkdir()
        (folder / 'character.json').write_text(json.dumps({
            'animations': {'idle': {'frames': ['missing.png']}}}), encoding='utf-8')
        with patch('maeagi_biseo.core.sprites.sprite_roots', return_value=[self.root]):
            with self.assertRaises(SpriteError):
                load_character('custom')
        (folder / 'character.json').write_text(json.dumps({
            'animations': {'idle': {'frames': ['../outside.png']}}}), encoding='utf-8')
        with patch('maeagi_biseo.core.sprites.sprite_roots', return_value=[self.root]):
            with self.assertRaises(SpriteError):
                load_character('custom')

    def test_character_menu_discovers_added_png(self):
        self.png(self.root / 'custom.png')
        with patch('maeagi_biseo.core.sprites.sprite_roots', return_value=[self.root]):
            menu = QMenu()
            submenu = character_menu(menu)
            self.assertEqual([action.text() for action in submenu.actions()], ['custom'])
            menu.close()

    def test_image_paths_do_not_depend_on_working_directory(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            self.assertFalse(load_character('robot').frame('idle', 0).isNull())
        finally:
            os.chdir(previous)

    def test_test_artifacts_stay_inside_ignored_test_folder(self):
        self.assertTrue(artifact_path('preview.png').is_relative_to(PROJECT_ROOT / 'Test'))
        with self.assertRaises(ValueError):
            artifact_path('../outside.png')
        ignore = (PROJECT_ROOT / '.gitignore').read_text(encoding='utf-8')
        self.assertIn('Test/', ignore.splitlines())

    def test_rendered_sprite_preview_is_saved_under_test(self):
        sheet = QPixmap(130 * len(STATES), 155 * 2)
        sheet.fill(QColor('#faf7fc'))
        painter = QPainter(sheet)
        for row, identifier in enumerate(('robot', 'bunny')):
            pet = Pet(kind=identifier)
            pet.timer.stop()
            for column, state in enumerate(STATES):
                pet.state = state
                pet.motion = 'ceiling' if state == 'ceiling' else 'air' if state in ('fall', 'hop', 'drag') else 'ground'
                pet.sprite_state = None
                if state == 'pet':
                    pet.state = 'idle'
                    pet.petted_until = float('inf')
                painter.drawPixmap(column * 130, row * 155, pet.grab())
            PETS.remove(pet)
            pet.close()
        painter.end()
        output = artifact_path('sprites_preview.png')
        self.assertTrue(sheet.save(str(output)))
        self.assertTrue(output.is_file())


if __name__ == '__main__':
    unittest.main()
