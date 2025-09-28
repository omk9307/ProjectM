# auto_control.py

import serial
import time
import json
import os
import random
import copy
from collections import defaultdict
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QSpinBox, QMessageBox, QFrame, QCheckBox,
    QListWidgetItem, QInputDialog, QAbstractItemView, QTabWidget, QFileDialog,
    QGridLayout
)
from PyQt6.QtCore import pyqtSlot, Qt, QTimer, pyqtSignal, QMimeData, QSize, QSettings
from PyQt6.QtGui import QIcon, QColor
from pynput.keyboard import Key, Listener
from datetime import datetime

# --- 설정 및 상수 ---
SERIAL_PORT = 'COM6'
BAUD_RATE = 115200
CMD_PRESS = 0x01
CMD_RELEASE = 0x02
BASE_DIR = Path(__file__).resolve().parents[1]

#  모든 키의 표준 HID 코드를 담는 통합 맵
FULL_KEY_MAP = {
    'a': 4, 'b': 5, 'c': 6, 'd': 7, 'e': 8, 'f': 9, 'g': 10, 'h': 11, 'i': 12, 'j': 13, 'k': 14, 'l': 15, 'm': 16, 'n': 17, 'o': 18, 'p': 19, 'q': 20, 'r': 21, 's': 22, 't': 23, 'u': 24, 'v': 25, 'w': 26, 'x': 27, 'y': 28, 'z': 29,
    '1': 30, '2': 31, '3': 32, '4': 33, '5': 34, '6': 35, '7': 36, '8': 37, '9': 38, '0': 39,
    Key.enter: 40, Key.esc: 41, Key.backspace: 42, Key.tab: 43, Key.space: 44,
    Key.insert: 73, Key.delete: 76, Key.home: 74, Key.end: 77,
    Key.page_up: 75, Key.page_down: 78,
    Key.right: 79, Key.left: 80, Key.down: 81, Key.up: 82,
    # 수식 키(Modifier)들의 표준 HID 코드를 추가
    Key.ctrl: 224, Key.ctrl_l: 224,
    Key.shift: 225, Key.shift_l: 225,
    Key.alt: 226, Key.alt_l: 226,
    Key.cmd: 227, Key.cmd_l: 227, # Windows Key
    Key.shift_r: 229,
    Key.alt_r: 230,
    Key.cmd_r: 231,
}


class _VisualKey(QLabel):
    """시각화용 키 한 개를 표현한다."""

    _BASE_STYLE = (
        "padding: 6px 12px; border: 1px solid #7fa3d4; border-radius: 8px;"
        "background-color: #f5f8ff; color: #1f2330; font-weight: 600;"
    )
    _PRESSED_STYLE = (
        "padding: 6px 12px; border: 2px solid #2456a6; border-radius: 8px;"
        "background-color: #2f6fd1; color: white; font-weight: 700;"
    )

    def __init__(self, label_text: str, key_aliases: tuple[str, ...], parent=None):
        super().__init__(label_text, parent)
        self.key_aliases = key_aliases
        self._pressed = False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(52)
        self.setFixedHeight(36)
        self.setStyleSheet(self._BASE_STYLE)

    def set_pressed(self, pressed: bool) -> None:
        if self._pressed == pressed:
            return
        self._pressed = pressed
        self.setStyleSheet(self._PRESSED_STYLE if pressed else self._BASE_STYLE)


class KeyboardVisualizer(QWidget):
    """주요 이동·수식·편집 키 상태를 카드 형태로 표시한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key_to_widget: dict[str, _VisualKey] = {}
        self._visual_keys: list[_VisualKey] = []
        self._init_layout()

    def _init_layout(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(18)

        # 좌측: 수식키 + 예제 문자 키
        modifier_column = QVBoxLayout()
        modifier_column.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        shift_key = self._create_key("Shift", ("Key.shift", "Key.shift_l", "Key.shift_r"))
        shift_key.setMinimumWidth(94)
        z_key = self._create_key("Z", ("z",))
        top_row.addWidget(shift_key)
        top_row.addWidget(z_key)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        ctrl_key = self._create_key("Ctrl", ("Key.ctrl", "Key.ctrl_l", "Key.ctrl_r"))
        alt_key = self._create_key("Alt", ("Key.alt", "Key.alt_l", "Key.alt_r"))
        bottom_row.addWidget(ctrl_key)
        bottom_row.addWidget(alt_key)

        modifier_column.addLayout(top_row)
        modifier_column.addLayout(bottom_row)
        layout.addLayout(modifier_column)

        # 우측: 편집 키 + 방향키 블록
        right_column = QVBoxLayout()
        right_column.setSpacing(12)

        edit_grid = QGridLayout()
        edit_grid.setHorizontalSpacing(8)
        edit_grid.setVerticalSpacing(6)
        insert_key = self._create_key("Insert", ("Key.insert",))
        home_key = self._create_key("Home", ("Key.home",))
        pg_up_key = self._create_key("Pg Up", ("Key.page_up",))
        delete_key = self._create_key("Delete", ("Key.delete",))
        end_key = self._create_key("End", ("Key.end",))
        pg_dn_key = self._create_key("Pg Dn", ("Key.page_down",))
        for row, widgets in enumerate(((insert_key, home_key, pg_up_key), (delete_key, end_key, pg_dn_key))):
            for col, widget in enumerate(widgets):
                edit_grid.addWidget(widget, row, col)

        right_column.addLayout(edit_grid)

        arrow_grid = QGridLayout()
        arrow_grid.setHorizontalSpacing(8)
        arrow_grid.setVerticalSpacing(6)
        up_key = self._create_key("↑", ("Key.up",))
        left_key = self._create_key("←", ("Key.left",))
        down_key = self._create_key("↓", ("Key.down",))
        right_key = self._create_key("→", ("Key.right",))
        arrow_grid.addWidget(up_key, 0, 1)
        arrow_grid.addWidget(left_key, 1, 0)
        arrow_grid.addWidget(down_key, 1, 1)
        arrow_grid.addWidget(right_key, 1, 2)

        right_column.addLayout(arrow_grid)
        layout.addLayout(right_column)

        layout.addStretch(1)

    def _create_key(self, label: str, aliases: tuple[str, ...]) -> _VisualKey:
        widget = _VisualKey(label, aliases, self)
        self._visual_keys.append(widget)
        for alias in aliases:
            self._key_to_widget[alias] = widget
        return widget

    def update_key_state(self, key_name: str, pressed: bool) -> None:
        widget = self._key_to_widget.get(key_name)
        if widget is None and key_name.lower() != key_name:
            widget = self._key_to_widget.get(key_name.lower())
        if widget is None:
            return
        widget.set_pressed(pressed)

    def reset(self) -> None:
        for widget in self._visual_keys:
            widget.set_pressed(False)

CATEGORY_NAMES = ("이동", "스킬", "기타", "이벤트")
SKILL_CATEGORY_NAME = "스킬"

PROFILE_MIME_TYPE = "application/x-autocontrol-profile"

CATEGORY_KEYWORDS = {
    "스킬": ["스킬", "skill", "버프", "필살", "텔레포트", "teleport", "공격", "strike", "slash"],
    "이벤트": ["이벤트", "event", "퀘스트", "quest"],
    "기타": ["기타", "other", "포션", "물약", "아이템", "item", "설정", "config"],
}


def _resolve_key_mappings_path():
    legacy_relative = Path(os.path.join('Project_Maple', 'workspace', 'config', 'key_mappings.json'))
    module_workspace = Path(__file__).resolve().parents[1] / 'workspace' / 'config' / 'key_mappings.json'
    workspace_relative = Path('workspace') / 'config' / 'key_mappings.json'

    candidates = [
        legacy_relative,
        Path.cwd() / legacy_relative,
        module_workspace,
        workspace_relative,
        Path.cwd() / workspace_relative,
    ]

    for candidate in candidates:
        try:
            candidate_path = candidate if candidate.is_absolute() else (Path.cwd() / candidate)
            if candidate_path.is_file():
                return candidate_path.resolve()
        except OSError:
            continue

    fallback = candidates[1] if len(candidates) > 1 else module_workspace
    fallback_path = fallback if fallback.is_absolute() else (Path.cwd() / fallback)
    return fallback_path.resolve()


KEY_MAPPINGS_FILE = _resolve_key_mappings_path()

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


class CommandProfileListWidget(QListWidget):
    def __init__(self, category, parent=None):
        super().__init__(parent)
        self.category = category
        self.parent_tab = parent
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.itemChanged.connect(self._on_item_changed)

    def mimeTypes(self):
        return [PROFILE_MIME_TYPE]

    def mimeData(self, items):
        names = [item.text() for item in items if item]
        mime_data = QMimeData()
        mime_data.setData(PROFILE_MIME_TYPE, json.dumps(names, ensure_ascii=False).encode('utf-8'))
        return mime_data

    def _on_item_changed(self, item):
        if self.parent_tab is None or item is None:
            return
        self.parent_tab.handle_profile_item_changed(self.category, item)


class CommandCategoryTabWidget(QTabWidget):
    profileDropped = pyqtSignal(list, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(PROFILE_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(PROFILE_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(PROFILE_MIME_TYPE):
            try:
                data = event.mimeData().data(PROFILE_MIME_TYPE)
                names = json.loads(bytes(data).decode('utf-8'))
            except (ValueError, json.JSONDecodeError):
                names = []
            valid_names = []
            seen = set()
            for name in names:
                if isinstance(name, str) and name not in seen:
                    seen.add(name)
                    valid_names.append(name)
            if not valid_names:
                event.ignore()
                return

            tab_index = self.tabBar().tabAt(event.position().toPoint())
            if tab_index < 0:
                event.ignore()
                return

            target_widget = self.widget(tab_index)
            category = getattr(target_widget, 'category', None)
            if not category:
                event.ignore()
                return

            self.profileDropped.emit(valid_names, category)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction


class AutoControlTab(QWidget):
    recording_status_changed = pyqtSignal(str)
    reset_auto_stop_timer_signal = pyqtSignal()
    stop_recording_signal = pyqtSignal()
    log_generated = pyqtSignal(str, str)
    request_detection_toggle = pyqtSignal()
    sequence_completed = pyqtSignal(str, object, bool)
    command_profile_renamed = pyqtSignal(str, str)
    keyboard_state_changed = pyqtSignal(str, bool)
    keyboard_state_reset = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.settings = QSettings("Gemini Inc.", "Maple AI Trainer")
        saved_visual_enabled = self.settings.value("auto_control/keyboard_visual_enabled", None)
        if saved_visual_enabled is None:
            self.keyboard_visual_enabled = True
        elif isinstance(saved_visual_enabled, bool):
            self.keyboard_visual_enabled = saved_visual_enabled
        else:
            self.keyboard_visual_enabled = str(saved_visual_enabled).lower() == "true"
        self.keyboard_visual_checkbox = None
        self.keyboard_visual_widget = None
        self.ser = None
        self.held_keys = set()
        self.mappings = {}
        self.profile_categories = {}
        self.category_overrides = set()
        self.parallel_profile_flags = {}
        self.key_list_str = self._generate_key_list()
        self.active_category = CATEGORY_NAMES[0]
        self.category_lists = {}
        self.command_tab_widget = None
        self._is_syncing_selection = False
        self.key_mappings_path = KEY_MAPPINGS_FILE

        # --- 녹화 관련 변수 ---
        self.is_recording = False
        self.is_waiting_for_start_key = False
        self.keyboard_listener = None
        self.recorded_sequence = []
        self._sequence_clipboard_cache = None
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
        self.current_command_reason = None
        self.is_test_mode = False

        self.is_processing_step = False                 # 중복 _process_next_step 재진입 방지 플래그
        self.last_sent_timestamps = {}                  # 전송한 키의 타임스탬프 (에코 무시용)
        self.ECHO_IGNORE_MS = 30                        # 기본 30ms, 필요하면 40~120 범위로 조절 권장
        self.last_command_start_time = 0.0              # 마지막 시퀀스 시작 시각
        self.sequence_watchdog = QTimer(self)           # 시퀀스가 멈추는 경우 복구용 와치독
        self.sequence_watchdog.setSingleShot(True)
        self.sequence_watchdog.timeout.connect(self._on_sequence_stuck)  # stuck 시 복구 시도
        self.SEQUENCE_STUCK_TIMEOUT_MS = 5000           # 와치독 기본 시간 (조정 가능)
        self.is_map_detection_running = False
        self.last_log_time = 0.0

        self.SEQUENTIAL_OWNER = "__sequential__"
        self.global_key_counts = defaultdict(int)
        self.sequence_owned_keys = {self.SEQUENTIAL_OWNER: self.held_keys}
        self.active_parallel_sequences = {}

        self.globally_pressed_keys = set()
        self.global_listener = None
        
        self.init_ui()
        self._apply_initial_keyboard_visual_state()
        self.load_mappings()
        self.connect_to_pi()

        # --- 시그널/슬롯 연결 ---
        self.recording_status_changed.connect(self.update_status_label)
        self.reset_auto_stop_timer_signal.connect(self._handle_reset_auto_stop_timer)
        self.stop_recording_signal.connect(self.stop_recording)
        self.log_generated.connect(self._add_log_entry)
        self.keyboard_state_changed.connect(self._handle_keyboard_state_change)
        self.keyboard_state_reset.connect(self._handle_keyboard_state_reset)
      
        self.setStyleSheet("""
            QFrame { border: 1px solid #444; border-radius: 5px; }
            QLabel#TitleLabel { font-size: 13px; font-weight: bold; padding: 5px; background-color: #3a3a3a; color: white; border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QGroupBox { font-size: 12px; font-weight: bold; }
            QPushButton { padding: 4px; }
            QPushButton:checked { background-color: #c62828; color: white; border: 1px solid #999; }
        """)

    def _parallel_owner(self, command_name: str) -> str:
        return f"parallel::{command_name}"

    def _notify_sequence_completed(self, success):
        command_name = self.current_command_name
        if command_name:
            try:
                self.sequence_completed.emit(command_name, self.current_command_reason, success)
            except Exception:
                pass
        self.current_command_name = ""
        self.current_command_reason = None
        self.current_sequence = []
        self.current_sequence_index = 0
        self.is_sequence_running = False
        self.is_processing_step = False
        self.is_test_mode = False

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
        cmd_title_layout = QHBoxLayout()
        cmd_title = QLabel("명령 프로필"); cmd_title.setObjectName("TitleLabel")
        load_btn = QPushButton(QIcon.fromTheme("document-open"), " 불러오기")
        load_btn.clicked.connect(self.prompt_load_mappings)
        cmd_title_layout.addWidget(cmd_title)
        cmd_title_layout.addStretch()
        cmd_title_layout.addWidget(load_btn)
        cmd_group_layout.addLayout(cmd_title_layout)
        
        self.command_tab_widget = CommandCategoryTabWidget(self)
        self.command_tab_widget.currentChanged.connect(self._on_category_tab_changed)
        self.command_tab_widget.profileDropped.connect(self.handle_profile_drop)
        for category in CATEGORY_NAMES:
            list_widget = CommandProfileListWidget(category, self)
            list_widget.currentItemChanged.connect(lambda curr, prev, cat=category: self.on_command_selected(curr, prev, cat))
            self.category_lists[category] = list_widget
            self.command_tab_widget.addTab(list_widget, category)

        self.command_list = self.category_lists[self.active_category]
        cmd_group_layout.addWidget(self.command_tab_widget)

        cmd_buttons_layout = QHBoxLayout()
        add_cmd_btn = QPushButton(QIcon.fromTheme("list-add"), "추가"); add_cmd_btn.clicked.connect(self.add_command_profile)
        remove_cmd_btn = QPushButton(QIcon.fromTheme("list-remove"), "삭제"); remove_cmd_btn.clicked.connect(self.remove_command_profile)
        rename_cmd_btn = QPushButton(QIcon.fromTheme("edit-rename"), "이름변경"); rename_cmd_btn.clicked.connect(self.rename_command_profile)
        randomize_btn = QPushButton(QIcon.fromTheme("view-refresh"), "랜덤"); randomize_btn.clicked.connect(self.randomize_delays)

        for btn in (add_cmd_btn, remove_cmd_btn, rename_cmd_btn, randomize_btn):
            btn.setIconSize(QSize(14, 14))
            btn.setFixedWidth(88)

        cmd_buttons_layout.addWidget(add_cmd_btn)
        cmd_buttons_layout.addWidget(remove_cmd_btn)
        cmd_buttons_layout.addWidget(rename_cmd_btn)
        cmd_buttons_layout.addWidget(randomize_btn)
        cmd_buttons_layout.addStretch(1)
        cmd_group_layout.addLayout(cmd_buttons_layout)
        top_h_layout.addLayout(cmd_group_layout, 2)

        # --- 시퀀스 편집기 ---
        seq_group_layout = QVBoxLayout()
        
        #  제목과 복사 버튼을 한 줄에 배치
        seq_title_layout = QHBoxLayout()
        seq_title = QLabel("액션 시퀀스"); seq_title.setObjectName("TitleLabel")
        copy_seq_btn = QPushButton(QIcon.fromTheme("edit-copy"), " 복사")
        copy_seq_btn.clicked.connect(self.copy_sequence_to_clipboard)
        paste_seq_btn = QPushButton(QIcon.fromTheme("edit-paste"), " 붙여넣기")
        paste_seq_btn.clicked.connect(self.paste_sequence_from_clipboard)
        seq_title_layout.addWidget(seq_title)
        seq_title_layout.addStretch()
        seq_title_layout.addWidget(copy_seq_btn)
        seq_title_layout.addWidget(paste_seq_btn)
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
        self.keyboard_visual_group = self._create_keyboard_visual_panel()
        main_v_layout.addWidget(self.keyboard_visual_group)
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

    def _create_keyboard_visual_panel(self):
        group = QGroupBox()
        group.setTitle("")
        outer_layout = QVBoxLayout(group)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        title_label = QLabel("실시간 키보드")
        title_label.setObjectName("TitleLabel")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.keyboard_visual_checkbox = QCheckBox("활성화")
        self.keyboard_visual_checkbox.toggled.connect(self._on_keyboard_visual_checkbox_toggled)
        self.keyboard_visual_checkbox.blockSignals(True)
        self.keyboard_visual_checkbox.setChecked(self.keyboard_visual_enabled)
        self.keyboard_visual_checkbox.blockSignals(False)
        header_layout.addWidget(self.keyboard_visual_checkbox)

        outer_layout.addLayout(header_layout)

        self.keyboard_visual_widget = KeyboardVisualizer(self)
        self.keyboard_visual_widget.setEnabled(self.keyboard_visual_checkbox.isChecked())
        outer_layout.addWidget(self.keyboard_visual_widget)

        return group

    def _create_right_panel(self):
        right_widget = QFrame()
        right_layout = QVBoxLayout(right_widget)
        
        header_layout = QHBoxLayout()
        title = QLabel("실시간 로그")
        title.setObjectName("TitleLabel")
        
        self.log_checkbox = QCheckBox("입력 감지")
        self.log_checkbox.setChecked(True)
        self.log_checkbox.toggled.connect(self._update_global_listener_state)

        self.log_persist_checkbox = QCheckBox("저장 모드")
        self.log_persist_checkbox.setChecked(False)
        
        self.console_log_checkbox = QCheckBox("상세 콘솔 로그")
        self.console_log_checkbox.setChecked(False)
        
        clear_log_btn = QPushButton(QIcon.fromTheme("edit-clear"), "로그 지우기")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.log_checkbox)
        header_layout.addWidget(self.log_persist_checkbox)
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
        visual_enabled = bool(self.keyboard_visual_checkbox.isChecked()) if self.keyboard_visual_checkbox else False
        should_listen = (self.is_map_detection_running and self.log_checkbox.isChecked()) or visual_enabled

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
            self.keyboard_state_reset.emit()
            if self.console_log_checkbox.isChecked():
                print("[AutoControl] 전역 키보드 리스너를 중지합니다.")

    def _apply_initial_keyboard_visual_state(self):
        if not self.keyboard_visual_checkbox or not self.keyboard_visual_widget:
            return
        checked = self.keyboard_visual_checkbox.isChecked()
        self.keyboard_visual_enabled = checked
        self.keyboard_visual_widget.setEnabled(checked)
        self.keyboard_visual_widget.reset()
        if checked:
            self._sync_keyboard_visual_state()
        if hasattr(self, "log_checkbox"):
            self._update_global_listener_state()

    def _on_keyboard_visual_checkbox_toggled(self, checked: bool):
        checked = bool(checked)
        if self.keyboard_visual_enabled != checked:
            self.keyboard_visual_enabled = checked
            self.settings.setValue("auto_control/keyboard_visual_enabled", checked)
        if self.keyboard_visual_widget:
            self.keyboard_visual_widget.setEnabled(checked)
            if checked:
                self._sync_keyboard_visual_state()
            else:
                self.keyboard_state_reset.emit()
        self._update_global_listener_state()

    def _sync_keyboard_visual_state(self):
        if not self.keyboard_visual_widget or not self.keyboard_visual_checkbox or not self.keyboard_visual_checkbox.isChecked():
            return
        active_keys = set(self.globally_pressed_keys)
        active_keys.update(self.currently_pressed_keys_for_recording)
        self.keyboard_visual_widget.reset()
        for key_str in active_keys:
            self.keyboard_visual_widget.update_key_state(key_str, True)

    @pyqtSlot(str, bool)
    def _handle_keyboard_state_change(self, key_str: str, pressed: bool):
        if not self.keyboard_visual_checkbox or not self.keyboard_visual_checkbox.isChecked():
            return
        if not self.keyboard_visual_widget:
            return
        self.keyboard_visual_widget.update_key_state(key_str, pressed)

    @pyqtSlot()
    def _handle_keyboard_state_reset(self):
        if not self.keyboard_visual_widget:
            return
        self.keyboard_visual_widget.reset()

    def load_mappings(self):
        if self._load_mappings_from_path(self.key_mappings_path):
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"'{self.key_mappings_path.name}' 매핑을 불러왔습니다.")
        else:
            self._stop_all_parallel_sequences(forced=True)
            self.mappings = self.create_default_mappings()
            self.category_overrides.clear()
            self.parallel_profile_flags = {name: False for name in self.mappings}
            self._ensure_profile_categories()
            self.populate_command_list()
            if hasattr(self, 'status_label'):
                self.status_label.setText("기본 매핑을 불러왔습니다.")

    def prompt_load_mappings(self):
        start_dir = str(self.key_mappings_path.parent) if self.key_mappings_path and self.key_mappings_path.exists() else str(Path.cwd())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "키 매핑 불러오기",
            start_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return

        if self._load_mappings_from_path(file_path):
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"'{Path(file_path).name}' 매핑을 불러왔습니다.")
        else:
            QMessageBox.warning(self, "불러오기 실패", "선택한 파일에서 매핑을 불러올 수 없습니다. JSON 구조를 확인해주세요.")

    def _ensure_profile_categories(self, categories=None, overrides=None):
        if not isinstance(categories, dict):
            categories = {}

        if overrides is None:
            overrides = getattr(self, 'category_overrides', set())
        if not isinstance(overrides, (set, list, tuple)):
            overrides = set()
        else:
            overrides = set(overrides)

        valid_categories = set(CATEGORY_NAMES)
        if not isinstance(self.mappings, dict):
            self.mappings = {}

        updated_overrides = set()
        self.profile_categories = {}
        for name in self.mappings.keys():
            category = categories.get(name)
            if category not in valid_categories:
                category = CATEGORY_NAMES[0]
            self.profile_categories[name] = category
            if name in overrides:
                updated_overrides.add(name)
            if name not in getattr(self, 'parallel_profile_flags', {}):
                self.parallel_profile_flags[name] = False

        self.category_overrides = updated_overrides

    def save_mappings(self):
        try:
            self._ensure_profile_categories(self.profile_categories, self.category_overrides)

            categories_to_save = {
                name: self.profile_categories.get(name, CATEGORY_NAMES[0])
                for name in self.mappings.keys()
            }
            meta_to_save = {
                'category_overrides': sorted(self.category_overrides),
            }
            parallel_to_save = {
                name: bool(self.parallel_profile_flags.get(name, False))
                for name in self.mappings.keys()
            }
            data_to_save = {
                '_meta': meta_to_save,
                '_categories': categories_to_save,
                '_parallel': parallel_to_save,
                'profiles': self.mappings,
            }
            self.key_mappings_path.parent.mkdir(parents=True, exist_ok=True)
            with self.key_mappings_path.open('w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=4, ensure_ascii=False)
            self.status_label.setText("키 매핑이 성공적으로 저장되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"키 매핑 저장에 실패했습니다:\n{e}")
    def _load_mappings_from_path(self, path):
        try:
            target_path = Path(path)
        except TypeError:
            return False

        if not target_path.is_file():
            return False

        raw_data = None
        for encoding in ('utf-8', 'utf-8-sig', 'cp949', 'euc-kr'):
            try:
                with target_path.open('r', encoding=encoding) as f:
                    raw_data = json.load(f)
                break
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                raw_data = None
        if not isinstance(raw_data, dict):
            return False

        meta = raw_data.get('_meta') if isinstance(raw_data.get('_meta'), dict) else {}
        categories = raw_data.get('_categories') or meta.get('categories') or {}
        overrides_from_meta = meta.get('category_overrides') if isinstance(meta.get('category_overrides'), list) else None
        if overrides_from_meta is None and isinstance(categories, dict):
            overrides_from_meta = list(categories.keys())

        raw_parallel = raw_data.get('_parallel')
        if isinstance(raw_parallel, dict):
            parallel_flags = {str(name): bool(value) for name, value in raw_parallel.items()}
        else:
            parallel_flags = {}

        if isinstance(raw_data.get('profiles'), dict):
            new_mappings = raw_data.get('profiles', {})
        else:
            new_mappings = {
                key: value
                for key, value in raw_data.items()
                if not key.startswith('_')
            }

        if not isinstance(new_mappings, dict):
            return False

        self._stop_all_parallel_sequences(forced=True)
        self.mappings = new_mappings
        self.key_mappings_path = target_path.resolve()
        self.parallel_profile_flags = {
            name: bool(parallel_flags.get(name, False))
            for name in self.mappings.keys()
        }
        self._ensure_profile_categories(categories, overrides_from_meta)
        self._apply_category_heuristics()
        self.populate_command_list()
        return True

    def _apply_category_heuristics(self):
        overrides = getattr(self, 'category_overrides', set())
        for name in self.mappings.keys():
            if name in overrides:
                continue

            current_category = self.profile_categories.get(name)
            if current_category in CATEGORY_NAMES and current_category != CATEGORY_NAMES[0]:
                continue

            lowered = name.lower()
            chosen = None
            for category, keywords in CATEGORY_KEYWORDS.items():
                if any(keyword in lowered for keyword in keywords):
                    chosen = category
                    break

            if not chosen and any(keyword in name for keyword in CATEGORY_KEYWORDS.get("스킬", [])):
                chosen = "스킬"

            if chosen and chosen in CATEGORY_NAMES:
                self.profile_categories[name] = chosen
            else:
                self.profile_categories[name] = CATEGORY_NAMES[0]

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
            "모든 키 떼기": [{"type": "release_all"}],
            # <<< [추가] 방향성 점프 명령 추가
            "점프(좌)": [
                {"type": "release_specific", "key_str": "Key.right"},
                {"type": "press", "key_str": "Key.left"},
                {"type": "delay", "min_ms": 40, "max_ms": 60},
                {"type": "press", "key_str": "Key.alt_l"},
                {"type": "delay", "min_ms": 75, "max_ms": 113},
                {"type": "release", "key_str": "Key.alt_l"}
            ],
            "점프(우)": [
                {"type": "release_specific", "key_str": "Key.left"},
                {"type": "press", "key_str": "Key.right"},
                {"type": "delay", "min_ms": 40, "max_ms": 60},
                {"type": "press", "key_str": "Key.alt_l"},
                {"type": "delay", "min_ms": 75, "max_ms": 113},
                {"type": "release", "key_str": "Key.alt_l"}
            ]
        }

    def reset_to_defaults(self):
        reply = QMessageBox.question(self, "기본값 복원", "모든 키 매핑을 기본값으로 되돌리시겠습니까?\n저장하지 않은 변경사항은 사라집니다.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            self._stop_all_parallel_sequences(forced=True)
            self.mappings = self.create_default_mappings()
            self.category_overrides.clear()
            self.parallel_profile_flags = {name: False for name in self.mappings}
            self._ensure_profile_categories()
            self.populate_command_list()
            current_list = self._current_command_list()
            if current_list and current_list.count() > 0:
                current_list.setCurrentRow(0)

    def populate_command_list(self):
        if not self.category_lists:
            return

        self._ensure_profile_categories(self.profile_categories, self.category_overrides)
        current_selection = self._current_command_name()

        for list_widget in self.category_lists.values():
            list_widget.blockSignals(True)
            list_widget.clear()

        sorted_names = sorted(self.mappings.keys())
        for name in sorted_names:
            category = self.profile_categories.get(name, CATEGORY_NAMES[0])
            list_widget = self.category_lists.get(category)
            if list_widget is None:
                list_widget = self.category_lists.get(CATEGORY_NAMES[0])
                self.profile_categories[name] = CATEGORY_NAMES[0]
                self.category_overrides.discard(name)
            if list_widget is None:
                continue
            item = QListWidgetItem(name)
            flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            item.setFlags(flags)
            is_parallel = bool(self.parallel_profile_flags.get(name, False))
            self.parallel_profile_flags[name] = is_parallel
            item.setCheckState(Qt.CheckState.Checked if is_parallel else Qt.CheckState.Unchecked)
            list_widget.addItem(item)

        for list_widget in self.category_lists.values():
            list_widget.blockSignals(False)

        if current_selection and self._select_command_in_lists(current_selection):
            return

        for category in CATEGORY_NAMES:
            list_widget = self.category_lists.get(category)
            if list_widget and list_widget.count() > 0:
                list_widget.setCurrentRow(0)
                return

        self.editor_group.setEnabled(False)
        self.action_sequence_list.clear()

    def handle_profile_item_changed(self, category, item):
        if item is None:
            return

        name = item.text()
        is_parallel = item.checkState() == Qt.CheckState.Checked
        previous = self.parallel_profile_flags.get(name)
        self.parallel_profile_flags[name] = is_parallel

        if previous == is_parallel:
            return

        self.save_mappings()
        if getattr(self, 'status_label', None):
            state_text = "병렬 실행 허용" if is_parallel else "병렬 실행 해제"
            self.status_label.setText(f"'{name}' {state_text}로 설정되었습니다.")

    def _on_category_tab_changed(self, index):
        if self._is_syncing_selection:
            return

        if not self.command_tab_widget:
            return

        if not hasattr(self, 'editor_group'):
            return

        widget = self.command_tab_widget.widget(index)
        if widget is None:
            self.active_category = CATEGORY_NAMES[0]
            self.command_list = None
            self.editor_group.setEnabled(False)
            self.action_sequence_list.clear()
            return

        for category, list_widget in self.category_lists.items():
            if list_widget is widget:
                self.active_category = category
                self.command_list = list_widget
                break

        current_item = widget.currentItem() if hasattr(widget, 'currentItem') else None
        if current_item is not None:
            self.on_command_selected(current_item, None, self.active_category)
        elif widget.count() > 0:
            widget.setCurrentRow(0)
        else:
            self.editor_group.setEnabled(False)
            self.action_sequence_list.clear()

    def _current_command_list(self):
        return self.category_lists.get(self.active_category)

    def _current_command_item(self):
        current_list = self._current_command_list()
        return current_list.currentItem() if current_list else None

    def _current_command_name(self):
        item = self._current_command_item()
        return item.text() if item else None

    def _is_skill_profile(self, command_name: str) -> bool:
        """현재 명령이 스킬 탭에 속하는지 여부를 반환합니다."""
        if not isinstance(command_name, str):
            return False

        base_name = command_name.strip()
        if base_name.startswith("TEST: "):
            base_name = base_name[6:]

        return self.profile_categories.get(base_name, CATEGORY_NAMES[0]) == SKILL_CATEGORY_NAME

    def _find_command_item(self, command_name):
        for category, list_widget in self.category_lists.items():
            if not list_widget:
                continue
            items = list_widget.findItems(command_name, Qt.MatchFlag.MatchExactly)
            if items:
                return category, items[0]
        return None, None

    def _select_command_in_lists(self, command_name):
        category, item = self._find_command_item(command_name)
        if not item:
            return False
        target_list = self.category_lists[category]
        if target_list.currentItem() is item:
            self.on_command_selected(item, None, category)
        else:
            target_list.setCurrentItem(item)
        return True

    def handle_profile_drop(self, profile_names, target_category):
        if isinstance(profile_names, str):
            profile_names = [profile_names]

        if not profile_names or target_category not in CATEGORY_NAMES:
            return

        unique_names = []
        seen = set()
        for name in profile_names:
            if isinstance(name, str) and name in self.mappings and name not in seen:
                unique_names.append(name)
                seen.add(name)

        if not unique_names:
            return

        changed = False
        for name in unique_names:
            previous_category = self.profile_categories.get(name, CATEGORY_NAMES[0])
            if previous_category != target_category:
                self.profile_categories[name] = target_category
                changed = True
            if target_category in CATEGORY_NAMES and name not in self.category_overrides:
                self.category_overrides.add(name)
                changed = True

        if changed:
            self.populate_command_list()
            self.save_mappings()

        focused_name = None
        for name in unique_names:
            if self.profile_categories.get(name) == target_category:
                focused_name = name
                break

        if focused_name:
            self._select_command_in_lists(focused_name)
            if changed and getattr(self, 'status_label', None):
                count = len(unique_names)
                if count == 1:
                    self.status_label.setText(f"'{focused_name}' 프로필을 '{target_category}' 탭으로 이동했습니다.")
                else:
                    self.status_label.setText(f"{count}개 프로필을 '{target_category}' 탭으로 이동했습니다.")



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
                raw_name = k.name
                if raw_name.startswith('alt'):
                    name = raw_name  # alt_l, alt_r 그대로 사용
                elif raw_name == 'ctrl_l':
                    name = raw_name
                else:
                    name = raw_name.replace('_l', '').replace('_r', '')  # ctrl, shift 등은 단일 이름으로

                if raw_name in ('ctrl', 'ctrl_l'):
                    key_str = "Key.ctrl_l"
                else:
                    key_str = f"Key.{name}"

                if name in ['up', 'down', 'left', 'right']:
                    keys_by_type["방향키"].append(key_str)
                elif name.startswith('f') and name[1:].isdigit():
                    keys_by_type["기능키 (F1-F12)"].append(key_str)
                elif name in ['insert', 'delete', 'home', 'end', 'page_up', 'page_down']:
                    keys_by_type["편집키"].append(key_str)
                elif name in ['space', 'enter', 'esc', 'tab', 'backspace']:
                    keys_by_type["주요 특수키"].append(key_str)
                elif name in ['ctrl', 'ctrl_l', 'shift', 'cmd', 'alt_l']:
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
    def on_command_selected(self, current_item, previous_item, category=None):
        if self._is_syncing_selection:
            return

        if not hasattr(self, 'editor_group'):
            return

        if current_item is not None and category is None:
            widget = current_item.listWidget()
            for cat, list_widget in self.category_lists.items():
                if list_widget is widget:
                    category = cat
                    break

        if category in self.category_lists:
            target_list = self.category_lists[category]
            if self.command_tab_widget.currentWidget() is not target_list:
                self._is_syncing_selection = True
                self.command_tab_widget.setCurrentWidget(target_list)
                self._is_syncing_selection = False
            self.active_category = category
            self.command_list = target_list

        self._is_syncing_selection = True
        for cat, list_widget in self.category_lists.items():
            if cat != category:
                list_widget.clearSelection()
        self._is_syncing_selection = False

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
            
        command_item = self._current_command_item()
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
        command_item = self._current_command_item(); action_item = self.action_sequence_list.currentItem()
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
            self.profile_categories[text] = self.active_category
            self.category_overrides.add(text)
            self.parallel_profile_flags[text] = False
            self.populate_command_list()
            self._select_command_in_lists(text)

    def remove_command_profile(self):
        current_item = self._current_command_item()
        if not current_item: return
        command_text = current_item.text()
        reply = QMessageBox.question(self, "명령 프로필 삭제", f"'{command_text}' 명령 프로필을 삭제하시겠습니까?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            if command_text in self.active_parallel_sequences:
                self._stop_parallel_sequence(command_text, forced=True)
            self.mappings.pop(command_text, None)
            self.profile_categories.pop(command_text, None)
            self.category_overrides.discard(command_text)
            self.parallel_profile_flags.pop(command_text, None)
            self.populate_command_list()

    def rename_command_profile(self):
        current_item = self._current_command_item()
        if not current_item:
            QMessageBox.warning(self, "알림", "이름을 변경할 명령 프로필을 선택하세요.")
            return

        old_name = current_item.text()
        new_name, ok = QInputDialog.getText(self, "명령 프로필 이름 변경", f"'{old_name}'의 새 이름:", text=old_name)
        if not ok:
            return

        new_name = (new_name or "").strip()
        if not new_name or new_name == old_name:
            return

        if new_name in self.mappings:
            QMessageBox.warning(self, "오류", "이미 존재하는 명령어입니다.")
            return

        sequence = self.mappings.pop(old_name, [])
        self.mappings[new_name] = sequence

        category = self.profile_categories.pop(old_name, self.active_category)
        self.profile_categories[new_name] = category
        had_override = old_name in self.category_overrides
        self.category_overrides.discard(old_name)
        if had_override:
            self.category_overrides.add(new_name)

        is_parallel = self.parallel_profile_flags.pop(old_name, False)
        self.parallel_profile_flags[new_name] = is_parallel

        self._rename_active_references(old_name, new_name)
        self.populate_command_list()
        self._select_command_in_lists(new_name)
        self._populate_action_sequence_list(new_name)

        self.save_mappings()
        if getattr(self, 'status_label', None):
            self.status_label.setText(f"명령 프로필 이름을 '{old_name}'에서 '{new_name}'(으)로 변경했습니다.")
        self.command_profile_renamed.emit(old_name, new_name)

    def _rename_active_references(self, old_name: str, new_name: str) -> None:
        if self.current_command_name == old_name:
            self.current_command_name = new_name

        if old_name in self.active_parallel_sequences:
            self._stop_parallel_sequence(old_name, forced=True)

    def add_action_step(self):
        command_item = self._current_command_item()
        if not command_item:
            QMessageBox.warning(self, "오류", "먼저 좌측에서 명령을 선택하세요.")
            return
        command_text = command_item.text()
        new_action = {"type": "press", "key_str": "Key.space"}
        self.mappings[command_text].append(new_action)
        self._populate_action_sequence_list(command_text)
        self.action_sequence_list.setCurrentRow(self.action_sequence_list.count() - 1)

    def remove_action_step(self):
        command_item = self._current_command_item(); row = self.action_sequence_list.currentRow()
        if not command_item or row < 0: return
        command_text = command_item.text()
        del self.mappings[command_text][row]
        self._populate_action_sequence_list(command_text)

    def randomize_delays(self):
        """선택된 명령 프로필의 모든 delay 액션에 랜덤성을 부여합니다."""
        command_item = self._current_command_item()
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
        command_item = self._current_command_item(); row = self.action_sequence_list.currentRow()
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
        command_item = self._current_command_item()
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
            self._sequence_clipboard_cache = copy.deepcopy(sequence)
            
            self.status_label.setText(f"'{command_text}' 시퀀스가 클립보드에 복사되었습니다.")
            print(f"--- 클립보드에 복사된 내용 ---\n{sequence_text}\n--------------------------")

        except Exception as e:
            QMessageBox.critical(self, "오류", f"클립보드 복사 중 오류가 발생했습니다:\n{e}")

    def paste_sequence_from_clipboard(self):
        command_item = self._current_command_item()
        if not command_item:
            QMessageBox.warning(self, "알림", "붙여넣을 명령 프로필을 선택하세요.")
            return

        sequence_data = None
        if isinstance(self._sequence_clipboard_cache, list):
            sequence_data = copy.deepcopy(self._sequence_clipboard_cache)
        else:
            clipboard_text = QApplication.clipboard().text().strip()
            if clipboard_text:
                try:
                    parsed = json.loads(clipboard_text)
                    if isinstance(parsed, list):
                        self._sequence_clipboard_cache = copy.deepcopy(parsed)
                        sequence_data = copy.deepcopy(self._sequence_clipboard_cache)
                except json.JSONDecodeError:
                    sequence_data = None

        if not isinstance(sequence_data, list):
            QMessageBox.information(self, "알림", "복사한 시퀀스가 없습니다.")
            return

        command_text = command_item.text()
        self.mappings[command_text] = copy.deepcopy(sequence_data)
        self._populate_action_sequence_list(command_text)
        self.status_label.setText(f"'{command_text}' 시퀀스가 붙여넣기 되었습니다.")

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
        if not key_str:
            return None
        if key_str.startswith("Key."):
            key_name = key_str.split('.', 1)[1]
            if key_name == 'ctrl':
                key_name = 'ctrl_l'
            return getattr(Key, key_name, None)
        return key_str 

    def _send_command(self, command, key_object):
        if not self.ser or not self.ser.is_open:
            return
        
        #  KEY_MAP 대신 FULL_KEY_MAP 사용
        key_code = FULL_KEY_MAP.get(key_object)
        if key_code is not None:
            key_str_id = self._key_obj_to_str(key_object)
            try:
                self.ser.write(bytes([command, key_code]))
                # --- (신규) 전송 직후 타임스탬프 저장 (에코/리스너 무시에 사용) ---
                self.last_sent_timestamps[key_str_id] = time.time()  # 전송 시각 저장
                if command == CMD_PRESS:
                    self.keyboard_state_changed.emit(key_str_id, True)
                elif command == CMD_RELEASE:
                    self.keyboard_state_changed.emit(key_str_id, False)
            except serial.SerialException as e:
                print(f"[AutoControl] 데이터 전송 실패: {e}")
                self.connect_to_pi()

    def _get_key_set_for_owner(self, owner: str) -> set:
        key_set = self.sequence_owned_keys.get(owner)
        if key_set is None:
            key_set = set()
            self.sequence_owned_keys[owner] = key_set
        return key_set

    def _press_key_for_owner(self, owner: str, key_object, *, force: bool = False) -> bool:
        if key_object is None:
            return False

        key_set = self._get_key_set_for_owner(owner)
        already_owned = key_object in key_set

        if not already_owned:
            key_set.add(key_object)
            prev_count = self.global_key_counts.get(key_object, 0)
            self.global_key_counts[key_object] = prev_count + 1
            if force or prev_count == 0:
                self._send_command(CMD_PRESS, key_object)
            return True

        if force:
            prev_count = self.global_key_counts.get(key_object, 0)
            if prev_count == 0:
                self.global_key_counts[key_object] = 1
            self._send_command(CMD_PRESS, key_object)
            return True

        return False

    def _release_key_for_owner(self, owner: str, key_object, *, force: bool = False) -> bool:
        if key_object is None:
            return False

        key_set = self._get_key_set_for_owner(owner)
        had_key = key_object in key_set

        if had_key:
            key_set.remove(key_object)
            prev_count = self.global_key_counts.get(key_object, 0)
            new_count = max(prev_count - 1, 0)
            if new_count:
                self.global_key_counts[key_object] = new_count
            else:
                self.global_key_counts.pop(key_object, None)
            if new_count == 0:
                self._send_command(CMD_RELEASE, key_object)
            return True

        if force and self.global_key_counts.get(key_object, 0) == 0:
            self._send_command(CMD_RELEASE, key_object)
            return True

        return False

    def _release_all_for_owner(self, owner: str, *, force: bool = False) -> None:
        key_set = list(self._get_key_set_for_owner(owner))
        for key_obj in key_set:
            self._release_key_for_owner(owner, key_obj, force=force)
        self._get_key_set_for_owner(owner).clear()

    def _press_key(self, key_object, force=False):
        """
        (수정) 전송이 실제로 발생했는지 True/False 반환.
        force=True면 held_keys 상태를 무시하고 강제로 전송(재시도)함.
        """
        action_taken = self._press_key_for_owner(self.SEQUENTIAL_OWNER, key_object, force=force)

        if action_taken:
            log_action = "(누르기-forced)" if force else "(누르기)"
            self.log_generated.emit(
                f"{log_action} {self._translate_key_for_logging(self._key_obj_to_str(key_object))}",
                "white",
            )
            return True

        if self.console_log_checkbox.isChecked():
            print(f"[AutoControl] PRESS skipped (already held): {self._key_obj_to_str(key_object)}")
        return False

    def _release_key(self, key_object, force=False):
        """
        (수정) 반환값 명시, force=True면 강제 릴리즈 시도.
        """
        return self._release_key_for_owner(self.SEQUENTIAL_OWNER, key_object, force=force)

    def _release_all_keys(self, force=False):
        """
        (수정) 안전하게 모든 키를 떼고 held_keys를 초기화.
        force=True이면 _release_key에 force=True로 호출(하드 릴리즈).
        """
        self._release_all_for_owner(self.SEQUENTIAL_OWNER, force=force)

# [기능 추가] 테스트 종료 후 안전하게 모든 키를 떼는 슬롯
    @pyqtSlot()
    def _safe_release_all_keys(self):
        """테스트 종료 후 안전하게 모든 키를 떼고 상태를 업데이트하는 슬롯."""
        print("[AutoControl] All keys released automatically after test.")
        self._release_all_keys()
        self.status_label.setText("테스트 후 모든 키가 자동으로 해제되었습니다.")

    def test_selected_sequence(self):
        command_item = self._current_command_item()
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
    def _start_sequence_execution(self, sequence, command_name, is_test=False, reason=None):
        """
        시퀀스 실행 시작.
        기존: 동일 명령 중복이면 무시 -> 문제: 실패 복구 시 재시도가 막힘.
        수정: 동일 명령이 들어오면 '안전하게 중단하고' 재시작(강제 재실행) 처리.
        """
        # 만약 현재 동일 명령이 실행 중이면 '강제 재시작' 수행
        if self.is_sequence_running and self.current_command_name == command_name:
            if self.console_log_checkbox.isChecked():
                print(f"--- [AutoControl] 동일 명령 재요청: '{command_name}' -> 강제 재시작 수행 ---")
            # 안전하게 기존 시퀀스 정리
            try:
                self.sequence_timer.stop()
            except Exception:
                pass
            try:
                self.sequence_watchdog.stop()
            except Exception:
                pass
            # 이미 눌린 키가 남아있을 수 있으므로 강제 해제
            self._release_all_keys(force=True)
            self._notify_sequence_completed(False)

        # 만약 다른 시퀀스가 실행 중이면 기존 시퀀스 중단(이전 동작 취소)
        elif self.is_sequence_running:
            if self.console_log_checkbox.isChecked():
                print(f"--- [AutoControl] 이전 시퀀스 중단: '{self.current_command_name}' ---")
            try:
                self.sequence_timer.stop()
            except Exception:
                pass
            try:
                self.sequence_watchdog.stop()
            except Exception:
                pass
            # 안전하게 키들만 해제 (기본 동작: 강제 해제는 하지 않음)
            self._release_all_keys()
            self._notify_sequence_completed(False)

        # 이제 새 시퀀스 초기화
        self.status_label.setText(f"'{command_name}' 실행 중.")
        if self.console_log_checkbox.isChecked():
            print(f"--- [AutoControl] 실행 시작: '{command_name}' ---")

        self.current_sequence = sequence
        self.current_command_name = command_name
        self.current_command_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
        self.is_test_mode = is_test
        self.current_sequence_index = 0
        self.is_sequence_running = True
        self.is_first_key_event_in_sequence = True
        self.last_command_start_time = time.time()
        
        if self.current_command_reason:
            start_msg = f"--- (시작) {self.current_command_name} (원인: {self.current_command_reason}) ---"
        else:
            start_msg = f"--- (시작) {self.current_command_name} ---"              # <<< (추가) UI에 '(시작)' 로그를 즉시 남기기 위해 생성
        start_color = "orange" if self._is_skill_profile(self.current_command_name) else "magenta"
        self.log_generated.emit(start_msg, start_color)                        # <<< (추가) UI 로그 시그널로 즉시 표시

        # (와치독) 시퀀스가 멈추는 걸 감지하기 위해 재시작
        self.sequence_watchdog.start(self.SEQUENCE_STUCK_TIMEOUT_MS)

        self._process_next_step()

    def _process_next_step(self):
        """
        시퀀스의 현재 단계를 처리하고, 다음 단계를 QTimer로 스케줄링합니다.
        - 재진입 방지(is_processing_step)
        - 단계 처리 후 와치독 재시작
        - 예외가 발생해도 상태가 깨지지 않도록 finally에서 정리
        """
        if not self.is_sequence_running:
            return

        # 중복 진입 차단
        if self.is_processing_step:
            if self.console_log_checkbox.isChecked():
                print("[AutoControl] 스텝 재진입 차단됨 (is_processing_step=True)")
            return

        self.is_processing_step = True
        try:
            # 완료 검사
            if self.current_sequence_index >= len(self.current_sequence):
                self.sequence_watchdog.stop()
                if self.current_command_reason:
                    log_msg = f"--- (완료) {self.current_command_name} (원인: {self.current_command_reason}) ---"
                else:
                    log_msg = f"--- (완료) {self.current_command_name} ---"
                completion_color = "orange" if self._is_skill_profile(self.current_command_name) else "lightgreen"
                self.log_generated.emit(log_msg, completion_color)
                # 테스트 모드 후 키 남아있으면 안전 해제
                if self.is_test_mode and self.held_keys:
                    QTimer.singleShot(2000, lambda: self._release_all_keys(force=True))
                self._notify_sequence_completed(True)
                return

            step = self.current_sequence[self.current_sequence_index]
            action_type = step.get("type")
            delay_ms = 1

            # key event 처리
            if action_type in ["press", "release", "release_specific"]:
                key_obj = self._str_to_key_obj(step.get("key_str"))
                if not key_obj:
                    self.log_generated.emit(f"오류: 알 수 없는 키 '{step.get('key_str')}'", "red")
                elif action_type == "press":
                    # <<< [수정] _press_key 메서드가 이제 로그와 전송을 모두 처리
                    self._press_key(key_obj, force=False)
                else:  # release
                    released = self._release_key(key_obj, force=False)
                    if released:
                        self.log_generated.emit(f"(떼기) {self._translate_key_for_logging(step.get('key_str'))}", "white")
                    else:
                        if self.console_log_checkbox.isChecked():
                            print(f"[AutoControl] RELEASE skipped (not held) -> 강제 릴리즈 시도: {key_obj}")
                        self._release_key(key_obj, force=True)
                        self.log_generated.emit(f"(떼기-forced) {self._translate_key_for_logging(step.get('key_str'))}", "white")

            elif action_type == "delay":
                min_ms = step.get("min_ms", 0)
                max_ms = step.get("max_ms", 0)
                if min_ms >= max_ms: delay_ms = min_ms
                else:
                    mean = (min_ms + max_ms) / 2
                    std_dev = (max_ms - min_ms) / 6
                    delay_ms = int(max(min(random.gauss(mean, std_dev), max_ms), min_ms))
                self.log_generated.emit(f"(대기) {delay_ms}ms", "gray")
        
            elif action_type == "release_all":
                self._release_all_keys(force=True)
                if self.current_command_reason:
                    self.log_generated.emit(f"(모든 키 떼기) (원인: {self.current_command_reason})", "white")
                else:
                    self.log_generated.emit("(모든 키 떼기)", "white")

            # 다음 스텝로 이동 및 타이머 재시작
            self.current_sequence_index += 1
            try:
                self.sequence_timer.stop()
            except Exception:
                pass
            self.sequence_watchdog.start(self.SEQUENCE_STUCK_TIMEOUT_MS)
            self.sequence_timer.start(delay_ms)

        except Exception as e:
            print(f"[AutoControl] _process_next_step 예외: {e}")
            self.log_generated.emit(f"오류: _process_next_step 예외 발생 - {e}", "red")
            self._release_all_keys(force=True)
            self.sequence_watchdog.stop()
            self._notify_sequence_completed(False)
        finally:
            self.is_processing_step = False

    def _start_parallel_sequence(self, sequence, command_name, reason=None):
        sequence_copy = copy.deepcopy(sequence) if isinstance(sequence, list) else []

        if command_name in self.active_parallel_sequences:
            self._stop_parallel_sequence(command_name, forced=True)

        owner = self._parallel_owner(command_name)
        self.sequence_owned_keys[owner] = set()

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda cn=command_name: self._process_parallel_step(cn))

        watchdog = QTimer(self)
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(lambda cn=command_name: self._on_parallel_sequence_stuck(cn))

        clean_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
        state = {
            "command_name": command_name,
            "sequence": sequence_copy,
            "index": 0,
            "timer": timer,
            "watchdog": watchdog,
            "reason": clean_reason,
            "owner": owner,
            "is_processing": False,
        }
        self.active_parallel_sequences[command_name] = state

        start_color = "orange" if self._is_skill_profile(command_name) else "cyan"
        if clean_reason:
            self.log_generated.emit(f"[{command_name}] (시작) (원인: {clean_reason})", start_color)
        else:
            self.log_generated.emit(f"[{command_name}] (시작)", start_color)

        watchdog.start(self.SEQUENCE_STUCK_TIMEOUT_MS)
        self._process_parallel_step(command_name)

    def _process_parallel_step(self, command_name: str) -> None:
        state = self.active_parallel_sequences.get(command_name)
        if not state:
            return

        if state.get("is_processing"):
            if self.console_log_checkbox.isChecked():
                print(f"[AutoControl] 병렬 스텝 재진입 차단: {command_name}")
            return

        state["is_processing"] = True
        try:
            if state["index"] >= len(state["sequence"]):
                self._finalize_parallel_sequence(command_name, state, success=True)
                return

            step = state["sequence"][state["index"]] or {}
            action_type = step.get("type")
            delay_ms = 1
            owner = state["owner"]

            if action_type in ["press", "release", "release_specific"]:
                key_obj = self._str_to_key_obj(step.get("key_str"))
                if not key_obj:
                    self.log_generated.emit(f"[{command_name}] 오류: 알 수 없는 키 '{step.get('key_str')}'", "red")
                elif action_type == "press":
                    pressed = self._press_key_for_owner(owner, key_obj, force=False)
                    if pressed:
                        self.log_generated.emit(
                            f"[{command_name}] (누르기) {self._translate_key_for_logging(step.get('key_str'))}",
                            "white",
                        )
                    elif self.console_log_checkbox.isChecked():
                        print(f"[AutoControl] 병렬 PRESS skipped (already held): {step.get('key_str')}")
                else:
                    released = self._release_key_for_owner(owner, key_obj, force=False)
                    if released:
                        self.log_generated.emit(
                            f"[{command_name}] (떼기) {self._translate_key_for_logging(step.get('key_str'))}",
                            "white",
                        )
                    else:
                        if self.global_key_counts.get(key_obj, 0) == 0:
                            forced = self._release_key_for_owner(owner, key_obj, force=True)
                            if forced:
                                self.log_generated.emit(
                                    f"[{command_name}] (떼기-forced) {self._translate_key_for_logging(step.get('key_str'))}",
                                    "white",
                                )
                        elif self.console_log_checkbox.isChecked():
                            print(f"[AutoControl] 병렬 RELEASE skipped (held elsewhere): {step.get('key_str')}")

            elif action_type == "delay":
                min_ms = int(step.get("min_ms", 0))
                max_ms = int(step.get("max_ms", min_ms))
                if min_ms >= max_ms:
                    delay_ms = max(0, min_ms)
                else:
                    mean = (min_ms + max_ms) / 2
                    std_dev = (max_ms - min_ms) / 6
                    delay_ms = int(max(min(random.gauss(mean, std_dev), max_ms), min_ms))
                self.log_generated.emit(f"[{command_name}] (대기) {delay_ms}ms", "gray")

            elif action_type == "release_all":
                self._release_all_for_owner(owner, force=True)
                self.log_generated.emit(f"[{command_name}] (모든 키 떼기)", "white")

            else:
                self.log_generated.emit(
                    f"[{command_name}] 경고: 알 수 없는 동작 '{action_type}'", "orange"
                )

            state["index"] += 1

            if command_name in self.active_parallel_sequences:
                state["watchdog"].start(self.SEQUENCE_STUCK_TIMEOUT_MS)
                try:
                    state["timer"].stop()
                except Exception:
                    pass
                state["timer"].start(max(int(delay_ms), 1))

        except Exception as exc:
            print(f"[AutoControl] 병렬 시퀀스 예외: {command_name} -> {exc}")
            self.log_generated.emit(
                f"[{command_name}] 오류: 병렬 시퀀스 처리 중 예외 발생 - {exc}",
                "red",
            )
            self._stop_parallel_sequence(command_name, forced=True)
        finally:
            if command_name in self.active_parallel_sequences:
                self.active_parallel_sequences[command_name]["is_processing"] = False

    def _finalize_parallel_sequence(self, command_name: str, state: dict, success: bool) -> None:
        timer = state.get("timer")
        watchdog = state.get("watchdog")
        for qtimer in (timer, watchdog):
            if qtimer:
                try:
                    qtimer.stop()
                except Exception:
                    pass

        owner = state.get("owner", self._parallel_owner(command_name))
        self._release_all_for_owner(owner, force=False)
        self.sequence_owned_keys.pop(owner, None)
        self.active_parallel_sequences.pop(command_name, None)

        reason = state.get("reason")
        suffix = f" (원인: {reason})" if reason else ""
        if success:
            completion_color = "orange" if self._is_skill_profile(command_name) else "lightgreen"
            self.log_generated.emit(f"[{command_name}] (완료){suffix}", completion_color)
        else:
            self.log_generated.emit(f"[{command_name}] (중단){suffix}", "orange")

    def _stop_parallel_sequence(self, command_name: str, forced: bool = False) -> None:
        state = self.active_parallel_sequences.pop(command_name, None)
        if not state:
            return

        timer = state.get("timer")
        watchdog = state.get("watchdog")
        for qtimer in (timer, watchdog):
            if qtimer:
                try:
                    qtimer.stop()
                except Exception:
                    pass

        owner = state.get("owner", self._parallel_owner(command_name))
        self._release_all_for_owner(owner, force=forced)
        self.sequence_owned_keys.pop(owner, None)

        if forced:
            self.log_generated.emit(f"[{command_name}] 병렬 시퀀스를 강제 종료했습니다.", "orange")
        else:
            self.log_generated.emit(f"[{command_name}] 병렬 시퀀스를 중단했습니다.", "orange")

    def _stop_all_parallel_sequences(self, forced: bool = False) -> None:
        for name in list(self.active_parallel_sequences.keys()):
            self._stop_parallel_sequence(name, forced=forced)

    def _on_parallel_sequence_stuck(self, command_name: str) -> None:
        if command_name not in self.active_parallel_sequences:
            return
        self.log_generated.emit(
            f"경고: '{command_name}' 병렬 시퀀스가 멈춤. 복구 시도 중...",
            "orange",
        )
        self._stop_parallel_sequence(command_name, forced=True)

    @pyqtSlot(str, object)
    def receive_control_command(self, command_text, reason=None):
        sequence = self.mappings.get(command_text)
        if not sequence:
            print(f"[AutoControl] 경고: '{command_text}'에 대한 매핑이 없습니다.")
            return

        sequence_payload = copy.deepcopy(sequence)
        if self.parallel_profile_flags.get(command_text, False):
            self._start_parallel_sequence(sequence_payload, command_text, reason=reason)
        else:
            # 새 동작: 만약 동일 명령이 이미 실행 중이라면 강제 재시작하도록 _start_sequence_execution이 처리
            self._start_sequence_execution(sequence_payload, command_text, is_test=False, reason=reason)

    def _on_sequence_stuck(self):
        """(신규) 시퀀스가 일정 시간 진행이 없을 때 호출되어 안전 복구를 시도합니다."""
        print(f"[AutoControl] Sequence watchdog fired for '{self.current_command_name}'. Performing safe recovery.")
        self.log_generated.emit(f"경고: '{self.current_command_name}' 시퀀스가 멈춤. 복구 시도 중...", "orange")
        # 시퀀스 강제 중단 및 키 정리
        try:
            self.sequence_timer.stop()
        except Exception:
            pass
        try:
            self.sequence_watchdog.stop()
        except Exception:
            pass
        self._release_all_keys(force=True)
        self._notify_sequence_completed(False)

    def toggle_recording(self):
        if self.is_recording or self.is_waiting_for_start_key:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if not self._current_command_item():
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
        self.currently_pressed_keys_for_recording.clear()

        command_item = self._current_command_item()
        if command_item and self.recorded_sequence:
            command_text = command_item.text()
            self.mappings[command_text] = self.recorded_sequence
            self._populate_action_sequence_list(command_text)
            self.recording_status_changed.emit("녹화 완료. '매핑 저장'을 눌러주세요.")
        else:
            self.recording_status_changed.emit("녹화가 중단되었습니다.")
            
        self.record_btn.setChecked(False)
        self.record_btn.setText(" 녹화")
        self._sync_keyboard_visual_state()

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
        self.keyboard_state_changed.emit(key_str, True)
        
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
        self.keyboard_state_changed.emit(key_str, False)

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
            self.keyboard_state_reset.emit()
            self._sync_keyboard_visual_state()

    def _on_global_press(self, key):
        key_str = self._key_to_str(key)  # 기존에 있던 헬퍼 사용 (문자열 일관화용)

        # <<< (수정) 우리가 직전에 전송한 키의 '에코'라면 무시 (ECHO_IGNORE_MS 사용) >>>
        last_sent = self.last_sent_timestamps.get(key_str, 0)
        if time.time() - last_sent < (self.ECHO_IGNORE_MS / 1000.0):  # ms -> s 로 변환하여 비교
            if getattr(self, "console_log_checkbox", None) and self.console_log_checkbox.isChecked():
                print(f"[AutoControl] Global press ignored (echo) for {key_str} (within {self.ECHO_IGNORE_MS} ms)")
            return

        # 기존 처리 (정상적인 외부 입력으로 처리)
        if key_str in self.globally_pressed_keys:
            return

        self.globally_pressed_keys.add(key_str)
        friendly_key_name = self._translate_key_for_logging(key_str)
        self.log_generated.emit(f"(누르기) {friendly_key_name}", "white")
        self.keyboard_state_changed.emit(key_str, True)

    def _on_global_release(self, key):
        key_str = self._key_to_str(key)

        # <<< (수정) 에코 무시 로직 (ECHO_IGNORE_MS 사용) >>>
        last_sent = self.last_sent_timestamps.get(key_str, 0)
        if time.time() - last_sent < (self.ECHO_IGNORE_MS / 1000.0):
            if getattr(self, "console_log_checkbox", None) and self.console_log_checkbox.isChecked():
                print(f"[AutoControl] Global release ignored (echo) for {key_str} (within {self.ECHO_IGNORE_MS} ms)")
            return

        self.globally_pressed_keys.discard(key_str)
        friendly_key_name = self._translate_key_for_logging(key_str)
        self.log_generated.emit(f"(떼기) {friendly_key_name}", "white")
        self.keyboard_state_changed.emit(key_str, False)

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
        
        if not self.log_persist_checkbox.isChecked() and self.key_log_list.count() > 200:
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
        if not self.log_persist_checkbox.isChecked() and self.key_log_list.count() > 200:
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
        
        if not self.log_persist_checkbox.isChecked() and self.key_log_list.count() > 200:
            self.key_log_list.takeItem(0)
            
        self.key_log_list.scrollToBottom()

    def _translate_key_for_logging(self, key_str):
        translation_map = {
            'Key.right': '→', 'Key.left': '←', 'Key.down': '↓', 'Key.up': '↑',
            'Key.space': 'Space', 'Key.enter': 'Enter', 'Key.esc': 'Esc',
            'Key.ctrl_l': 'Ctrl_L', 'Key.ctrl': 'Ctrl',
            'Key.alt_l': 'Alt_L', 'Key.alt_r': 'Alt_R', 'Key.alt': 'Alt',
            'Key.shift_l': 'Shift_L', 'Key.shift_r': 'Shift_R', 'Key.shift': 'Shift',
            'Key.cmd': 'Win', 'Key.cmd_l': 'Win_L', 'Key.cmd_r': 'Win_R',
            'Key.tab': 'Tab', 'Key.backspace': 'Backspace',
            'Key.insert': 'Insert', 'Key.delete': 'Delete',
            'Key.home': 'Home', 'Key.end': 'End',
            'Key.page_up': 'PageUp', 'Key.page_down': 'PageDown',
        }
        # 맵에 키가 있으면 변환된 값을, 없으면 원래 값을 반환
        return translation_map.get(key_str, key_str)

    def cleanup_on_close(self):
        print("'자동 제어' 탭 정리 중...")
        self.is_sequence_running = False
        self.sequence_timer.stop()
        self.current_command_reason = None
        
        # 녹화용 리스너 중지
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        
        # [수정] 전역 키 로깅용 리스너를 안전하게 중지
        if self.global_listener:
            self.global_listener.stop()
            self.global_listener = None
            self.keyboard_state_reset.emit()

        if self.ser and self.ser.is_open:
            self._release_all_keys()
            time.sleep(0.1)
            self.ser.close()
            print("시리얼 포트 연결을 해제했습니다.")
