"""Exercise actual user-scoped DPAPI using disposable credentials."""
import os
import tempfile
import unittest
from unittest.mock import patch

from maeagi_biseo.llm import key_store
from tests.artifacts import artifact_path


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI required')
class KeyStoreTests(unittest.TestCase):
    def test_saved_key_is_loaded_when_environment_and_env_file_are_empty(self):
        from maeagi_biseo.llm.settings import key_with_source
        with patch('maeagi_biseo.llm.settings.env_file_values', return_value={}), patch.dict(os.environ, {}, clear=True), patch('maeagi_biseo.llm.settings.read_key', return_value='saved-test-key'):
            self.assertEqual(key_with_source('openai'), ('saved-test-key', 'AppData (Windows DPAPI)'))
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'environment-test-key'}):
                self.assertEqual(key_with_source('openai'), ('environment-test-key', 'OPENAI_API_KEY'))

    def test_encrypted_roundtrip_replace_delete_and_provider_isolation(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as root:
            with patch.dict(os.environ, {'LOCALAPPDATA': root}):
                key_store.store_key('openai', 'test-only-secret-한글')
                encrypted = key_store.key_path('openai').read_bytes()
                self.assertNotIn(b'test-only-secret', encrypted)
                self.assertEqual(key_store.read_key('openai'), 'test-only-secret-한글')
                self.assertEqual(key_store.read_key('claude'), '')
                key_store.store_key('nexon', 'test-nexon-secret')
                self.assertEqual(key_store.read_key('nexon'), 'test-nexon-secret')
                self.assertNotIn(b'test-nexon-secret', key_store.key_path('nexon').read_bytes())
                key_store.store_key('openai', 'replacement')
                self.assertEqual(key_store.read_key('openai'), 'replacement')
                key_store.store_key('openai', '')
                self.assertFalse(key_store.key_path('openai').exists())
                self.assertEqual(key_store.read_key('openai'), '')

    def test_unreadable_credentials_do_not_prevent_startup(self):
        with tempfile.TemporaryDirectory(dir=artifact_path('scratch').parent) as root:
            with patch.dict(os.environ, {'LOCALAPPDATA': root}):
                path = key_store.key_path('gemini')
                path.parent.mkdir(parents=True)
                path.write_bytes(b'invalid ciphertext')
                self.assertEqual(key_store.read_key('gemini'), '')
