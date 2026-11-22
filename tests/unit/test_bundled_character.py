import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from maeagi_biseo.core.sprites import available_characters, default_character, load_character, read_manifest
from maeagi_biseo.core.character_profiles import load_profiles
from maeagi_biseo.resources import PROJECT_ROOT, read_json
from tests.artifacts import artifact_path


class BundledCharacterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_character_runs_without_appdata_in_source_and_frozen_layouts(self):
        identifier = read_json('characters.json')['default']
        for frozen in (False, True):
            with self.subTest(frozen=frozen), tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
                store = QSettings(str(Path(temp) / 'empty.ini'), QSettings.IniFormat)
                load_character.cache_clear()
                with patch('maeagi_biseo.core.sprites.user_character_root', return_value=Path(temp) / 'no_appdata'), \
                     patch('maeagi_biseo.core.character_catalog.catalog_store', return_value=store), \
                     patch.object(sys, 'frozen', frozen, create=True), \
                     patch.object(sys, '_MEIPASS', str(PROJECT_ROOT), create=True), \
                     patch.object(sys, 'executable', str(Path(temp) / 'MaeagiBiseo.exe')):
                    characters = available_characters()
                    self.assertNotIn('robot', characters)
                    self.assertNotIn('bunny', characters)
                    self.assertEqual(set(characters), {identifier})
                    self.assertEqual(default_character(), identifier)
                    self.assertEqual(characters[identifier].name, '기본 메애기')
                    pack = load_character(identifier)
                    self.assertFalse(pack.frame('idle', 0).isNull())
                    manifest = read_manifest(characters[identifier].path)
                    self.assertIn(identifier, load_profiles(store))
                    self.assertEqual(load_profiles(store)[identifier], manifest['profile'])
                    self.assertEqual(manifest['profile']['persona']['name'], '기본 메애기')
                    self.assertEqual(set(read_json('personas.json')['presets']), {'기본 페르소나'})
                load_character.cache_clear()


if __name__ == '__main__':
    unittest.main()
