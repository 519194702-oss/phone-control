import unittest

from phone_control.app import DisplayTransform


class DisplayTransformTests(unittest.TestCase):
    def test_fit_scales_large_portrait_screen(self):
        transform = DisplayTransform.fit(1080, 2400, 900, 900)

        self.assertEqual(transform.scale_divisor, 3)
        self.assertEqual(transform.display_width, 360)
        self.assertEqual(transform.display_height, 800)

    def test_to_device_clamps_coordinates(self):
        transform = DisplayTransform(screen_width=100, screen_height=200, scale_divisor=2)

        self.assertEqual(transform.to_device(10.2, 20.6), (20, 41))
        self.assertEqual(transform.to_device(-1, 999), (0, 199))


if __name__ == "__main__":
    unittest.main()
