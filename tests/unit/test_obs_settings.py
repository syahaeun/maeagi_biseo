"""OBS setting drafts, persistence and applying settings on Save only."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QSettings, Qt, QPoint, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtGui import QFontDatabase, QTransform
from maeagi_biseo.core.obs_settings import DEFAULT_OBS,load_obs,save_obs
from maeagi_biseo.ui.obs_settings import ObsSettingsPage
from maeagi_biseo.ui.chat import ChatWindow
from maeagi_biseo.resources import DEFAULTS
from tests.artifacts import artifact_path


class ObsSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf')

    def setUp(self):
        self.store=QSettings(str(artifact_path('obs/settings-test.ini')),QSettings.IniFormat)
        self.store.clear()
        self.page=ObsSettingsPage(self.store)
        self.addCleanup(self.page.close)

    def test_drafts_do_not_write_and_saved_values_round_trip(self):
        self.page.resize(700,800)
        self.page.show()
        self.app.processEvents()
        field=self.page.fields['pet_scale']
        field.setFocus()
        QTest.keyClick(field,Qt.Key_A,Qt.ControlModifier)
        QTest.keyClicks(field,'180')
        QTest.keyClick(field,Qt.Key_Tab)
        self.page.position.setCurrentIndex(self.page.position.findData('fixed'))
        self.page.bubble_position.setCurrentIndex(self.page.bubble_position.findData('below'))
        self.page.fields['bubble_scale'].setValue(140)
        self.assertNotIn('anchor_x',self.page.fields)
        self.assertEqual(load_obs(self.store),DEFAULT_OBS)
        save_obs(self.page.values(),self.store)
        reread=QSettings(self.store.fileName(),QSettings.IniFormat)
        self.assertEqual(load_obs(reread)['pet_scale'],180)
        self.assertEqual(load_obs(reread)['bubble_scale'],140)
        self.assertEqual(load_obs(reread)['position'],'fixed')
        self.assertEqual(load_obs(reread)['bubble_position'],'below')
        self.page.grab().save(str(artifact_path('obs/settings-page.png')))

    def test_invalid_preferences_fall_back_and_are_bounded(self):
        self.store.setValue('obs_settings','broken json')
        self.assertEqual(load_obs(self.store),DEFAULT_OBS)
        config=save_obs(dict(pet_scale=999,bubble_scale=-5,position='unknown',anchor_x=500),self.store)
        self.assertEqual(config['pet_scale'],300)
        self.assertEqual(config['bubble_scale'],25)
        self.assertEqual(config['position'],'follow')
        self.assertNotIn('anchor_x',config)
        self.assertEqual(save_obs(dict(pet_alignment=-50),self.store)['pet_alignment'],0)
        self.assertEqual(save_obs(dict(pet_alignment=150),self.store)['pet_alignment'],100)

    def test_visual_presets_drag_keyboard_and_reset_are_drafts(self):
        editor=self.page.placement
        editor.setParent(None)
        self.addCleanup(editor.close)
        editor.resize(700,560)
        editor.show()
        self.app.processEvents()
        QTest.mouseClick(editor.presets[0],Qt.LeftButton)
        self.assertEqual(self.page.values()['pet_alignment'],0)
        QTest.mouseClick(editor.presets[100],Qt.LeftButton)
        self.assertEqual(self.page.values()['pet_alignment'],100)
        QTest.mouseClick(editor.presets[50],Qt.LeftButton)
        transform,pet,_,_=editor.preview.scene()
        start=transform.map(pet.center())
        end=start+QPoint(36,20)
        QTest.mousePress(editor.preview,Qt.LeftButton,pos=start)
        QTest.mouseMove(editor.preview,end)
        QTest.mouseRelease(editor.preview,Qt.LeftButton,pos=end)
        self.assertGreater(editor.alignment.value(),50)
        self.assertGreater(editor.gap.value(),8)
        before=editor.alignment.value()
        QTest.keyClick(editor.preview,Qt.Key_Left)
        self.assertEqual(editor.alignment.value(),before-1)
        self.assertEqual(load_obs(self.store),DEFAULT_OBS)
        save_obs(self.page.values(),self.store)
        self.assertEqual(load_obs(self.store)['pet_alignment'],editor.alignment.value())
        self.assertEqual(load_obs(self.store)['pet_gap'],editor.gap.value())
        editor.grab().save(str(artifact_path('obs/placement-editor.png')))
        editor.reset()
        self.assertEqual(editor.alignment.value(),50)
        self.assertEqual(editor.gap.value(),8)

    def test_cancel_does_not_apply_and_save_applies_to_all_pets(self):
        pets=[Mock(kind='robot'),Mock(kind='bunny')]
        chat=SimpleNamespace(store=self.store,config=dict(DEFAULTS),pets=pets,
                             character_store=self.store,status=Mock(),refresh_heading=Mock())
        dialog=SimpleNamespace(deleteLater=Mock(),obs_page=self.page,values=lambda:dict(DEFAULTS),
                               key=Mock(text=lambda:''),provider_keys={},provider_drafts={},pending_runtime_action=None)
        self.page.enabled.setChecked(True)
        self.page.position.setCurrentIndex(self.page.position.findData('fixed'))
        self.page.desktop_motion.setChecked(True)
        ChatWindow._settings_finished(chat,dialog,QDialog.Rejected)
        self.assertEqual(load_obs(self.store),DEFAULT_OBS)
        for pet in pets:
            pet.apply_obs_settings.assert_not_called()
        ChatWindow._settings_finished(chat,dialog,QDialog.Accepted)
        for pet in pets:
            pet.apply_obs_settings.assert_called_once_with(self.page.values())
        self.assertEqual(load_obs(self.store),self.page.values())

    def test_preview_scales_text_together_with_bubble(self):
        editor=self.page.placement
        editor.setParent(None)
        self.addCleanup(editor.close)
        editor.resize(700,580)
        editor.show()
        self.app.processEvents()
        source=editor.sample_bubble
        text_heights=[]
        for scale in (100,200):
            self.page.fields['bubble_scale'].setValue(scale)
            rect=QRect(0,0,round(source.width()*scale/100),round(source.height()*scale/100))
            # Compare at identical zoom, separately from fit-to-preview zoom.
            with patch.object(editor.preview,'scene',return_value=(QTransform(),QRect(0,230,50,50),rect,False)):
                frame=editor.preview.grab().toImage()
            rows=[]
            for y in range(20*scale//100,min(frame.height(),rect.height()-20*scale//100)):
                for x in range(20*scale//100,rect.width()-20*scale//100):
                    c=frame.pixelColor(x,y)
                    if max(c.red(),c.green(),c.blue())<140:
                        rows.append(y)
                        break
            self.assertTrue(rows)
            text_heights.append(max(rows)-min(rows)+1)
            frame.save(str(artifact_path('obs/preview-text-'+str(scale)+'.png')))
        self.assertGreaterEqual(text_heights[1],text_heights[0]*1.8)
