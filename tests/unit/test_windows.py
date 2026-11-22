"""Window-perching behavior, tested without touching the user's applications."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from PySide6.QtCore import QRect, QPoint
from PySide6.QtWidgets import QApplication
from maeagi_biseo.app import Pet, PETS
from maeagi_biseo.platforms.windows import WindowSurface, landing_surface, logical_rect, monitor_screen, keep_above_taskbar


class FakeTracker:
    def __init__(self, surfaces):
        self.surfaces = surfaces

    def snapshot(self, force=False):
        return self.surfaces


class WindowTests(unittest.TestCase):
    def test_pet_group_has_stable_creation_order_with_one_coordinator(self):
        older, newer = Mock(), Mock()
        with patch('maeagi_biseo.app.PETS', [older, newer]), patch('maeagi_biseo.app.keep_above_taskbar') as keep:
            Pet.ensure_above_taskbar(older)
            keep.assert_not_called()
            Pet.ensure_above_taskbar(newer)
            self.assertEqual(keep.call_args_list, [unittest.mock.call(newer),
                                                  unittest.mock.call(older, behind=newer)])

    def test_older_pet_is_placed_behind_newer_without_activation(self):
        api = Mock()
        widget, front = Mock(), Mock()
        widget.winId.return_value = 200
        front.winId.return_value = 300
        api.GetWindow.return_value = 100
        with patch('maeagi_biseo.platforms.windows.ctypes.WinDLL', return_value=api), patch('maeagi_biseo.platforms.windows.QGuiApplication.platformName', return_value='windows'):
            keep_above_taskbar(widget, behind=front)
            args = api.SetWindowPos.call_args.args
            self.assertEqual(args[0], 200)
            self.assertEqual(args[1].value, 300)
            self.assertEqual(args[2:], (0, 0, 0, 0, 0x13))
            api.SetWindowPos.reset_mock()
            api.GetWindow.return_value = 200
            keep_above_taskbar(widget, behind=front)
            api.SetWindowPos.assert_not_called()

    def test_taskbar_order_restored_without_moving_resizing_or_activating(self):
        api = Mock()
        api.GetTopWindow.return_value = 100
        api.IsWindowVisible.return_value = True
        def class_name(handle, buffer, size):
            buffer.value = 'OtherApplicationWindow'
            return len(buffer.value)
        api.GetClassNameW.side_effect = class_name
        widget = Mock()
        widget.isVisible.return_value = True
        widget.winId.return_value = 200
        with patch('maeagi_biseo.platforms.windows.ctypes.WinDLL', return_value=api), patch('maeagi_biseo.platforms.windows.QGuiApplication.platformName', return_value='windows'):
            keep_above_taskbar(widget)
        args = api.SetWindowPos.call_args.args
        self.assertEqual(args[0], 200)
        self.assertEqual(args[2:], (0, 0, 0, 0, 0x13))
        api.reset_mock()
        api.GetTopWindow.return_value = 200
        with patch('maeagi_biseo.platforms.windows.ctypes.WinDLL', return_value=api), patch('maeagi_biseo.platforms.windows.QGuiApplication.platformName', return_value='windows'):
            keep_above_taskbar(widget)
        api.SetWindowPos.assert_not_called()
        api.reset_mock()
        api.GetTopWindow.return_value = 100
        api.GetWindow.return_value = 200
        def own_process(handle, output):
            output._obj.value = os.getpid()
        api.GetWindowThreadProcessId.side_effect = own_process
        with patch('maeagi_biseo.platforms.windows.ctypes.WinDLL', return_value=api), patch('maeagi_biseo.platforms.windows.QGuiApplication.platformName', return_value='windows'):
            keep_above_taskbar(widget)
        api.SetWindowPos.assert_not_called()

    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tracker = FakeTracker([WindowSurface(1, QRect(100, 250, 500, 300))])
        self.pet = Pet(x=220, kind='robot', window_tracker=self.tracker)
        self.pet.timer.stop()

    def tearDown(self):
        PETS.remove(self.pet)
        self.pet.close()

    def place_on_window(self):
        self.pet.xpos = 220
        self.pet.ypos = 250 - self.pet.foot_offset + 15
        self.pet.land()

    def test_drag_landing_and_follow_moving_window(self):
        self.place_on_window()
        self.assertEqual(self.pet.platform, 1)
        self.assertEqual(self.pet.ypos + self.pet.foot_offset, 250)
        self.tracker.surfaces = [WindowSurface(1, QRect(160, 280, 500, 300))]
        self.pet.follow_platform()
        self.assertEqual(self.pet.xpos, 280)
        self.assertEqual(self.pet.ypos + self.pet.foot_offset, 280)

    def test_walk_turns_at_platform_edge(self):
        self.place_on_window()
        self.pet.xpos = 470
        self.pet.direction = 1
        self.pet.set_state('walk')
        self.pet.tick()
        self.assertEqual(self.pet.xpos, 470)
        self.assertEqual(self.pet.direction, -1)
        self.assertEqual(self.pet.platform, 1)

    def test_removed_or_minimized_window_starts_a_fall(self):
        self.place_on_window()
        before = self.pet.ypos
        self.tracker.surfaces = []
        self.pet.follow_platform()
        self.assertIsNone(self.pet.platform)
        self.assertEqual(self.pet.motion, 'air')
        self.assertEqual(self.pet.ypos, before)
        for _ in range(100):
            if self.pet.motion != 'air':
                break
            self.pet.step_air()
        self.assertEqual(self.pet.motion, 'ground')
        self.assertEqual(self.pet.ypos + self.pet.foot_offset, self.pet.area.bottom() + 1)

    def test_maximized_or_narrow_window_returns_pet_to_floor(self):
        for rect in (QRect(100, 0, 500, 500), QRect(100, 250, 90, 300)):
            self.tracker.surfaces = [WindowSurface(1, QRect(100, 250, 500, 300))]
            self.place_on_window()
            self.tracker.surfaces = [WindowSurface(1, rect)]
            self.pet.follow_platform()
            self.assertIsNone(self.pet.platform)
            self.assertEqual(self.pet.motion, 'air')

    def test_landing_requires_nearby_exposed_top_edge(self):
        platform = WindowSurface(1, QRect(100, 250, 500, 300))
        blocker = WindowSurface(2, QRect(200, 200, 200, 300))
        self.assertIsNone(landing_surface([blocker, platform], 280, 250, 130, 139))
        self.assertEqual(landing_surface([blocker, platform], 150, 250, 130, 139), platform)
        self.assertIsNone(landing_surface([platform], 280, 350, 130, 139))

    def test_occluded_platform_returns_pet_to_floor(self):
        self.place_on_window()
        self.tracker.surfaces.insert(0, WindowSurface(2, QRect(200, 200, 200, 300)))
        self.pet.follow_platform()
        self.assertIsNone(self.pet.platform)

    def test_scaled_secondary_display_coordinates(self):
        rect = logical_rect((2070, 300, 2820, 900), (1920, 0), QPoint(1920, 0), 1.5)
        self.assertEqual(rect, QRect(2020, 200, 500, 400))
        negative = logical_rect((-1800, 300, -1200, 900), (-1920, 0), QPoint(-1920, 0), 1.5)
        self.assertEqual(negative, QRect(-1840, 200, 400, 400))

    def test_monitor_mapping_with_qt_friendly_names(self):
        screen = SimpleNamespace(name=lambda: 'Friendly monitor',
            geometry=lambda: QRect(1920, 0, 1280, 720), devicePixelRatio=lambda: 1.5)
        info = SimpleNamespace(szDevice='DISPLAY2', rcMonitor=SimpleNamespace(
            left=1920, top=0, right=3840, bottom=1080))
        self.assertIs(monitor_screen(info, [screen]), screen)


if __name__ == '__main__':
    unittest.main()
