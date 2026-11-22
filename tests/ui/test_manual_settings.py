"""Settings isolation and physical-pixel selection on Qt-rendered snapshots."""
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QSettings, QPointF, QCoreApplication, QEvent
from PySide6.QtGui import QImage, QFontDatabase, QFont
from PySide6.QtWidgets import QApplication, QComboBox, QTabWidget
from maeagi_biseo.resources import DEFAULTS
from maeagi_biseo.ui.chat import SettingsDialog
from maeagi_biseo.ui.region_selector import RegionCanvas
from tests.artifacts import artifact_path


class ManualSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf')
        names = QFontDatabase.applicationFontFamilies(font_id)
        if names:
            cls.app.setFont(QFont(names[0], 10))

    def tearDown(self):
        # Release dialog signal graphs while QApplication is still alive.
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_legacy_vision_settings_restore_as_local_and_preserve_regions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = QSettings(directory + '/capture.ini', QSettings.IniFormat)
            store.setValue('method_meso', 'vision')
            store.setValue('method_sol_erda', 'vision')
            dialog = SettingsDialog(DEFAULTS, 'chat-key', capture_store=store)
            original = dialog.values()
            self.assertFalse(hasattr(dialog, 'vision_panel'))
            meso = dialog.meso_panel.manual
            meso.region = {'box': [10, 20, 210, 50], 'client_size': [800, 600]}
            for panel in (dialog.meso_panel, dialog.sol_erda_panel):
                self.assertIsNone(panel.manual.findChild(QComboBox))
            self.assertEqual(dialog.key.text(), 'chat-key')
            self.assertEqual(dialog.values(), original)
            dialog.save()
            saved = Path(directory + '/capture.ini').read_text(encoding='utf-8')
            self.assertNotIn('chat-key', saved)
            self.assertEqual(store.value('method_meso'), 'local')
            restored = SettingsDialog(DEFAULTS, 'chat-key', capture_store=store)
            self.assertEqual(restored.meso_panel.manual.region, meso.region)
            self.assertFalse(restored.meso_panel.manual.reset_button.isHidden())
            restored.findChild(QTabWidget, 'settingsTabs').setCurrentWidget(restored.capture_page)
            restored.show()
            self.app.processEvents()
            restored.grab().save(str(artifact_path('manual/local_ocr_settings.png')))
            restored.close()
            dialog.close()

    def test_cancel_does_not_save_region(self):
        with tempfile.TemporaryDirectory() as directory:
            store = QSettings(directory + '/capture.ini', QSettings.IniFormat)
            dialog = SettingsDialog(DEFAULTS, '', capture_store=store)
            dialog.meso_panel.manual.region = {'box': [1, 2, 30, 40], 'client_size': [800, 600]}
            dialog.reject()
            self.assertFalse(store.contains('region_meso'))

    def test_default_read_enabled_and_reset_restores_automatic_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            store = QSettings(directory + '/capture.ini', QSettings.IniFormat)
            dialog = SettingsDialog(DEFAULTS, '', capture_store=store)
            controls = dialog.meso_panel.manual
            self.assertIsNone(controls.region)
            self.assertTrue(controls.read_button.isEnabled())
            self.assertFalse(controls.reset_button.isEnabled())
            controls.region = {'box': [1, 2, 30, 40], 'client_size': [800, 600]}
            controls.update_label()
            self.assertTrue(controls.reset_button.isEnabled())
            controls.reset_button.click()
            self.assertIsNone(controls.region)
            self.assertTrue(controls.read_button.isEnabled())
            controls.save_settings()
            self.assertEqual(json.loads(str(store.value('region_meso'))), None)
            dialog.close()

    def test_display_coordinates_map_to_physical_pixels(self):
        image = QImage(1600, 900, QImage.Format_RGB888)
        image.fill(0)
        canvas = RegionCanvas(image)
        canvas.resize(800, 600)
        target = canvas.image_rect()
        self.assertEqual(canvas.pixel(QPointF(target.x()+target.width()/2, target.y()+target.height()/2)), (800, 450))
        canvas.start_point, canvas.end_point = (500, 400), (100, 200)
        self.assertEqual(canvas.box(), [100, 200, 500, 400])

    def test_selector_drag_and_cancel(self):
        from PIL import Image
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtWidgets import QDialogButtonBox, QDialog
        from maeagi_biseo.ui.region_selector import RegionSelector
        selector = RegionSelector(Image.new('RGB', (800, 600), '#dddddd'), 'test')
        selector.show()
        self.app.processEvents()
        rect = selector.canvas.image_rect()
        start = QPoint(round(rect.x()+rect.width()*0.2), round(rect.y()+rect.height()*0.3))
        end = QPoint(round(rect.x()+rect.width()*0.6), round(rect.y()+rect.height()*0.4))
        QTest.mousePress(selector.canvas, Qt.LeftButton, pos=start)
        QTest.mouseRelease(selector.canvas, Qt.LeftButton, pos=end)
        self.assertTrue(selector.buttons.button(QDialogButtonBox.Ok).isEnabled())
        for actual, expected in zip(selector.canvas.box(), [160, 180, 480, 240]):
            self.assertLessEqual(abs(actual-expected), 2)
        selector.grab().save(str(artifact_path('manual/region_selector.png')))
        selector.reject()
        self.assertEqual(selector.result(), QDialog.DialogCode.Rejected)
