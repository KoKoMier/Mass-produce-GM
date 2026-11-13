import struct
import unittest

from protocol import RSP_ACK, build_frame, crc16_modbus, parse_response


class ProtocolTests(unittest.TestCase):
    def test_crc16_reference_vector(self):
        self.assertEqual(crc16_modbus(b"123456789"), 0x4B37)

    def test_request_frame_layout(self):
        frame = build_frame(0x03, 0x12345678, b"abc")
        self.assertEqual(frame[:9], b"\x55\xAA\x03\x78\x56\x34\x12\x03\x00")
        self.assertEqual(frame[9:12], b"abc")
        self.assertEqual(struct.unpack_from("<H", frame, 12)[0], crc16_modbus(frame[:12]))

    def test_response_parser(self):
        body = b"\x55\xAA" + struct.pack("<BBI", RSP_ACK, 0, 256)
        response = parse_response(body + struct.pack("<H", crc16_modbus(body)))
        self.assertEqual(response.code, RSP_ACK)
        self.assertEqual(response.error, 0)
        self.assertEqual(response.value, 256)


if __name__ == "__main__":
    unittest.main()
