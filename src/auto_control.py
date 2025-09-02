# auto_control.py

import serial
import time
import json
import os
import random
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QSpinBox, QMessageBox, QFrame, QCheckBox,
    QListWidgetItem, QInputDialog, QAbstractItemView
)
from PyQt6.QtCore import pyqtSlot, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QColor
from pynput.keyboard import Key, Listener
from datetime import datetime

# --- 설정 및 상수 ---
SERIAL_PORT = 'COM6'
BAUD_RATE = 115200
CMD_PRESS = 0x01
CMD_RELEASE = 0x02
KEY_MAPPINGS_FILE = os.path.join('Project_Maple','workspace', 'config', 'key_mappings.json')

#  모든 키의 표준 HID 코드를 담는 통합 맵
FULL_KEY_MAP = {
    'a': 4, 'b': 5, 'c': 6, 'd': 7, 'e': 8, 'f': 9, 'g': 10, 'h': 11, 'i': 12, 'j': 13, 'k': 14, 'l': 15, 'm': 16, 'n': 17, 'o': 18, 'p': 19, 'q': 20, 'r': 21, 's': 22, 't': 23, 'u': 24, 'v': 25, 'w': 26, 'x': 27, 'y': 28, 'z': 29,
    '1': 30, '2': 31, '3': 32, '4': 33, '5': 34, '6': 35, '7': 36, '8': 37, '9': 38, '0': 39,
    Key.enter: 40, Key.esc: 41, Key.backspace: 42, Key.tab: 43, Key.space: 44,
    Key.right: 79, Key.left: 80, Key.down: 81, Key.up: 82,
    # 수식 키(Modifier)들의 표준 HID 코드를 추가
    Key.ctrl: 224, Key.ctrl_l: 224,
    Key.shift: 225, Key.shift_l: 225,
    Key.alt: 226, Key.alt_l: 226,
    Key.cmd: 227, Key.cmd_l: 227, # Windows Key
    Key.ctrl_r: 228,
    Key.shift_r: 229,
    Key.alt_r: 230,
    Key.cmd_r: 231,
}

class CopyableListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 여러 항목을 선택할 수 있도록 설정
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def keyPressEvent(self, event):
        # Ctrl+C가 눌렸는지 확인
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            selected_items = self.selectedItems()
            if selected_items:
                # 선택된 모든 항목의 텍스트를 줄바꿈으로 연결
                copied_text = "\n".join(item.text() for item in selected_items)
                QApplication.clipboard().setText(copied_text)
        else:
            # 다른 키 입력은 기본 동작을 따름
            super().keyPressEvent(event)


class AutoControlTab(QWidget):
    recording_status_changed = pyqtSignal(str)
    reset_auto_stop_timer_signal = pyqtSignal()
    stop_recording_signal = pyqtSignal()
    log_generated = pyqtSignal(str, str)
    request_detection_toggle = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.ser = None
        self.held_keys = set()
        self.mappings = {}
        self.key_list_str = self._generate_key_list()

        # --- 녹화 관련 변수 ---
        self.is_recording = False
        self.is_waiting_for_start_key = False
        self.keyboard_listener = None
        self.recorded_sequence = []
        self.last_event_time = 0
        self.auto_stop_timer = QTimer(self)
        self.auto_stop_timer.setSingleShot(True)
        self.auto_stop_timer.timeout.connect(self.stop_recording)
        self.currently_pressed_keys_for_recording = set()

        # --- 시퀀스 실행 관련 변수 ---
        self.sequence_timer = QTimer(self)
        self.sequence_timer.setSingleShot(True)
        self.sequence_timer.timeout.connect(self._process_next_step)
        self.is_sequence_running = False
        self.current_sequence = []
        self.current_sequence_index = 0
        self.current_command_name = ""
        self.is_test_mode = False

        self.is_processing_step = False                    # <- (신규) _process_next_step 재진입 방지 플래그
        self.last_sent_timestamps = {}                     # <- (신규) 키 전송 시각 기록 (에코 무시용)

        self.is_map_detection_running = False
        self.last_log_time = 0.0

        self.globally_pressed_keys = set()
        self.global_listener = None
        
        self.init_ui()
        self.load_mappings()
        self.connect_to_pi()
        
        # --- 시그널/슬롯 연결 ---
        self.recording_status_changed.connect(self.update_status_label)
        self.reset_auto_stop_timer_signal.connect(self._handle_reset_auto_stop_timer)
        self.stop_recording_signal.connect(self.stop_recording)
        self.log_generated.connect(self._add_log_entry)
      
        self.setStyleSheet("""
            QFrame { border: 1px solid #444; border-radius: 5px; }
            QLabel#TitleLabel { font-size: 13px; font-weight: bold; padding: 5px; background-color: #3a3a3a; color: white; border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QGroupBox { font-size: 12px; font-weight: bold; }
            QPushButton { padding: 4px; }
            QPushButton:checked { background-color: #c62828; color: white; border: 1px solid #999; }
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
        randomize_btn = QPushButton(QIcon.fromTheme("view-refresh"), " 지연 랜덤화")
        randomize_btn.clicked.connect(self.randomize_delays)

        cmd_buttons_layout.addWidget(add_cmd_btn)
        cmd_buttons_layout.addWidget(remove_cmd_btn)
        cmd_buttons_layout.addWidget(randomize_btn)
        cmd_group_layout.addLayout(cmd_buttons_layout)
        top_h_layout.addLayout(cmd_group_layout, 2)

        # --- 시퀀스 편집기 ---
        seq_group_layout = QVBoxLayout()
        
        #  제목과 복사 버튼을 한 줄에 배치
        seq_title_layout = QHBoxLayout()
        seq_title = QLabel("액션 시퀀스"); seq_title.setObjectName("TitleLabel")
        copy_seq_btn = QPushButton(QIcon.fromTheme("edit-copy"), " 복사")
        copy_seq_btn.clicked.connect(self.copy_sequence_to_clipboard)
        seq_title_layout.addWidget(seq_title)
        seq_title_layout.addStretch()
        seq_title_layout.addWidget(copy_seq_btn)
        seq_group_layout.addLayout(seq_title_layout)
        
        self.action_sequence_list = QListWidget()
        self.action_sequence_list.currentItemChanged.connect(self.on_action_step_selected)
        seq_group_layout.addWidget(self.action_sequence_list)

        seq_buttons_layout = QHBoxLayout()
        self.record_btn = QPushButton(QIcon.fromTheme("media-record"), " 녹화")
        self.record_btn.setCheckable(True)
        self.record_btn.clicked.connect(self.toggle_recording)
        test_seq_btn = QPushButton(QIcon.fromTheme("media-playback-start"), " 테스트"); test_seq_btn.clicked.connect(self.test_selected_sequence)
        
        add_step_btn = QPushButton(QIcon.fromTheme("list-add"), ""); add_step_btn.clicked.connect(self.add_action_step)
        remove_step_btn = QPushButton(QIcon.fromTheme("list-remove"), ""); remove_step_btn.clicked.connect(self.remove_action_step)
        move_up_btn = QPushButton(QIcon.fromTheme("go-up"), ""); move_up_btn.clicked.connect(lambda: self.move_action_step(-1))
        move_down_btn = QPushButton(QIcon.fromTheme("go-down"), ""); move_down_btn.clicked.connect(lambda: self.move_action_step(1))
        
        seq_buttons_layout.addWidget(self.record_btn)
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
        self.recording_settings_group = self._create_recording_settings_panel()
        main_v_layout.addWidget(self.recording_settings_group)
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

    def _create_recording_settings_panel(self):
        group = QGroupBox("녹화 설정")
        layout = QFormLayout(group)
        
        key_options = ["없음"] + self.key_list_str
        self.start_key_combo = QComboBox()
        self.start_key_combo.addItems(key_options)
        self.stop_key_combo = QComboBox()
        self.stop_key_combo.addItems(key_options)
        self.auto_stop_spin = QSpinBox()
        self.auto_stop_spin.setRange(500, 30000) # 0.5초 ~ 30초
        self.auto_stop_spin.setSingleStep(100)
        self.auto_stop_spin.setValue(2000)
        self.auto_stop_spin.setSuffix(" ms")

        layout.addRow("녹화 시작 키:", self.start_key_combo)
        layout.addRow("녹화 종료 키:", self.stop_key_combo)
        layout.addRow("자동 종료 시간:", self.auto_stop_spin)
        return group

    def _create_right_panel(self):
        right_widget = QFrame()
        right_layout = QVBoxLayout(right_widget)
        
        header_layout = QHBoxLayout()
        title = QLabel("실시간 로그")
        title.setObjectName("TitleLabel")
        
        self.log_checkbox = QCheckBox("입력 감지")
        self.log_checkbox.setChecked(False)
        # [수정] 체크박스 상태가 변경될 때 리스너 상태를 업데이트하도록 연결
        self.log_checkbox.toggled.connect(self._update_global_listener_state)
        
        self.console_log_checkbox = QCheckBox("상세 콘솔 로그")
        self.console_log_checkbox.setChecked(False)
        
        clear_log_btn = QPushButton(QIcon.fromTheme("edit-clear"), "로그 지우기")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.log_checkbox)
        header_layout.addWidget(self.console_log_checkbox)
        header_layout.addWidget(clear_log_btn)
        
        right_layout.addLayout(header_layout)

        self.key_log_list = CopyableListWidget()
        self.key_log_list.setWordWrap(True)
        self.key_log_list.setStyleSheet("""
            QListWidget {
                background-color: #2E2E2E;
                color: white;
                border: 1px solid #555;
            }
        """)
        right_layout.addWidget(self.key_log_list)

        self.detection_button = QPushButton("탐지 시작")
        self.detection_button.setCheckable(True)
        self.detection_button.clicked.connect(self.request_detection_toggle.emit)
        right_layout.addWidget(self.detection_button)

        clear_log_btn.clicked.connect(self.key_log_list.clear)

        return right_widget

    #  전역 키보드 리스너의 상태를 관리하는 메소드
    def _update_global_listener_state(self):
        should_listen = self.is_map_detection_running and self.log_checkbox.isChecked()

        # 현재 리스너가 동작해야 하는 상태인데, 리스너가 없는 경우
        if should_listen and self.global_listener is None:
            try:
                self.global_listener = Listener(on_press=self._on_global_press, on_release=self._on_global_release)
                self.global_listener.start()
                if self.console_log_checkbox.isChecked():
                    print("[AutoControl] 전역 키보드 리스너를 시작합니다.")
            except Exception as e:
                print(f"[AutoControl] 전역 키보드 리스너 시작 실패: {e}")

        # 현재 리스너가 동작하면 안 되는데, 리스너가 있는 경우
        elif not should_listen and self.global_listener is not None:
            self.global_listener.stop()
            self.global_listener = None
            self.globally_pressed_keys.clear() # 키 상태 초기화
            if self.console_log_checkbox.isChecked():
                print("[AutoControl] 전역 키보드 리스너를 중지합니다.")

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
        return {
            "걷기(우)": [
                {"type": "release_specific", "key_str": "Key.left"}, 
                {"type": "press", "key_str": "Key.right"}
            ],
            "걷기(좌)": [
                {"type": "release_specific", "key_str": "Key.right"}, 
                {"type": "press", "key_str": "Key.left"}
            ],
            # [수정] 점프키를 Key.alt_l 로 변경
            "점프키 누르기": [
                {"type": "press", "key_str": "Key.alt_l"}, 
                {"type": "delay", "min_ms": 80, "max_ms": 120}, 
                {"type": "release", "key_str": "Key.alt_l"}
            ],
            "아래점프": [
                {"type": "press", "key_str": "Key.down"}, {"type": "delay", "min_ms": 70, "max_ms": 120},
                {"type": "press", "key_str": "Key.alt_l"}, {"type": "delay", "min_ms": 40, "max_ms": 90},
                {"type": "release", "key_str": "Key.alt_l"}, {"type": "delay", "min_ms": 10, "max_ms": 50},
                {"type": "release", "key_str": "Key.down"}
            ],
            # [수정] 사다리타기 시퀀스의 점프키도 Key.alt_l 로 변경
            "사다리타기(우)": [
                {"type": "release_specific", "key_str": "Key.left"},
                {"type": "press", "key_str": "Key.right"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "press", "key_str": "Key.alt_l"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "release", "key_str": "Key.alt_l"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "release", "key_str": "Key.right"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "press", "key_str": "Key.up"}
            ],
            "사다리타기(좌)": [
                {"type": "release_specific", "key_str": "Key.right"},
                {"type": "press", "key_str": "Key.left"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "press", "key_str": "Key.alt_l"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "release", "key_str": "Key.alt_l"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "release", "key_str": "Key.left"}, {"type": "delay", "min_ms": 80, "max_ms": 120},
                {"type": "press", "key_str": "Key.up"}
            ],
            "오르기": [{"type": "press", "key_str": "Key.up"}],
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
        """FULL_KEY_MAP에서 UI 콤보박스에 표시할 그룹화된 문자열 리스트 생성"""
        
        # 1. 키를 타입별로 분류
        keys_by_type = {
            "주요 특수키": [], "방향키": [], "알파벳": [], "숫자": [],
            "기능키 (F1-F12)": [], "편집키": [], "수식키": []
        }
        
        for k in FULL_KEY_MAP.keys():
            key_str = ""
            if isinstance(k, str):
                if 'a' <= k <= 'z':
                    keys_by_type["알파벳"].append(k)
                elif '0' <= k <= '9':
                    keys_by_type["숫자"].append(k)
                continue # 그 외 문자열 키는 일단 제외
                
            elif isinstance(k, Key):
                name = k.name.replace('_l', '').replace('_r', '')
                key_str = f"Key.{name}"
                
                if name in ['up', 'down', 'left', 'right']:
                    keys_by_type["방향키"].append(key_str)
                elif name.startswith('f') and name[1:].isdigit():
                    keys_by_type["기능키 (F1-F12)"].append(key_str)
                elif name in ['insert', 'delete', 'home', 'end', 'page_up', 'page_down']:
                    keys_by_type["편집키"].append(key_str)
                elif name in ['space', 'enter', 'esc', 'tab', 'backspace']:
                    keys_by_type["주요 특수키"].append(key_str)
                elif name in ['ctrl', 'alt', 'shift', 'cmd']:
                    keys_by_type["수식키"].append(key_str)
        
        # 2. 각 그룹 내부 정렬
        # 기능키는 F1, F2, F10 순서가 되도록 숫자 기준으로 특별 정렬
        keys_by_type["기능키 (F1-F12)"].sort(key=lambda x: int(x.split('.')[1][1:]))
        keys_by_type["방향키"].sort()
        keys_by_type["알파벳"].sort()
        keys_by_type["숫자"].sort()
        
        # 3. 최종 리스트 생성 (그룹화 및 구분선 추가)
        final_key_list = []
        for group_name, key_list in keys_by_type.items():
            if key_list:
                if final_key_list: # 첫 그룹이 아니면 구분선 추가
                    final_key_list.append(f"─── {group_name} ───")
                final_key_list.extend(sorted(list(set(key_list))))
                
        return final_key_list

    def on_command_selected(self, current_item, previous_item):
        self.editor_group.setEnabled(False) 
        self.action_sequence_list.clear()
        if not current_item:
            return
        
        command_text = current_item.text()
        self._populate_action_sequence_list(command_text)

    def on_action_step_selected(self, current_item, previous_item):
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

    def randomize_delays(self):
        """선택된 명령 프로필의 모든 delay 액션에 랜덤성을 부여합니다."""
        command_item = self.command_list.currentItem()
        if not command_item:
            QMessageBox.warning(self, "알림", "지연 시간을 변경할 명령 프로필을 선택하세요.")
            return

        command_text = command_item.text()
        sequence = self.mappings.get(command_text, [])
        
        changed_count = 0
        for step in sequence:
            if step.get("type") == "delay":
                min_ms = step.get("min_ms", 0)
                max_ms = step.get("max_ms", 0)
                
                # 최소값은 20ms 빼고, 최대값은 20ms 더함
                new_min = max(0, min_ms - 20) # 음수가 되지 않도록 보장
                new_max = max_ms + 20
                
                step["min_ms"] = new_min
                step["max_ms"] = new_max
                changed_count += 1
        
        if changed_count > 0:
            # 변경된 내용을 UI에 즉시 반영
            self._populate_action_sequence_list(command_text)
            self.status_label.setText(f"'{command_text}' 프로필의 지연 시간 {changed_count}개를 랜덤화했습니다.")
        else:
            QMessageBox.information(self, "알림", "선택된 프로필에 지연(delay) 액션이 없습니다.")

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

    def copy_sequence_to_clipboard(self):
        """현재 선택된 명령 프로필의 액션 시퀀스를 JSON 문자열로 클립보드에 복사합니다."""
        command_item = self.command_list.currentItem()
        if not command_item:
            QMessageBox.warning(self, "알림", "복사할 명령 프로필을 선택하세요.")
            return

        command_text = command_item.text()
        sequence = self.mappings.get(command_text, [])

        if not sequence:
            QMessageBox.information(self, "알림", "선택된 프로필에 복사할 액션이 없습니다.")
            return

        try:
            # 보기 좋게 들여쓰기된 JSON 문자열로 변환
            sequence_text = json.dumps(sequence, indent=4, ensure_ascii=False)
            
            # PyQt의 클립보드 기능 사용
            clipboard = QApplication.clipboard()
            clipboard.setText(sequence_text)
            
            self.status_label.setText(f"'{command_text}' 시퀀스가 클립보드에 복사되었습니다.")
            print(f"--- 클립보드에 복사된 내용 ---\n{sequence_text}\n--------------------------")

        except Exception as e:
            QMessageBox.critical(self, "오류", f"클립보드 복사 중 오류가 발생했습니다:\n{e}")

    # --- 시리얼 통신 및 명령 실행 ---
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
        if not self.ser or not self.ser.is_open:
            return
        
        #  KEY_MAP 대신 FULL_KEY_MAP 사용
        key_code = FULL_KEY_MAP.get(key_object)
        if key_code is not None:
            try:
                self.ser.write(bytes([command, key_code]))
                # --- (신규) 전송 직후 타임스탬프 저장 (에코/리스너 무시에 사용) ---
                key_str_id = self._key_obj_to_str(key_object)  # 새로운 헬퍼 사용
                self.last_sent_timestamps[key_str_id] = time.time()  # 전송 시각 저장
            except serial.SerialException as e:
                print(f"[AutoControl] 데이터 전송 실패: {e}")
                self.connect_to_pi()

    def _press_key(self, key_object):
        """
        (수정) 실제로 전송이 발생했는지(True/False)를 반환하도록 변경.
        기존: 내부에서만 held_keys를 관리.
        """
        if key_object not in self.held_keys:
            self.held_keys.add(key_object)
            self._send_command(CMD_PRESS, key_object)
            return True    # 실제 전송이 발생했음을 알림
        return False       # 이미 눌려있어 전송하지 않음

    def _release_key(self, key_object):
        """
        (수정) 실제로 전송이 발생했는지(True/False)를 반환하도록 변경.
        """
        if key_object in self.held_keys:
            self.held_keys.discard(key_object)
            self._send_command(CMD_RELEASE, key_object)
            return True
        return False

    def _release_all_keys(self):
        for key_obj in list(self.held_keys): self._release_key(key_obj)

# [기능 추가] 테스트 종료 후 안전하게 모든 키를 떼는 슬롯
    @pyqtSlot()
    def _safe_release_all_keys(self):
        """테스트 종료 후 안전하게 모든 키를 떼고 상태를 업데이트하는 슬롯."""
        print("[AutoControl] All keys released automatically after test.")
        self._release_all_keys()
        self.status_label.setText("테스트 후 모든 키가 자동으로 해제되었습니다.")

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
        
        self.status_label.setText("2초 후 테스트를 시작합니다...")
        QTimer.singleShot(2000, lambda: self._start_sequence_execution(sequence, f"TEST: {command_text}", is_test=True))
    
    # --- [핵심 수정] time.sleep()을 QTimer 기반의 비동기 방식으로 변경 ---
    def _start_sequence_execution(self, sequence, command_name, is_test=False):
        """
        시퀀스 실행을 시작합니다. 이미 실행 중인 시퀀스가 있다면 중단합니다.
        """
        # [핵심 수정 1] 현재 실행 중인 명령과 동일한 명령이 들어오면 무시
        if self.is_sequence_running and self.current_command_name == command_name:
            if self.console_log_checkbox.isChecked():
                print(f"--- [AutoControl] 중복 명령 무시: '{command_name}' ---")
            return

        if self.is_sequence_running:
            self.sequence_timer.stop()
            # [핵심 수정 2] 무조건적인 _release_all_keys() 호출 제거
            if self.console_log_checkbox.isChecked():
                print(f"--- [AutoControl] 이전 시퀀스 중단: '{self.current_command_name}' ---")

        self.status_label.setText(f"'{command_name}' 실행 중...")
        if self.console_log_checkbox.isChecked():
            print(f"--- [AutoControl] 실행 시작: '{command_name}' ---")

        self.current_sequence = sequence
        self.current_command_name = command_name
        self.is_test_mode = is_test
        self.current_sequence_index = 0
        self.is_sequence_running = True
        self.is_first_key_event_in_sequence = True
        
        self._process_next_step()

    def _process_next_step(self):
        """
        시퀀스의 현재 단계를 처리하고, 다음 단계를 QTimer로 스케줄링합니다.
        -> 재진입 방지, 실제 전송 여부에 따른 로그 출력, 타이머 중복 start 방지 적용
        """
        # --- (신규) 재진입 방지 ---
        if getattr(self, "is_processing_step", False):
            if self.console_log_checkbox.isChecked():
                print("[AutoControl] 중복 스텝 처리 차단 (is_processing_step=True).")
            return
        self.is_processing_step = True

        try:
            if not self.is_sequence_running or self.current_sequence_index >= len(self.current_sequence):
                self.is_sequence_running = False
                
                log_msg = f"--- (완료) {self.current_command_name} ---"
                self.log_generated.emit(log_msg, "lightgreen")

                if self.is_test_mode:
                    self.action_sequence_list.clearSelection()
                    if self.held_keys:
                        self.status_label.setText("테스트 완료. 2초 후 모든 키를 해제합니다...")
                        if self.console_log_checkbox.isChecked():
                            print("[AutoControl] TEST END: Sequence left keys pressed. Releasing all in 2s.")
                        QTimer.singleShot(2000, self._safe_release_all_keys)
                    else:
                        self.status_label.setText(f"'{self.current_command_name}' 실행 완료.")
                else:
                    self.status_label.setText(f"'{self.current_command_name}' 실행 완료.")

                if self.console_log_checkbox.isChecked():
                    print(f"--- [AutoControl] 실행 완료: '{self.current_command_name}' ---")
                return

            step = self.current_sequence[self.current_sequence_index]
            if self.is_test_mode:
                self.action_sequence_list.setCurrentRow(self.current_sequence_index)

            action_type = step.get("type")
            delay_ms = 1

            is_key_event = action_type in ["press", "release", "release_specific", "release_all"]
            if is_key_event and self.is_first_key_event_in_sequence:
                log_msg = f"--- (시작) {self.current_command_name} ---"
                self.log_generated.emit(log_msg, "magenta")
                self.is_first_key_event_in_sequence = False

            if action_type in ["press", "release", "release_specific"]:
                key_obj = self._str_to_key_obj(step.get("key_str"))
                if not key_obj:
                    log_msg = f"오류: 알 수 없는 키 '{step.get('key_str')}'"
                    self.log_generated.emit(log_msg, "red")
                    if self.console_log_checkbox.isChecked(): print(f"  - {log_msg}")
                elif action_type == "press":
                    sent = self._press_key(key_obj)  # 이제 True/False 반환
                    # --- (수정) 실제 전송이 있었을 때만 '(누르기)' 로그 생성 ---
                    if sent:
                        self.log_generated.emit(f"(누르기) {self._translate_key_for_logging(step.get('key_str'))}", "white")
                        if self.console_log_checkbox.isChecked(): print(f"  - PRESS (SENT): {key_obj}")
                    else:
                        # 중복 전송 스킵 로그 (디버그용)
                        if self.console_log_checkbox.isChecked(): print(f"  - PRESS skipped (already held): {key_obj}")
                else:
                    released = self._release_key(key_obj)  # True/False 반환
                    if released:
                        self.log_generated.emit(f"(떼기) {self._translate_key_for_logging(step.get('key_str'))}", "white")
                        if self.console_log_checkbox.isChecked(): print(f"  - RELEASE (SENT): {key_obj}")
                    else:
                        if self.console_log_checkbox.isChecked(): print(f"  - RELEASE skipped (not held): {key_obj}")

            elif action_type == "delay":
                min_ms = step.get("min_ms", 0)
                max_ms = step.get("max_ms", 0)
                if min_ms >= max_ms:
                    delay_ms = min_ms
                else:
                    mean = (min_ms + max_ms) / 2
                    std_dev = (max_ms - min_ms) / 6
                    random_delay = random.gauss(mean, std_dev)
                    delay_ms = int(max(min(random_delay, max_ms), min_ms))
                if self.console_log_checkbox.isChecked():
                    print(f"  - DELAY: {delay_ms}ms (범위: {min_ms}~{max_ms}ms)")

            elif action_type == "release_all":
                # 항상 실제 릴리즈 시도 (내부에서 held_keys 기준으로 전송)
                self._release_all_keys()
                self.log_generated.emit("(모든 키 떼기)", "white")
                if self.console_log_checkbox.isChecked(): print("  - RELEASE_ALL_KEYS")

            # --- 다음 스텝 예약: 기존 타이머 안전하게 멈추고 시작 ---
            self.current_sequence_index += 1
            try:
                self.sequence_timer.stop()    # 기존 타이머 중지 (중복 start 방지)
            except Exception:
                pass
            self.sequence_timer.start(delay_ms)
        finally:
            self.is_processing_step = False


    @pyqtSlot(str)
    def receive_control_command(self, command_text):

        sequence = self.mappings.get(command_text)
        if not sequence:
            print(f"[AutoControl] 경고: '{command_text}'에 대한 매핑이 없습니다.")
            return
        
        # is_test 인자를 False로 하여 실행 시작
        self._start_sequence_execution(sequence, command_text, is_test=False)
        
    def toggle_recording(self):
        if self.is_recording or self.is_waiting_for_start_key:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if not self.command_list.currentItem():
            QMessageBox.warning(self, "알림", "녹화할 명령 프로필을 먼저 선택하세요.")
            self.record_btn.setChecked(False)
            return
        
        self.recorded_sequence = []
        self.last_event_time = 0 #  0으로 초기화하는 것은 유지
        
        #  녹화 시작 시 눌린 키 상태 초기화
        self.currently_pressed_keys_for_recording.clear()
        
        self.start_key_str = self.start_key_combo.currentText()
        self.stop_key_str = self.stop_key_combo.currentText()
        
        self.keyboard_listener = Listener(on_press=self._on_press, on_release=self._on_release)
        self.keyboard_listener.start()
        
        if self.start_key_str != "없음":
            self.is_waiting_for_start_key = True
            self.recording_status_changed.emit(f"'{self.start_key_str}' 키를 눌러 녹화를 시작하세요...")
        else:
            self.is_recording = True
            #  녹화가 즉시 시작되면, last_event_time을 현재 시간으로 설정
            self.last_event_time = time.time()
            self.reset_auto_stop_timer_signal.emit()
            self.recording_status_changed.emit(f"녹화 중... ({self.auto_stop_spin.value()}ms 동안 입력 없으면 자동 종료)")
        
        self.record_btn.setText(" 녹화 중단")

    @pyqtSlot()
    def stop_recording(self):
        if not self.is_recording and not self.is_waiting_for_start_key:
            return

        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None
        
        self.auto_stop_timer.stop()
        self.is_recording = False
        self.is_waiting_for_start_key = False
        
        command_item = self.command_list.currentItem()
        if command_item and self.recorded_sequence:
            command_text = command_item.text()
            self.mappings[command_text] = self.recorded_sequence
            self._populate_action_sequence_list(command_text)
            self.recording_status_changed.emit("녹화 완료. '매핑 저장'을 눌러주세요.")
        else:
            self.recording_status_changed.emit("녹화가 중단되었습니다.")
            
        self.record_btn.setChecked(False)
        self.record_btn.setText(" 녹화")

    def _key_to_str(self, key):
        if isinstance(key, Key): return f"Key.{key.name}"
        return key.char if hasattr(key, 'char') else 'N/A'

    def _key_obj_to_str(self, key_obj):
        """(신규) key object -> 일관된 문자열 표현으로 변환 (예: 'Key.alt_l' 또는 'a')"""
        from pynput.keyboard import Key
        if isinstance(key_obj, Key):
            return f"Key.{key_obj.name}"
        return str(key_obj)

    def _on_press(self, key):
        key_str = self._key_to_str(key)
        
        if self.is_waiting_for_start_key:
            if key_str == self.start_key_str:
                self.is_waiting_for_start_key = False
                self.is_recording = True
                self.last_event_time = time.time()
                self.reset_auto_stop_timer_signal.emit()
                self.recording_status_changed.emit(f"녹화 시작! ('{self.stop_key_str}'로 종료)")
            return

        if self.is_recording:
            # [핵심 수정] 시퀀스 기록 여부와 상관없이, 키 이벤트가 발생하면 무조건 타이머를 리셋
            self.reset_auto_stop_timer_signal.emit()

            # 키 반복 이벤트는 시퀀스에 기록하지 않고 무시
            if key_str in self.currently_pressed_keys_for_recording:
                return
            
            # 새로운 키 입력이므로 상태 집합과 시퀀스에 추가
            self.currently_pressed_keys_for_recording.add(key_str)

            now = time.time()
            if self.last_event_time > 0:
                delay_ms = int((now - self.last_event_time) * 1000)
                if delay_ms > 0: 
                    self.recorded_sequence.append({"type": "delay", "min_ms": delay_ms, "max_ms": delay_ms})
            
            self.recorded_sequence.append({"type": "press", "key_str": key_str})
            self.last_event_time = now
            
            if key_str == self.stop_key_str:
                self.recording_status_changed.emit("종료 키 입력됨. 녹화를 중단합니다.")
                self.stop_recording_signal.emit()

    def _on_release(self, key):
        key_str = self._key_to_str(key)

        if self.is_recording:
            # [핵심 수정] 시퀀스 기록 여부와 상관없이, 키 이벤트가 발생하면 무조건 타이머를 리셋
            self.reset_auto_stop_timer_signal.emit()

            # 키를 떼었으므로 상태 집합에서 제거
            self.currently_pressed_keys_for_recording.discard(key_str)

            now = time.time()
            delay_ms = int((now - self.last_event_time) * 1000)
            if delay_ms > 0: 
                self.recorded_sequence.append({"type": "delay", "min_ms": delay_ms, "max_ms": delay_ms})
            
            self.recorded_sequence.append({"type": "release", "key_str": key_str})
            self.last_event_time = now


    @pyqtSlot()
    def _handle_reset_auto_stop_timer(self):
        self.auto_stop_timer.start(self.auto_stop_spin.value())

    @pyqtSlot(str)
    def update_status_label(self, text):
        self.status_label.setText(text)

    #  전역 키보드 리스너 관련 메소드들
    def start_global_listener(self):
        if self.global_listener is None:
            try:
                self.global_listener = Listener(on_press=self._on_global_press, on_release=self._on_global_release)
                self.global_listener.start()
            except Exception as e:
                print(f"[AutoControl] 전역 키보드 리스너 시작 실패: {e}")

    #  MapTab의 탐지 상태를 수신하는 슬롯
    @pyqtSlot(bool)
    @pyqtSlot(bool)
    def update_map_detection_status(self, is_running):
        self.is_map_detection_running = is_running
        self.detection_button.setChecked(is_running)
        self.detection_button.setText("탐지 중단" if is_running else "탐지 시작")
        
        # [수정] 탐지 상태가 변경될 때마다 리스너 상태를 업데이트하도록 호출
        self._update_global_listener_state()

        if not is_running:
            # 탐지가 중지되면 눌린 키 상태를 확실히 초기화
            self.globally_pressed_keys.clear()

    def _on_global_press(self, key):
        key_str = self._key_to_str(key)

        # --- (신규) 우리가 직전에 보낸 키의 '에코'라면 무시 ---
        last_sent = self.last_sent_timestamps.get(key_str, 0)
        if time.time() - last_sent < 0.06:   # 60ms 이내면 '자체 전송의 에코'로 간주하여 무시
            if self.console_log_checkbox.isChecked():
                print(f"[AutoControl] Global press ignored (echo) for {key_str}")
            return

        if key_str in self.globally_pressed_keys:
            return

        self.globally_pressed_keys.add(key_str)
        friendly_key_name = self._translate_key_for_logging(key_str)
        self.log_generated.emit(f"(누르기) {friendly_key_name}", "white")

    def _on_global_release(self, key):
        key_str = self._key_to_str(key)

        # --- (신규) 에코 무시 (release도 동일하게 처리) ---
        last_sent = self.last_sent_timestamps.get(key_str, 0)
        if time.time() - last_sent < 0.06:
            if self.console_log_checkbox.isChecked():
                print(f"[AutoControl] Global release ignored (echo) for {key_str}")
            return

        self.globally_pressed_keys.discard(key_str)
        friendly_key_name = self._translate_key_for_logging(key_str)
        self.log_generated.emit(f"(떼기) {friendly_key_name}", "white")

    #  모든 로그를 처리하는 통합 슬롯
    @pyqtSlot(str, str)
    def _add_log_entry(self, message, color_str):
        if not self.log_checkbox.isChecked():
            return

        now = time.time()
        
        # [신규] 이전 로그와의 시간차 계산 및 문자열 생성
        delta_text = ""
        if self.last_log_time > 0:
            delta_ms = int((now - self.last_log_time) * 1000)
            delta_text = f" (Δ {delta_ms}ms)"

        if self.last_log_time > 0 and (now - self.last_log_time) > 5:
            separator_item = QListWidgetItem("──────────")
            separator_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            separator_item.setForeground(QColor("#888"))
            self.key_log_list.addItem(separator_item)
        
        timestamp = datetime.now().strftime("%H:%M:%S:%f")[:-3]
        # [수정] 로그 메시지에 시간차 정보 추가
        log_text = f"[{timestamp}] {message}{delta_text}"
        
        item = QListWidgetItem(log_text)
        item.setForeground(QColor(color_str))
        self.key_log_list.addItem(item)
        
        if self.key_log_list.count() > 200:
            self.key_log_list.takeItem(0)
            
        self.key_log_list.scrollToBottom()
        self.last_log_time = now

    @pyqtSlot(str, str)
    def _add_key_log_entry(self, action, key_name):
        # HH:MM:SS:ms 형식으로 타임스탬프 생성
        timestamp = datetime.now().strftime("%H:%M:%S:%f")[:-3]
        log_text = f"[{timestamp}] ({action}) {key_name}"
        
        item = QListWidgetItem(log_text)
        self.key_log_list.addItem(item)
        
        # 로그가 200줄을 넘어가면 가장 오래된 로그를 삭제하여 메모리 관리
        if self.key_log_list.count() > 200:
            self.key_log_list.takeItem(0)
            
        # 항상 최신 로그가 보이도록 스크롤
        self.key_log_list.scrollToBottom()

    @pyqtSlot(str)
    def _add_execution_log_entry(self, log_message):
        """시퀀스 실행 로그를 타임스탬프와 함께 GUI에 추가합니다."""
        timestamp = datetime.now().strftime("%H:%M:%S:%f")[:-3]
        full_log = f"[{timestamp}] {log_message}"
        
        item = QListWidgetItem(full_log)
        # 실행 로그는 다른 색상으로 구분 (예: 파란색)
        item.setForeground(Qt.GlobalColor.cyan)
        self.key_log_list.addItem(item)
        
        if self.key_log_list.count() > 200:
            self.key_log_list.takeItem(0)
            
        self.key_log_list.scrollToBottom()

    def _translate_key_for_logging(self, key_str):
        translation_map = {
            'Key.right': '→', 'Key.left': '←', 'Key.down': '↓', 'Key.up': '↑',
            'Key.space': 'Space', 'Key.enter': 'Enter', 'Key.esc': 'Esc',
            'Key.ctrl_l': 'Ctrl_L', 'Key.ctrl_r': 'Ctrl_R', 'Key.ctrl': 'Ctrl',
            'Key.alt_l': 'Alt_L', 'Key.alt_r': 'Alt_R', 'Key.alt': 'Alt',
            'Key.shift_l': 'Shift_L', 'Key.shift_r': 'Shift_R', 'Key.shift': 'Shift',
            'Key.cmd': 'Win', 'Key.cmd_l': 'Win_L', 'Key.cmd_r': 'Win_R',
            'Key.tab': 'Tab', 'Key.backspace': 'Backspace',
        }
        # 맵에 키가 있으면 변환된 값을, 없으면 원래 값을 반환
        return translation_map.get(key_str, key_str)

    def cleanup_on_close(self):
        print("'자동 제어' 탭 정리 중...")
        self.is_sequence_running = False
        self.sequence_timer.stop()
        
        # 녹화용 리스너 중지
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        
        # [수정] 전역 키 로깅용 리스너를 안전하게 중지
        if self.global_listener:
            self.global_listener.stop()
            self.global_listener = None

        if self.ser and self.ser.is_open:
            self._release_all_keys()
            time.sleep(0.1)
            self.ser.close()
            print("시리얼 포트 연결을 해제했습니다.")