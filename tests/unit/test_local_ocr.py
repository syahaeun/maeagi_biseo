"""Real local OCR on supplied UI images; no mocked recognizer or remote API."""
import json
import os
import subprocess
import sys
import unittest
from PIL import Image
from maeagi_biseo.core.local_ocr import parse_amount, read_values
from maeagi_biseo.resources import PROJECT_ROOT
from tools.sol_erda_capture import CAPTURE_ROOT
from tests.artifacts import artifact_path


class LocalOCRTests(unittest.TestCase):
    def test_parse_meso_units(self):
        for text, value in [('629억 4611만 4234', 62946114234), ('629역4611만4234', 62946114234),
                            ('1조2억3만4', 1000200030004), ('0', 0), ('1,234', 1234), ('4만', 40000)]:
            with self.subTest(text=text):
                self.assertEqual(parse_amount(text, 'meso'), value)

    def test_reject_ambiguous_text(self):
        for text in ('', 'O0', '11네', '114/1000', '-1'):
            self.assertIsNone(parse_amount(text, 'sol_erda'))
        for text in ('629억46114234', '1억2억', '1만2억', '잔액 123', '1.23', '-3'):
            self.assertIsNone(parse_amount(text, 'meso'))

    def run_reference(self, kind, scale=1, wide=False):
        name, expected = ('Meso.png', 62946114234) if kind == 'meso' else ('Sol Erda.png', 114)
        if wide:
            name, expected = 'Meso2.png', 46114234
        with Image.open(CAPTURE_ROOT / name) as source:
            image = source.convert('RGB')
        if scale != 1:
            image = image.resize((round(image.width*scale), round(image.height*scale)), Image.Resampling.BILINEAR)
        folder = artifact_path(f"ocr/{'meso2' if wide else kind}_{scale}x")
        folder.mkdir(exist_ok=True)
        image.save(folder / 'input.png')
        result = read_values(image, kind, folder)
        (folder / 'result.json').write_text(json.dumps({'expected': expected, 'actual': result,
            'real_local_engine': True, 'source': name}, ensure_ascii=False, indent=2), encoding='utf-8')
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['value'], expected, result)
        self.assertGreaterEqual(result['agreement'], 3)

    def test_real_meso(self):
        self.run_reference('meso')

    def test_real_fragment_count(self):
        self.run_reference('sol_erda')

    def test_scaled_meso(self):
        self.run_reference('meso', 1.5)

    def test_scaled_fragment_count(self):
        self.run_reference('sol_erda', 1.5)

    def test_real_wide_meso(self):
        self.run_reference('meso', wide=True)

    def test_scaled_wide_meso(self):
        self.run_reference('meso', 1.5, wide=True)

    def test_blank_fragment_is_not_zero(self):
        folder = artifact_path('ocr/blank')
        result = read_values(Image.new('RGB', (165, 65), '#333333'), 'sol_erda', folder)
        (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        self.assertEqual(result['status'], 'uncertain', result)
        self.assertIsNone(result['value'])

    def test_end_to_end_cli_ocr(self):
        for kind, image, expected in [('meso', 'Meso.png', 62946114234), ('sol_erda', 'Sol Erda.png', 114),
                                      ('meso', 'Meso2.png', 46114234)]:
            with self.subTest(kind=kind):
                output = artifact_path(f'ocr/{kind}_cli')
                process = subprocess.run([sys.executable, '-m', f'tools.{kind}_capture', '--image',
                    str(CAPTURE_ROOT / image), '--output', str(output)], cwd=PROJECT_ROOT,
                    env=dict(os.environ, PYTHONIOENCODING='utf-8'), capture_output=True,
                    encoding='utf-8', errors='replace', timeout=60)
                artifact_path(f'ocr/{kind}_cli.log').write_text(process.stdout+process.stderr, encoding='utf-8')
                self.assertEqual(process.returncode, 0, process.stdout+process.stderr)
                folder = max(output.iterdir(), key=lambda path: path.name)
                result = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
                self.assertEqual(result['version'], 2)
                self.assertEqual(result['ocr']['status'], 'ok', result)
                self.assertEqual(result['ocr']['value'], expected)
