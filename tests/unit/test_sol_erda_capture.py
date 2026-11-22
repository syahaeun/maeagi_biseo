import unittest
import json
import subprocess
import sys
from PIL import Image, ImageDraw
from tools.sol_erda_capture import ROOT, CAPTURE_ROOT, locate
from tests.artifacts import artifact_path


class SolErdaDetectionTests(unittest.TestCase):
    def test_moved_scaled_and_changed_count(self):
        with Image.open(CAPTURE_ROOT / 'Sol Erda.png') as source:
            reference = source.convert('RGB')
        modified = reference.copy()
        ImageDraw.Draw(modified).rectangle((10, 43, 153, 58), fill='black')
        for scale in (1, 1.5, 2):
            with self.subTest(scale=scale):
                size = (round(165*scale), round(65*scale))
                frame = Image.new('RGB', (640, 360), '#446633')
                frame.paste(modified.resize(size, Image.Resampling.BILINEAR), (117, 83))
                result = locate(frame, reference)
                self.save_evidence(f'scale_{scale}', frame, result)
                self.assertTrue(result['detected'], result)
                self.assertEqual(result['box'], [117, 83, 117+size[0], 83+size[1]])

    def test_missing_ui(self):
        with Image.open(CAPTURE_ROOT / 'Sol Erda.png') as source:
            result = locate(Image.new('RGB', (640, 360), '#446633'), source)
        self.assertFalse(result['detected'])
        self.save_evidence('missing_ui', Image.new('RGB', (640, 360), '#446633'), result)

    def save_evidence(self, name, frame, result):
        frame.save(artifact_path(f'sol_erda/{name}_source.png'))
        artifact_path(f'sol_erda/{name}_result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        if result['detected']:
            frame.crop(result['box']).save(artifact_path(f'sol_erda/{name}_crop.png'))

    def test_offline_command_saves_artifacts(self):
        output = artifact_path('sol_erda/cli')
        result = subprocess.run([sys.executable, '-m', 'tools.sol_erda_capture',
                                 '--image', str(CAPTURE_ROOT / 'Sol Erda.png'), '--output', str(output)],
                                cwd=ROOT, capture_output=True, encoding='utf-8', errors='replace', timeout=60)
        artifact_path('sol_erda/cli.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        folder = max(output.iterdir(), key=lambda path: path.name)
        for filename in ('source.png', 'result.json', 'detected.png', 'sol_erda.png', 'sol_erda_4x.png'):
            self.assertTrue((folder / filename).is_file(), filename)
        data = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
        self.assertTrue(data['detected'])
        self.assertEqual(data['source'], 'offline')

    def test_single_icon_is_not_enough(self):
        with Image.open(CAPTURE_ROOT / 'Sol Erda.png') as source:
            reference = source.convert('RGB')
        frame = Image.new('RGB', (640, 360), '#446633')
        frame.paste(reference.crop((32, 16, 60, 38)), (149, 99))
        result = locate(frame, reference)
        self.save_evidence('single_icon', frame, result)
        self.assertFalse(result['detected'])
