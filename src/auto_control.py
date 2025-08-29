# auto_control.py

import serial
import time
import json
import os
import random
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QSpinBox, QMessageBox, QFrame,
    QListWidgetItem, QInputDialog
)
from PyQt6.QtCore import pyqtSlot, Qt
from PyQt6.QtGui import QIcon
from pynput.keyboard import Key

# --- 설정 및 상수 ---
SERIAL_PORT = 'COM6'
BAUD_RATE = 115200
CMD_PRESS = 0x01
CMD_RELEASE = 0x02
KEY_MAPPINGS_FILE = os.path.join('Project_Maple','workspace', 'config', 'key_mappings.json')

# ... (KEY_MAP은 이전과 동일하게 유지) ...
KEY_MAP = {
    'a': 4, 'b': 5, 'c': 6, 'd': 7, 'e': 8, 'f': 9, 'g': 10, 'h': 11, 'i': 12, 'j': 13, 'k': 14, 'l': 15, 'm': 16, 'n': 17, 'o': 18, 'p': 19, 'q': 20, 'r': 21, 's': 22, 't': 23, 'u': 24, 'v': 25, 'w': 26, 'x': 27, 'y': 28, 'z': 29, '1': 30, '2': 31, '3': 32, '4': 33, '5': 34, '6': 35, '7': 36, '8': 37, '9': 38, '0': 39, Key.enter: 40, Key.esc: 41, Key.backspace: 42, Key.tab: 43, Key.space: 44, '-': 45, '_': 45, '=': 46, '+': 46, '[': 47, '{': 47, ']': 48, '}': 48, '\\': 49, '|': 49, ';': 51, ':': 51, "'": 52, '"': 52, '`': 53, '~': 53, ',': 54, '<': 54, '.': 55, '>': 55, '/': 56, '?': 56, Key.caps_lock: 57, Key.f1: 58, Key.f2: 59, Key.f3: 60, Key.f4: 61, Key.f5: 62, Key.f6: 63, Key.f7: 64, Key.f8: 65, Key.f9: 66, Key.f10: 67, Key.f11: 68, Key.f12: 69, Key.print_screen: 70, Key.scroll_lock: 71, Key.pause: 72, Key.insert: 73, Key.home: 74, Key.page_up: 75, Key.delete: 76, Key.end: 77, Key.page_down: 78, Key.right: 79, Key.left: 80, Key.down: 81, Key.up: 82, Key.num_lock: 83,
    Key.alt: 0, Key.alt_l: 0, Key.alt_r: 0, 
    Key.ctrl: 0, Key.ctrl_l: 0, Key.ctrl_r: 0,
    Key.shift: 0, Key.shift_l: 0, Key.shift_r: 0,
}

class AutoControlTab(QWidget):
    def __init__(self):
        super().__init__()
        self.ser = None
        self.held_keys = set()
        self.mappings = {}
        self.key_list_str = self._generate_key_list()

        self.init_ui()
        self.load_mappings()
        self.connect_to_pi()
        
        self.setStyleSheet("""
            QFrame { border: 1px solid #444; border-radius: 5px; }
            QLabel#TitleLabel { font-size: 13px; font-weight: bold; padding: 5px; background-color: #3a3a3a; color: white; border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QGroupBox { font-size: 12px; font-weight: bold; }
            QPushButton { padding: 4px; }
        """)

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        left_panel = self._create_left_panel()
        main_layout.addWidget(left_panel, 1)

        right_panel = self._create_right_panel()
        main_layout.addWidget(right_panel, 1)

    def _create_left_panel(self):
        left_widget = QFrame()
        main_v_layout = QVBoxLayout(left_widget)
        
        top_h_layout = QHBoxLayout()
        
        # --- 명령 목록 ---
        cmd_group_layout = QVBoxLayout()
        cmd_title = QLabel("명령 프로필"); cmd_title.setObjectName("TitleLabel")
        cmd_group_layout.addWidget(cmd_title)
        
        self.command_list = QListWidget()
        self.command_list.currentItemChanged.connect(self.on_command_selected)
        cmd_group_layout.addWidget(self.command_list)

        cmd_buttons_layout = QHBoxLayout()
        add_cmd_btn = QPushButton(QIcon.fromTheme("list-add"), " 추가"); add_cmd_btn.clicked.connect(self.add_command_profile)
        remove_cmd_btn = QPushButton(QIcon.fromTheme("list-remove"), " 삭제"); remove_cmd_btn.clicked.connect(self.remove_command_profile)
        cmd_buttons_layout.addWidget(add_cmd_btn)
        cmd_buttons_layout.addWidget(remove_cmd_btn)
        cmd_group_layout.addLayout(cmd_buttons_layout)
        # [UI 수정] 명령 프로필(2) : 액션 시퀀스(1) 비율로 변경
        top_h_layout.addLayout(cmd_group_layout, 2)

        # --- 시퀀스 편집기 ---
        seq_group_layout = QVBoxLayout()
        seq_title = QLabel("액션 시퀀스"); seq_title.setObjectName("TitleLabel")
        seq_group_layout.addWidget(seq_title)
        
        self.action_sequence_list = QListWidget()
        self.action_sequence_list.currentItemChanged.connect(self.on_action_step_selected)
        seq_group_layout.addWidget(self.action_sequence_list)

        seq_buttons_layout = QHBoxLayout()
        test_seq_btn = QPushButton(QIcon.fromTheme("media-playback-start"), " 테스트"); test_seq_btn.clicked.connect(self.test_selected_sequence)
        
        add_step_btn = QPushButton(QIcon.fromTheme("list-add"), ""); add_step_btn.clicked.connect(self.add_action_step)
        remove_step_btn = QPushButton(QIcon.fromTheme("list-remove"), ""); remove_step_btn.clicked.connect(self.remove_action_step)
        move_up_btn = QPushButton(QIcon.fromTheme("go-up"), ""); move_up_btn.clicked.connect(lambda: self.move_action_step(-1))
        move_down_btn = QPushButton(QIcon.fromTheme("go-down"), ""); move_down_btn.clicked.connect(lambda: self.move_action_step(1))
        
        seq_buttons_layout.addWidget(test_seq_btn)
        seq_buttons_layout.addStretch()
        seq_buttons_layout.addWidget(add_step_btn)
        seq_buttons_layout.addWidget(remove_step_btn)
        seq_buttons_layout.addWidget(move_up_btn)
        seq_buttons_layout.addWidget(move_down_btn)
        seq_group_layout.addLayout(seq_buttons_layout)
        top_h_layout.addLayout(seq_group_layout, 1)
        
        main_v_layout.addLayout(top_h_layout)

        self.editor_group = self._create_editor_panel()
        main_v_layout.addWidget(self.editor_group)
        main_v_layout.addStretch()
        
        bottom_layout = QVBoxLayout()
        save_buttons_layout = QHBoxLayout()
        save_btn = QPushButton(QIcon.fromTheme("document-save"), " 매핑 저장"); save_btn.clicked.connect(self.save_mappings)
        reset_btn = QPushButton(QIcon.fromTheme("edit-undo"), " 기본값으로 복원"); reset_btn.clicked.connect(self.reset_to_defaults)
        save_buttons_layout.addStretch()
        save_buttons_layout.addWidget(save_btn)
        save_buttons_layout.addWidget(reset_btn)
        
        status_layout = QHBoxLayout()
        self.status_label = QLabel("라즈베리파이에 연결을 시도합니다...")
        reconnect_btn = QPushButton(QIcon.fromTheme("view-refresh"), " 재연결")
        reconnect_btn.clicked.connect(self.connect_to_pi)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(reconnect_btn)
        
        bottom_layout.addLayout(save_buttons_layout)
        bottom_layout.addLayout(status_layout)
        main_v_layout.addLayout(bottom_layout)
        
        return left_widget

    def _create_editor_panel(self):
        editor_group = QGroupBox("선택된 액션 상세 편집")
        editor_layout = QFormLayout(editor_group)
        self.action_type_combo = QComboBox()
        self.action_type_combo.addItems(["press", "release", "delay", "release_all", "release_specific"])
        self.action_type_combo.currentIndexChanged.connect(self._on_editor_type_changed)
        self.key_combo = QComboBox()
        self.key_combo.addItems(self.key_list_str)
        self.delay_widget = QWidget()
        delay_layout = QHBoxLayout(self.delay_widget)
        delay_layout.setContentsMargins(0,0,0,0)
        self.min_delay_spin = QSpinBox()
        self.min_delay_spin.setRange(0, 10000); self.min_delay_spin.setSuffix(" ms")
        self.max_delay_spin = QSpinBox()
        self.max_delay_spin.setRange(0, 10000); self.max_delay_spin.setSuffix(" ms")
        delay_layout.addWidget(self.min_delay_spin)
        delay_layout.addWidget(QLabel("~"))
        delay_layout.addWidget(self.max_delay_spin)
        editor_layout.addRow("타입:", self.action_type_combo)
        editor_layout.addRow("키:", self.key_combo)
        editor_layout.addRow("지연 시간:", self.delay_widget)
        self.action_type_combo.currentTextChanged.connect(self._update_action_from_editor)
        self.key_combo.currentTextChanged.connect(self._update_action_from_editor)
        self.min_delay_spin.valueChanged.connect(self._update_action_from_editor)
        self.max_delay_spin.valueChanged.connect(self._update_action_from_editor)
        editor_group.setEnabled(False)
        return editor_group

    def _create_right_panel(self):
        right_widget = QFrame()
        right_layout = QVBoxLayout(right_widget)
        info_label = QLabel("추후 기능 추가 예정")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(info_label)
        return right_widget

    def load_mappings(self):
        if os.path.exists(KEY_MAPPINGS_FILE):
            try:
                with open(KEY_MAPPINGS_FILE, 'r', encoding='utf-8') as f:
                    self.mappings = json.load(f)
            except json.JSONDecodeError:
                self.mappings = self.create_default_mappings()
        else:
            self.mappings = self.create_default_mappings()
        self.populate_command_list()

    def save_mappings(self):
        try:
            with open(KEY_MAPPINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.mappings, f, indent=4, ensure_ascii=False)
            self.status_label.setText("키 매핑이 성공적으로 저장되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"키 매핑 저장에 실패했습니다:\n{e}")

    def create_default_mappings(self):
        # [수정] 기본 지연 시간을 80~120ms로, 명령 프로필 이름을 새로운 이름으로 변경
        return {
            "걷기(우)": [{"type": "release_specific", "key_str": "Key.left"}, {"type": "press", "key_str": "Key.right"}],
            "걷기(좌)": [{"type": "release_specific", "key_str": "Key.right"}, {"type": "press", "key_str": "Key.left"}],
            "점프키 누르기": [{"type": "press", "key_str": "Key.space"}, {"type": "delay", "min_ms": 80, "max_ms": 120}, {"type": "release", "key_str": "Key.space"}],
            "아래점프": [
                {"type": "press", "key_str": "Key.down"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "press", "key_str": "Key.space"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "release", "key_str": "Key.space"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "release", "key_str": "Key.down"}
            ],
            "사다리타기(우)": [
                {"type": "press", "key_str": "Key.right"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "press", "key_str": "Key.space"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "release", "key_str": "Key.space"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "release", "key_str": "Key.right"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "press", "key_str": "Key.up"}
            ],
            "사다리타기(좌)": [
                {"type": "press", "key_str": "Key.left"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "press", "key_str": "Key.space"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "release", "key_str": "Key.space"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "release", "key_str": "Key.left"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "press", "key_str": "Key.up"}
            ],
            "모든 키 떼기": [{"type": "release_all"}]
        }
    def reset_to_defaults(self):
        reply = QMessageBox.question(self, "기본값 복원", "모든 키 매핑을 기본값으로 되돌리시겠습니까?\n저장하지 않은 변경사항은 사라집니다.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            self.mappings = self.create_default_mappings()
            self.populate_command_list()
            if self.command_list.count() > 0:
                self.command_list.setCurrentRow(0)

    def populate_command_list(self):
        current_selection = self.command_list.currentItem().text() if self.command_list.currentItem() else None
        self.command_list.clear()
        self.command_list.addItems(sorted(self.mappings.keys()))
        if current_selection:
            items = self.command_list.findItems(current_selection, Qt.MatchFlag.MatchExactly)
            if items:
                self.command_list.setCurrentItem(items[0])

    def _generate_key_list(self):
        keys = []
        for k in KEY_MAP.keys():
            if isinstance(k, str):
                keys.append(k)
            elif isinstance(k, Key):
                keys.append(f"Key.{k.name}")
        return sorted(list(set(keys)))

    def on_command_selected(self, current_item, _=None):
        self.editor_group.setEnabled(False) 
        self.action_sequence_list.clear()
        if not current_item: return
        
        command_text = current_item.text()
        self._populate_action_sequence_list(command_text)

    def on_action_step_selected(self, current_item, _=None):
        if not current_item:
            self.editor_group.setEnabled(False)
            return
        command_item = self.command_list.currentItem()
        if not command_item: return
        
        command_text = command_item.text()
        row = self.action_sequence_list.currentRow()
        sequence = self.mappings.get(command_text, [])
        
        if 0 <= row < len(sequence):
            action_data = sequence[row]
            self._update_editor_panel(action_data)
            self.editor_group.setEnabled(True)
        else:
            self.editor_group.setEnabled(False)

    def _on_editor_type_changed(self, _):
        action_type = self.action_type_combo.currentText()
        is_delay = (action_type == 'delay')
        is_key_based = action_type in ['press', 'release', 'release_specific']
        
        self.key_combo.setVisible(is_key_based)
        self.delay_widget.setVisible(is_delay)
        
        form_layout = self.editor_group.layout()
        label_for_key = form_layout.labelForField(self.key_combo)
        if label_for_key: label_for_key.setVisible(is_key_based)
            
        label_for_delay = form_layout.labelForField(self.delay_widget)
        if label_for_delay: label_for_delay.setVisible(is_delay)

    def _update_editor_panel(self, action_data):
        self.action_type_combo.blockSignals(True); self.key_combo.blockSignals(True); self.min_delay_spin.blockSignals(True); self.max_delay_spin.blockSignals(True)
        action_type = action_data.get("type", "press")
        self.action_type_combo.setCurrentText(action_type)
        self._on_editor_type_changed(0) 
        if action_type in ['press', 'release', 'release_specific']:
            self.key_combo.setCurrentText(action_data.get("key_str", "Key.space"))
        elif action_type == 'delay':
            self.min_delay_spin.setValue(action_data.get("min_ms", 0))
            self.max_delay_spin.setValue(action_data.get("max_ms", 0))
        self.action_type_combo.blockSignals(False); self.key_combo.blockSignals(False); self.min_delay_spin.blockSignals(False); self.max_delay_spin.blockSignals(False)

    def _update_action_from_editor(self, _=None):
        command_item = self.command_list.currentItem(); action_item = self.action_sequence_list.currentItem()
        if not command_item or not action_item: return
        command_text = command_item.text(); row = self.action_sequence_list.currentRow()
        action_type = self.action_type_combo.currentText()
        new_action_data = {"type": action_type}
        if action_type in ['press', 'release', 'release_specific']:
            new_action_data["key_str"] = self.key_combo.currentText()
        elif action_type == 'delay':
            new_action_data["min_ms"] = self.min_delay_spin.value(); new_action_data["max_ms"] = self.max_delay_spin.value()
        self.mappings[command_text][row] = new_action_data
        self._update_action_item_text(action_item, new_action_data)

    def _update_action_item_text(self, item, action_data):
        step_text = ""
        type = action_data.get("type")
        if type == "press": step_text = f"누르기: {action_data.get('key_str', 'N/A')}"
        elif type == "release": step_text = f"떼기: {action_data.get('key_str', 'N/A')}"
        elif type == "delay": step_text = f"지연: {action_data.get('min_ms', 0)}ms ~ {action_data.get('max_ms', 0)}ms"
        elif type == "release_all": step_text = "모든 키 떼기"
        elif type == "release_specific": step_text = f"특정 키 떼기: {action_data.get('key_str', 'N/A')}"
        item.setText(step_text)

    def _populate_action_sequence_list(self, command_text):
        self.action_sequence_list.clear()
        sequence = self.mappings.get(command_text, [])
        for step in sequence:
            item = QListWidgetItem()
            self._update_action_item_text(item, step)
            self.action_sequence_list.addItem(item)

    def add_command_profile(self):
        text, ok = QInputDialog.getText(self, "새 명령 프로필 추가", "명령어 이름:")
        if ok and text:
            if text in self.mappings:
                QMessageBox.warning(self, "오류", "이미 존재하는 명령어입니다.")
                return
            self.mappings[text] = []
            self.populate_command_list()
            items = self.command_list.findItems(text, Qt.MatchFlag.MatchExactly)
            if items: self.command_list.setCurrentItem(items[0])

    def remove_command_profile(self):
        current_item = self.command_list.currentItem()
        if not current_item: return
        command_text = current_item.text()
        reply = QMessageBox.question(self, "명령 프로필 삭제", f"'{command_text}' 명령 프로필을 삭제하시겠습니까?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            del self.mappings[command_text]
            self.populate_command_list()

    def add_action_step(self):
        command_item = self.command_list.currentItem()
        if not command_item:
            QMessageBox.warning(self, "오류", "먼저 좌측에서 명령을 선택하세요.")
            return
        command_text = command_item.text()
        new_action = {"type": "press", "key_str": "Key.space"}
        self.mappings[command_text].append(new_action)
        self._populate_action_sequence_list(command_text)
        self.action_sequence_list.setCurrentRow(self.action_sequence_list.count() - 1)

    def remove_action_step(self):
        command_item = self.command_list.currentItem(); row = self.action_sequence_list.currentRow()
        if not command_item or row < 0: return
        command_text = command_item.text()
        del self.mappings[command_text][row]
        self._populate_action_sequence_list(command_text)

    def move_action_step(self, direction):
        command_item = self.command_list.currentItem(); row = self.action_sequence_list.currentRow()
        if not command_item or row < 0: return
        new_row = row + direction
        if not (0 <= new_row < self.action_sequence_list.count()): return
        command_text = command_item.text()
        sequence = self.mappings[command_text]
        item = sequence.pop(row)
        sequence.insert(new_row, item)
        self._populate_action_sequence_list(command_text)
        self.action_sequence_list.setCurrentRow(new_row)

    def connect_to_pi(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("[AutoControl] 기존 시리얼 연결을 해제했습니다.")
        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            self.status_label.setText(f"성공: {SERIAL_PORT}에 연결되었습니다.")
            print(f"[AutoControl] {SERIAL_PORT}에 연결되었습니다.")
        except serial.SerialException as e:
            self.status_label.setText(f"실패: {SERIAL_PORT}에 연결할 수 없습니다.")
            print(f"[AutoControl] 시리얼 연결 실패: {e}")

    def _str_to_key_obj(self, key_str):
        if key_str.startswith("Key."): return getattr(Key, key_str.split('.')[1], None)
        else: return key_str 

    def _send_command(self, command, key_object):
        if not self.ser or not self.ser.is_open: return
        key_code = KEY_MAP.get(key_object)
        if key_code is not None:
            try:
                self.ser.write(bytes([command, key_code]))
            except serial.SerialException as e:
                print(f"[AutoControl] 데이터 전송 실패: {e}"); self.connect_to_pi()

    def _press_key(self, key_object):
        if key_object not in self.held_keys:
            self.held_keys.add(key_object); self._send_command(CMD_PRESS, key_object)

    def _release_key(self, key_object):
        if key_object in self.held_keys:
            self.held_keys.discard(key_object); self._send_command(CMD_RELEASE, key_object)

    def _release_all_keys(self):
        for key_obj in list(self.held_keys): self._release_key(key_obj)

    def test_selected_sequence(self):
        command_item = self.command_list.currentItem()
        if not command_item:
            QMessageBox.warning(self, "알림", "테스트할 명령 프로필을 선택하세요.")
            return
        command_text = command_item.text()
        sequence = self.mappings.get(command_text)
        if sequence is None:
            QMessageBox.warning(self, "오류", "선택된 명령에 대한 시퀀스를 찾을 수 없습니다.")
            return
        self._execute_sequence(sequence, f"TEST: {command_text}")

    def _execute_sequence(self, sequence, command_name):
        print(f"--- [AutoControl] 실행 시작: '{command_name}' ---")
        for step in sequence:
            action_type = step.get("type")
            if action_type in ["press", "release", "release_specific"]:
                key_obj = self._str_to_key_obj(step.get("key_str"))
                if not key_obj:
                    print(f"  - 오류: 알 수 없는 키 '{step.get('key_str')}'")
                    continue
                if action_type == "press":
                    self._press_key(key_obj); print(f"  - PRESS: {key_obj}")
                else:
                    self._release_key(key_obj); print(f"  - RELEASE: {key_obj}")
            elif action_type == "delay":
                min_ms = step.get("min_ms", 0); max_ms = step.get("max_ms", 0)
                # [수정] 정규 분포 랜덤 지연 적용
                if min_ms >= max_ms:
                    delay_s = min_ms / 1000.0
                else:
                    mean = (min_ms + max_ms) / 2
                    std_dev = (max_ms - min_ms) / 6
                    delay_ms = random.gauss(mean, std_dev)
                    # 생성된 값이 범위를 벗어나지 않도록 강제
                    delay_ms = max(min(delay_ms, max_ms), min_ms)
                    delay_s = delay_ms / 1000.0

                print(f"  - DELAY: {delay_s*1000:.0f}ms (범위: {min_ms}~{max_ms}ms)")
                time.sleep(delay_s)
            elif action_type == "release_all":
                self._release_all_keys(); print("  - RELEASE_ALL_KEYS")
        print(f"--- [AutoControl] 실행 완료 ---")

    @pyqtSlot(str)
    def receive_control_command(self, command_text):
        sequence = self.mappings.get(command_text)
        if not sequence:
            print(f"[AutoControl] 경고: '{command_text}'에 대한 매핑이 없습니다.")
            return
        self._execute_sequence(sequence, command_text)

    def cleanup_on_close(self):
        print("'자동 제어' 탭 정리 중...")
        if self.ser and self.ser.is_open:
            self._release_all_keys()
            time.sleep(0.1)
            self.ser.close()
            print("시리얼 포트 연결을 해제했습니다.")