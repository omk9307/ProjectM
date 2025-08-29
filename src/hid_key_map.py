from pynput.keyboard import Key

# HID Usage IDs for letters and numbers
KEY_MAP = {
    'a': 4, 'b': 5, 'c': 6, 'd': 7, 'e': 8, 'f': 9, 'g': 10, 'h': 11,
    'i': 12, 'j': 13, 'k': 14, 'l': 15, 'm': 16, 'n': 17, 'o': 18,
    'p': 19, 'q': 20, 'r': 21, 's': 22, 't': 23, 'u': 24, 'v': 25,
    'w': 26, 'x': 27, 'y': 28, 'z': 29,
    '1': 30, '2': 31, '3': 32, '4': 33, '5': 34,
    '6': 35, '7': 36, '8': 37, '9': 38, '0': 39,
    Key.enter: 40, Key.esc: 41, Key.backspace: 42, Key.tab: 43,
    Key.space: 44,
    '-': 45, '_': 45, '=': 46, '+': 46, '[': 47, '{': 47, ']': 48, '}': 48,
    '\\': 49, '|': 49,
    ';': 51, ':': 51, "'": 52, '"': 52, '`': 53, '~': 53,
    ',': 54, '<': 54, '.': 55, '>': 55, '/': 56, '?': 56,
    Key.caps_lock: 57,
    Key.f1: 58, Key.f2: 59, Key.f3: 60, Key.f4: 61, Key.f5: 62,
    Key.f6: 63, Key.f7: 64, Key.f8: 65, Key.f9: 66, Key.f10: 67,
    Key.f11: 68, Key.f12: 69,
    Key.print_screen: 70, Key.scroll_lock: 71, Key.pause: 72,
    Key.insert: 73, Key.home: 74, Key.page_up: 75, Key.delete: 76,
    Key.end: 77, Key.page_down: 78,
    Key.right: 79, Key.left: 80, Key.down: 81, Key.up: 82,
    Key.num_lock: 83,
}

# Modifier keys are handled separately by a bitmask
# "Key.win" 관련 줄을 모두 제거하고 "Key.cmd"만 사용하도록 수정했습니다.
MODIFIER_MAP = {
    Key.ctrl: 0x01, Key.ctrl_l: 0x01, Key.ctrl_r: 0x10,
    Key.shift: 0x02, Key.shift_l: 0x02, Key.shift_r: 0x20,
    Key.alt: 0x04, Key.alt_l: 0x04, Key.alt_r: 0x40,
    Key.cmd: 0x08, Key.cmd_l: 0x08, Key.cmd_r: 0x80, # GUI/Windows/Command key
}

# Reverse map for debugging and display
REVERSE_KEY_MAP = {v: str(k).replace("Key.", "") for k, v in KEY_MAP.items()}
for char in "abcdefghijklmnopqrstuvwxyz0123456789":
    if char in KEY_MAP:
        REVERSE_KEY_MAP[KEY_MAP[char]] = char

REVERSE_MODIFIER_MAP = {
    0x01: 'L_CTRL', 0x02: 'L_SHIFT', 0x04: 'L_ALT', 0x08: 'L_GUI',
    0x10: 'R_CTRL', 0x20: 'R_SHIFT', 0x40: 'R_ALT', 0x80: 'R_GUI'
}

def get_hid_code(key):
    """ Get HID code from pynput key. """
    if isinstance(key, Key):
        return KEY_MAP.get(key)
    elif hasattr(key, 'char') and key.char:
        return KEY_MAP.get(key.char.lower())
    return None

def get_modifier_bit(key):
    """ Get modifier bit from pynput key. """
    return MODIFIER_MAP.get(key)
