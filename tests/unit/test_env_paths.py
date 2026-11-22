"""Environment configuration survives moving the executable."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maeagi_biseo.llm import settings
from tests.artifacts import artifact_path


class EnvPathTests(unittest.TestCase):
    def setUp(self):
        parent = artifact_path('env_paths')
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.legacy = self.root / 'old_install'
        self.legacy.mkdir()
        self.target = self.root / 'appdata' / 'DesktopShimeji' / '.env'
        patches = (
            patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'appdata')}),
            patch.object(settings, 'PROJECT_ROOT', self.legacy),
            patch.object(settings.sys, 'frozen', False, create=True),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_source_migration_preserves_original_bytes(self):
        original = self.legacy / '.env'
        original.write_text('GEMINI_MODEL="example-model"\n', encoding='utf-8-sig')
        self.assertEqual(settings.env_file_values()['GEMINI_MODEL'], 'example-model')
        self.assertEqual(self.target.read_bytes(), original.read_bytes())

    def test_frozen_migration_survives_executable_move(self):
        (self.legacy / '.env').write_text('OPENAI_MODEL=test-model\n', encoding='utf-8')
        with patch.object(settings.sys, 'frozen', True), patch.object(settings.sys, 'executable', str(self.legacy / 'app.exe')):
            self.assertEqual(settings.env_file_values()['OPENAI_MODEL'], 'test-model')
            with patch.object(settings.sys, 'executable', str(self.root / 'moved' / 'app.exe')):
                self.assertEqual(settings.env_file_values()['OPENAI_MODEL'], 'test-model')

    def test_existing_appdata_is_not_overwritten(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text('OPENAI_MODEL=user-model\n', encoding='utf-8')
        (self.legacy / '.env').write_text('OPENAI_MODEL=old-model\n', encoding='utf-8')
        self.assertEqual(settings.env_file_values()['OPENAI_MODEL'], 'user-model')

    def test_explicit_directory_remains_isolated(self):
        (self.legacy / '.env').write_text('OPENAI_MODEL=isolated\n', encoding='utf-8')
        self.assertEqual(settings.env_file_values(self.legacy)['OPENAI_MODEL'], 'isolated')
        self.assertFalse(self.target.exists())

    def test_frozen_recovers_store_python_credentials_without_exe_adjacent_env(self):
        package=self.root/'appdata'/'Packages'/'PythonSoftwareFoundation.Python.3.12_test'/'LocalCache'/'Local'/'DesktopShimeji'
        package.mkdir(parents=True)
        original=package/'.env'
        original.write_text('OPENAI_API_KEY=disposable-test-key\nNEXON_API_KEY=disposable-nexon-key\n',encoding='utf-8-sig')
        with patch.object(settings.sys,'frozen',True),patch.object(settings.sys,'executable',str(self.legacy/'app.exe')):
            values=settings.env_file_values()
        self.assertEqual(values['OPENAI_API_KEY'],'disposable-test-key')
        self.assertEqual(values['NEXON_API_KEY'],'disposable-nexon-key')
        self.assertEqual(self.target.read_bytes(),original.read_bytes())
        self.assertTrue(original.is_file())

    def test_store_migration_does_not_replace_existing_user_keys(self):
        package=self.root/'appdata'/'Packages'/'PythonSoftwareFoundation.Python.3.12_test'/'LocalCache'/'Local'/'DesktopShimeji'
        package.mkdir(parents=True)
        (package/'.env').write_text('OPENAI_API_KEY=old-test-key\n',encoding='utf-8')
        self.target.parent.mkdir(parents=True)
        self.target.write_text('OPENAI_API_KEY=current-test-key\n',encoding='utf-8')
        self.assertEqual(settings.env_file_values()['OPENAI_API_KEY'],'current-test-key')
