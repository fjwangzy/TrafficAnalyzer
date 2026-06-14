import tempfile
import unittest
from pathlib import Path

from app.api.v1 import system


class SystemApiTest(unittest.TestCase):
    def test_list_model_files_reads_weight_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "uav_best.pt").write_bytes(b"1234")
            (root / "notes.txt").write_text("ignore")

            models = system.list_model_files(root)

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["name"], "uav_best.pt")
        self.assertEqual(models[0]["size_bytes"], 4)


if __name__ == "__main__":
    unittest.main()
