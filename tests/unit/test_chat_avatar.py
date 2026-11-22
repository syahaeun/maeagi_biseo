"""Profile photo editor: fixed frame, drag to pan, wheel/slider to zoom."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from maeagi_biseo.resources import PROJECT_ROOT, read_json
from maeagi_biseo.core.sprites import CharacterInfo
from maeagi_biseo.ui.chat_avatar import (CUSTOM_MAX_SIDE, DEFAULT_CROP, ChatAvatarDialog, MIN_SCALE, avatar_pixmap,
                                    avatar_source, crop_rect, custom_avatar_path, face_crop, full_scale)
from tests.artifacts import artifact_path


def figure():
    """A tall test figure: a red head block on top of a blue body."""
    image = QPixmap(100, 200)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.fillRect(30, 0, 40, 40, QColor('red'))
    painter.fillRect(20, 50, 60, 150, QColor('blue'))
    painter.end()
    return image


class ChatAvatarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, crop=DEFAULT_CROP, image=None):
        dialog = ChatAvatarDialog(image or figure(), 'Test', crop)
        self.addCleanup(dialog.close)
        dialog.resize(640, 460)
        dialog.show()
        QTest.qWaitForWindowExposed(dialog)
        return dialog

    def test_face_crop_targets_the_head(self):
        crop = face_crop(figure())
        box = crop_rect(figure().rect().toRectF(), crop)
        self.assertTrue(box.contains(QPointF(30, 0)) and box.contains(QPointF(70, 40)))
        self.assertLess(box.bottom(), 110)

    def test_opens_on_face_and_full_body_shows_everything(self):
        dialog = self.dialog()
        view = dialog.source
        self.assertIsInstance(dialog.crop(), dict)
        self.assertEqual(view.source_rect(), crop_rect(figure().rect().toRectF(), face_crop(figure())))
        QTest.mouseClick(dialog.full_button, Qt.LeftButton)
        self.assertAlmostEqual(dialog.crop()['scale'], full_scale(100, 200))
        self.assertEqual(view.source_rect().height(), 200)
        QTest.mouseClick(dialog.face_button, Qt.LeftButton)
        self.assertEqual(dialog.crop(), view.selection)
        self.assertLess(dialog.crop()['scale'], 1)

    def test_drag_pans_the_image_and_stops_at_edges(self):
        dialog = self.dialog(dict(x=.5, y=.5, scale=.5))
        view = dialog.source
        before = view.source_rect()
        centre = view.frame_rect().center().toPoint()
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, centre)
        QTest.mouseMove(view, centre + QPoint(0, 40))
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, centre + QPoint(0, 40))
        after = view.source_rect()
        self.assertLess(after.top(), before.top())
        self.assertAlmostEqual(after.width(), before.width())
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, centre)
        for step in range(1, 30):
            QTest.mouseMove(view, centre + QPoint(0, step * 40))
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, centre + QPoint(0, 1160))
        self.assertEqual(view.source_rect().top(), 0)
        self.assertAlmostEqual(view.selection['y'], view.source_rect().center().y() / 200)

    def test_wheel_slider_and_keys_zoom(self):
        dialog = self.dialog(dict(x=.5, y=.3, scale=.6))
        view = dialog.source
        centre = QPointF(view.frame_rect().center())
        wheel = QWheelEvent(centre, view.mapToGlobal(centre), QPoint(), QPoint(0, 120), Qt.NoButton,
                            Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(view, wheel)
        self.assertLess(dialog.crop()['scale'], .6)
        self.assertEqual(dialog.zoom_slider.value(), view.slider_value())
        dialog.zoom_slider.setValue(1000)
        self.assertAlmostEqual(dialog.crop()['scale'], MIN_SCALE)
        dialog.zoom_slider.setValue(0)
        self.assertAlmostEqual(dialog.crop()['scale'], full_scale(100, 200))
        view.setFocus()
        QTest.keyClick(view, Qt.Key_Plus)
        self.assertLess(dialog.crop()['scale'], full_scale(100, 200))
        QTest.keyClick(view, Qt.Key_Space)
        self.assertEqual(view.source_rect(), crop_rect(figure().rect().toRectF(), face_crop(figure())))

    def test_saved_crop_renders_what_the_frame_shows(self):
        dialog = self.dialog()
        portrait = avatar_pixmap(figure(), 'Test', 120, dialog.crop()).toImage()
        self.assertEqual(portrait.pixelColor(60, 25).name(), '#ff0000')
        full = avatar_pixmap(figure(), 'Test', 120, dict(x=.5, y=.5, scale=2)).toImage()
        self.assertEqual(full.pixelColor(60, 100).name(), '#0000ff')
        self.assertEqual(full.pixelColor(60, 10).name(), '#ff0000')
        self.assertEqual([label.pixmap().width() for _, label in dialog.small_previews], [44, 34])

    def test_bundled_character_screenshot(self):
        identifier = read_json('characters.json')['default']
        image = avatar_source(PROJECT_ROOT / 'Images/Characters' / identifier)
        self.assertIsNotNone(image)
        dialog = self.dialog(image=image)
        self.app.processEvents()
        dialog.grab().save(str(artifact_path('chat_avatar/editor_face.png')))
        QTest.mouseClick(dialog.full_button, Qt.LeftButton)
        self.app.processEvents()
        dialog.grab().save(str(artifact_path('chat_avatar/editor_full.png')))


    def photo(self, folder, name='photo.jpg', size=(1600, 900)):
        """An opaque landscape photo: green left half, yellow right half."""
        image = QPixmap(*size)
        image.fill(QColor('green'))
        painter = QPainter(image)
        painter.fillRect(size[0] // 2, 0, size[0] // 2, size[1], QColor('yellow'))
        painter.end()
        path = Path(folder) / name
        self.assertTrue(image.save(str(path)))
        return path

    def test_imported_photo_is_shrunk_and_centred(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            dialog = self.dialog()
            self.assertFalse(dialog.character_button.isEnabled())
            self.assertTrue(dialog.load_image_file(self.photo(temp)))
            self.assertEqual(max(dialog.image_choice.width(), dialog.image_choice.height()), CUSTOM_MAX_SIDE)
            self.assertEqual(dialog.crop(), dict(x=.5, y=.5, scale=1.0))
            self.assertTrue(dialog.character_button.isEnabled())
            QTest.mouseClick(dialog.character_button, Qt.LeftButton)
            self.assertEqual(dialog.image_choice, 'character')
            self.assertFalse(dialog.character_button.isEnabled())
            dialog.grab().save(str(artifact_path('chat_avatar/editor_back_to_character.png')))

    def test_unreadable_file_is_rejected_without_changing_the_picture(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            broken = Path(temp) / 'broken.png'
            broken.write_bytes(b'not an image')
            dialog = self.dialog()
            before = dialog.crop()
            with patch.object(QMessageBox, 'warning') as warning:
                self.assertFalse(dialog.load_image_file(broken))
            warning.assert_called_once()
            self.assertIsNone(dialog.image_choice)
            self.assertEqual(dialog.crop(), before)

    def test_chat_saves_uses_and_removes_the_custom_picture(self):
        fixture = Path(__file__).resolve().parents[1] / 'fixtures' / 'characters' / 'robot'
        catalog = {'robot': CharacterInfo('robot', 'Robot', fixture)}
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp,              patch('maeagi_biseo.ui.chat.registered_characters', side_effect=lambda *args: dict(catalog)):
            from maeagi_biseo.ui.chat import ChatWindow
            store = QSettings(str(Path(temp) / 'chat.ini'), QSettings.IniFormat)
            robot = Mock(kind='robot')
            chat = ChatWindow([robot], Mock(), store, store, store, avatar_root=Path(temp) / 'avatars')
            self.addCleanup(chat.close)
            self.addCleanup(chat.target_refresh_timer.stop)
            chat.open_for(robot)
            photo = self.photo(temp, 'me.png')
            target = custom_avatar_path(Path(temp) / 'avatars', 'robot')

            def pick_photo(dialog):
                dialog.load_image_file(photo)
                return QDialog.Accepted

            with patch.object(ChatAvatarDialog, 'exec', pick_photo):
                QTest.mouseClick(chat.profile_button, Qt.LeftButton)
            self.assertTrue(target.is_file())
            self.assertFalse(target.with_name(target.name + '.tmp').exists())
            portrait = chat.avatar('robot', 'Robot', 120).toImage()
            self.assertEqual(portrait.pixelColor(30, 60).name(), '#008000')
            self.assertEqual(portrait.pixelColor(90, 60).name(), '#ffff00')

            def keep(dialog):
                self.assertTrue(dialog.custom)
                self.assertEqual(dialog.image.width(), CUSTOM_MAX_SIDE)
                return QDialog.Accepted

            with patch.object(ChatAvatarDialog, 'exec', keep):
                QTest.mouseClick(chat.profile_button, Qt.LeftButton)
            self.assertTrue(target.is_file())

            def back(dialog):
                QTest.mouseClick(dialog.character_button, Qt.LeftButton)
                return QDialog.Accepted

            with patch.object(ChatAvatarDialog, 'exec', back):
                QTest.mouseClick(chat.profile_button, Qt.LeftButton)
            self.assertFalse(target.exists())
            self.assertNotEqual(chat.avatar('robot', 'Robot', 120).toImage().pixelColor(30, 60).name(), '#008000')

    def test_unsafe_identifiers_get_hashed_file_names(self):
        root = Path('avatars')
        self.assertEqual(custom_avatar_path(root, 'user_abc-1').name, 'user_abc-1.png')
        unsafe = custom_avatar_path(root, '../루시드')
        self.assertEqual(unsafe.parent, root)
        self.assertRegex(unsafe.name, r'^id_[0-9a-f]{32}\.png$')

if __name__ == '__main__':
    unittest.main()
