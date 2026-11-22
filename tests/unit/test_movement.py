import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
from types import SimpleNamespace

from PySide6.QtCore import QRect, QPointF, Qt
from PySide6.QtWidgets import QApplication

from maeagi_biseo.app import Pet, PETS
from maeagi_biseo.core.movement import BEHAVIORS
from maeagi_biseo.platforms.windows import WindowSurface, crossed_surface
from maeagi_biseo.ui.dialogue import DialogueManager


class Tracker:
    def __init__(self, surfaces=None):
        self.surfaces = surfaces or []

    def snapshot(self, force=False):
        return self.surfaces


class MovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tracker = Tracker()
        self.pet = Pet(x=200, kind='robot', window_tracker=self.tracker)
        self.pet.timer.stop()

    def tearDown(self):
        self.pet.timer.stop()
        PETS.remove(self.pet)
        self.pet.close()

    def settle(self):
        for _ in range(200):
            if self.pet.motion != 'air':
                return
            self.pet.step_air()
        self.fail('Flight did not finish')

    def test_drop_in_midair_falls_without_teleporting(self):
        self.pet.ypos = 50
        self.pet.land()
        self.assertEqual(self.pet.motion, 'air')
        self.assertEqual(self.pet.ypos, 50)
        self.pet.step_air()
        self.assertGreater(self.pet.ypos, 50)
        self.settle()
        self.assertEqual(self.pet.ypos + self.pet.foot_offset, self.pet.area.bottom() + 1)

    def test_fall_lands_on_first_window_below(self):
        self.tracker.surfaces = [WindowSurface(1, QRect(100, 300, 500, 120)),
                                 WindowSurface(2, QRect(100, 450, 500, 120))]
        self.pet.ypos = 40
        self.pet.begin_fall()
        self.settle()
        self.assertEqual(self.pet.platform, 1)
        self.assertEqual(self.pet.ypos + self.pet.foot_offset, 300)

    def test_high_window_accepts_transparent_space_above_screen(self):
        margin = self.pet.sprites.idle_top_margin
        self.assertGreater(margin, 0)
        top = self.pet.area.top()
        surface_y = top + self.pet.foot_offset - margin
        self.tracker.surfaces = [WindowSurface(1, QRect(100, surface_y, 500, 120))]
        self.pet.ypos = float(top - margin)
        self.pet.land()
        self.assertEqual(self.pet.platform, 1)
        self.pet.follow_platform()
        self.assertEqual(self.pet.motion, 'ground')
        self.assertEqual(self.pet.ypos + margin, top)
        self.pet.begin_fall()
        self.pet.step_air()
        self.assertEqual(self.pet.platform, 1)

    def test_fast_fall_interpolates_horizontal_collision(self):
        target = WindowSurface(1, QRect(100, 250, 180, 80))
        surface, x = crossed_surface([target], 150, 240, 350, 280, 130, 139)
        self.assertEqual(surface, target)
        self.assertEqual(x, 200)
        self.assertEqual(crossed_surface([target], 150, 280, 150, 240, 130, 139), (None, None))

    def test_jump_moves_real_position_then_lands(self):
        before = self.pet.ypos
        self.pet.direction = 1
        self.pet.start_jump()
        self.pet.step_air()
        self.assertLess(self.pet.ypos, before)
        self.assertGreater(self.pet.xpos, 200)
        self.settle()
        self.assertEqual(self.pet.motion, 'ground')
        self.assertEqual(self.pet.ypos, before)

    def test_jump_returns_to_original_window(self):
        surface = WindowSurface(1, QRect(100, 300, 500, 200))
        self.tracker.surfaces = [surface]
        self.pet.attach(surface)
        self.pet.start_jump()
        self.settle()
        self.assertEqual(self.pet.platform, 1)
        self.assertEqual(self.pet.ypos + self.pet.foot_offset, 300)

    def test_wall_to_ceiling_and_ceiling_timeout_to_fall(self):
        self.pet.attach_wall(-1)
        before = self.pet.ypos
        self.pet.step_wall()
        self.assertLess(self.pet.ypos, before)
        self.pet.ypos = self.pet.area.top() + 1
        self.pet.step_wall()
        self.assertEqual(self.pet.motion, 'ceiling')
        self.assertEqual(self.pet.direction, 1)
        self.pet.step_ceiling()
        self.assertGreater(self.pet.xpos, self.pet.area.left())
        self.pet.state_until = 0
        self.pet.step_ceiling()
        self.assertEqual(self.pet.motion, 'air')

    def test_manual_climb_walks_to_screen_edge(self):
        self.pet.request_climb()
        before = self.pet.xpos
        self.pet.tick()
        self.assertEqual(abs(self.pet.xpos - before), BEHAVIORS['movement']['walk_speed'])
        self.pet.xpos = self.pet.area.left()
        self.pet.direction = -1
        self.pet.tick()
        self.assertEqual(self.pet.motion, 'wall')

    def test_focus_stops_climbing_but_preserves_gravity(self):
        self.pet.attach_wall(-1)
        self.pet.ypos = 100
        self.pet.set_focus(True)
        self.assertEqual(self.pet.motion, 'air')
        before = self.pet.ypos
        self.pet.tick()
        self.assertGreater(self.pet.ypos, before)
        self.settle()
        self.pet.choose()
        self.assertEqual(self.pet.state, 'idle')

    def test_pause_freezes_flight_and_resume_continues(self):
        self.pet.ypos = 40
        self.pet.begin_fall()
        self.pet.set_paused(True)
        self.pet.tick()
        self.assertEqual(self.pet.ypos, 40)
        self.pet.set_paused(False)
        self.pet.tick()
        self.assertGreater(self.pet.ypos, 40)

    def test_click_does_not_snap_airborne_pet_to_floor(self):
        self.pet.ypos = 80
        self.pet.begin_fall()
        event = SimpleNamespace(button=lambda: Qt.LeftButton,
                                globalPosition=lambda: QPointF(self.pet.x(), self.pet.y()))
        self.pet.mousePressEvent(event)
        self.pet.mouseReleaseEvent(event)
        self.assertEqual(self.pet.ypos, 80)
        self.assertEqual(self.pet.motion, 'air')

    def test_throw_velocity_is_bounded_and_stale_samples_are_ignored(self):
        now = time.monotonic()
        self.pet.drag_samples = [(now-.1, 100, 100), (now, 500, 500)]
        vx, vy = self.pet.release_velocity()
        self.assertGreater(vx, 0)
        self.assertLessEqual(vx, BEHAVIORS['physics']['throw_max_speed'])
        self.pet.drag_samples = [(now-1, 100, 100), (now-.9, 500, 500)]
        self.assertEqual(self.pet.release_velocity(), (0, 0))

    def test_throw_faces_release_direction_and_vertical_drop_keeps_facing(self):
        for initial, dx, expected in ((-1, 100, 1), (1, -100, -1), (-1, 0, -1), (1, 0, 1)):
            with self.subTest(initial=initial, dx=dx):
                self.pet.direction = initial
                self.pet.ypos = 50
                self.pet.drag_offset = QPointF(0, 0)
                self.pet.drag_active = True
                now = time.monotonic()
                self.pet.drag_samples = [(now - .1, 200, 50), (now, 200 + dx, 60)]
                event = SimpleNamespace(button=lambda: Qt.LeftButton)
                self.pet.mouseReleaseEvent(event)
                self.assertEqual(self.pet.direction, expected)
                self.assertEqual(self.pet.motion, 'air')
                if dx:
                    self.assertGreater(self.pet.vx * expected, 0)

    def test_dialogue_never_freezes_airborne_or_paused_pet(self):
        friend = Pet(x=350, kind='robot', window_tracker=self.tracker)
        friend.timer.stop()
        manager = DialogueManager(PETS)
        manager.timer.stop()
        try:
            manager.start(self.pet, friend)
            self.assertIsNotNone(manager.active)
            self.pet.begin_fall()
            manager.tick()
            self.assertIsNone(manager.active)
            self.assertEqual(self.pet.state, 'fall')
            manager.start(self.pet, friend)
            self.assertIsNone(manager.active)
            self.pet.go_to_floor()
            self.pet.set_paused(True)
            manager.start(self.pet, friend)
            self.assertIsNone(manager.active)
        finally:
            for bubble in manager.bubbles.values():
                bubble.close()
                bubble.deleteLater()
            PETS.remove(friend)
            friend.close()


if __name__ == '__main__':
    unittest.main()
