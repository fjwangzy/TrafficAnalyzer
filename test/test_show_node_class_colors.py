import unittest
import sys
import types
import numpy as np

sys.modules.setdefault("supervision", types.SimpleNamespace())
from nodes.ShowNode import ShowNode


class ShowNodeClassColorsTest(unittest.TestCase):
    def test_class_color_indices_are_stable_and_type_specific(self):
        node = object.__new__(ShowNode)
        node.class_color_idx = {
            class_name: idx
            for idx, class_name in enumerate(ShowNode.CLASS_COLOR_KEYS)
        }

        indices = node._class_color_indices(np.array([
            "people",
            "pedestrian",
            "car",
            "truck",
            "motor",
            "motorcycle",
            "awning_tricycle",
            "unknown-label",
        ], dtype=object))

        self.assertEqual(indices[0], indices[1])
        self.assertNotEqual(indices[2], indices[3])
        self.assertEqual(indices[4], indices[5])
        self.assertEqual(indices[6], node.class_color_idx["awning-tricycle"])
        self.assertEqual(indices[7], node.class_color_idx["unknown"])


if __name__ == "__main__":
    unittest.main()
