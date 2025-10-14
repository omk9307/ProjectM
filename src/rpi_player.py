#  main.py 등과는 상관없고 독립적으로  라즈베리파이4에서 사용되는 코드이다. 

import serial
import time
import signal
import threading
import logging
import sys
from typing import Optional

# ---------------------
# Config
# ---------------------
SERIAL_PORT = '/dev/ttyGS0'   # PC side (gadget serial)
BAUD_RATE = 115200
HID_DEVICE_PATH = '/dev/hidg0'

CMD_PRESS = 0x01
CMD_RELEASE = 0x02
CMD_CLEAR_ALL = 0x03

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
                 hid_path: str = HID_DEVICE_PATH,
                 reconnect_delay: float = 5.0):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.hid_path = hid_path
        self.reconnect_delay = reconnect_delay

        self.ser: Optional[serial.Serial] = None
        self.hid_file = None

        # internal state (protected by lock)
        self._lock = threading.Lock()
        self.modifier_state = 0       # 8-bit mask for modifiers
        self.pressed_keys = set()     # set of key codes (ints)

        self._stop_event = threading.Event()

        # logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    def request_stop(self):
        logging.info("stop requested")
        self._stop_event.set()

    def _open_hid(self):
        # Open HID device once and reuse file descriptor
        try:
            self.hid_file = open(self.hid_path, 'wb+', buffering=0)
            logging.info(f"HID device opened: {self.hid_path}")
        except Exception as e:
            logging.error(f"Failed to open HID device {self.hid_path}: {e}")
            self.hid_file = None

    def _close_hid(self):
        if self.hid_file:
            try:
                self.hid_file.close()
                logging.info("HID device closed")
            except Exception as e:
                logging.warning(f"Error closing HID device: {e}")
            self.hid_file = None

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

    def write_report(self):
        """Compose and send an 8-byte HID report: [modifier, reserved, key1..key6]"""
        with self._lock:
            report = bytearray(8)
            report[0] = self.modifier_state & 0xFF
            # report[1] is reserved (0)
            keys = sorted(self.pressed_keys)[:6]  # deterministic order
            for i, kc in enumerate(keys):
                report[2 + i] = int(kc) & 0xFF

        if not self.hid_file:
            logging.debug("HID file not opened; skipping write_report")
            return

        try:
            # write and flush
            self.hid_file.write(report)
            self.hid_file.flush()
            # optional debug
            logging.debug(f"Sent HID report: {list(report)}")
        except Exception as e:
            logging.error(f"HID write error: {e}")

    def _handle_incoming(self, cmd: int, key_code: int):
        """Update internal state based on a received command."""
        # 우선 전체 해제 명령을 처리
        if cmd == CMD_CLEAR_ALL:
            with self._lock:
                self.modifier_state = 0
                self.pressed_keys.clear()
            logging.info("Received CLEAR_ALL: state reset and report will be sent")
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
                # read 2 bytes (blocking up to timeout=1s)
                data = self.ser.read(2)
                if not data or len(data) < 2:
                    continue  # timeout or incomplete; loop back
                cmd = data[0]
                key_code = data[1]
                if cmd not in (CMD_PRESS, CMD_RELEASE):
                    logging.debug(f"Ignoring unknown cmd: {cmd}")
                    continue

                self._handle_incoming(cmd, key_code)
                self.write_report()

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
            self._open_hid()
            if not self.hid_file:
                logging.error("HID device not available; exiting")
                return

            # At start, ensure no keys are pressed
            with self._lock:
                self.modifier_state = 0
                self.pressed_keys.clear()
            self.write_report()

            logging.info("Starting main read loop (press Ctrl+C to stop)")
            self._read_loop()

        finally:
            logging.info("Shutting down: clearing keys and closing resources")
            # clear state and send final "all released" report
            with self._lock:
                self.modifier_state = 0
                self.pressed_keys.clear()
            self.write_report()

            self._close_serial()
            self._close_hid()
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
