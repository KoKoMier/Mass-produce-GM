import unittest

from gm_plotter import Measurement, parse_measurement


class ParserTests(unittest.TestCase):
    def test_valid_measurement(self):
        self.assertEqual(
            parse_measurement("DATA,12540,12.35,8.20,0.00,3250,18420,7610\r\n"),
            Measurement(12540, 12.35, 8.20, 0.0, 3250, 18420, 7610),
        )

    def test_ignores_bootloader_and_noise(self):
        self.assertIsNone(parse_measurement("garbage"))
        self.assertIsNone(parse_measurement("DATA,1,2,3"))
        self.assertIsNone(parse_measurement("DATA,1,a,3,4,5,6,7"))


if __name__ == "__main__":
    unittest.main()
