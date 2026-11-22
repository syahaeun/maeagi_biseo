"""Capture canvas contains the pet and speech at their desktop-relative positions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from maeagi_biseo.app import Pet, PETS
from maeagi_biseo.ui.broadcast import BroadcastWindow
from maeagi_biseo.ui.dialogue import Bubble
from maeagi_biseo.resources import tr
from maeagi_biseo.core.obs_settings import DEFAULT_OBS
from tests.artifacts import artifact_path


class BroadcastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf')

    def setUp(self):
        self.pet = Pet(kind='robot')
        self.pet.apply_obs_settings(DEFAULT_OBS)
        self.pet.timer.stop()
        self.pet.topmost_timer.stop()
        screen = self.pet.screen().availableGeometry()
        self.pet.move(screen.left()+200, screen.top()+250)
        self.bubble = Bubble(self.pet)
        self.bubble.say(tr('editor.bubble_sample'))
        self.window = BroadcastWindow(self.pet, lambda: self.bubble)
        self.window.show()
        self.window.timer.stop()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.bubble.page_timer.stop()
        self.bubble.close()
        self.pet.set_broadcast_enabled(False)
        if self.pet.broadcast_window is not None:
            self.pet.broadcast_window.close()
        PETS.remove(self.pet)
        self.pet.close()

    def test_frame_includes_bubble_and_pet_with_transparent_surroundings(self):
        frame = self.window.grab().toImage()
        origin = self.window.canvas_geometry.topLeft()
        bubble_point = self.bubble.pos()-origin+QPoint(8,self.bubble.height()//2)
        self.assertEqual(frame.pixelColor(bubble_point), self.bubble.grab().toImage().pixelColor(8,self.bubble.height()//2))
        self.assertEqual(frame.pixelColor(bubble_point).alpha(),255)
        pet_frame=self.pet.grab().toImage()
        visible=next(QPoint(x,y) for y in range(pet_frame.height()) for x in range(pet_frame.width())
                     if pet_frame.pixelColor(x,y).alpha()==255)
        self.assertEqual(frame.pixelColor(self.pet.pos()-origin+visible),pet_frame.pixelColor(visible))
        self.assertEqual(frame.pixelColor(2,2).alpha(),0)
        frame.save(str(artifact_path('obs/combined.png')))
        self.bubble.hide()
        self.assertEqual(self.window.grab().toImage().pixelColor(bubble_point).alpha(),0)

    def test_movement_and_text_changes_are_reflected_without_stale_pixels(self):
        self.pet.move(self.pet.pos()+QPoint(120,100))
        self.bubble.say(tr('chat.title'))
        self.window.refresh()
        frame=self.window.grab().toImage()
        point=self.bubble.pos()-self.window.canvas_geometry.topLeft()+QPoint(8,self.bubble.height()//2)
        self.assertEqual(frame.pixelColor(point).alpha(),255)
        self.assertEqual(self.window.canvas_geometry,self.pet.screen().geometry())
        self.assertEqual(self.window.windowTitle(),tr('obs.window_title',name=self.pet.sprites.info.name))

    def test_broadcast_menu_opens_and_hides_the_canvas(self):
        menu=self.pet.action_menu()
        try:
            action=next(a for a in menu.actions() if a.text()==tr('obs.menu'))
            action.trigger()
            self.assertTrue(self.pet.broadcast_window.isVisible())
            self.assertTrue(self.pet.broadcast_window.timer.isActive())
            action.trigger()
            self.assertFalse(self.pet.broadcast_window.isVisible())
            self.assertFalse(self.pet.broadcast_window.timer.isActive())
        finally:
            menu.close()

    def test_bubble_is_named_and_is_not_a_tool_window(self):
        self.assertEqual(self.bubble.windowTitle(),tr('obs.bubble_title',name=self.pet.sprites.info.name))
        self.assertEqual(self.bubble.windowFlags() & Qt.WindowType_Mask,Qt.Window)

    def test_independent_scales_leave_desktop_widgets_unchanged(self):
        original_pet=self.pet.size()
        original_bubble=self.bubble.size()
        original_tail=self.bubble.tail_on_top
        self.window.set_config(dict(position='fixed',anchor_x=50,anchor_y=80,
                                    pet_scale=200,bubble_scale=150))
        pet_rect,bubble_rect,_=self.window.layout_rects(self.bubble)
        top_margin = self.pet.sprites.idle_top_margin
        self.assertGreater(top_margin, 0)
        self.assertEqual(pet_rect.size(), (original_pet - QSize(0, top_margin))*2)
        self.assertEqual(bubble_rect.size(),original_bubble*1.5)
        frame=self.window.grab().toImage()
        frame.save(str(artifact_path('obs/scaled-fixed.png')))
        self.assertEqual(self.pet.size(),original_pet)
        self.assertEqual(self.bubble.size(),original_bubble)
        self.assertEqual(self.bubble.tail_on_top,original_tail)
        self.assertTrue(self.window.rect().contains(pet_rect))
        self.assertTrue(self.window.rect().contains(bubble_rect))

    def test_fixed_broadcast_position_stays_while_desktop_pet_walks(self):
        self.window.set_config(dict(position='fixed',anchor_x=50,anchor_y=80))
        before=self.window.layout_rects(self.bubble)
        self.pet.go_to_floor()
        self.pet.xpos=self.pet.area.left()+200
        self.pet.direction=1
        self.pet.state='walk'
        self.pet.state_until=float('inf')
        x=self.pet.xpos
        for _ in range(12):
            self.pet.tick()
        self.assertGreater(self.pet.xpos,x)
        self.window.refresh()
        self.assertEqual(self.window.layout_rects(self.bubble),before)

    def test_desktop_motion_toggle_preserves_animation_and_resumes(self):
        self.pet.set_desktop_motion(False)
        position=self.pet.pos()
        phase=self.pet.phase
        for _ in range(5):
            self.pet.tick()
        self.assertEqual(self.pet.pos(),position)
        self.assertGreater(self.pet.phase,phase)
        self.pet.go_to_floor()
        self.pet.xpos=self.pet.area.left()+200
        self.pet.set_desktop_motion(True)
        self.pet.state='walk'
        self.pet.state_until=float('inf')
        self.pet.direction=1
        x=self.pet.xpos
        self.pet.tick()
        self.assertGreater(self.pet.xpos,x)

    def test_fixed_canvas_uses_content_sizes_and_does_not_shrink_when_silent(self):
        self.window.set_config(dict(position='fixed',pet_scale=200,bubble_scale=150))
        pet_size,bubble_size=self.window.fixed_sizes()
        self.assertEqual(self.window.width(),max(pet_size.width(),bubble_size.width())+32)
        self.assertEqual(self.window.height(),pet_size.height()+bubble_size.height()+40)
        size=self.window.size()
        before=self.window.layout_rects(self.bubble)[0]
        self.bubble.hide()
        self.pet.move(self.pet.pos()+QPoint(100,80))
        self.window.refresh()
        self.assertEqual(self.window.size(),size)
        self.assertEqual(self.window.layout_rects(self.bubble)[0],before)
        self.assertIsNone(self.window.layout_rects(self.bubble)[1])

    def test_fixed_canvas_expands_for_long_bubble_without_clipping(self):
        self.window.set_config(dict(position='fixed'))
        self.bubble.say('W '*140)
        self.window.refresh()
        size=self.window.size()
        pet_rect,bubble_rect,_=self.window.layout_rects(self.bubble)
        self.assertTrue(self.window.rect().contains(pet_rect))
        self.assertTrue(self.window.rect().contains(bubble_rect))
        self.bubble.hide()
        self.window.refresh()
        self.assertEqual(self.window.size(),size)

    def test_fixed_broadcast_uses_focus_pose_despite_desktop_jumping_and_climbing(self):
        self.window.set_config(dict(position='fixed'))
        with patch('maeagi_biseo.ui.broadcast.time.monotonic',return_value=self.window.fixed_started+1):
            baseline=self.window.pet_frame().toImage()
            for motion,state in [('air','hop'),('air','fall'),('wall','climb'),('ceiling','ceiling'),('ground','walk')]:
                self.pet.motion=motion
                self.pet.state=state
                self.pet.direction*=-1
                self.assertEqual(self.window.pet_frame().toImage(),baseline)
                self.assertEqual(self.pet.state,state)
                self.assertEqual(self.pet.motion,motion)

    def test_bubble_side_changes_layout_and_tail_without_changing_desktop(self):
        original_tail=self.bubble.tail_on_top
        canvas_size=None
        for side in ('above','below'):
            self.window.set_config(dict(position='fixed',bubble_position=side))
            pet,bubble,below=self.window.layout_rects(self.bubble)
            self.assertEqual(below,side=='below')
            if below:
                self.assertGreater(bubble.top(),pet.bottom())
            else:
                self.assertLess(bubble.bottom(),pet.top())
            self.assertTrue(self.window.rect().contains(pet))
            self.assertTrue(self.window.rect().contains(bubble))
            self.window.grab().save(str(artifact_path('obs/fixed-'+side+'.png')))
            self.assertEqual(self.window.bubble_copy.tail_on_top,below)
            self.assertEqual(self.bubble.tail_on_top,original_tail)
            if canvas_size is None:
                canvas_size=self.window.size()
            else:
                self.assertEqual(self.window.size(),canvas_size)

    def test_bubble_below_in_follow_mode_when_space_is_available(self):
        self.window.set_config(dict(position='follow',bubble_position='below'))
        pet,bubble,below=self.window.layout_rects(self.bubble)
        self.assertTrue(below)
        self.assertGreater(bubble.top(),pet.bottom())

    def test_alignment_stops_at_bubble_edges_and_maintains_spacing(self):
        for side in ('above','below'):
            for alignment in (-50,0,50,100,150):
                self.window.set_config(dict(position='fixed',bubble_position=side,
                                            pet_alignment=alignment,pet_gap=36))
                pet,bubble,below=self.window.layout_rects(self.bubble)
                self.assertTrue(self.window.rect().contains(pet))
                self.assertTrue(self.window.rect().contains(bubble))
                self.assertGreaterEqual(pet.left(),bubble.left())
                self.assertLessEqual(pet.right(),bubble.right())
                distance=(bubble.top()-pet.bottom()-1) if below else (pet.top()-bubble.bottom()-1)
                self.assertEqual(distance,36)
                if alignment==0:
                    self.assertEqual(pet.left(),bubble.left())
                if alignment==100:
                    self.assertEqual(pet.right(),bubble.right())
        self.window.grab().save(str(artifact_path('obs/offcenter-placement.png')))

    def test_oversized_pet_does_not_cross_bubble_edges(self):
        for alignment in (0,50,100):
            self.window.set_config(dict(position='fixed',pet_scale=300,bubble_scale=25,pet_alignment=alignment))
            pet,bubble,_=self.window.layout_rects(self.bubble)
            self.assertGreaterEqual(pet.left(),bubble.left())
            self.assertLessEqual(pet.right(),bubble.right())
            self.assertTrue(self.window.rect().contains(bubble))
            self.window.grab()

    def test_facing_menu_follows_obs_action_and_changes_fixed_broadcast(self):
        self.pet.set_broadcast_enabled(True)
        self.pet.broadcast_window.set_config(dict(position='fixed'))
        menu=self.pet.action_menu()
        try:
            actions=menu.actions()
            obs_index=next(i for i,a in enumerate(actions) if a.text()==tr('obs.menu'))
            self.assertEqual(actions[obs_index+1].text(),tr('menu.facing'))
            facing=actions[obs_index+1].menu()
            left=next(a for a in facing.actions() if a.text()==tr('menu.face_left'))
            right=next(a for a in facing.actions() if a.text()==tr('menu.face_right'))
            broadcast=self.pet.broadcast_window
            with patch('maeagi_biseo.ui.broadcast.time.monotonic',return_value=broadcast.fixed_started+1):
                left.trigger()
                self.assertEqual(self.pet.direction,-1)
                self.assertEqual(broadcast.fixed_direction,-1)
                left_frame=broadcast.pet_frame().toImage()
                right.trigger()
                self.assertEqual(self.pet.direction,1)
                self.assertEqual(broadcast.fixed_direction,1)
                self.assertEqual(broadcast.pet_frame().toImage(),left_frame.mirrored(True,False))
            self.assertTrue(right.isChecked())
            self.assertFalse(left.isChecked())
        finally:
            menu.close()
