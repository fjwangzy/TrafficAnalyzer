import unittest

from utils_local.utils import intersects_central_point


class IntersectsCentralPointTest(unittest.TestCase):
    def test_returns_road_id_when_bbox_center_is_inside_polygon(self):
        roads = {
            "1": [0, 0, 10, 0, 10, 10, 0, 10],
            "2": [20, 0, 30, 0, 30, 10, 20, 10],
        }

        self.assertEqual(intersects_central_point([2, 2, 4, 4], roads), 1)
        self.assertEqual(intersects_central_point([22, 2, 24, 4], roads), 2)

    def test_returns_none_when_bbox_center_is_outside_all_polygons(self):
        roads = {"1": [0, 0, 10, 0, 10, 10, 0, 10]}

        self.assertIsNone(intersects_central_point([20, 20, 24, 24], roads))

    def test_polygon_boundary_is_not_counted_as_inside(self):
        roads = {"1": [0, 0, 10, 0, 10, 10, 0, 10]}

        self.assertIsNone(intersects_central_point([0, 4, 0, 6], roads))


if __name__ == "__main__":
    unittest.main()
