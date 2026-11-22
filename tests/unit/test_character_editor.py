import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import QApplication
from maeagi_biseo.core.character_store import save_character
from maeagi_biseo.core.sprites import SpritePack, CharacterInfo, available_characters
from maeagi_biseo.ui.character_editor import CharacterEditor
from tests.artifacts import artifact_path


class CharacterEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])

    def test_maple_enter_searches_once_without_saving_or_closing(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        with patch.object(CharacterEditor, 'import_maple') as search, patch.object(CharacterEditor, 'save') as save:
            editor = CharacterEditor()
            try:
                editor.show()
                self.app.processEvents()
                editor.maple_section.toggle.click()
                for field in (editor.maple_name, editor.maple_key):
                    for key in (Qt.Key_Return, Qt.Key_Enter):
                        search.reset_mock()
                        field.setFocus()
                        QTest.keyClick(field, key)
                        self.app.processEvents()
                        search.assert_called_once_with()
                        save.assert_not_called()
                        self.assertTrue(editor.isVisible())
            finally:
                editor.close()

    def test_copied_frame_keeps_metadata_and_can_be_resized_independently(self):
        editor = CharacterEditor()
        try:
            from maeagi_biseo.core.sprites import read_manifest
            info = available_characters()['robot']
            source = str(info.path / read_manifest(info.path)['animations']['idle']['frames'][0])
            editor.animations = {'idle': {'frames': [source], 'frame_ms': 120,
                                         'sizes': {source: [40, 50]}, 'delays': {source: 230}}}
            editor.change_behavior()
            editor.frames.setCurrentRow(0)
            editor.copy_button.click()
            copied = editor.entry()['frames'][1]
            self.assertNotEqual(source, copied)
            self.assertEqual(Path(source).read_bytes(), Path(copied).read_bytes())
            self.assertEqual(editor.entry()['delays'][copied], 230)
            self.assertEqual(editor.entry()['sizes'][copied], [40, 50])
            editor.width_box.setValue(70)
            self.assertEqual(editor.entry()['sizes'][source], [40, 50])
            self.assertEqual(editor.entry()['sizes'][copied], [70, 50])
        finally:
            editor.close()

    def test_delete_user_character_removes_files_and_updates_default(self):
        from PySide6.QtCore import QSettings
        from maeagi_biseo.core.character_catalog import delete_character, registered_characters, set_default, preferences
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            root = Path(temp)
            user_root = root / 'characters'
            folder = user_root / 'user_test'
            folder.mkdir(parents=True)
            (folder / 'character.json').write_text('{}', encoding='utf-8')
            builtin = available_characters()['robot']
            entries = {'user_test': CharacterInfo('user_test', 'Test', folder), 'robot': builtin}
            store = QSettings(str(root / 'catalog.ini'), QSettings.IniFormat)
            with patch('maeagi_biseo.core.sprites.available_characters', return_value=entries), patch('maeagi_biseo.core.sprites.user_character_root', return_value=user_root):
                set_default('user_test', store=store)
                delete_character('user_test', store)
                self.assertFalse(folder.exists())
                self.assertEqual(list(registered_characters(store)), ['robot'])
                self.assertEqual(preferences(store)[0], 'robot')
                with self.assertRaises(ValueError):
                    delete_character('robot', store)
                self.assertTrue(builtin.path.exists())

    def test_bundled_character_delete_hides_without_removing_artwork(self):
        from PySide6.QtCore import QSettings
        from maeagi_biseo.core.character_catalog import delete_character, registered_characters
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            store = QSettings(str(Path(temp) / 'catalog.ini'), QSettings.IniFormat)
            builtin = available_characters()['robot'].path
            delete_character('robot', store)
            self.assertTrue(builtin.exists())
            self.assertNotIn('robot', registered_characters(store))

    def test_delete_button_requires_confirmation_and_refreshes_editor(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QMessageBox
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            store = QSettings(str(Path(temp) / 'catalog.ini'), QSettings.IniFormat)
            editor = CharacterEditor(selected_identifier='robot', catalog_store=store)
            deleted = []
            editor.characterDeleted.connect(deleted.append)
            try:
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.No):
                    editor.delete_button.click()
                self.assertEqual(editor.identifier, 'robot')
                self.assertEqual(deleted, [])
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    editor.delete_button.click()
                self.assertEqual(deleted, ['robot'])
                self.assertEqual(editor.characters.findData('robot'), -1)
                self.assertIsNone(editor.identifier)
                self.assertFalse(editor.delete_button.isEnabled())
            finally:
                editor.close()

    def test_import_survives_source_removal_and_preserves_sequence_and_speed(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            root = Path(temp)
            sources = []
            for index, color in enumerate(('red', 'blue')):
                path = root / f'{index}.png'
                image = QPixmap(40, 50)
                image.fill(QColor(color))
                image.save(str(path))
                sources.append(str(path))
            with patch('maeagi_biseo.core.character_store.user_character_root', return_value=root / 'characters'):
                identifier = save_character('테스트 메애기', {'idle': {'frames': sources, 'frame_ms': 240}}, (80, 90))
                for source in sources:
                    Path(source).unlink()
                pack = SpritePack(CharacterInfo(identifier, '테스트 메애기', root / 'characters' / identifier))
                self.assertNotEqual(pack.frame('idle', 0).toImage(), pack.frame('idle', 240).toImage())
                self.assertEqual(pack.frame('idle', 0).toImage(), pack.frame('idle', 480).toImage())
                self.assertEqual(pack.frame('walk', 240).toImage(), pack.frame('idle', 240).toImage())
                old_manifest = (root / 'characters' / identifier / 'character.json').read_bytes()
                with self.assertRaises(Exception):
                    save_character('변경', {'idle': {'frames': ['missing.png']}}, (80, 90), identifier)
                self.assertEqual(old_manifest, (root / 'characters' / identifier / 'character.json').read_bytes())

    def test_editor_reorder_fallback_and_preview(self):
        editor = CharacterEditor()
        try:
            info = available_characters()['robot']
            from maeagi_biseo.core.sprites import read_manifest
            manifest = read_manifest(info.path)
            frames = [str(info.path / manifest['animations'][state]['frames'][0]) for state in ('idle', 'walk')]
            editor.animations = {'idle': {'frames': frames[:], 'frame_ms': 220}}
            editor.change_behavior()
            editor.frames.setCurrentRow(1)
            editor.reorder(-1)
            self.assertEqual(editor.entry()['frames'], list(reversed(frames)))
            editor.behavior.setCurrentIndex(4)
            self.assertIn('대기 대체', editor.status.text())
            self.assertEqual(editor.timer.interval(), 220)
            editor.name.setText('나의 메애기')
            editor.show()
            self.app.processEvents()
            editor.grab().save(str(artifact_path('character_editor_preview.png')))
        finally:
            editor.timer.stop()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_idle_required(self):
        with self.assertRaises(ValueError):
            save_character('빈 메애기', {}, (130, 155))

    def test_individual_frame_sizes_round_trip_and_reference_box(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            root = Path(temp)
            paths = []
            for index in range(2):
                image = QPixmap(40, 50)
                image.fill(QColor('red'))
                path = str(root / f'{index}.png')
                image.save(path)
                paths.append(path)
            animations = {'idle': {'frames': paths, 'sizes': {paths[0]: [40, 50], paths[1]: [80, 100]}}}
            with patch('maeagi_biseo.core.character_store.user_character_root', return_value=root / 'characters'):
                identifier = save_character('개별 크기', animations, (130, 155), comparison_box=[10, 20, 60, 80], bubble_offset=[24, -12])
            folder = root / 'characters' / identifier
            from maeagi_biseo.core.sprites import read_manifest
            manifest = read_manifest(folder)
            self.assertEqual(manifest['animations']['idle']['frame_sizes'], [[40, 50], [80, 100]])
            self.assertEqual(manifest['comparison_box'], [10, 20, 60, 80])
            pack = SpritePack(CharacterInfo(identifier, '개별 크기', folder))
            self.assertEqual(pack.bubble_offset, [24, -12])
            # Small frame occupies y=105..154; large frame occupies y=55..154.
            self.assertEqual(pack.frame('idle', 0).toImage().pixelColor(65, 80).alpha(), 0)
            self.assertEqual(pack.frame('idle', 120).toImage().pixelColor(65, 80), QColor('red'))

    def test_editor_changes_only_selected_frame_size(self):
        editor = CharacterEditor()
        try:
            from maeagi_biseo.core.sprites import read_manifest
            info = available_characters()['robot']
            manifest = read_manifest(info.path)
            paths = [str(info.path / manifest['animations'][state]['frames'][0]) for state in ('idle', 'walk')]
            editor.animations = {'idle': {'frames': paths, 'frame_ms': 120}}
            editor.change_behavior()
            editor.frames.setCurrentRow(0)
            editor.width_box.setValue(80)
            self.assertEqual(editor.entry()['sizes'][paths[0]], [80, 155])
            self.assertNotIn(paths[1], editor.entry()['sizes'])
            editor.show()
            self.app.processEvents()
            self.assertNotIn('foot_offset', editor.entry())
            editor.grab().save(str(artifact_path('character_editor_individual_sizes.png')))
        finally:
            editor.timer.stop()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_gif_import_preserves_frame_timing_after_save(self):
        from maeagi_biseo.core.gif_import import import_gif
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            root = Path(temp)
            source = root / 'animation.gif'
            header = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\x00\x00\x00\x00\xff'
            def frame(delay, pixel):
                return (b'\x21\xf9\x04\x00' + delay.to_bytes(2, 'little') + b'\x00\x00'
                        + b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02' + bytes([pixel, 1]) + b'\x00')
            source.write_bytes(header + frame(5, 0x44) + frame(15, 0x4c) + b'\x3b')
            paths, delays = import_gif(source, root)
            self.assertEqual(len(paths), 2)
            self.assertEqual(list(delays.values()), [50, 150])
            with patch('maeagi_biseo.core.character_store.user_character_root', return_value=root / 'characters'):
                identifier = save_character('GIF', {'idle': {'frames': paths, 'delays': delays}}, (40, 50))
            source.unlink()
            pack = SpritePack(CharacterInfo(identifier, 'GIF', root / 'characters' / identifier))
            self.assertNotEqual(pack.frame('idle', 0).toImage(), pack.frame('idle', 50).toImage())
            self.assertEqual(pack.frame('idle', 0).toImage(), pack.frame('idle', 200).toImage())

    def test_click_sets_action_foot_with_scaled_centered_and_rotated_preview(self):
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtTest import QTest
        editor = CharacterEditor()
        try:
            from maeagi_biseo.core.sprites import read_manifest
            info = available_characters()['robot']
            manifest = read_manifest(info.path)
            path = str(info.path / manifest['animations']['idle']['frames'][0])
            editor.animations = {state: {'frames': [path, path], 'frame_ms': 120}
                                 for state in ('idle', 'walk', 'ceiling')}
            editor.show()
            editor.change_behavior()
            self.app.processEvents()
            for state, fraction, expected in (('idle', .6, 93), ('ceiling', .2, 124)):
                editor.behavior.setCurrentIndex(editor.behavior.findData(state))
                pixmap = editor.preview.pixmap()
                rect = editor.preview.contentsRect()
                top = rect.y() + (rect.height() - pixmap.height()) / 2
                point = QPoint(rect.center().x(), round(top + fraction * pixmap.height()))
                QTest.mouseClick(editor.preview, Qt.LeftButton, pos=point)
                self.assertAlmostEqual(editor.entry()['foot_offset'], expected, delta=1)
                self.assertTrue(editor.play.isChecked())
                self.assertEqual(len(editor.entry()['frames']), 2)
            self.assertNotIn('foot_offset', editor.animations['walk'])
        finally:
            editor.timer.stop()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_action_feet_share_physics_anchor_without_clipping_weapon(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            root = Path(temp)
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QPainter
            for state, foot, weapon_bottom in (('idle', 20, 49), ('walk', 35, 49), ('hop', 15, 40)):
                image = QPixmap(40, 50)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                painter.fillRect(10, foot, 1, 1, QColor('red'))
                painter.fillRect(20, weapon_bottom, 1, 1, QColor('blue'))
                painter.end()
                image.save(str(root / f'{state}.png'))
            animations = {state: {'frames': [str(root / f'{state}.png')], 'foot_offset': foot}
                          for state, foot in (('idle', 20), ('walk', 35), ('hop', 15))}
            with patch('maeagi_biseo.core.character_store.user_character_root', return_value=root / 'characters'):
                identifier = save_character('무기 캐릭터', animations, (40, 50))
            pack = SpritePack(CharacterInfo(identifier, '무기 캐릭터', root / 'characters' / identifier))
            self.assertEqual(pack.facing, 'left')
            self.assertEqual(pack.foot_offset, 35)
            self.assertEqual(pack.canvas.height(), 65)
            for state in ('idle', 'walk', 'hop'):
                self.assertEqual(pack.frame(state, 0).toImage().pixelColor(10, 35), QColor('red'))
            self.assertEqual(pack.frame('idle', 0).toImage().pixelColor(20, 64), QColor('blue'))
            self.assertEqual(pack.frame('hop', 0).toImage().pixelColor(20, 60), QColor('blue'))
            self.assertEqual(pack.frame('fall', 0).toImage(), pack.frame('idle', 0).toImage())


if __name__ == '__main__':
    unittest.main()
