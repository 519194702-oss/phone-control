import unittest
from unittest.mock import patch

from phone_control.adb import AdbClient, AndroidDevice, encode_input_text


class AdbClientTests(unittest.TestCase):
    def test_devices_parses_adb_output(self):
        output = """List of devices attached\nemulator-5554 device product:sdk model:Pixel_6 device:generic\nabc123 unauthorized\n\n"""
        client = AdbClient(adb_path="adb")
        with patch.object(client, "run", return_value=output):
            devices = client.devices()

        self.assertEqual(
            devices,
            [
                AndroidDevice("emulator-5554", "device", "product:sdk model:Pixel_6 device:generic"),
                AndroidDevice("abc123", "unauthorized", ""),
            ],
        )

    def test_screen_size_parses_physical_size(self):
        client = AdbClient(adb_path="adb")
        with patch.object(client, "run", return_value="Physical size: 1080x2400\n"):
            self.assertEqual(client.screen_size(), (1080, 2400))

    def test_encode_input_text_converts_spaces_and_shell_sensitive_chars(self):
        self.assertEqual(encode_input_text("hello world & more"), "hello%sworld%s\\&%smore")


if __name__ == "__main__":
    unittest.main()
