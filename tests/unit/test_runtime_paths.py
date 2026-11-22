"""Frozen capture diagnostics must never write into the install directory."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from maeagi_biseo.core.runtime_paths import capture_output_root
from maeagi_biseo.resources import PROJECT_ROOT


class RuntimePathTests(unittest.TestCase):
    def test_source_capture_uses_test_folder(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(capture_output_root(), PROJECT_ROOT / 'Test')

    def test_frozen_capture_uses_user_data_even_in_read_only_install(self):
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, '_MEIPASS', 'C:/temporary/extracted', create=True), \
             patch.object(sys, 'executable', 'C:/Program Files/DesktopShimeji/app.exe'), \
             patch('maeagi_biseo.core.runtime_paths.QStandardPaths.writableLocation', return_value='C:/Users/example/AppData/Local'):
            output = capture_output_root()
            self.assertEqual(output, Path('C:/Users/example/AppData/Local/DesktopShimeji/Capture'))
            self.assertNotIn('Program Files', str(output))
            self.assertNotIn('extracted', str(output))
