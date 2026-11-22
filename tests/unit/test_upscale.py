import unittest
import os
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PIL import Image
from tests.artifacts import artifact_path
from maeagi_biseo.core.upscale import upscale_frame


class UpscaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_save_keeps_animation_metadata_and_logical_canvas(self):
        import json
        from maeagi_biseo.core.character_store import save_character
        source = artifact_path('upscale/save_source.png')
        Image.new('RGBA', (20, 24), (100, 80, 20, 128)).save(source)
        root = artifact_path('upscale/characters')
        entry = {'frames': [str(source)], 'frame_ms': 150,
                 'foot_offset': 22, 'delays': {str(source): 210},
                 'sizes': {str(source): [20, 24]}}
        with patch('maeagi_biseo.core.character_store.user_character_root', return_value=root):
            identifier = save_character('test', {'idle': entry}, [20, 24], upscale_factor=2)
        manifest = json.loads((root / identifier / 'character.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['canvas'], [20, 24])
        idle = manifest['animations']['idle']
        self.assertEqual(idle['frame_durations'], [210])
        self.assertEqual(idle['foot_offset'], 22)
        self.assertEqual(idle['frame_sizes'], [[20, 24]])
        with Image.open(root / identifier / idle['frames'][0]) as image:
            self.assertEqual(image.size, (40, 48))

    def test_rgba_export_preserves_source_and_transparency(self):
        source = artifact_path('upscale/source.png')
        target = artifact_path('upscale/result.png')
        image = Image.new('RGBA', (20, 24), (0, 0, 0, 0))
        image.paste((200, 80, 20, 255), (6, 6, 14, 18))
        image.save(source)
        original = source.read_bytes()
        for factor in (2, 4):
            upscale_frame(source, target, factor)
            with Image.open(target) as result:
                self.assertEqual(result.size, (20 * factor, 24 * factor))
                self.assertEqual(result.mode, 'RGBA')
                self.assertEqual(result.getpixel((0, 0))[3], 0)
            self.assertEqual(source.read_bytes(), original)

    def test_invalid_factor_does_not_open_source(self):
        for factor in (0, 3, True, 2.0):
            with self.assertRaises(ValueError):
                upscale_frame('missing.png', 'unused.png', factor)

    def test_smoothing_softens_edges_without_dark_halo(self):
        source = artifact_path('upscale/edge.png')
        target = artifact_path('upscale/soft_edge.png')
        image = Image.new('RGBA', (24, 24))
        image.paste((240, 80, 40, 255), (8, 8, 16, 16))
        image.save(source)
        upscale_frame(source, target, 1, smoothing=2)
        with Image.open(target) as result:
            self.assertEqual(result.size, image.size)
            self.assertTrue(0 < result.getpixel((7, 12))[3] < 255)
            self.assertGreater(result.getpixel((7, 12))[0], 220)
            self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(Image.open(source).getpixel((7, 12))[3], 0)

    def test_editor_preview_matches_saved_pixels_and_original_toggle(self):
        from PySide6.QtCore import QSize, Qt
        from PySide6.QtGui import QPixmap
        from maeagi_biseo.ui.character_editor import CharacterEditor
        source = artifact_path('upscale/preview_source.png')
        target = artifact_path('upscale/preview_export.png')
        image = Image.new('RGBA', (24, 24))
        image.paste((240, 80, 40, 255), (8, 8, 16, 16))
        image.save(source)
        with patch('maeagi_biseo.ui.character_editor.registered_characters', return_value={}):
            editor = CharacterEditor()
        try:
            editor.timer.stop()
            editor.upscale_box.setCurrentIndex(1)
            editor.smoothing_box.setCurrentIndex(2)
            rendered = editor.processed_preview(str(source), [24, 24])
            upscale_frame(source, target, 2, 2)
            expected = QPixmap(str(target)).scaled(QSize(24, 24), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.assertEqual(rendered.toImage(), expected.toImage())
            editor.preview_original.setChecked(True)
            original = editor.processed_preview(str(source), [24, 24])
            self.assertEqual(original.toImage(), QPixmap(str(source)).toImage())
            self.assertNotEqual(original.toImage(), rendered.toImage())
        finally:
            editor.close()
            import shiboken6
            shiboken6.delete(editor)

    def test_reconstruction_keeps_small_dark_details_and_flat_colors(self):
        from maeagi_biseo.core.upscale import processed_frame
        source = artifact_path('upscale/detail.png')
        image = Image.new('RGBA', (32, 32))
        image.paste((240, 180, 100, 255), (4, 4, 28, 28))
        image.putpixel((16, 16), (0, 0, 0, 255))
        image.save(source)
        for factor in (1, 2, 4):
            for strength in (1, 2):
                with processed_frame(source, factor, strength) as result:
                    self.assertEqual(result.getpixel((10 * factor, 10 * factor)), (240, 180, 100, 255))
                    self.assertLess(result.getpixel((16 * factor + factor // 2, 16 * factor + factor // 2))[0], 120)

    def test_connected_internal_corner_is_reconstructed_without_new_colors(self):
        from maeagi_biseo.core.upscale import _scale2x
        image = Image.new('RGBA', (3, 3), (255, 255, 255, 255))
        image.putpixel((1, 0), (0, 0, 0, 255))
        image.putpixel((0, 1), (0, 0, 0, 255))
        result = _scale2x(image)
        # The white center's top-left quarter connects the black diagonal.
        self.assertEqual(result.getpixel((2, 2)), (0, 0, 0, 255))
        self.assertEqual(result.getpixel((3, 3)), (255, 255, 255, 255))
        self.assertEqual(set(result.get_flattened_data()), set(image.get_flattened_data()))

    def test_xbrz_matches_upstream_transparent_reference_pixels(self):
        from maeagi_biseo.core.xbrz import scale_xbrz
        from maeagi_biseo.core.upscale import processed_frame
        fixtures = Path(__file__).resolve().parents[1] / 'fixtures' / 'xbrz'
        source = fixtures / 'yoshi-transparent.png'
        with Image.open(source) as image:
            for factor in (2, 4):
                with self.subTest(factor=factor):
                    with Image.open(fixtures / f'yoshi-transparent-xbrz-5b-x{factor}.png') as expected:
                        actual = scale_xbrz(image, factor)
                        self.assertEqual(actual.size, expected.size)
                        self.assertEqual(actual.tobytes(), expected.convert('RGBA').tobytes())
                        processed = processed_frame(source, factor, smoothing=3)
                        self.assertEqual(processed.tobytes(), actual.tobytes())

    def test_xbrz_preview_and_save_use_identical_pixels(self):
        from maeagi_biseo.core.character_store import save_character
        from maeagi_biseo.ui.character_editor import CharacterEditor
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import Qt, QSize
        import json
        source = Path(__file__).resolve().parents[1] / 'fixtures/xbrz/yoshi-transparent.png'
        root = artifact_path('upscale/xbrz_characters')
        with patch('maeagi_biseo.ui.character_editor.registered_characters', return_value={}):
            editor = CharacterEditor()
        try:
            editor.timer.stop()
            editor.upscale_box.setCurrentIndex(2)
            editor.smoothing_box.setCurrentIndex(editor.smoothing_box.findData(3))
            preview = editor.processed_preview(str(source), [32, 32])
            with patch('maeagi_biseo.core.character_store.user_character_root', return_value=root):
                identifier = save_character('xBRZ', {'idle': {'frames': [str(source)], 'frame_ms': 210}},
                                            [32, 32], upscale_factor=4, smoothing=3)
            manifest = json.loads((root / identifier / 'character.json').read_text(encoding='utf-8'))
            entry = manifest['animations']['idle']
            self.assertEqual(entry['frame_ms'], 210)
            self.assertEqual(manifest['canvas'], [32, 32])
            saved = QPixmap(str(root / identifier / entry['frames'][0]))
            self.assertEqual(preview.toImage(), saved.scaled(QSize(32, 32), Qt.KeepAspectRatio, Qt.SmoothTransformation).toImage())
        finally:
            editor.close()
            import shiboken6
            shiboken6.delete(editor)

    def test_xbrz_without_enlargement_keeps_dimensions(self):
        from maeagi_biseo.core.upscale import processed_frame
        source = Path(__file__).resolve().parents[1] / 'fixtures/xbrz/yoshi-transparent.png'
        with Image.open(source) as image, processed_frame(source, 1, smoothing=3) as result:
            self.assertEqual(result.size, image.size)
            self.assertEqual(result.mode, 'RGBA')

    def test_xbrz_rejects_excessive_allocation_before_loading_runtime(self):
        from maeagi_biseo.core.xbrz import scale_xbrz
        with patch('maeagi_biseo.core.xbrz._module') as module:
            with self.assertRaises(ValueError):
                scale_xbrz(Image.new('RGBA', (2049, 2049)), 4)
            module.assert_not_called()

    def test_all_actions_and_frames_match_runtime_at_display_scales(self):
        from maeagi_biseo.core.sprites import STATES, SpritePack, CharacterInfo
        from maeagi_biseo.core.character_store import save_character
        from maeagi_biseo.ui.character_editor import CharacterEditor
        from PySide6.QtGui import QPixmap, QPainter
        from PySide6.QtCore import Qt, QSize
        root = artifact_path('upscale/all_states')
        animations = {}
        for state_index, state in enumerate(STATES):
            paths = []
            for index in range(2):
                source = artifact_path(f'upscale/all_sources/{state}_{index}.png')
                image = Image.new('RGBA', (24, 24))
                image.paste((30 + state_index * 20, 80 + index * 100, 200, 255), (4, 4, 20, 20))
                image.putpixel((10, 10), (0, 0, 0, 255))
                image.save(source)
                paths.append(str(source))
            animations[state] = {'frames': paths, 'frame_ms': 150, 'foot_offset': 32,
                                 'sizes': {path: [24, 24] for path in paths}}
        with patch('maeagi_biseo.ui.character_editor.registered_characters', return_value={}):
            editor = CharacterEditor()
        try:
            editor.timer.stop()
            editor.upscale_box.setCurrentIndex(1)
            editor.smoothing_box.setCurrentIndex(editor.smoothing_box.findData(3))
            for scale in (100, 150, 200):
                with patch('maeagi_biseo.core.character_store.user_character_root', return_value=root):
                    identifier = save_character('all', animations, [32, 32], display_scale=scale,
                                                upscale_factor=2, smoothing=3)
                pack = SpritePack(CharacterInfo(identifier, 'all', root / identifier))
                for state, entry in animations.items():
                    for index, path in enumerate(entry['frames']):
                        with self.subTest(scale=scale, state=state, frame=index):
                            canvas = QPixmap(32, 32)
                            canvas.fill(Qt.transparent)
                            painter = QPainter(canvas)
                            painter.drawPixmap(4, 8, editor.processed_preview(path, [24, 24]))
                            painter.end()
                            size = QSize(round(32 * scale / 100), round(32 * scale / 100))
                            expected = canvas.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                            self.assertEqual(pack.frame(state, index * 150).toImage(), expected.toImage())
        finally:
            editor.close()
            import shiboken6
            shiboken6.delete(editor)

    def test_saving_refreshes_every_running_instance_of_selected_character(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        from PySide6.QtCore import QRect, QSize
        from PySide6.QtWidgets import QDialog
        from maeagi_biseo import app as application
        pets = []
        for kind in ('selected', 'other', 'selected'):
            pet = Mock(kind=kind, xpos=100.0, ypos=200.0, foot_offset=32, motion='ground')
            pet.area = QRect(0, 0, 1000, 800)
            pet.width.return_value = 32
            pets.append(pet)
        pack = SimpleNamespace(info=SimpleNamespace(name='updated'), foot_offset=32, canvas=QSize(32, 32))
        dialog = Mock(identifier='selected')
        dialog.exec.return_value = QDialog.Accepted
        old_other = pets[1].sprites
        with patch('maeagi_biseo.ui.character_editor.CharacterEditor', return_value=dialog), \
                patch.object(application, 'PETS', pets), patch.object(application, 'CHAT', None), \
                patch.object(application, 'load_character', return_value=pack) as load:
            application.edit_characters()
        self.assertEqual(load.call_count, 2)
        self.assertIs(pets[0].sprites, pack)
        self.assertIs(pets[2].sprites, pack)
        self.assertIs(pets[1].sprites, old_other)
