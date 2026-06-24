import os
import tempfile
import unittest
from pathlib import Path

from core.windows_dpapi_store import WindowsDPAPISecretStore


@unittest.skipUnless(os.name == "nt", "Windows DPAPI is only available on Windows")
class WindowsDPAPISecretStoreTests(unittest.TestCase):
    def test_round_trip_persists_encrypted_value_without_plaintext(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "api-key.dpapi"
            store = WindowsDPAPISecretStore(path)

            self.assertTrue(store.set_key("sk-dpapi-round-trip"))

            encrypted = path.read_bytes()
            self.assertNotIn(b"sk-dpapi-round-trip", encrypted)
            self.assertGreater(len(encrypted), 20)
            self.assertEqual("sk-dpapi-round-trip", store.get_key())

            self.assertTrue(store.delete_key())
            self.assertFalse(path.exists())
            self.assertEqual("", store.get_key())

    def test_corrupted_blob_fails_closed_without_exposing_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "api-key.dpapi"
            path.write_bytes(b"not-a-valid-dpapi-blob")
            store = WindowsDPAPISecretStore(path)

            self.assertEqual("", store.get_key())


if __name__ == "__main__":
    unittest.main()
