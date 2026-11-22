"""Manual coordinates, crop-only processing, and local-only image reading."""
import json
import os
import unittest
from unittest.mock import patch
from PIL import Image
from maeagi_biseo.core.capture_region import absolute_region, capture_manual


from maeagi_biseo.resources import PROJECT_ROOT
from tools.sol_erda_capture import CAPTURE_ROOT
from tests.artifacts import artifact_path


class ManualCaptureTests(unittest.TestCase):
    def test_nonlocal_method_is_rejected_before_capture_or_network(self):
        for method in ('vision', 'unknown'):
            with self.subTest(method=method), \
                 patch('tools.sol_erda_capture.game_rect') as game, \
                 patch('tools.sol_erda_capture.capture_game') as grab, \
                 patch('maeagi_biseo.llm.client.json_request') as request:
                with self.assertRaisesRegex(ValueError, 'PC 내부 OCR'):
                    capture_manual('meso', None, method, {}, 'unused-key', artifact_path('manual/rejected'))
                game.assert_not_called()
                grab.assert_not_called()
                request.assert_not_called()

    def test_selected_crop_uses_local_ocr_without_network(self):
        region = {'box': [100, 100, 282, 130], 'client_size': [800, 600]}
        image = Image.new('RGB', (182, 30), 'white')
        with patch('tools.sol_erda_capture.game_rect', return_value=(30, 40, 830, 640)), \
             patch('tools.sol_erda_capture.capture_game', return_value=image) as grab, \
             patch('maeagi_biseo.core.local_ocr.read_values', return_value={'status': 'ok', 'value': 42}) as reader, \
             patch('maeagi_biseo.llm.client.json_request') as request:
            folder, result = capture_manual('meso', region, 'local', {}, 'unused-key', artifact_path('manual/local'))
        grab.assert_called_once_with((130, 140, 312, 170))
        self.assertEqual(reader.call_args.args[0].size, (182, 30))
        self.assertTrue(reader.call_args.kwargs['number_only'])
        self.assertEqual(result['reading']['value'], 42)
        self.assertNotIn('unused-key', (folder / 'result.json').read_text(encoding='utf-8'))
        request.assert_not_called()

    def test_automatic_default_and_resized_region_fallback(self):
        for kind, name, expected in [('meso', 'Meso2.png', 46114234), ('sol_erda', 'Sol Erda.png', 114)]:
            for stale in (False, True):
                with self.subTest(kind=kind, stale=stale):
                    frame = Image.new('RGB', (400, 240), '#446633')
                    with Image.open(CAPTURE_ROOT / name) as source:
                        frame.paste(source.convert('RGB'), (100, 80))
                    region = {'box': [1, 2, 30, 40], 'client_size': [800, 600]} if stale else None
                    with patch('tools.sol_erda_capture.game_rect', return_value=(20, 30, 420, 270)), \
                         patch('tools.sol_erda_capture.capture_game', return_value=frame):
                        folder, data = capture_manual(kind, region, 'local', {}, '', artifact_path('automatic/' + kind))
                    self.assertEqual(data['mode'], 'automatic')
                    self.assertEqual(data['reading']['status'], 'ok', data)
                    self.assertEqual(data['reading']['value'], expected)
                    self.assertEqual(data['screen_box'][:2], (120, 110))
                    self.assertEqual(bool(data['region_warning']), stale)

    def test_automatic_failure_does_not_send_full_screen(self):
        with patch('tools.sol_erda_capture.game_rect', return_value=(0, 0, 400, 240)), \
             patch('tools.sol_erda_capture.capture_game', return_value=Image.new('RGB', (400, 240), '#446633')):
            folder, data = capture_manual('meso', None, 'local', {}, '', artifact_path('automatic/missing'))

        self.assertEqual(data['reading']['status'], 'not_detected')
        self.assertTrue((folder / 'result.json').is_file())

    def test_relative_coordinates_follow_window(self):
        region = {'box': [10, 20, 120, 50], 'client_size': [800, 600]}
        self.assertEqual(absolute_region(region, (-300, 100, 500, 700)), (-290, 120, -180, 150))
        with self.assertRaises(ValueError):
            absolute_region(region, (0, 0, 1024, 768))
        with self.assertRaises(ValueError):
            absolute_region({'box': [-1, 0, 1, 2], 'client_size': [800, 600]}, (0, 0, 800, 600))

    def test_manual_number_crops_real_local_ocr(self):
        from maeagi_biseo.core.local_ocr import read_values
        for kind, name, box, expected in [('meso', 'Meso2.png', (30, 6, 198, 23), 46114234),
                                         ('sol_erda', 'Sol Erda.png', (96, 43, 149, 58), 114)]:
            with self.subTest(kind=kind):
                with Image.open(CAPTURE_ROOT / name) as source:
                    image = source.crop(box).convert('RGB')
                folder = artifact_path(f'manual/{kind}_numbers')
                result = read_values(image, kind, folder, number_only=True)
                (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                self.assertEqual(result['status'], 'ok', result)
                self.assertEqual(result['value'], expected, result)

