import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication
from maeagi_biseo.core.maple_import import MapleClient, MapleImportError
from maeagi_biseo.core.character_store import save_character
from maeagi_biseo.core.sprites import SpritePack, CharacterInfo
from maeagi_biseo.ui.character_editor import CharacterEditor
from tests.artifacts import artifact_path


class MapleImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def png(self):
        image = QImage(300, 300, QImage.Format_ARGB32)
        image.fill(QColor('transparent'))
        for y in range(140, 250):
            for x in range(100, 200):
                image.setPixelColor(x, y, QColor('red'))
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, 'PNG')
        return bytes(buffer.data())

    def responses(self, url, authenticated=False):
        if '/v1/id?' in url:
            self.assertEqual(parse_qs(urlsplit(url).query)['character_name'], ['테스트'])
            self.assertTrue(authenticated)
            return b'{"ocid":"example"}'
        if '/v1/character/basic?' in url:
            self.assertTrue(authenticated)
            return json.dumps({'character_name': '테스트', 'character_image':
                'https://open.api.nexon.com/static/maplestory/character/look/example?wmotion=W01'}).encode()
        self.assertFalse(authenticated)
        self.assertEqual(parse_qs(urlsplit(url).query)['wmotion'], ['W01'])
        return self.png()

    def test_download_round_trip_scale_and_editor(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
            root = Path(temp)
            client = MapleClient('secret')
            with patch.object(client, 'request', side_effect=self.responses) as request:
                result = client.download('테스트', root)
            self.assertEqual(request.call_count, 12)
            actions = [parse_qs(urlsplit(call.args[0]).query)['action'][0] for call in request.call_args_list[2:]]
            self.assertEqual(actions, ['A00.0', 'A00.1', 'A00.2', 'A02.0', 'A02.1', 'A02.2', 'A02.3', 'A06.0', 'A08.0', 'A08.1'])
            editor = CharacterEditor()
            try:
                editor.apply_maple(result)
                editor.scale_box.setValue(50)
                editor.show()
                self.app.processEvents()
                editor.grab().save(str(artifact_path('maple_character_editor.png')))
                with patch('maeagi_biseo.core.character_store.user_character_root', return_value=root / 'characters'):
                    identifier = save_character(result['name'], editor.animations, result['canvas'], display_scale=50)
                pack = SpritePack(CharacterInfo(identifier, result['name'], root / 'characters' / identifier))
                self.assertEqual((pack.canvas.width(), pack.canvas.height(), pack.foot_offset), (54, 59, 57))
                self.assertEqual(pack.frame('climb', 180).size(), pack.canvas)
                self.assertEqual(editor.identifier, None)
                self.assertEqual(editor.entry()['foot_offset'], 114)
            finally:
                editor.close()
                editor.deleteLater()
                self.app.processEvents()

    def test_bad_images_and_cancellation_leave_no_partial_pack(self):
        for cancel in (False, True):
            with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as temp:
                client = MapleClient('secret')
                def response(url, authenticated=False):
                    return self.responses(url, authenticated) if authenticated else b'invalid image'
                with patch.object(client, 'request', side_effect=response), self.assertRaises(MapleImportError):
                    client.download('테스트', temp, lambda: cancel)
                self.assertEqual(list(Path(temp).iterdir()), [])

    def test_untrusted_image_host_and_api_errors_do_not_leak_key(self):
        client = MapleClient('private-key')
        with patch.object(client, 'api', side_effect=[{'ocid': 'x'}, {'character_image': 'https://example.com/image.png'}]):
            with self.assertRaises(MapleImportError):
                client.download('테스트', '.')
        with patch.object(client.opener, 'open', side_effect=HTTPError('https://example.com', 401, 'private-key', {}, None)):
            with self.assertRaises(MapleImportError) as caught:
                client.api('id', character_name='테스트')
            self.assertNotIn('private-key', str(caught.exception))
            self.assertIn('API 키', str(caught.exception))

    def test_background_import_restores_controls_and_keeps_existing_on_failure(self):
        from PySide6.QtCore import QElapsedTimer
        from PySide6.QtTest import QTest
        saved = {}
        store_patch = patch('maeagi_biseo.ui.character_editor.store_key', side_effect=lambda provider, key: saved.update({provider: key}))
        store = store_patch.start()
        self.addCleanup(store_patch.stop)
        read_patch = patch('maeagi_biseo.ui.character_editor.read_key', side_effect=lambda provider: saved.get(provider, ''))
        read_patch.start()
        self.addCleanup(read_patch.stop)
        env_patch = patch('maeagi_biseo.ui.character_editor.env_value', return_value='')
        env_patch.start()
        self.addCleanup(env_patch.stop)
        editor = CharacterEditor()
        try:
            editor.maple_name.setText('테스트')
            editor.maple_key.setText('session-secret')
            result = {'name': '테스트', 'canvas': [100, 100], 'animations': {}}
            for response in (result, MapleImportError('테스트 오류')):
                with patch.object(MapleClient, 'download', side_effect=response if isinstance(response, Exception) else None,
                                  return_value=result):
                    previous = editor.animations
                    editor.import_maple()
                    self.assertEqual(editor.maple_key.text(), 'session-secret')
                    self.assertFalse(editor.maple_button.isEnabled())
                    elapsed = QElapsedTimer()
                    elapsed.start()
                    while editor.maple_worker is not None and elapsed.elapsed() < 3000:
                        QTest.qWait(10)
                    self.assertIsNone(editor.maple_worker)
                    self.assertTrue(editor.maple_button.isEnabled())
                    if isinstance(response, Exception):
                        self.assertIs(editor.animations, previous)
                        self.assertEqual(editor.maple_status.text(), '테스트 오류')
            self.assertEqual(editor.name.text(), '테스트')
            store.assert_called_once_with('nexon', 'session-secret')
            self.assertEqual(saved['nexon'], 'session-secret')
        finally:
            if editor.maple_worker:
                editor.maple_worker.wait(3000)
                self.app.processEvents()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_key_is_loaded_and_masked_when_editor_opens(self):
        from PySide6.QtWidgets import QLineEdit
        for configured, saved, expected in (
            ('', 'saved-nexon-key', 'saved-nexon-key'),
            ('configured-nexon-key', 'saved-nexon-key', 'configured-nexon-key'),
            ('', '', ''),
        ):
            with self.subTest(configured=bool(configured), saved=bool(saved)), patch(
                'maeagi_biseo.ui.character_editor.env_value', return_value=configured
            ), patch('maeagi_biseo.ui.character_editor.read_key', return_value=saved):
                editor = CharacterEditor()
                try:
                    self.assertEqual(editor.maple_key.text(), expected)
                    self.assertEqual(editor.maple_key.echoMode(), QLineEdit.Password)
                finally:
                    editor.close()
                    editor.deleteLater()
                    self.app.processEvents()

    def test_key_save_failure_keeps_input_and_does_not_start_import(self):
        editor = CharacterEditor()
        try:
            editor.maple_name.setText('테스트')
            editor.maple_key.setText('test-secret')
            with patch('maeagi_biseo.ui.character_editor.store_key', side_effect=OSError('private detail')):
                editor.import_maple()
            self.assertIsNone(editor.maple_worker)
            self.assertEqual(editor.maple_key.text(), 'test-secret')
            self.assertIn('저장하지 못했습니다', editor.maple_status.text())
            self.assertNotIn('private detail', editor.maple_status.text())
        finally:
            editor.close()
            editor.deleteLater()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
