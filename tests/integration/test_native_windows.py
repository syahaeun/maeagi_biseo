"""Run separately on Windows to verify actual HWND/DWM geometry and lifecycle."""
import sys
import ctypes
import unittest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from maeagi_biseo.platforms.windows import WindowTracker, MonitorInfo
from maeagi_biseo.app import Pet, PETS
from maeagi_biseo.platforms.window_capture import capture_window
from tests.artifacts import artifact_path


@unittest.skipUnless(sys.platform == 'win32', 'Native Windows integration only')
class NativeWindowsTests(unittest.TestCase):
    def test_obs_canvas_captures_pet_and_bubble_together(self):
        from PySide6.QtCore import QPoint
        from maeagi_biseo.ui.broadcast import BroadcastWindow
        from maeagi_biseo.ui.dialogue import Bubble
        from maeagi_biseo.resources import tr
        pet = Pet(kind='robot')
        pet.timer.stop()
        pet.topmost_timer.stop()
        area = self.app.primaryScreen().availableGeometry()
        pet.move(area.left()+200, area.top()+250)
        bubble = Bubble(pet)
        bubble.say(tr('editor.bubble_sample'))
        canvas = BroadcastWindow(pet, lambda: bubble)
        try:
            canvas.show()
            QTest.qWait(150)
            user = ctypes.windll.user32
            def assert_off_desktop():
                bounds=ctypes.wintypes.RECT()
                user.GetWindowRect(ctypes.wintypes.HWND(int(canvas.winId())),ctypes.byref(bounds))
                right=user.GetSystemMetrics(76)+user.GetSystemMetrics(78)
                self.assertGreaterEqual(bounds.left,right)
                self.assertTrue(canvas.isVisible())
                self.assertFalse(user.IsIconic(ctypes.wintypes.HWND(int(canvas.winId()))))
            assert_off_desktop()
            canvas.move(pet.screen().geometry().topLeft())
            QTest.qWait(60)
            assert_off_desktop()
            canvas.hide()
            canvas.showNormal()
            QTest.qWait(60)
            assert_off_desktop()
            for widget in (bubble, canvas):
                handle = int(widget.winId())
                self.assertTrue(user.IsWindowVisible(handle))
                self.assertFalse(user.GetWindowLongW(handle,-20)&0x80)
                self.assertFalse(user.GetWindowLongW(handle,-16)&0x40000000)
            handle = int(canvas.winId())
            rect, point = ctypes.wintypes.RECT(), ctypes.wintypes.POINT()
            user.GetClientRect(ctypes.wintypes.HWND(handle),ctypes.byref(rect))
            user.ClientToScreen(ctypes.wintypes.HWND(handle),ctypes.byref(point))
            image = capture_window(handle,(point.x,point.y,point.x+rect.right,point.y+rect.bottom))
            sample = canvas.layout_rects(bubble)[1].topLeft()+QPoint(8,bubble.height()//2)
            self.assertEqual(image.getpixel((sample.x(),sample.y())),(255,255,255))
            self.assertEqual(image.getpixel((2,2)),(0,0,0))
            image.save(artifact_path('obs/native-combined.png'))
            canvas.set_config(dict(position='fixed',anchor_x=50,anchor_y=85,
                                   pet_scale=180,bubble_scale=140,bubble_position='below',
                                   pet_alignment=0,pet_gap=36))
            fixed_rects = canvas.layout_rects(bubble)
            pet.move(pet.pos()+QPoint(120,40))
            bubble.follow()
            QTest.qWait(100)
            self.assertEqual(canvas.layout_rects(bubble),fixed_rects)
            assert_off_desktop()
            point = ctypes.wintypes.POINT()
            user.GetClientRect(ctypes.wintypes.HWND(handle),ctypes.byref(rect))
            user.ClientToScreen(ctypes.wintypes.HWND(handle),ctypes.byref(point))
            image = capture_window(handle,(point.x,point.y,point.x+rect.right,point.y+rect.bottom))
            bubble_rect = fixed_rects[1]
            self.assertEqual(image.getpixel((bubble_rect.left()+12,bubble_rect.center().y())),(255,255,255))
            image.save(artifact_path('obs/native-scaled-fixed.png'))
        finally:
            canvas.close()
            bubble.page_timer.stop()
            bubble.close()
            PETS.remove(pet)
            pet.close()

    def test_pet_is_eligible_for_obs_window_capture(self):
        pet = Pet(x=200, kind='robot')
        try:
            QTest.qWait(100)
            user32 = ctypes.windll.user32
            handle = int(pet.winId())
            self.assertTrue(user32.IsWindowVisible(handle))
            self.assertFalse(user32.IsIconic(handle))
            # Match OBS check_window_valid: no tool windows or child windows.
            self.assertFalse(user32.GetWindowLongW(handle, -20) & 0x00000080)
            self.assertFalse(user32.GetWindowLongW(handle, -16) & 0x40000000)
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(handle, title, len(title))
            self.assertEqual(title.value, pet.sprites.info.name)
            self.assertGreater(user32.GetWindowTextLengthW(handle), 0)
        finally:
            pet.timer.stop()
            pet.topmost_timer.stop()
            PETS.remove(pet)
            pet.close()

    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])
        if cls.app.platformName() != 'windows':
            raise unittest.SkipTest('Run separately without QT_QPA_PLATFORM=offscreen')
        cls.app.setQuitOnLastWindowClosed(False)

    def test_native_window_perch_move_minimize_and_close(self):
        host = QWidget()
        host.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        area = self.app.primaryScreen().availableGeometry()
        host.setGeometry(area.left() + 100, area.top() + 250, 500, 220)
        host.show()
        QTest.qWait(150)
        tracker = WindowTracker(excluded_pid=-1)
        handle = int(host.winId())
        pet = None
        try:
            def surface():
                return next((item for item in tracker.snapshot(force=True) if item.handle == handle), None)

            initial = surface()
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            tracker.user32.GetMonitorInfoW(tracker.user32.MonitorFromWindow(handle, 2), ctypes.byref(info))
            self.assertIsNotNone(initial, (info.szDevice, [item.name() for item in self.app.screens()],
                tracker.user32.IsWindowVisible(handle), tracker.user32.IsIconic(handle),
                hex(tracker.user32.GetWindowLongW(handle, -20))))
            pet = Pet(x=initial.rect.left() + 60, kind='robot', window_tracker=tracker)
            pet.timer.stop()
            pet.ypos = initial.rect.top() - pet.foot_offset + 10
            pet.land()
            self.assertEqual(pet.platform, handle)
            old_x = pet.xpos
            host.move(host.x() + 40, host.y() + 25)
            QTest.qWait(120)
            moved = surface()
            pet.follow_platform()
            self.assertEqual(pet.xpos, old_x + moved.rect.left() - initial.rect.left())
            self.assertEqual(pet.ypos + pet.foot_offset, moved.rect.top())
            host.showMinimized()
            QTest.qWait(120)
            tracker.snapshot(force=True)
            pet.follow_platform()
            self.assertIsNone(pet.platform)
            host.showNormal()
            QTest.qWait(120)
            restored = surface()
            self.assertIsNotNone(restored)
            pet.xpos = restored.rect.left() + 60
            pet.ypos = restored.rect.top() - pet.foot_offset
            pet.land()
            self.assertEqual(pet.platform, handle)
            host.close()
            QTest.qWait(120)
            tracker.snapshot(force=True)
            pet.follow_platform()
            self.assertIsNone(pet.platform)
        finally:
            if pet:
                pet.timer.stop()
                PETS.remove(pet)
                pet.close()
            host.close()

    def test_background_capture_excludes_cover_without_changing_focus(self):
        host, cover = QWidget(), QWidget()
        host.setStyleSheet('background: rgb(30, 160, 70);')
        cover.setStyleSheet('background: rgb(200, 40, 50);')
        host.setGeometry(100, 150, 400, 220)
        cover.setGeometry(90, 140, 440, 260)
        try:
            host.show()
            QTest.qWait(150)
            cover.show()
            cover.raise_()
            cover.activateWindow()
            QTest.qWait(150)
            user = ctypes.windll.user32
            hwnd = int(host.winId())
            rect, point = ctypes.wintypes.RECT(), ctypes.wintypes.POINT()
            user.GetClientRect(ctypes.wintypes.HWND(hwnd), ctypes.byref(rect))
            user.ClientToScreen(ctypes.wintypes.HWND(hwnd), ctypes.byref(point))
            before = user.GetForegroundWindow()
            image = capture_window(hwnd, (point.x, point.y,
                                         point.x + rect.right, point.y + rect.bottom))
            image.save(artifact_path('background_capture/covered_window.png'))
            self.assertEqual(image.size, (rect.right, rect.bottom))
            self.assertEqual(image.getpixel((image.width // 2, image.height // 2)), (30, 160, 70))
            self.assertEqual(user.GetForegroundWindow(), before)
            self.assertTrue(cover.isVisible())
        finally:
            host.close()
            cover.close()


if __name__ == '__main__':
    unittest.main()
