"""Offline settings tests; screenshots are Qt renders, not live game evidence."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QTabWidget
from maeagi_biseo.resources import DEFAULTS, PROJECT_ROOT, tr
from maeagi_biseo.ui.chat import SettingsDialog
from tools.sol_erda_capture import CAPTURE_ROOT
from tests.artifacts import artifact_path


class SolErdaSettingsTests(unittest.TestCase):
    kind = 'sol_erda'
    reference_name = 'Sol Erda.png'

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from PySide6.QtGui import QFont, QFontDatabase
        font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'malgun.ttf'
        if font_path.is_file():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                cls.app.setFont(QFont(families[0], 10))

    def setUp(self):
        self.dialog = SettingsDialog(DEFAULTS, '')
        self.panel = getattr(self.dialog, f'{self.kind}_panel')
        tabs = self.dialog.findChild(QTabWidget, 'settingsTabs')
        self.assertEqual(tabs.tabText(tabs.indexOf(self.dialog.capture_page)), tr('settings.capture_tab'))
        self.assertTrue(self.dialog.capture_page.isAncestorOf(self.panel))
        tabs.setCurrentWidget(self.dialog.capture_page)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()

    def complete(self, data=None, error=''):
        process = Mock()
        folder = artifact_path(f'{self.kind}/settings_fixture')
        folder.mkdir(exist_ok=True)
        output = ''
        if data is not None:
            (folder / 'result.json').write_text(json.dumps(data), encoding='utf-8')
            from PySide6.QtGui import QPixmap
            pixmap = QPixmap(str(CAPTURE_ROOT / self.reference_name))
            self.assertFalse(pixmap.isNull())
            pixmap.scaled(pixmap.width()*4, pixmap.height()*4).save(str(folder / f'{self.kind}_4x.png'))
            output = f'Artifacts: {folder}\n'
        process.readAllStandardOutput.return_value = output.encode('utf-8')
        process.readAllStandardError.return_value = error.encode('utf-8')
        self.panel.process = process
        self.panel.finished(0 if data and data['detected'] else 2, QProcess.NormalExit)
        self.assertIsNone(self.panel.process)
        self.assertTrue(self.panel.capture_button.isEnabled())

    def screenshot(self, name):
        self.dialog.show()
        self.app.processEvents()
        self.assertTrue(self.dialog.grab().save(str(artifact_path(f'{self.kind}/settings_{name}.png'))))
        artifact_path(f'{self.kind}/settings_{name}.json').write_text(
            json.dumps({'capture_method': 'offscreen_qt_widget_render', 'input': 'mocked_capture_result',
                        'status_text': self.panel.status.text()}, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_success_preview(self):
        self.complete({'detected': True, 'score': 0.99, 'screen_box': [100, 100, 265, 165]})
        self.assertFalse(self.panel.preview.pixmap().isNull())
        self.assertTrue(self.panel.folder_button.isEnabled())
        self.screenshot('success')

    def test_not_found(self):
        self.complete({'detected': False, 'score': 0.2})
        self.assertTrue(self.panel.folder_button.isEnabled())
        self.assertIn('source.png', self.panel.status.text())
        self.screenshot('not_found')

    def test_missing_dependency(self):
        self.complete(error="ModuleNotFoundError: No module named 'cv2'")
        self.assertIn('requirements.txt', self.panel.status.text())
        self.assertFalse(self.panel.folder_button.isEnabled())
        self.screenshot('dependency_error')

    def test_start_failure(self):
        self.panel.process = Mock()
        self.panel.capture_button.setEnabled(False)
        self.panel.process_error(QProcess.FailedToStart)
        self.assertIsNone(self.panel.process)
        self.assertTrue(self.panel.capture_button.isEnabled())
        self.screenshot('start_error')

    def test_ocr_value_shown(self):
        value = 62946114234 if self.kind == 'meso' else 114
        self.complete({'detected': True, 'score': 0.99, 'screen_box': [0, 0, 182, 30],
                       'ocr': {'status': 'ok', 'value': value}})
        self.assertIn(f'{value:,}', self.panel.status.text())
        self.screenshot('ocr_success')

    def test_uncertain_ocr_is_not_a_balance(self):
        self.complete({'detected': True, 'score': 0.99, 'screen_box': [0, 0, 182, 30],
                       'ocr': {'status': 'uncertain', 'value': None}})
        self.assertIn('uncertain', self.panel.status.text())
        self.assertNotIn('None', self.panel.status.text())
        self.screenshot('ocr_uncertain')
