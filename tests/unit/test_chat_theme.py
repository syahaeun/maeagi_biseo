"""Appearance changes must preserve drafts and conversations across modes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QSettings
from PySide6.QtGui import QPalette, QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel
from maeagi_biseo.ui.chat import ChatWindow
from tests.artifacts import artifact_path


class ChatThemeTests(unittest.TestCase):
    def test_checked_indicators_have_a_centered_white_tick(self):
        from PySide6.QtWidgets import QWidget,QVBoxLayout,QCheckBox,QStyle,QStyleOptionButton,QMenu
        from maeagi_biseo.ui.chat_theme import apply_chat_theme
        for mode in ('light','dark'):
            root=QWidget()
            root.resize(300,100)
            layout=QVBoxLayout(root)
            check=QCheckBox('Test')
            check.setChecked(True)
            layout.addWidget(check)
            apply_chat_theme(root,mode)
            root.show()
            self.app.processEvents()
            try:
                option=QStyleOptionButton()
                check.initStyleOption(option)
                rect=check.style().subElementRect(QStyle.SE_CheckBoxIndicator,option,check)
                frame=check.grab().toImage()
                root.grab().save(str(artifact_path('checkmarks/'+mode+'.png')))
                ratio=frame.devicePixelRatio()
                rect=type(rect)(round(rect.x()*ratio),round(rect.y()*ratio),round(rect.width()*ratio),round(rect.height()*ratio))
                inside=rect.adjusted(2,2,-2,-2)
                white=[]
                for y in range(inside.top(),inside.bottom()+1):
                    for x in range(inside.left(),inside.right()+1):
                        color=frame.pixelColor(x,y)
                        if min(color.red(),color.green(),color.blue())>230:
                            white.append((x,y))
                self.assertGreater(len(white),5,mode)
                center_x=(min(x for x,y in white)+max(x for x,y in white))/2
                center_y=(min(y for x,y in white)+max(y for x,y in white))/2
                self.assertLessEqual(abs(center_x-rect.center().x()),1.5,mode)
                self.assertLessEqual(abs(center_y-rect.center().y()),1.5,mode)
                root.grab().save(str(artifact_path('checkmarks/'+mode+'.png')))
                menu=QMenu(root)
                action=menu.addAction('Test')
                action.setCheckable(True)
                action.setChecked(True)
                apply_chat_theme(menu,mode)
                menu.grab().save(str(artifact_path('checkmarks/menu-'+mode+'.png')))
            finally:
                root.close()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'malgun.ttf'
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))

    def test_switch_preserves_draft_history_and_persists(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            store = QSettings(str(Path(temp) / 'theme.ini'), QSettings.IniFormat)
            window = ChatWindow([], Mock(), store, store, store, store, store)
            self.addCleanup(window.close)
            window.input.setPlainText('draft')
            window.history.append({'role': 'user', 'content': 'hello'})
            window.add_message(window.config['name'], window.config['tone'])
            window.add_message('User', 'hello', True)
            window.show()
            self.app.processEvents()
            light = window.palette().color(QPalette.Window).lightness()
            window.grab().save(str(artifact_path('chat_theme_light.png')))
            window.theme_selector.setCurrentIndex(window.theme_selector.findData('dark'))
            self.app.processEvents()
            self.assertLess(window.palette().color(QPalette.Window).lightness(), light)
            self.assertEqual(window.input.toPlainText(), 'draft')
            self.assertEqual(len(window.history), 1)
            self.assertEqual(sum(bool(label.property('chatBubble')) for label in window.messages.findChildren(QLabel)), 2)
            self.assertEqual(len(window.messages.findChildren(QLabel, 'chatDate')), 1)
            self.assertNotIn('@background@', window.styleSheet())
            window.grab().save(str(artifact_path('chat_theme_dark.png')))
            window.close()
            reopened_store = QSettings(store.fileName(), QSettings.IniFormat)
            reopened = ChatWindow([], Mock(), reopened_store, store, store, store, store)
            self.addCleanup(reopened.close)
            self.assertEqual(reopened.theme_selector.currentData(), 'dark')
            reopened.theme_selector.setCurrentIndex(reopened.theme_selector.findData('light'))
            self.assertEqual(reopened_store.value('appearance'), 'light')

    def test_unknown_mode_falls_back_to_light(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            store = QSettings(str(Path(temp) / 'theme.ini'), QSettings.IniFormat)
            store.setValue('appearance', 'unknown')
            window = ChatWindow([], Mock(), store, store, store, store, store)
            self.addCleanup(window.close)
            self.assertEqual(window.theme_selector.currentData(), 'light')

    def test_all_auxiliary_windows_follow_dark_and_light(self):
        from PIL import Image
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QWidget, QMessageBox, QFileDialog, QMenu
        from maeagi_biseo.ui.chat import SettingsDialog
        from maeagi_biseo.ui.character_editor import CharacterEditor
        from maeagi_biseo.ui.region_selector import RegionSelector
        from maeagi_biseo.ui.dialogue import Bubble
        from maeagi_biseo.ui.chat_theme import apply_chat_theme, COLORS
        from maeagi_biseo.core.farming import FarmingStore
        from maeagi_biseo.resources import DEFAULTS
        root = QWidget()
        root.setObjectName('chat')
        windows = []
        try:
            apply_chat_theme(root, 'dark')
            with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
                store = QSettings(str(Path(temp) / 'audit.ini'), QSettings.IniFormat)
                settings = SettingsDialog(DEFAULTS, '', character_store=store, catalog_store=store,
                    capture_store=store, dialogue_store=store, farming_store=FarmingStore(Path(temp) / 'records.sqlite3'))
                editor = CharacterEditor(catalog_store=store)
                region = RegionSelector(Image.new('RGB', (600, 360), '#668866'), 'Test')
                message = QMessageBox(QMessageBox.Warning, 'Test', 'Test')
                files = QFileDialog()
                files.setOption(QFileDialog.DontUseNativeDialog)
                menu = QMenu()
                menu.addAction('Test')
                submenu = menu.addMenu('Submenu')
                submenu.addAction('Test')
                windows = [settings, editor, region, message, files, menu, submenu]
                for index, window in enumerate(windows):
                    window.show()
                    self.app.processEvents()
                    self.assertEqual(window.property('appearance'), 'dark', type(window).__name__)
                    self.assertLess(window.palette().color(QPalette.Window).lightness(), 80)
                    window.grab().save(str(artifact_path(f'theme_audit/{index}_{type(window).__name__}.png')))
                # Every settings page is rendered, including capture and records.
                for index in range(settings.navigation.count()):
                    settings.navigation.setCurrentRow(index)
                    self.app.processEvents()
                    settings.grab().save(str(artifact_path(f'theme_audit/settings_{index}.png')))
                bubble = Bubble(Mock())
                windows.append(bubble)
                self.assertEqual(bubble.appearance['background'], COLORS['dark']['surface'])
                apply_chat_theme(root, 'light')
                for window in windows[:-1]:
                    self.assertEqual(window.property('appearance'), 'light')
                    self.assertGreater(window.palette().color(QPalette.Window).lightness(), 220)
                self.assertEqual(bubble.appearance['background'], '#ffffff')
        finally:
            for window in reversed(windows):
                window.close()
                window.deleteLater()
            root.close()
            root.deleteLater()

    def test_native_chrome_covers_child_dialogs_and_message_boxes(self):
        from PySide6.QtWidgets import QWidget, QDialog, QMessageBox
        from maeagi_biseo.ui.chat_theme import apply_chat_theme, COLORS
        from maeagi_biseo.ui.window_chrome import install_window_chrome
        install_window_chrome()
        parent = QWidget()
        apply_chat_theme(parent, 'dark')
        windows = [parent, QDialog(parent), QMessageBox(parent)]
        try:
            with patch('maeagi_biseo.ui.window_chrome.apply_native_title_bar') as apply:
                for window in windows:
                    window.show()
                    self.app.processEvents()
                    self.assertTrue(any(call.args == (window, COLORS['dark'], True)
                                        for call in apply.call_args_list))
        finally:
            for window in reversed(windows):
                window.close()

    def test_loaded_models_can_be_selected_with_dropdown_click(self):
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QTabWidget
        from maeagi_biseo.ui.chat import SettingsDialog
        from maeagi_biseo.core.farming import FarmingStore
        from maeagi_biseo.resources import DEFAULTS
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            store = QSettings(str(Path(temp) / 'models.ini'), QSettings.IniFormat)
            dialog = SettingsDialog(DEFAULTS, '', character_store=store, catalog_store=store,
                                    capture_store=store, dialogue_store=store,
                                    farming_store=FarmingStore(Path(temp) / 'records.sqlite3'))
            try:
                tabs = dialog.findChild(QTabWidget, 'settingsTabs')
                dialog.navigation.setCurrentRow(tabs.indexOf(dialog.api_scroll))
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
                QTest.qWait(100)
                dialog.models_loaded(['gemini-model-one', 'gemini-model-two'])
                self.app.processEvents()
                combo = dialog.model_combo
                QTest.mouseClick(combo, Qt.LeftButton, pos=QPoint(combo.width() - 14, combo.height() // 2))
                self.app.processEvents()
                self.assertTrue(combo.view().isVisible(), f'combo={combo.geometry()} visible={combo.isVisible()} enabled={combo.isEnabled()} count={combo.count()}')
                index = combo.model().index(1, 0)
                QTest.mouseClick(combo.view().viewport(), Qt.LeftButton,
                                 pos=combo.view().visualRect(index).center())
                self.assertEqual(dialog.values()['model'], 'gemini-model-two')
                combo.lineEdit().setText('custom-model')
                self.assertEqual(dialog.values()['model'], 'custom-model')
            finally:
                dialog.close()

    def test_settings_allows_other_windows_and_preserves_save_cancel(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QPushButton
        from maeagi_biseo.ui.chat import SettingsDialog
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            store = QSettings(str(Path(temp) / 'settings.ini'), QSettings.IniFormat)
            from maeagi_biseo.core.farming import FarmingStore
            window = ChatWindow([], Mock(store=store), store, store, store,
                                FarmingStore(Path(temp) / 'records.sqlite3'), store)
            button = QPushButton('Pet input')
            clicked = Mock()
            button.clicked.connect(clicked)
            try:
                button.show()
                window.settings()
                dialog = window._settings_dialog
                self.app.processEvents()
                self.assertIsNone(QApplication.activeModalWidget())
                self.assertFalse(dialog.isModal())
                QTest.mouseClick(button, Qt.LeftButton)
                clicked.assert_called_once()
                window.settings()
                self.assertIs(window._settings_dialog, dialog)
                self.assertEqual(len(window.findChildren(SettingsDialog)), 1)
                original = window.config['model']
                dialog.reject()
                self.assertIsNone(window._settings_dialog)
                self.assertEqual(window.config['model'], original)
                window.settings()
                dialog = window._settings_dialog
                expected = dialog.values()['model']
                dialog.accept()
                self.assertIsNone(window._settings_dialog)
                self.assertEqual(store.value('model'), expected)
            finally:
                if window._settings_dialog is not None:
                    window._settings_dialog.reject()
                button.close()
                window.close()
