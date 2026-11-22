"""Offline Meso detection evidence; no live game or LLM connection."""
import json
import subprocess
import sys
import unittest
from PIL import Image, ImageDraw
from tools.sol_erda_capture import ROOT, CAPTURE_ROOT
from tools.meso_capture import locate
from tests.artifacts import artifact_path


class MesoDetectionTests(unittest.TestCase):
    def reference(self):
        with Image.open(CAPTURE_ROOT / 'Meso.png') as source:
            return source.convert('RGB')

    def evidence(self, name, frame, result):
        frame.save(artifact_path(f'meso/{name}_source.png'))
        artifact_path(f'meso/{name}_result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        if result['detected']:
            frame.crop(result['box']).save(artifact_path(f'meso/{name}_crop.png'))

    def test_moved_scaled_changed_amount(self):
        reference = self.reference()
        modified = reference.copy()
        draw = ImageDraw.Draw(modified)
        draw.rectangle((40, 9, 171, 21), fill='#e8edf3')
        draw.text((72, 9), '9,999,999', fill='#444444')
        for scale in (0.75, 1, 1.5, 2):
            with self.subTest(scale=scale):
                size = (round(182*scale), round(30*scale))
                frame = Image.new('RGB', (640, 360), '#446633')
                frame.paste(modified.resize(size, Image.Resampling.BILINEAR), (117, 83))
                result = locate(frame, reference)
                self.evidence(f'scale_{scale}', frame, result)
                self.assertTrue(result['detected'], result)
                self.assertEqual(result['box'], [117, 83, 117+size[0], 83+size[1]])

    def test_missing_ui(self):
        frame = Image.new('RGB', (640, 360), '#446633')
        result = locate(frame, self.reference())
        self.evidence('missing', frame, result)
        self.assertFalse(result['detected'])

    def test_wide_layout_with_changed_amount_and_scale(self):
        reference = self.reference()
        with Image.open(CAPTURE_ROOT / 'Meso2.png') as source:
            wide = source.convert('RGB')
        ImageDraw.Draw(wide).rectangle((40, 8, 190, 20), fill='white')
        ImageDraw.Draw(wide).text((80, 9), '999999', fill='#444444')
        for scale in (0.75, 1, 1.5, 2):
            with self.subTest(scale=scale):
                size = (round(wide.width*scale), round(wide.height*scale))
                frame = Image.new('RGB', (640, 360), '#446633')
                frame.paste(wide.resize(size, Image.Resampling.BILINEAR), (117, 83))
                result = locate(frame, reference)
                self.evidence(f'wide_scale_{scale}', frame, result)
                self.assertTrue(result['detected'], result)
                self.assertEqual(result['layout'], 'Meso2.png')
                self.assertEqual(result['box'], [117, 83, 117+size[0], 83+size[1]])

    def test_coin_without_complete_ui(self):
        reference = self.reference()
        frame = Image.new('RGB', (640, 360), '#446633')
        frame.paste(reference.crop((3, 5, 29, 25)), (120, 88))
        result = locate(frame, reference)
        self.evidence('coin_only', frame, result)
        self.assertFalse(result['detected'])

    def test_offline_command(self):
        output = artifact_path('meso/cli')
        result = subprocess.run([sys.executable, '-m', 'tools.meso_capture', '--image',
                                 str(CAPTURE_ROOT / 'Meso.png'), '--output', str(output)],
                                cwd=ROOT, capture_output=True, encoding='utf-8', errors='replace', timeout=60)
        artifact_path('meso/cli.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        folder = max(output.iterdir(), key=lambda path: path.name)
        for name in ('source.png', 'meso.png', 'meso_4x.png', 'detected.png', 'result.json'):
            self.assertTrue((folder / name).is_file(), name)
        data = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
        self.assertTrue(data['detected'])
        self.assertEqual(data['kind'], 'meso')
        self.assertEqual(data['source'], 'offline')
