import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "merge_release", Path(__file__).with_name("merge_release.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseTests(unittest.TestCase):
    def test_verified_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.write_bytes(b"map data")
            asset = {
                "name": "region.bin",
                "size": 8,
                "digest": "sha256:" + hashlib.sha256(b"map data").hexdigest(),
                "browser_download_url": source.as_uri(),
            }
            target = module.download(asset, root)
            self.assertEqual(target.read_bytes(), b"map data")

    def test_checksum_mismatch_never_publishes_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.write_bytes(b"bad data")
            asset = {
                "name": "region.bin",
                "size": 8,
                "digest": "sha256:" + "0" * 64,
                "browser_download_url": source.as_uri(),
            }
            with self.assertRaises(ValueError):
                module.download(asset, root)
            self.assertEqual(list(root.iterdir()), [source])

    def test_missing_region_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "Missing release assets"):
            module.select_assets({"assets": []}, ["europe-monaco"], "2026-09-14")


if __name__ == "__main__":
    unittest.main()
