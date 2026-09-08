import os
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from secure_credentials import save_key, load_key, delete_key, key_path


@unittest.skipUnless(os.name == "nt", "Windows DPAPI")
class CredentialTests(unittest.TestCase):
    def test_roundtrip_replace_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(load_key(root), "")
            save_key(root, "fake-test-secret-only")
            self.assertNotIn(b"fake-test-secret-only", key_path(root).read_bytes())
            self.assertEqual(load_key(root), "fake-test-secret-only")
            result = subprocess.run([sys.executable, "-c",
                "import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
                "from secure_credentials import load_key;"
                "assert load_key(Path(sys.argv[2])) == 'fake-test-secret-only'",
                str(Path(__file__).resolve().parents[1] / "src"), str(root)], capture_output=True)
            self.assertEqual(result.returncode, 0)
            save_key(root, "replacement-test-secret")
            self.assertEqual(load_key(root), "replacement-test-secret")
            delete_key(root)
            self.assertEqual(load_key(root), "")
            delete_key(root)

    def test_corrupt_and_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                save_key(root, "\n")
            key_path(root).parent.mkdir(parents=True)
            key_path(root).write_bytes(b"not-a-dpapi-blob")
            with self.assertRaises(ValueError):
                load_key(root)
