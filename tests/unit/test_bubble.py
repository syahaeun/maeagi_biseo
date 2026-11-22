import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from maeagi_biseo.app import Pet, PETS
from maeagi_biseo.ui.dialogue import Bubble, bubble_position
from maeagi_biseo.resources import SCRIPTS
from tests.artifacts import artifact_path


class BubbleTests(unittest.TestCase):
    def test_live_bubble_uses_visible_artwork_and_unscaled_offset(self):
        from unittest.mock import patch
        self.enterContext(patch.object(self.pet.sprites, 'bubble_offset', [0, 125]))
        self.enterContext(patch.object(self.pet.sprites, 'display_scale', 200))
        self.pet.move(self.pet.area.center().x(), self.pet.area.top() + 300)
        with patch('maeagi_biseo.ui.dialogue.bubble_position', wraps=bubble_position) as position:
            self.bubble.say('루티 위치 확인')
        self.assertEqual(position.call_args.args[3], [0, 125])
        anchor = self.pet.speech_anchor_rect()
        self.assertGreater(anchor.top(), self.pet.geometry().top())
        self.assertEqual(position.call_args.args[0], anchor)
        self.assertEqual((self.bubble.x(), self.bubble.y(), self.bubble.tail_on_top),
                         bubble_position(anchor, self.bubble.size(),
                                         self.pet.screen().availableGeometry(), (0, 125)))
        self.assertEqual(self.pet.sprites.bubble_offset, [0, 125])

    def test_position_offset_fallback_and_screen_clamping(self):
        from PySide6.QtCore import QRect, QSize
        screen = QRect(-800, 0, 800, 600)
        pet = QRect(-500, 250, 100, 100)
        normal = bubble_position(pet, QSize(300, 80), screen)
        moved = bubble_position(pet, QSize(300, 80), screen, (20, -10))
        self.assertEqual(moved, (normal[0] + 20, normal[1] - 10, False))
        self.assertEqual(bubble_position(pet, QSize(300, 80), screen, (0, 125)), normal)
        self.assertEqual(bubble_position(pet, QSize(300, 80), screen, (0, -200))[1:], (0, False))
        x, y, below = bubble_position(QRect(-790, 0, 100, 100), QSize(300, 80), screen)
        self.assertEqual((x, y, below), (-800, 108, True))

    @classmethod
    def setUpClass(cls):
        from tests.character_fixtures import use_character_fixtures
        use_character_fixtures(cls)
        cls.app = QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf')

    def setUp(self):
        self.pet = Pet(kind='robot')
        self.pet.timer.stop()
        self.bubble = Bubble(self.pet)

    def tearDown(self):
        self.bubble.page_timer.stop()
        self.bubble.close()
        PETS.remove(self.pet)
        self.pet.close()

    def test_white_background_is_opaque_on_translucent_window(self):
        self.bubble.say(SCRIPTS[0][0])
        image = self.bubble.grab().toImage()
        color = image.pixelColor(8, image.height()//2)
        self.assertEqual((color.red(), color.green(), color.blue(), color.alpha()), (255, 255, 255, 255))
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertTrue(image.save(str(artifact_path('bubble_preview.png'))))

    def test_bubble_moves_below_pet_near_screen_top(self):
        self.pet.move(self.pet.area.center().x(), self.pet.area.top())
        self.bubble.say(SCRIPTS[0][0])
        self.assertTrue(self.bubble.tail_on_top)
        self.assertGreater(self.bubble.y(), self.pet.y())
        image = self.bubble.grab().toImage()
        self.assertEqual(image.pixelColor(8, image.height()//2).alpha(), 255)


if __name__ == '__main__':
    unittest.main()
