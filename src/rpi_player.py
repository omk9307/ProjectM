#  main.py 등과는 상관없고 독립적으로  라즈베리파이4에서 사용되는 코드이다. 

import serial
import time
import signal
import threading
import logging
import sys
import math
import random
import struct
from typing import Optional

# ---------------------
# Config
# ---------------------
SERIAL_PORT = '/dev/ttyGS0'   # PC side (gadget serial)
BAUD_RATE = 115200
HID_KBD_PATH = '/dev/hidg0'
HID_MOUSE_PATH = '/dev/hidg1'

CMD_PRESS = 0x01
CMD_RELEASE = 0x02
CMD_CLEAR_ALL = 0x03

# Mouse command set
MOUSE_MOVE_REL = 0x10  # payload: int8 dx, int8 dy
MOUSE_SMOOTH_MOVE = 0x11  # payload: int16 dx, int16 dy, int16 duration_ms (LE)
MOUSE_LEFT_CLICK = 0x12  # no payload
MOUSE_RIGHT_CLICK = 0x13  # no payload
MOUSE_DOUBLE_CLICK = 0x14  # no payload

# Modifier HID code -> modifier bit mask
MODIFIER_BIT_MAP = {
    224: 0x01,  # Left Ctrl
    225: 0x02,  # Left Shift
    226: 0x04,  # Left Alt
    227: 0x08,  # Left GUI (Win/Cmd)
    228: 0x10,  # Right Ctrl
    229: 0x20,  # Right Shift
    230: 0x40,  # Right Alt
    231: 0x80,  # Right GUI
}

# ---------------------
# Listener
# ---------------------
class HIDListener:
    def __init__(self,
                 serial_port: str = SERIAL_PORT,
                 baud_rate: int = BAUD_RATE,
                 hid_kbd_path: str = HID_KBD_PATH,
                 hid_mouse_path: str = HID_MOUSE_PATH,
                 reconnect_delay: float = 5.0):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.hid_kbd_path = hid_kbd_path
        self.hid_mouse_path = hid_mouse_path
        self.reconnect_delay = reconnect_delay

        self.ser: Optional[serial.Serial] = None
        self.hid_kbd_file = None
        self.hid_mouse_file = None

        # internal state (protected by lock)
        self._lock = threading.Lock()
        self.modifier_state = 0       # 8-bit mask for modifiers
        self.pressed_keys = set()     # set of key codes (ints)
        self.mouse_buttons_mask = 0   # 1:L, 2:R, 4:M, 8:Btn4, 16:Btn5

        self._stop_event = threading.Event()

        # logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    def request_stop(self):
        logging.info("stop requested")
        self._stop_event.set()

    def _open_hid_keyboard(self):
        # Open keyboard HID device once and reuse file descriptor
        try:
            self.hid_kbd_file = open(self.hid_kbd_path, 'wb+', buffering=0)
            logging.info(f"Keyboard HID opened: {self.hid_kbd_path}")
        except Exception as e:
            logging.error(f"Failed to open Keyboard HID {self.hid_kbd_path}: {e}")
            self.hid_kbd_file = None

    def _open_hid_mouse(self):
        # Open mouse HID device once and reuse file descriptor
        try:
            self.hid_mouse_file = open(self.hid_mouse_path, 'wb+', buffering=0)
            logging.info(f"Mouse HID opened: {self.hid_mouse_path}")
        except Exception as e:
            logging.error(f"Failed to open Mouse HID {self.hid_mouse_path}: {e}")
            self.hid_mouse_file = None

    def _close_hid_keyboard(self):
        if self.hid_kbd_file:
            try:
                self.hid_kbd_file.close()
                logging.info("Keyboard HID closed")
            except Exception as e:
                logging.warning(f"Error closing Keyboard HID: {e}")
            self.hid_kbd_file = None

    def _close_hid_mouse(self):
        if self.hid_mouse_file:
            try:
                self.hid_mouse_file.close()
                logging.info("Mouse HID closed")
            except Exception as e:
                logging.warning(f"Error closing Mouse HID: {e}")
            self.hid_mouse_file = None

    def _connect_serial(self):
        # Try to open serial port (non-blocking with timeout)
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate, timeout=1)
            logging.info(f"Serial opened: {self.serial_port} @ {self.baud_rate}")
            return True
        except serial.SerialException as e:
            logging.warning(f"Cannot open serial {self.serial_port}: {e}")
            self.ser = None
            return False

    def _close_serial(self):
        if self.ser:
            try:
                self.ser.close()
                logging.info("Serial closed")
            except Exception as e:
                logging.warning(f"Error closing serial: {e}")
            self.ser = None

    def write_kbd_report(self):
        """Compose and send an 8-byte HID keyboard report: [modifier, reserved, key1..key6]"""
        with self._lock:
            report = bytearray(8)
            report[0] = self.modifier_state & 0xFF
            # report[1] is reserved (0)
            keys = sorted(self.pressed_keys)[:6]  # deterministic order
            for i, kc in enumerate(keys):
                report[2 + i] = int(kc) & 0xFF

        if not self.hid_kbd_file:
            logging.debug("Keyboard HID not opened; skipping write_kbd_report")
            return

        try:
            # write and flush
            self.hid_kbd_file.write(report)
            self.hid_kbd_file.flush()
            # optional debug
            logging.debug(f"Sent HID report: {list(report)}")
        except Exception as e:
            logging.error(f"Keyboard HID write error: {e}")

    def write_mouse_report(self, buttons: int, dx: int, dy: int, wheel: int = 0):
        """Send a 4-byte HID mouse report: [buttons, dx, dy, wheel]. dx/dy are int8."""
        # Clamp to int8 range as HID expects
        def clamp_int8(v: int) -> int:
            return max(-127, min(127, int(v)))

        report = bytearray(4)
        report[0] = buttons & 0xFF
        report[1] = clamp_int8(dx) & 0xFF if dx >= 0 else (256 + clamp_int8(dx)) & 0xFF
        report[2] = clamp_int8(dy) & 0xFF if dy >= 0 else (256 + clamp_int8(dy)) & 0xFF
        report[3] = clamp_int8(wheel) & 0xFF if wheel >= 0 else (256 + clamp_int8(wheel)) & 0xFF

        if not self.hid_mouse_file:
            logging.debug("Mouse HID not opened; skipping write_mouse_report")
            return
        try:
            self.hid_mouse_file.write(report)
            self.hid_mouse_file.flush()
            logging.debug(f"Sent Mouse report: {list(report)}")
        except Exception as e:
            logging.error(f"Mouse HID write error: {e}")

    def _handle_keyboard(self, cmd: int, key_code: Optional[int] = None):
        """Update keyboard internal state based on a received command."""
        if cmd == CMD_CLEAR_ALL:
            with self._lock:
                self.modifier_state = 0
                self.pressed_keys.clear()
            logging.info("Received CLEAR_ALL: keyboard state reset")
            self.write_kbd_report()
            return

        if key_code is None:
            return

        if key_code in MODIFIER_BIT_MAP:
            bit = MODIFIER_BIT_MAP[key_code]
            with self._lock:
                if cmd == CMD_PRESS:
                    self.modifier_state |= bit
                    logging.debug(f"Modifier press: code={key_code}, bit={bin(bit)}, modifier_state={bin(self.modifier_state)}")
                elif cmd == CMD_RELEASE:
                    self.modifier_state &= ~bit
                    logging.debug(f"Modifier release: code={key_code}, bit={bin(bit)}, modifier_state={bin(self.modifier_state)}")
        else:
            with self._lock:
                if cmd == CMD_PRESS:
                    self.pressed_keys.add(key_code)
                    logging.debug(f"Key press: {key_code} (pressed_keys now {sorted(self.pressed_keys)})")
                elif cmd == CMD_RELEASE:
                    self.pressed_keys.discard(key_code)
                    logging.debug(f"Key release: {key_code} (pressed_keys now {sorted(self.pressed_keys)})")
        self.write_kbd_report()

    # ---------------------
    # Mouse helpers
    # ---------------------
    def _mouse_press(self, mask: int):
        self.mouse_buttons_mask |= (mask & 0x1F)
        self.write_mouse_report(self.mouse_buttons_mask, 0, 0, 0)

    def _mouse_release(self, mask: int):
        self.mouse_buttons_mask &= ~(mask & 0x1F)
        self.write_mouse_report(self.mouse_buttons_mask, 0, 0, 0)

    def _mouse_click(self, mask: int, hold_ms: Optional[int] = None):
        # 사람같은 랜덤 눌림 유지시간: 기본 30~80ms, 평균 50ms
        if hold_ms is None:
            hold_ms = int(max(30, min(80, random.gauss(50, 10))))
        self._mouse_press(mask)
        time.sleep(hold_ms / 1000.0)
        self._mouse_release(mask)

    def _mouse_double_click(self):
        # 더블클릭 간격: 평균 160ms, 표준편차 40ms, 110~300ms 범위
        self._mouse_click(0x01)
        interval_ms = int(max(110, min(300, random.gauss(160, 40))))
        time.sleep(interval_ms / 1000.0)
        self._mouse_click(0x01)

    def _mouse_move_rel(self, dx: int, dy: int):
        # dx, dy가 int8 범위를 넘으면 여러 리포트로 분할
        while dx != 0 or dy != 0:
            step_x = max(-127, min(127, dx))
            step_y = max(-127, min(127, dy))
            self.write_mouse_report(self.mouse_buttons_mask, step_x, step_y, 0)
            dx -= step_x
            dy -= step_y

    def _smoothstep(self, t: float) -> float:
        # Cosine ease-in-out (부드러운 가감속)
        return 0.5 - 0.5 * math.cos(math.pi * t)

    def _mouse_smooth_move(self, dx_total: int, dy_total: int, duration_ms: int):
        # 최소/최대 duration 방어
        duration_ms = int(max(10, min(5000, duration_ms)))

        start = time.perf_counter()
        end = start + duration_ms / 1000.0

        last_tx = 0.0
        last_ty = 0.0
        now = start

        # 이동 직후 약간의 랜덤 대기(사람같은 반응)
        # 실제 이동 중에는 8~14ms 랜덤 주기 적용
        while True:
            now = time.perf_counter()
            if now >= end:
                break
            t = (now - start) / (end - start)
            t = max(0.0, min(1.0, t))
            s = self._smoothstep(t)
            tx = dx_total * s
            ty = dy_total * s
            # 이번 스텝에 보낼 정수 델타
            dx = int(round(tx - last_tx))
            dy = int(round(ty - last_ty))
            if dx != 0 or dy != 0:
                self._mouse_move_rel(dx, dy)
                last_tx += dx
                last_ty += dy
            # 다음 스텝까지 랜덤 간격(8~14ms)
            sleep_ms = random.randint(8, 14)
            time.sleep(sleep_ms / 1000.0)

        # 잔여 오차 보정
        rx = dx_total - int(round(last_tx))
        ry = dy_total - int(round(last_ty))
        if rx != 0 or ry != 0:
            self._mouse_move_rel(rx, ry)

        # 이동 직후 안정 대기 10~30ms
        time.sleep(random.randint(10, 30) / 1000.0)

    def _read_exact(self, n: int) -> Optional[bytes]:
        if n <= 0:
            return b""
        buf = bytearray()
        while not self._stop_event.is_set() and len(buf) < n:
            chunk = self.ser.read(n - len(buf)) if self.ser else b""
            if not chunk:
                # timeout; allow loop to check stop_event
                continue
            buf.extend(chunk)
        return bytes(buf) if len(buf) == n else None

    def _read_loop(self):
        """Main loop: read from serial and update HID."""
        while not self._stop_event.is_set():
            # ensure serial is connected
            if not self.ser:
                ok = self._connect_serial()
                if not ok:
                    # wait and retry (but check stop event)
                    for _ in range(int(self.reconnect_delay * 10)):
                        if self._stop_event.is_set(): break
                        time.sleep(0.1)
                    continue

            try:
                # read 1 byte command first
                data = self._read_exact(1)
                if not data:
                    continue
                cmd = data[0]

                # Determine payload length by command
                payload_len = 0
                if cmd in (CMD_PRESS, CMD_RELEASE):
                    payload_len = 1
                elif cmd == CMD_CLEAR_ALL:
                    payload_len = 0
                elif cmd == MOUSE_MOVE_REL:
                    payload_len = 2
                elif cmd == MOUSE_SMOOTH_MOVE:
                    payload_len = 6
                elif cmd in (MOUSE_LEFT_CLICK, MOUSE_RIGHT_CLICK, MOUSE_DOUBLE_CLICK):
                    payload_len = 0
                else:
                    logging.debug(f"Unknown cmd: {cmd}; skipping")
                    # attempt to continue loop
                    continue

                payload = self._read_exact(payload_len) if payload_len else b""
                if payload_len and (not payload or len(payload) != payload_len):
                    logging.debug("Incomplete payload; skipping")
                    continue

                # Dispatch per command
                if cmd in (CMD_PRESS, CMD_RELEASE):
                    key_code = payload[0]
                    self._handle_keyboard(cmd, key_code)
                elif cmd == CMD_CLEAR_ALL:
                    # 키보드 상태 초기화 + 마우스 버튼도 해제하여 스턱 방지
                    self._handle_keyboard(cmd)
                    # 하위 호환: 과거 2바이트 프레임(불필요한 dummy 바이트)을 보낼 수 있어
                    # 버퍼에 남아있다면 1바이트를 비동기적으로 버린다.
                    try:
                        if self.ser and getattr(self.ser, 'in_waiting', 0) > 0:
                            _ = self.ser.read(1)
                            logging.debug("CLEAR_ALL: drained 1 extra byte for compatibility")
                    except Exception:
                        pass
                    if self.mouse_buttons_mask:
                        self.mouse_buttons_mask = 0
                        self.write_mouse_report(0, 0, 0, 0)
                elif cmd == MOUSE_MOVE_REL:
                    dx = struct.unpack('<b', payload[0:1])[0]
                    dy = struct.unpack('<b', payload[1:2])[0]
                    self._mouse_move_rel(dx, dy)
                elif cmd == MOUSE_SMOOTH_MOVE:
                    dx, dy, dur = struct.unpack('<hhh', payload)
                    self._mouse_smooth_move(dx, dy, dur)
                elif cmd == MOUSE_LEFT_CLICK:
                    self._mouse_click(0x01)
                elif cmd == MOUSE_RIGHT_CLICK:
                    self._mouse_click(0x02)
                elif cmd == MOUSE_DOUBLE_CLICK:
                    self._mouse_double_click()

            except serial.SerialException as e:
                logging.warning(f"Serial error: {e}; closing and will retry")
                self._close_serial()
                # small pause to avoid busy retry
                for _ in range(int(self.reconnect_delay * 10)):
                    if self._stop_event.is_set(): break
                    time.sleep(0.1)
            except Exception as e:
                logging.exception(f"Unexpected error in read loop: {e}")
                # on unexpected exceptions, try to recover after a pause
                self._close_serial()
                for _ in range(int(self.reconnect_delay * 10)):
                    if self._stop_event.is_set(): break
                    time.sleep(0.1)

    def run(self):
        try:
            self._open_hid_keyboard()
            self._open_hid_mouse()
            if not self.hid_kbd_file:
                logging.error("Keyboard HID not available; exiting")
                return
            if not self.hid_mouse_file:
                logging.warning("Mouse HID not available; continuing with keyboard only")

            # At start, ensure no keys are pressed
            with self._lock:
                self.modifier_state = 0
                self.pressed_keys.clear()
            self.write_kbd_report()
            # Ensure mouse buttons up
            self.mouse_buttons_mask = 0
            self.write_mouse_report(0, 0, 0, 0)

            logging.info("Starting main read loop (press Ctrl+C to stop)")
            self._read_loop()

        finally:
            logging.info("Shutting down: clearing keys and closing resources")
            # clear state and send final "all released" report
            with self._lock:
                self.modifier_state = 0
                self.pressed_keys.clear()
            self.write_kbd_report()
            # release all mouse buttons
            self.mouse_buttons_mask = 0
            self.write_mouse_report(0, 0, 0, 0)

            self._close_serial()
            self._close_hid_keyboard()
            self._close_hid_mouse()
            logging.info("Shutdown complete")


# ---------------------
# Program entry
# ---------------------
def main():
    listener = HIDListener()

    def _signal_handler(signum, frame):
        logging.info(f"Signal {signum} received, requesting stop")
        listener.request_stop()

    # Register signal handlers
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Run listener (blocking)
    listener.run()


if __name__ == '__main__':
    main()
