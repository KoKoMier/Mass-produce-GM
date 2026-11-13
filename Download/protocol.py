from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Callable, Protocol


SOF = b"\x55\xAA"

CMD_ENTER = 0x01
CMD_ERASE = 0x02
CMD_WRITE = 0x03
CMD_FINISH = 0x05
CMD_ACTIVATE = 0x06
CMD_STATUS = 0x07

RSP_ACK = 0x7E
RSP_NACK = 0x7F

STATE_IDLE = 0
STATE_ENTERED = 1
STATE_ERASED = 2
STATE_RECEIVING = 3
STATE_READY = 4

ERROR_NAMES = {
    1: "frame length error",
    2: "frame CRC error",
    3: "flash operation error",
    4: "firmware offset error",
    5: "upgrade state error",
    6: "firmware CRC32 error",
    7: "W25Q64 JEDEC ID error",
}


class SerialPort(Protocol):
    def read(self, size: int = 1) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def flush(self) -> None: ...
    def reset_input_buffer(self) -> None: ...


class ProtocolError(RuntimeError):
    pass


class ResponseTimeout(ProtocolError):
    pass


class UpgradeCancelled(ProtocolError):
    pass


class DeviceNack(ProtocolError):
    def __init__(self, error: int, value: int):
        self.error = error
        self.value = value
        name = ERROR_NAMES.get(error, "unknown device error")
        super().__init__(f"NACK {error}: {name}, value=0x{value:08X}")


@dataclass(frozen=True)
class Response:
    code: int
    error: int
    value: int


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = ((crc >> 1) ^ 0xA001) if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF


def build_frame(command: int, argument: int = 0, data: bytes = b"") -> bytes:
    if len(data) > 256:
        raise ValueError("frame data cannot exceed 256 bytes")
    body = SOF + struct.pack("<BIH", command, argument, len(data)) + data
    return body + struct.pack("<H", crc16_modbus(body))


def parse_response(frame: bytes) -> Response:
    if len(frame) != 10 or frame[:2] != SOF:
        raise ProtocolError("invalid response frame")
    expected_crc = struct.unpack_from("<H", frame, 8)[0]
    if crc16_modbus(frame[:8]) != expected_crc:
        raise ProtocolError("response CRC16 mismatch")
    code, error, value = struct.unpack_from("<BBI", frame, 2)
    if code not in (RSP_ACK, RSP_NACK):
        raise ProtocolError(f"invalid response code 0x{code:02X}")
    return Response(code, error, value)


class BootloaderClient:
    def __init__(
        self,
        port: SerialPort,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self.port = port
        self.cancelled = cancelled or (lambda: False)

    def _check_cancelled(self) -> None:
        if self.cancelled():
            raise UpgradeCancelled("upgrade cancelled")

    def _read_response(self, timeout: float) -> Response:
        deadline = time.monotonic() + timeout
        buffer = bytearray()
        while time.monotonic() < deadline:
            self._check_cancelled()
            chunk = self.port.read(32)
            if chunk:
                buffer.extend(chunk)
                start = buffer.find(SOF)
                if start < 0:
                    if len(buffer) > 1:
                        del buffer[:-1]
                    continue
                if start:
                    del buffer[:start]
                if len(buffer) >= 10:
                    return parse_response(bytes(buffer[:10]))
        raise ResponseTimeout("device response timeout")

    def request(
        self,
        command: int,
        argument: int = 0,
        data: bytes = b"",
        timeout: float = 2.0,
    ) -> Response:
        self._check_cancelled()
        frame = build_frame(command, argument, data)
        self.port.reset_input_buffer()
        self.port.write(frame)
        self.port.flush()
        response = self._read_response(timeout)
        if response.code == RSP_NACK:
            raise DeviceNack(response.error, response.value)
        return response

    def wait_for_bootloader(self, size: int, crc32: int, timeout: float = 12.0) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        payload = struct.pack("<I", crc32)
        while time.monotonic() < deadline:
            self._check_cancelled()
            try:
                self.request(CMD_ENTER, size, payload, timeout=1.0)
                return
            except (ResponseTimeout, ProtocolError) as exc:
                last_error = exc
                time.sleep(0.15)
        raise ResponseTimeout(f"bootloader not found: {last_error}")

    def erase(self) -> None:
        try:
            self.request(CMD_ERASE, timeout=30.0)
        except ResponseTimeout:
            status = self.request(CMD_STATUS, timeout=2.0)
            if status.error != STATE_ERASED:
                raise

    def write_chunk(self, offset: int, data: bytes, retries: int = 5) -> int:
        expected = offset + len(data)
        last_error: Exception | None = None
        for _ in range(retries):
            self._check_cancelled()
            try:
                response = self.request(CMD_WRITE, offset, data, timeout=2.0)
                if response.value != expected:
                    raise ProtocolError(
                        f"unexpected device offset 0x{response.value:X}, expected 0x{expected:X}"
                    )
                return response.value
            except DeviceNack as exc:
                if exc.error == 4 and exc.value == expected:
                    return expected
                last_error = exc
            except (ResponseTimeout, ProtocolError) as exc:
                last_error = exc
            time.sleep(0.1)
        raise ProtocolError(f"write failed at 0x{offset:X}: {last_error}")

    def finish(self, expected_crc32: int) -> None:
        try:
            response = self.request(CMD_FINISH, timeout=10.0)
            if response.value != expected_crc32:
                raise ProtocolError(
                    f"device CRC32 0x{response.value:08X}, expected 0x{expected_crc32:08X}"
                )
        except ResponseTimeout:
            status = self.request(CMD_STATUS, timeout=2.0)
            if status.error != STATE_READY:
                raise

    def activate(self) -> None:
        self.request(CMD_ACTIVATE, timeout=2.0)
