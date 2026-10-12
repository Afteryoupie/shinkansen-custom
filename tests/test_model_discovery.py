import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from watchdog import manager


class ModelDiscoveryTest(unittest.TestCase):
    def test_nested_projector_and_model_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "Qwen3VL-test"
            folder.mkdir()
            model = folder / "model.gguf"
            projector = folder / "mmproj-f16.gguf"
            model.touch()
            projector.touch()
            (root / "unrelated-mmproj.gguf").touch()
            with patch.object(manager, "MODELS_DIR", root):
                self.assertEqual(manager.find_matching_mmproj(folder.name), str(projector.resolve()))
                self.assertIsNone(manager.find_matching_mmproj("text-only"))
                models = manager.scan_models()
                self.assertEqual(len(models), 1)
                self.assertEqual(models[0]["path"], str(model.resolve()))
