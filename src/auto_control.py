# auto_control.py

import serial
import time
import json
import os
import random
import copy
from collections import defaultdict
from pathlib import Path
import sys
import struct
import subprocess
import ctypes

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QSpinBox, QDoubleSpinBox, QMessageBox, QFrame, QCheckBox,
    QListWidgetItem, QInputDialog, QAbstractItemView, QTabWidget, QFileDialog,
    QGridLayout, QSizePolicy, QButtonGroup
)
from PyQt6.QtCore import pyqtSlot, Qt, QTimer, pyqtSignal, QMimeData, QSize, QSettings, QThread, QEvent
from PyQt6.QtGui import QIcon, QColor
from pynput.keyboard import Key, Listener
from datetime import datetime
import pygetwindow as gw
import uuid
import shutil

# --- 설정 및 상수 ---
SERIAL_PORT = 'COM6'
BAUD_RATE = 115200
CMD_PRESS = 0x01
CMD_RELEASE = 0x02
CMD_CLEAR_ALL = 0x03
# Mouse command constants
MOUSE_MOVE_REL = 0x10
MOUSE_SMOOTH_MOVE = 0x11
MOUSE_LEFT_CLICK = 0x12
MOUSE_RIGHT_CLICK = 0x13
MOUSE_DOUBLE_CLICK = 0x14
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


def _resolve_mouse_image_base_dir() -> Path:
    """이미지 기반 마우스 이동 템플릿의 기본 저장 디렉터리를 해상합니다.
    우선순위:
      1) 환경변수 MAPLE_MOUSE_IMAGE_DIR
      2) G:\\Coding\\Project_Maple\\workspace\\config\\mouse_move_image (사용자 지정 경로)
      3) <repo>/workspace/config/mouse_move_image (로컬 워크스페이스)
    """
    # 1) 환경변수
    try:
        env_p = os.environ.get('MAPLE_MOUSE_IMAGE_DIR')
        if env_p:
            p = Path(env_p)
            p.mkdir(parents=True, exist_ok=True)
            return p.resolve()
    except Exception:
        pass

    # 2) 사용자 지정 Windows 경로
    candidates = [
        Path(r"G:\\Coding\\Project_Maple\\workspace\\config\\mouse_move_image"),
        BASE_DIR / 'workspace' / 'config' / 'mouse_move_image',
    ]
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            return c.resolve()
        except Exception:
            continue
    # 끝까지 실패하면 BASE_DIR 하위로 폴백
    fb = BASE_DIR / 'workspace' / 'config' / 'mouse_move_image'
    try:
        fb.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return fb.resolve()

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
        self.current_command_reason_display = None
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

        self.MAX_SEQUENCE_RECOVERY_ATTEMPTS = 2
        self.sequence_recovery_attempts = defaultdict(int)

        self.globally_pressed_keys = set()

        # --- EPP(포인터 정확도 향상) 가드 ---
        self._epp_guard_refcount = 0
        self._epp_guard_main_active = False
        self._epp_guard_parallel_active: dict[str, bool] = {}
        self.global_listener = None
        # [NEW] 현재 실행 중인 순차 시퀀스의 출처 태그 ("[맵]"/"[사냥]")
        self.current_command_source_tag = None
        
        # --- (신규) Quiet 모드: 지정 시간 동안 화이트리스트 외 입력 차단 ---
        self._quiet_until_ts: float = 0.0
        self._quiet_whitelist: set[str] = set()
        
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
        # Ensure EPP guard is released for main sequence if held
        try:
            if getattr(self, '_epp_guard_main_active', False):
                self._epp_guard_release(tag=f"main:{self.current_command_name or ''}")
                self._epp_guard_main_active = False
        except Exception:
            pass
        command_name = self.current_command_name
        if command_name:
            try:
                self.sequence_completed.emit(command_name, self.current_command_reason, success)
            except Exception:
                pass
            self.sequence_recovery_attempts.pop(command_name, None)
        self.current_command_name = ""
        self.current_command_reason = None
        self.current_command_reason_display = None
        self.current_command_source_tag = None
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
        self.command_tab_widget.setMinimumHeight(360)
        self.command_tab_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        cmd_group_layout.addWidget(self.command_tab_widget)
        cmd_group_layout.setStretch(0, 0)
        cmd_group_layout.setStretch(1, 1)
        cmd_group_layout.setStretch(2, 0)

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
        self.action_sequence_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.action_sequence_list.itemSelectionChanged.connect(self.on_action_step_selected)
        self.action_sequence_list.setMinimumHeight(360)
        self.action_sequence_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        seq_group_layout.addWidget(self.action_sequence_list)
        seq_group_layout.setStretch(0, 0)
        seq_group_layout.setStretch(1, 1)
        seq_group_layout.setStretch(2, 0)

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

        main_v_layout.setStretch(0, 6)
        main_v_layout.setStretch(1, 2)
        main_v_layout.setStretch(2, 1)
        main_v_layout.setStretch(3, 1)
        main_v_layout.setStretch(4, 1)
        main_v_layout.setStretch(5, 1)

        return left_widget

    def _create_editor_panel(self):
        editor_group = QGroupBox("선택된 액션 상세 편집")
        editor_layout = QFormLayout(editor_group)
        self.action_type_combo = QComboBox()
        self.action_type_combo.addItems([
            "press", "release", "delay", "release_all", "release_specific",
            # mouse actions
            "mouse_move_abs", "mouse_left_click", "mouse_right_click", "mouse_double_click",
        ])
        self.action_type_combo.currentIndexChanged.connect(self._on_editor_type_changed)
        self.key_combo = QComboBox()
        self.key_combo.addItems(self.key_list_str)
        self.force_checkbox = QCheckBox("강제 전송")
        self.force_checkbox.setChecked(False)
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
        # Mouse absolute move editor (UI 개편)
        self.mouse_move_widget = QWidget()
        mm_vlayout = QVBoxLayout(self.mouse_move_widget)
        mm_vlayout.setContentsMargins(0,0,0,0)

        # 모드 체크박스(서로 배타)
        self.mouse_mode_coord = QCheckBox("좌표")
        self.mouse_mode_image = QCheckBox("이미지")
        self.mouse_mode_group = QButtonGroup(self.mouse_move_widget)
        self.mouse_mode_group.setExclusive(True)
        self.mouse_mode_group.addButton(self.mouse_mode_coord)
        self.mouse_mode_group.addButton(self.mouse_mode_image)
        self.mouse_mode_coord.setChecked(True)

        # 좌표 행: 좌표 체크박스 우측에 x/y/dur 배치
        coord_row = QHBoxLayout()
        coord_row.setContentsMargins(0,0,0,0)
        self.mouse_x_spin = QSpinBox(); self.mouse_x_spin.setRange(-32768, 32767)
        self.mouse_y_spin = QSpinBox(); self.mouse_y_spin.setRange(-32768, 32767)
        self.mouse_dur_spin = QSpinBox(); self.mouse_dur_spin.setRange(40, 5000); self.mouse_dur_spin.setSuffix(" ms"); self.mouse_dur_spin.setValue(240)
        for w, width in ((self.mouse_x_spin, 90), (self.mouse_y_spin, 90), (self.mouse_dur_spin, 110)):
            try:
                w.setFixedWidth(width)
                w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            except Exception:
                pass
        coord_row.addWidget(self.mouse_mode_coord)
        coord_row.addSpacing(8)
        coord_row.addWidget(QLabel("x:")); coord_row.addWidget(self.mouse_x_spin)
        coord_row.addWidget(QLabel("y:")); coord_row.addWidget(self.mouse_y_spin)
        coord_row.addWidget(QLabel("dur:")); coord_row.addWidget(self.mouse_dur_spin)
        coord_row.addStretch(1)
        mm_vlayout.addLayout(coord_row)

        # 이미지 행: 이미지 체크박스는 좌표 행 아래
        image_row = QHBoxLayout()
        image_row.setContentsMargins(0,0,0,0)
        image_row.addWidget(self.mouse_mode_image)
        image_row.addStretch(1)
        mm_vlayout.addLayout(image_row)

        # 이미지 설정 위젯(이미지 모드일 때만 표시)
        self.image_settings_widget = QFrame()
        self.image_settings_widget.setFrameShape(QFrame.Shape.NoFrame)
        img_layout = QVBoxLayout(self.image_settings_widget)
        img_layout.setContentsMargins(0,0,0,0)
        img_layout.setSpacing(6)

        # 상단: 영역 지정 + 임계값
        top_img_row = QHBoxLayout()
        self.image_region_btn = QPushButton("영역 지정")
        self.image_region_btn.setFixedWidth(90)
        self.image_region_label = QLabel("(영역 미설정)")
        self.image_region_label.setStyleSheet("color: #aaa;")
        top_img_row.addWidget(self.image_region_btn)
        top_img_row.addWidget(self.image_region_label, 1)
        top_img_row.addSpacing(12)
        top_img_row.addWidget(QLabel("임계값:"))
        self.image_threshold_spin = QDoubleSpinBox()
        self.image_threshold_spin.setRange(0.0, 1.0)
        self.image_threshold_spin.setSingleStep(0.01)
        self.image_threshold_spin.setDecimals(2)
        self.image_threshold_spin.setValue(0.85)
        self.image_threshold_spin.setFixedWidth(80)
        top_img_row.addWidget(self.image_threshold_spin)
        self.image_click_checkbox = QCheckBox("매칭 후 클릭")
        self.image_click_checkbox.setChecked(False)
        top_img_row.addSpacing(12)
        top_img_row.addWidget(self.image_click_checkbox)
        img_layout.addLayout(top_img_row)

        # 템플릿 리스트 + 버튼들
        self.image_template_list = QListWidget()
        self.image_template_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.image_template_list.setIconSize(QSize(128, 72))
        self.image_template_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.image_template_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.image_template_list.setMinimumHeight(120)
        img_layout.addWidget(self.image_template_list)

        tpl_btn_row = QHBoxLayout()
        self.image_add_btn = QPushButton("파일 추가")
        self.image_del_btn = QPushButton("선택 삭제")
        self.image_test_btn = QPushButton("매칭 테스트")
        tpl_btn_row.addWidget(self.image_add_btn)
        tpl_btn_row.addWidget(self.image_del_btn)
        tpl_btn_row.addStretch(1)
        tpl_btn_row.addWidget(self.image_test_btn)
        img_layout.addLayout(tpl_btn_row)

        mm_vlayout.addWidget(self.image_settings_widget)
        editor_layout.addRow("타입:", self.action_type_combo)
        editor_layout.addRow("키:", self.key_combo)
        editor_layout.addRow("지연 시간:", self.delay_widget)
        editor_layout.addRow("마우스 이동:", self.mouse_move_widget)
        editor_layout.addRow("", self.force_checkbox)
        self.action_type_combo.currentTextChanged.connect(self._update_action_from_editor)
        self.key_combo.currentTextChanged.connect(self._update_action_from_editor)
        self.min_delay_spin.valueChanged.connect(self._update_action_from_editor)
        self.max_delay_spin.valueChanged.connect(self._update_action_from_editor)
        self.mouse_x_spin.valueChanged.connect(self._update_action_from_editor)
        self.mouse_y_spin.valueChanged.connect(self._update_action_from_editor)
        self.mouse_dur_spin.valueChanged.connect(self._update_action_from_editor)
        self.mouse_mode_coord.toggled.connect(self._on_mouse_mode_toggled)
        self.mouse_mode_image.toggled.connect(self._on_mouse_mode_toggled)
        # 이미지 설정 시그널
        self.image_region_btn.clicked.connect(self._on_pick_image_region)
        self.image_threshold_spin.valueChanged.connect(self._on_image_threshold_changed)
        self.image_click_checkbox.toggled.connect(self._on_image_click_toggled)
        self.image_add_btn.clicked.connect(self._on_add_image_templates)
        self.image_del_btn.clicked.connect(self._on_delete_selected_templates)
        self.image_test_btn.clicked.connect(self._on_test_image_matching)
        self.force_checkbox.toggled.connect(self._update_action_from_editor)
        editor_group.setEnabled(False)
        # 편집기에서 Z 키로 좌표 채우기 이벤트 필터 설치
        editor_group.installEventFilter(self)
        return editor_group

    def _on_mouse_mode_toggled(self, _checked: bool) -> None:
        # 좌표/이미지 모드 상호배타 처리 및 입력 활성화 갱신
        # 시퀀스 데이터도 즉시 반영
        self._update_mouse_move_mode_enabled()
        self._update_action_from_editor()
        # 이미지 모드 켜짐 시 템플릿 UI 초기화
        try:
            if self.mouse_mode_image.isChecked():
                _, _, action = self._get_selected_action_ref()
                if isinstance(action, dict):
                    self._ensure_step_image_dir(action)
                    self._refresh_image_template_list(action)
        except Exception:
            pass

    def _update_mouse_move_mode_enabled(self) -> None:
        is_coord = bool(getattr(self, 'mouse_mode_coord', None) and self.mouse_mode_coord.isChecked())
        for w in (getattr(self, 'mouse_x_spin', None), getattr(self, 'mouse_y_spin', None), getattr(self, 'mouse_dur_spin', None)):
            if w is not None:
                try:
                    w.setEnabled(is_coord)
                except Exception:
                    pass
        # 이미지 설정 표시 토글
        if getattr(self, 'image_settings_widget', None) is not None and getattr(self, 'mouse_mode_image', None) is not None:
            try:
                self.image_settings_widget.setVisible(self.mouse_mode_image.isChecked())
            except Exception:
                pass

    def eventFilter(self, obj, event):
        try:
            if obj is self.editor_group and event.type() == QEvent.Type.KeyPress:
                # Z 키로 현재 커서 좌표 채우기 (mouse_move_abs 편집 중에만)
                if self.action_type_combo.currentText() == 'mouse_move_abs':
                    key = event.key()
                    mods = event.modifiers()
                    if key in (Qt.Key.Key_Z, ) and mods == Qt.KeyboardModifier.NoModifier:
                        # 좌표 모드일 때만 적용
                        if self.mouse_mode_coord.isChecked():
                            x, y = self._get_cursor_pos()
                            self.mouse_x_spin.setValue(int(x))
                            self.mouse_y_spin.setValue(int(y))
                            self._update_action_from_editor()
                            if getattr(self, 'status_label', None):
                                self.status_label.setText(f"마우스 좌표 적용: ({x},{y})")
                            return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

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

    # ---------------------------
    # 이미지 기반 이동: 편집/파일/매칭 헬퍼
    # ---------------------------
    def _get_selected_action_ref(self):
        command_item = self._current_command_item()
        if not command_item:
            return None, None, None
        selected_rows = self._selected_action_rows()
        if len(selected_rows) != 1:
            return None, None, None
        row = selected_rows[0]
        command_text = command_item.text()
        sequence = self.mappings.get(command_text, [])
        if not (0 <= row < len(sequence)):
            return None, None, None
        return command_text, row, sequence[row]

    def _ensure_step_image_dir(self, action_data: dict) -> Path | None:
        try:
            base = _resolve_mouse_image_base_dir()
            image_id = action_data.get('image_id')
            if not image_id:
                image_id = uuid.uuid4().hex[:12]
                action_data['image_id'] = image_id
            step_dir = base / f"img-{image_id}"
            step_dir.mkdir(parents=True, exist_ok=True)
            return step_dir
        except Exception as e:
            QMessageBox.critical(self, "오류", f"이미지 저장 폴더 준비 실패: {e}")
            return None

    def _refresh_image_template_list(self, action_data: dict | None = None) -> None:
        if action_data is None:
            _, _, action_data = self._get_selected_action_ref()
            if not isinstance(action_data, dict):
                return
        self.image_template_list.clear()
        step_dir = self._ensure_step_image_dir(action_data)
        if step_dir is None:
            return
        # 파일 목록 로드/동기화
        valid_ext = {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}
        files = []
        try:
            for p in sorted(step_dir.iterdir()):
                if p.is_file() and p.suffix.lower() in valid_ext:
                    files.append(p.name)
        except Exception:
            files = []
        action_data['image_files'] = files
        if not files:
            placeholder = QListWidgetItem(QIcon(), "등록된 템플릿이 없습니다")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.image_template_list.addItem(placeholder)
            return
        for name in files:
            full = step_dir / name
            item = QListWidgetItem(QIcon(str(full)), name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.image_template_list.addItem(item)

    def _on_pick_image_region(self):
        # 현재 스텝 참조
        cmd, row, action = self._get_selected_action_ref()
        if not action or self.action_type_combo.currentText() != 'mouse_move_abs':
            return
        # Snipper 선택(듀얼모니터 우선)
        region = None
        try:
            from map_widgets import MultiScreenSnipper
            snipper = MultiScreenSnipper(self)
            if snipper.exec():
                roi = snipper.get_global_roi()
                region = {
                    'top': int(roi.top()), 'left': int(roi.left()),
                    'width': int(roi.width()), 'height': int(roi.height()),
                }
        except Exception:
            try:
                from detection_runtime import ScreenSnipper
                sn = ScreenSnipper(self)
                if sn.exec():
                    r = sn.get_roi()
                    region = {
                        'top': int(r.top()), 'left': int(r.left()),
                        'width': int(r.width()), 'height': int(r.height()),
                    }
            except Exception as e:
                QMessageBox.critical(self, "영역 지정 실패", f"화면 스니퍼를 사용할 수 없습니다: {e}")
                region = None
        if region and region['width'] > 0 and region['height'] > 0:
            action['region'] = region
            self.image_region_label.setStyleSheet("")
            self.image_region_label.setText(f"({region['left']},{region['top']}) {region['width']}x{region['height']}")
        else:
            self.image_region_label.setStyleSheet("color: #aaa;")
            self.image_region_label.setText("(영역 미설정)")

    def _on_image_threshold_changed(self, value: float):
        _, _, action = self._get_selected_action_ref()
        if isinstance(action, dict) and self.action_type_combo.currentText() == 'mouse_move_abs':
            try:
                action['threshold'] = float(value)
            except Exception:
                action['threshold'] = 0.85

    def _on_image_click_toggled(self, checked: bool):
        _, _, action = self._get_selected_action_ref()
        if isinstance(action, dict) and self.action_type_combo.currentText() == 'mouse_move_abs':
            action['click_after'] = bool(checked)

    def _on_add_image_templates(self):
        cmd, row, action = self._get_selected_action_ref()
        if not action:
            return
        step_dir = self._ensure_step_image_dir(action)
        if step_dir is None:
            return
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, '이미지 템플릿 불러오기', str(step_dir), '이미지 파일 (*.png *.jpg *.jpeg *.bmp *.webp)'
        )
        if not file_paths:
            return
        added = 0
        errors = []
        for src in file_paths:
            try:
                dst = step_dir / os.path.basename(src)
                shutil.copy2(src, dst)
                added += 1
            except Exception as e:
                errors.append(f"{os.path.basename(src)}: {e}")
        self._refresh_image_template_list(action)
        msg = f"템플릿 {added}개 추가"
        if errors:
            msg += f"\n실패 {len(errors)}개: " + ", ".join(errors[:3]) + ("..." if len(errors) > 3 else "")
        self.status_label.setText(msg)

    def _on_delete_selected_templates(self):
        cmd, row, action = self._get_selected_action_ref()
        if not action:
            return
        step_dir = self._ensure_step_image_dir(action)
        if step_dir is None:
            return
        selected = [it for it in self.image_template_list.selectedItems() if it.flags() != Qt.ItemFlag.NoItemFlags]
        if not selected:
            QMessageBox.information(self, '삭제', '삭제할 템플릿을 선택하세요.')
            return
        for it in selected:
            name = it.data(Qt.ItemDataRole.UserRole) or it.text()
            try:
                (step_dir / name).unlink(missing_ok=True)
            except Exception:
                pass
        self._refresh_image_template_list(action)

    def _grab_region_bgr(self, region: dict):
        """절대 좌표 영역을 캡처하여 BGR numpy array로 반환."""
        try:
            import mss
            import numpy as np
            with mss.mss() as sct:
                monitor = {
                    'left': int(region['left']), 'top': int(region['top']),
                    'width': int(region['width']), 'height': int(region['height'])
                }
                shot = sct.grab(monitor)
            img = np.array(shot)  # BGRA
            return img[:, :, :3].copy()  # BGR
        except Exception as e:
            QMessageBox.critical(self, '캡처 오류', f'화면 캡처 실패: {e}')
            return None

    def _list_step_template_paths(self, action: dict) -> list[Path]:
        step_dir = self._ensure_step_image_dir(action)
        if step_dir is None:
            return []
        files = action.get('image_files') or []
        paths = []
        for name in files:
            p = step_dir / name
            if p.is_file():
                paths.append(p)
        return paths

    def _perform_image_match(self, action: dict):
        """이미지 매칭 수행. 성공 시 (True, (x,y), best_score, tpl_name), 실패 시 (False, None, best_score, None)."""
        try:
            import cv2
            import numpy as np
        except Exception as e:
            QMessageBox.critical(self, '의존성 오류', f'OpenCV가 필요합니다: {e}')
            return False, None, -1.0, None
        region = action.get('region')
        if not (isinstance(region, dict) and all(k in region for k in ('top','left','width','height'))):
            return False, None, -1.0, None
        bgr = self._grab_region_bgr(region)
        if bgr is None:
            return False, None, -1.0, None
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        tpl_paths = self._list_step_template_paths(action)
        if not tpl_paths:
            return False, None, -1.0, None
        best_score = -1.0
        best_loc = None
        best_sz = None
        best_name = None
        for p in tpl_paths:
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            h, w = img.shape[:2]
            if h <= 0 or w <= 0 or h > gray.shape[0] or w > gray.shape[1]:
                continue
            res = cv2.matchTemplate(gray, img, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
            if max_val > best_score:
                best_score = max_val
                best_loc = max_loc
                best_sz = (w, h)
                best_name = p.name
        threshold = float(action.get('threshold', 0.85))
        if best_score >= threshold and best_loc is not None and best_sz is not None:
            left, top = int(region['left']), int(region['top'])
            w, h = best_sz
            cx = left + int(best_loc[0] + w / 2)
            cy = top + int(best_loc[1] + h / 2)
            return True, (cx, cy), best_score, best_name
        return False, None, best_score, None

    def _on_test_image_matching(self):
        _, _, action = self._get_selected_action_ref()
        if not action:
            return
        ok, pos, score, name = self._perform_image_match(action)
        if ok:
            QMessageBox.information(self, '매칭 성공', f"{name} → 좌표 ({pos[0]}, {pos[1]}) | 점수 {score:.2f}")
        else:
            QMessageBox.information(self, '매칭 실패', f"영역/템플릿을 확인하세요. 최고 점수: {score:.2f}")

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

        # 구분선
        try:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFrameShadow(QFrame.Shadow.Sunken)
            right_layout.addWidget(sep)
        except Exception:
            pass

        # [신규] 긴급 정지 버튼 (모든 키 떼기)
        self.emergency_stop_btn = QPushButton(QIcon.fromTheme("process-stop"), " 긴급 정지 (모든 키 떼기)")
        try:
            self.emergency_stop_btn.setStyleSheet(
                "QPushButton { background-color: #c62828; color: white; font-weight: 700; padding: 8px; }"
                "QPushButton:hover { background-color: #b71c1c; }"
            )
        except Exception:
            pass
        self.emergency_stop_btn.clicked.connect(self._on_emergency_stop_clicked)
        right_layout.addWidget(self.emergency_stop_btn)

        clear_log_btn.clicked.connect(self.key_log_list.clear)

        return right_widget

    #  전역 키보드 리스너의 상태를 관리하는 메소드
    def _update_global_listener_state(self):
        base_listen = self.is_map_detection_running and self.log_checkbox.isChecked()
        visual_enabled = bool(self.keyboard_visual_checkbox.isChecked()) if self.keyboard_visual_checkbox else False
        should_listen = base_listen or (visual_enabled and self.is_map_detection_running)

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

    def _on_emergency_stop_clicked(self):
        """UI 하단 '긴급 정지' 버튼: 즉시 모든 키 해제 트리거."""
        try:
            if getattr(self, 'console_log_checkbox', None) and self.console_log_checkbox.isChecked():
                print("[AutoControl] UI 긴급정지 버튼 클릭 → 모든 키 떼기")
        except Exception:
            pass

        # 1) 매핑 기반 실행을 우선 시도
        if isinstance(self.mappings, dict) and '모든 키 떼기' in self.mappings:
            try:
                self.receive_control_command('모든 키 떼기', reason='ui:emergency_stop')
                if getattr(self, 'status_label', None):
                    self.status_label.setText("긴급 정지: 모든 키 떼기 실행")
                return
            except Exception:
                pass

        # 2) 폴백: 직접 전역 해제 + 라즈베리에 CLEAR_ALL 전송
        try:
            self.api_release_all_keys_global()
            if getattr(self, 'status_label', None):
                self.status_label.setText("긴급 정지: 전역 해제(폴백)")
        except Exception:
            pass

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

    def _activate_mapleland_window(self) -> bool:
        # 0) 대상 창 탐색
        try:
            candidate_windows = gw.getWindowsWithTitle('Mapleland')
        except Exception as exc:
            # UI 차단 없는 상태 메시지 업데이트만 수행
            if getattr(self, 'status_label', None):
                self.status_label.setText(f"창 탐색 오류: {exc}")
            return False

        target_window = None
        for window in candidate_windows:
            if not window:
                continue
            title = (getattr(window, 'title', '') or '').strip()
            if 'mapleland' in title.lower():
                target_window = window
                break

        if target_window is None:
            if getattr(self, 'status_label', None):
                self.status_label.setText("Mapleland 창을 찾을 수 없습니다.")
            return False

        # 공용 헬퍼
        def msleep(ms: int) -> None:
            try:
                QThread.msleep(int(ms))
            except Exception:
                time.sleep(max(float(ms) / 1000.0, 0.0))

        # Win32 준비
        try:
            import win32gui  # type: ignore
            import win32con  # type: ignore
            import win32api  # type: ignore
        except Exception:
            win32gui = None  # type: ignore
            win32con = None  # type: ignore
            win32api = None  # type: ignore

        hwnd = getattr(target_window, '_hWnd', None)

        # 최대 3회 재시도
        for attempt in range(3):
            # 1) pygetwindow 경로
            try:
                if target_window.isMinimized:
                    target_window.restore(); msleep(120)
                target_window.activate(); msleep(120)
            except Exception:
                pass

            # 2) Win32 강제 전면화(가능하면)
            if win32gui is not None and win32con is not None and hwnd:
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE); msleep(60)
                    # AttachThreadInput을 사용하여 포그라운드 제한 우회 (ALT 트릭 사용 안 함)
                    try:
                        import win32process  # type: ignore
                    except Exception:
                        win32process = None  # type: ignore
                    attached = False
                    try:
                        if win32api is not None and win32process is not None:
                            curr_tid = win32api.GetCurrentThreadId()
                            target_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
                            win32api.AttachThreadInput(curr_tid, target_tid, True)
                            attached = True
                        win32gui.SetForegroundWindow(hwnd)
                        msleep(30)
                        try:
                            win32gui.BringWindowToTop(hwnd)
                        except Exception:
                            pass
                    finally:
                        if attached and win32api is not None and win32process is not None:
                            try:
                                win32api.AttachThreadInput(curr_tid, target_tid, False)
                            except Exception:
                                pass
                    msleep(50)
                    try:
                        # TopMost 토글로 최전면 강제
                        win32gui.SetWindowPos(hwnd, -1, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                        msleep(40)
                        win32gui.SetWindowPos(hwnd, -2, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                    except Exception:
                        pass
                except Exception:
                    # 비차단: 예외는 무시하고 계속 확인
                    pass

            # 3) 성공 확인
            try:
                if win32gui is not None and hwnd:
                    fg = win32gui.GetForegroundWindow()
                    if int(fg) == int(hwnd):
                        if getattr(self, 'status_label', None):
                            self.status_label.setText(f"게임 창 활성화: '{target_window.title}'")
                        return True
            except Exception:
                # 확인 불가 시 소폭 대기 후 다음 단계 진행
                pass

            try:
                if getattr(target_window, 'isActive', False):
                    if getattr(self, 'status_label', None):
                        self.status_label.setText(f"게임 창 활성화(추정): '{target_window.title}'")
                    return True
            except Exception:
                pass

            msleep(120)

        # 최종 실패
        if getattr(self, 'status_label', None):
            self.status_label.setText("게임 창 활성화 실패(재시도 완료)")
        return False

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

    def _selected_action_rows(self) -> list[int]:
        items = self.action_sequence_list.selectedItems()
        if not items:
            return []
        rows = [self.action_sequence_list.row(item) for item in items]
        return sorted(index for index in rows if index >= 0)

    def _select_action_rows(self, rows: list[int]) -> None:
        self.action_sequence_list.blockSignals(True)
        self.action_sequence_list.clearSelection()
        for row in rows:
            item = self.action_sequence_list.item(row)
            if item:
                item.setSelected(True)
        if rows:
            self.action_sequence_list.setCurrentRow(rows[-1])
        self.action_sequence_list.blockSignals(False)
        self.on_action_step_selected()

    def on_action_step_selected(self):
        selected_rows = self._selected_action_rows()
        if len(selected_rows) != 1:
            self.editor_group.setEnabled(False)
            return
        row = selected_rows[0]
        item = self.action_sequence_list.item(row)
        if not item:
            self.editor_group.setEnabled(False)
            return

        command_item = self._current_command_item()
        if not command_item: return

        command_text = command_item.text()
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
        is_mouse_move_abs = (action_type == 'mouse_move_abs')
        is_mouse_click = action_type in ['mouse_left_click', 'mouse_right_click', 'mouse_double_click']
        
        self.key_combo.setVisible(is_key_based)
        self.delay_widget.setVisible(is_delay)
        self.mouse_move_widget.setVisible(is_mouse_move_abs)
        
        form_layout = self.editor_group.layout()
        label_for_key = form_layout.labelForField(self.key_combo)
        if label_for_key: label_for_key.setVisible(is_key_based)
            
        label_for_delay = form_layout.labelForField(self.delay_widget)
        if label_for_delay: label_for_delay.setVisible(is_delay)
        label_for_mouse = form_layout.labelForField(self.mouse_move_widget)
        if label_for_mouse: label_for_mouse.setVisible(is_mouse_move_abs)

        if hasattr(self, 'force_checkbox'):
            # force는 키 기반에서만 사용
            self.force_checkbox.setVisible(is_key_based)
            self.force_checkbox.setEnabled(is_key_based)
            label_for_force = form_layout.labelForField(self.force_checkbox)
            if label_for_force:
                label_for_force.setVisible(is_key_based)

        # 마우스 모드에 따른 입력 활성화 갱신
        self._update_mouse_move_mode_enabled()

    def _update_editor_panel(self, action_data):
        self.action_type_combo.blockSignals(True); self.key_combo.blockSignals(True); self.min_delay_spin.blockSignals(True); self.max_delay_spin.blockSignals(True)
        action_type = action_data.get("type", "press")
        self.action_type_combo.setCurrentText(action_type)
        self._on_editor_type_changed(0) 
        if action_type in ['press', 'release', 'release_specific']:
            self.key_combo.setCurrentText(action_data.get("key_str", "Key.space"))
            if hasattr(self, 'force_checkbox'):
                self.force_checkbox.blockSignals(True)
                self.force_checkbox.setChecked(bool(action_data.get("force", False)))
                self.force_checkbox.blockSignals(False)
        elif action_type == 'delay':
            self.min_delay_spin.setValue(action_data.get("min_ms", 0))
            self.max_delay_spin.setValue(action_data.get("max_ms", 0))
            if hasattr(self, 'force_checkbox'):
                self.force_checkbox.blockSignals(True)
                self.force_checkbox.setChecked(False)
                self.force_checkbox.blockSignals(False)
        elif action_type == 'mouse_move_abs':
            self.mouse_x_spin.setValue(int(action_data.get("x", 0)))
            self.mouse_y_spin.setValue(int(action_data.get("y", 0)))
            self.mouse_dur_spin.setValue(int(action_data.get("dur_ms", 240)))
            mode = str(action_data.get("mode", "coord"))
            self.mouse_mode_coord.blockSignals(True); self.mouse_mode_image.blockSignals(True)
            if mode == 'image':
                self.mouse_mode_image.setChecked(True)
                self.mouse_mode_coord.setChecked(False)
            else:
                self.mouse_mode_coord.setChecked(True)
                self.mouse_mode_image.setChecked(False)
            self.mouse_mode_coord.blockSignals(False); self.mouse_mode_image.blockSignals(False)
            self._update_mouse_move_mode_enabled()
            # 이미지 설정 UI 반영
            try:
                threshold = float(action_data.get('threshold', 0.85))
            except Exception:
                threshold = 0.85
            self.image_threshold_spin.blockSignals(True)
            self.image_threshold_spin.setValue(threshold)
            self.image_threshold_spin.blockSignals(False)
            click_after = bool(action_data.get('click_after', False))
            try:
                self.image_click_checkbox.blockSignals(True)
                self.image_click_checkbox.setChecked(click_after)
                self.image_click_checkbox.blockSignals(False)
            except Exception:
                pass
            region = action_data.get('region') or {}
            if isinstance(region, dict) and all(k in region for k in ('top','left','width','height')):
                self.image_region_label.setStyleSheet("")
                self.image_region_label.setText(f"({region.get('left')},{region.get('top')}) {region.get('width')}x{region.get('height')}")
            else:
                self.image_region_label.setStyleSheet("color: #aaa;")
                self.image_region_label.setText("(영역 미설정)")
            self._refresh_image_template_list(action_data)
            if hasattr(self, 'force_checkbox'):
                self.force_checkbox.blockSignals(True)
                self.force_checkbox.setChecked(False)
                self.force_checkbox.blockSignals(False)
        else:
            # mouse click types
            if hasattr(self, 'force_checkbox'):
                self.force_checkbox.blockSignals(True)
                self.force_checkbox.setChecked(False)
                self.force_checkbox.blockSignals(False)
        self.action_type_combo.blockSignals(False); self.key_combo.blockSignals(False); self.min_delay_spin.blockSignals(False); self.max_delay_spin.blockSignals(False)

    def _update_action_from_editor(self, _=None):
        command_item = self._current_command_item()
        if not command_item:
            return
        selected_rows = self._selected_action_rows()
        if len(selected_rows) != 1:
            return
        row = selected_rows[0]
        action_item = self.action_sequence_list.item(row)
        if not action_item:
            return
        command_text = command_item.text()
        action_type = self.action_type_combo.currentText()
        # 기존 데이터 머지(특히 mouse/image 부가설정 보존)
        existing = {}
        try:
            existing = dict(self.mappings.get(command_text, [])[row])
        except Exception:
            existing = {}
        new_action_data = {"type": action_type}
        if action_type in ['press', 'release', 'release_specific']:
            new_action_data["key_str"] = self.key_combo.currentText()
            if hasattr(self, 'force_checkbox') and self.force_checkbox.isChecked():
                new_action_data["force"] = True
        elif action_type == 'delay':
            new_action_data["min_ms"] = self.min_delay_spin.value(); new_action_data["max_ms"] = self.max_delay_spin.value()
        elif action_type == 'mouse_move_abs':
            new_action_data["x"] = int(self.mouse_x_spin.value())
            new_action_data["y"] = int(self.mouse_y_spin.value())
            new_action_data["dur_ms"] = int(self.mouse_dur_spin.value())
            new_action_data["mode"] = 'image' if self.mouse_mode_image.isChecked() else 'coord'
            # 부가 설정 보존
            for k in ("threshold", "region", "image_id", "image_files", "click_after"):
                if k in existing and k not in new_action_data:
                    new_action_data[k] = existing[k]
            # 현재 클릭 토글 UI값 반영
            try:
                new_action_data["click_after"] = bool(self.image_click_checkbox.isChecked())
            except Exception:
                pass
        self.mappings[command_text][row] = new_action_data
        self._update_action_item_text(action_item, new_action_data)

    def _update_action_item_text(self, item, action_data):
        step_text = ""
        type = action_data.get("type")
        force_prefix = "[강제] " if bool(action_data.get("force", False)) else ""
        if type == "press": step_text = f"{force_prefix}누르기: {action_data.get('key_str', 'N/A')}"
        elif type == "release": step_text = f"{force_prefix}떼기: {action_data.get('key_str', 'N/A')}"
        elif type == "delay": step_text = f"지연: {action_data.get('min_ms', 0)}ms ~ {action_data.get('max_ms', 0)}ms"
        elif type == "release_all": step_text = "모든 키 떼기"
        elif type == "release_specific": step_text = f"{force_prefix}특정 키 떼기: {action_data.get('key_str', 'N/A')}"
        elif type == "mouse_move_abs": step_text = f"마우스 이동(절대): x={action_data.get('x', 0)}, y={action_data.get('y', 0)}, dur={action_data.get('dur_ms', 0)}ms"
        
        # 모드 표시(좌표/이미지)
        if type == "mouse_move_abs":
            mode = str(action_data.get('mode', 'coord'))
            tag = "[좌표]" if mode == 'coord' else "[이미지]"
            if mode == 'image' and bool(action_data.get('click_after', False)):
                step_text = f"{step_text} {tag} [클릭]"
            else:
                step_text = f"{step_text} {tag}"
        elif type == "mouse_left_click": step_text = "마우스 좌클릭"
        elif type == "mouse_right_click": step_text = "마우스 우클릭"
        elif type == "mouse_double_click": step_text = "마우스 더블클릭"
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
            # (신규) 이미지 스텝 폴더 정리(참조 카운트 기반)
            try:
                # 전체 참조 카운트 수집
                id_counts: dict[str, int] = {}
                for seq_name, seq in self.mappings.items():
                    for st in (seq or []):
                        if isinstance(st, dict) and st.get('type') == 'mouse_move_abs' and str(st.get('mode','coord')) == 'image':
                            iid = st.get('image_id')
                            if iid:
                                id_counts[iid] = id_counts.get(iid, 0) + 1
                # 삭제 대상 명령 시퀀스 내 id 카운트
                del_counts: dict[str, int] = {}
                for st in (self.mappings.get(command_text, []) or []):
                    if isinstance(st, dict) and st.get('type') == 'mouse_move_abs' and str(st.get('mode','coord')) == 'image':
                        iid = st.get('image_id')
                        if iid:
                            del_counts[iid] = del_counts.get(iid, 0) + 1
                # 디렉터리 삭제: 다른 명령에서 더 이상 참조하지 않을 경우만
                base = _resolve_mouse_image_base_dir()
                for iid, delc in del_counts.items():
                    total = id_counts.get(iid, 0)
                    if total <= delc:
                        p = base / f"img-{iid}"
                        if p.exists():
                            shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
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
        new_index = self.action_sequence_list.count() - 1
        if new_index >= 0:
            self._select_action_rows([new_index])

    def remove_action_step(self):
        command_item = self._current_command_item()
        if not command_item:
            return
        selected_rows = self._selected_action_rows()
        if not selected_rows:
            return
        command_text = command_item.text()
        sequence = self.mappings.get(command_text, [])
        # 삭제 전 이미지 스텝 디렉터리 정리(참조 카운트 기반)
        def _count_image_ids() -> dict[str, int]:
            counts: dict[str, int] = {}
            try:
                for seq in self.mappings.values():
                    for st in (seq or []):
                        if isinstance(st, dict) and st.get('type') == 'mouse_move_abs' and str(st.get('mode','coord')) == 'image':
                            iid = st.get('image_id')
                            if iid:
                                counts[iid] = counts.get(iid, 0) + 1
            except Exception:
                pass
            return counts
        id_counts_before = _count_image_ids()
        delete_counts: dict[str, int] = {}
        for row in selected_rows:
            if 0 <= row < len(sequence):
                st = sequence[row]
                if isinstance(st, dict) and st.get('type') == 'mouse_move_abs' and str(st.get('mode','coord')) == 'image':
                    iid = st.get('image_id')
                    if iid:
                        delete_counts[iid] = delete_counts.get(iid, 0) + 1
        for row in reversed(selected_rows):
            if 0 <= row < len(sequence):
                del sequence[row]
        # 실제 디렉터리 삭제(다른 스텝에서 더 이상 참조하지 않는 경우만)
        try:
            base = _resolve_mouse_image_base_dir()
            for iid, delc in delete_counts.items():
                total = id_counts_before.get(iid, 0)
                if total <= delc and iid:
                    p = base / f"img-{iid}"
                    if p.exists():
                        shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass
        self._populate_action_sequence_list(command_text)
        if sequence:
            next_row = min(selected_rows[0], len(sequence) - 1)
            self._select_action_rows([next_row])
        else:
            self.action_sequence_list.clearSelection()
            self.editor_group.setEnabled(False)

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
        command_item = self._current_command_item()
        if not command_item:
            return
        selected_rows = self._selected_action_rows()
        if not selected_rows:
            return
        command_text = command_item.text()
        sequence = self.mappings[command_text]
        if direction < 0:
            if selected_rows[0] == 0:
                return
            for row in selected_rows:
                sequence[row - 1], sequence[row] = sequence[row], sequence[row - 1]
            new_rows = [row - 1 for row in selected_rows]
        elif direction > 0:
            if selected_rows[-1] == len(sequence) - 1:
                return
            for row in reversed(selected_rows):
                sequence[row], sequence[row + 1] = sequence[row + 1], sequence[row]
            new_rows = [row + 1 for row in selected_rows]
        else:
            return
        self._populate_action_sequence_list(command_text)
        self._select_action_rows(new_rows)

    def copy_sequence_to_clipboard(self):
        """현재 선택된 명령 프로필의 액션 시퀀스를 JSON 문자열로 클립보드에 복사합니다."""
        command_item = self._current_command_item()
        if not command_item:
            QMessageBox.warning(self, "알림", "복사할 명령 프로필을 선택하세요.")
            return

        command_text = command_item.text()
        full_sequence = self.mappings.get(command_text, [])
        selected_rows = self._selected_action_rows()
        if selected_rows:
            sequence = [copy.deepcopy(full_sequence[row]) for row in selected_rows if 0 <= row < len(full_sequence)]
        else:
            sequence = copy.deepcopy(full_sequence)

        if not sequence:
            QMessageBox.information(self, "알림", "복사할 액션이 선택되지 않았습니다.")
            return

        try:
            # 보기 좋게 들여쓰기된 JSON 문자열로 변환
            sequence_text = json.dumps(sequence, indent=4, ensure_ascii=False)
            
            # PyQt의 클립보드 기능 사용
            clipboard = QApplication.clipboard()
            clipboard.setText(sequence_text)
            self._sequence_clipboard_cache = sequence
            
            copied_count = len(sequence)
            if selected_rows:
                self.status_label.setText(f"'{command_text}' 시퀀스에서 선택한 {copied_count}개 액션을 복사했습니다.")
            else:
                self.status_label.setText(f"'{command_text}' 시퀀스 전체 {copied_count}개 액션을 복사했습니다.")
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
        sequence = self.mappings.setdefault(command_text, [])
        selected_rows = self._selected_action_rows()
        if selected_rows:
            insert_at = selected_rows[0]
            for row in reversed(selected_rows):
                if 0 <= row < len(sequence):
                    del sequence[row]
        else:
            insert_at = len(sequence)

        for offset, action in enumerate(sequence_data):
            sequence.insert(insert_at + offset, copy.deepcopy(action))

        self._populate_action_sequence_list(command_text)
        new_rows = list(range(insert_at, insert_at + len(sequence_data)))
        if new_rows:
            self._select_action_rows(new_rows)
        else:
            self.action_sequence_list.clearSelection()
        self.status_label.setText(f"'{command_text}' 시퀀스에 {len(sequence_data)}개 액션을 붙여넣었습니다.")

    # --- 시리얼 통신 및 명령 실행 ---
    def connect_to_pi(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("[AutoControl] 기존 시리얼 연결을 해제했습니다.")
        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            try:
                # 일부 환경에서 필요
                self.ser.dtr = True
                self.ser.rts = True
            except Exception:
                pass
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
        # (보강) Ctrl 조합이 기록될 때 비가시 제어문자(예: '\x16' = ^V)로 들어오는 경우를 영문자로 정규화
        #  - \x01..\x1A  =>  'a'..'z' 로 매핑하여 HID 전송 가능하게 함
        try:
            if isinstance(key_str, str) and len(key_str) == 1:
                code = ord(key_str)
                if 1 <= code <= 26:
                    # ^A(1)->'a'(97), ^B(2)->'b', ... ^Z(26)->'z'
                    return chr(ord('a') + code - 1)
        except Exception:
            pass
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
        elif command == CMD_CLEAR_ALL:
            # 키코드 없이 CLEAR_ALL 명령(0x03, 0x00) 전송
            try:
                self.ser.write(bytes([CMD_CLEAR_ALL, 0x00]))
                # 전역 상태/시각 초기화 및 UI 리셋
                self.last_sent_timestamps.clear()
                try:
                    self.keyboard_state_reset.emit()
                except Exception:
                    pass
                if getattr(self, 'console_log_checkbox', None) and self.console_log_checkbox.isChecked():
                    print("[AutoControl] CLEAR_ALL sent")
            except serial.SerialException as e:
                print(f"[AutoControl] CLEAR_ALL 전송 실패: {e}")
                self.connect_to_pi()

    # ---------------------------
    # Mouse helpers (COM transmit)
    # ---------------------------
    def _send_mouse_smooth_move(self, dx_counts: int, dy_counts: int, dur_ms: int) -> bool:
        if not self.ser or not self.ser.is_open:
            return False
        # int16 LE 범위 클램프
        def clamp16(v: int) -> int:
            return max(-32768, min(32767, int(v)))
        dx = clamp16(dx_counts)
        dy = clamp16(dy_counts)
        dur = max(10, min(5000, int(dur_ms)))
        try:
            payload = bytes([MOUSE_SMOOTH_MOVE]) + struct.pack('<hhh', dx, dy, dur)
            self.ser.write(payload)
            return True
        except Exception as e:
            print(f"[AutoControl] 마우스 이동 전송 실패: {e}")
            return False

    def _send_mouse_click_cmd(self, which: str) -> bool:
        if not self.ser or not self.ser.is_open:
            return False
        cmd = None
        if which == 'left':
            cmd = MOUSE_LEFT_CLICK
        elif which == 'right':
            cmd = MOUSE_RIGHT_CLICK
        elif which == 'double':
            cmd = MOUSE_DOUBLE_CLICK
        if cmd is None:
            return False
        try:
            self.ser.write(bytes([cmd]))
            return True
        except Exception as e:
            print(f"[AutoControl] 마우스 클릭 전송 실패: {e}")
            return False

    # ---------------------------
    # Cursor helpers (Windows)
    # ---------------------------
    def _get_cursor_pos(self) -> tuple[int, int]:
        try:
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return int(pt.x), int(pt.y)
        except Exception:
            pass
        return (0, 0)

    # ---------------------------
    # EPP guard helpers
    # ---------------------------
    def _epp_guard_acquire(self, tag: str) -> bool:
        """Acquire EPP OFF for a sequence. Returns True on success.
        Uses refcount so nested acquires are safe. Windows only.
        """
        if sys.platform != 'win32':
            # 비Windows에서는 스킵 (정확도 저하 가능성 경고만)
            self.log_generated.emit("[EPP] Windows가 아니므로 EPP 토글을 건너뜁니다.", "orange")
            return True
        try:
            if self._epp_guard_refcount == 0:
                script_path = self._resolve_epp_toggle_script()
                proc = subprocess.run([sys.executable, str(script_path), 'off'], capture_output=True, text=True)
                if proc.returncode != 0:
                    self.log_generated.emit(f"[EPP] OFF 실패: {proc.stdout or proc.stderr}", "red")
                    return False
                self.log_generated.emit("[EPP] OFF 적용(획득)", "cyan")
            self._epp_guard_refcount += 1
            return True
        except Exception as e:
            self.log_generated.emit(f"[EPP] OFF 예외: {e}", "red")
            return False

    def _epp_guard_release(self, tag: str) -> None:
        if sys.platform != 'win32':
            return
        try:
            if self._epp_guard_refcount > 0:
                self._epp_guard_refcount -= 1
                if self._epp_guard_refcount == 0:
                    script_path = self._resolve_epp_toggle_script()
                    proc = subprocess.run([sys.executable, str(script_path), 'restore'], capture_output=True, text=True)
                    if proc.returncode == 0:
                        self.log_generated.emit("[EPP] 복구(해제)", "cyan")
                    else:
                        self.log_generated.emit(f"[EPP] 복구 실패: {proc.stdout or proc.stderr}", "red")
        except Exception as e:
            self.log_generated.emit(f"[EPP] 복구 예외: {e}", "red")

    def _resolve_epp_toggle_script(self) -> str:
        """Resolve the path to epp_toggle.py with overrides.
        Priority:
          1) env MAPLE_EPP_TOGGLE
          2) G:\\Coding\\Project_Maple\\src\\epp_toggle.py (user-requested)
          3) repo scripts/epp_toggle.py
          4) repo src/epp_toggle.py
        Returns best-effort path (may not exist).
        """
        try:
            env_p = os.environ.get('MAPLE_EPP_TOGGLE')
            if env_p and os.path.exists(env_p):
                return env_p
        except Exception:
            pass
        candidates = [
            r"G:\\Coding\\Project_Maple\\src\\epp_toggle.py",
            str((BASE_DIR / 'scripts' / 'epp_toggle.py').resolve()),
            str((BASE_DIR / 'src' / 'epp_toggle.py').resolve()),
        ]
        for c in candidates:
            try:
                if os.path.exists(c):
                    return c
            except Exception:
                pass
        return candidates[0]

    def _sequence_contains_mouse(self, sequence: list) -> bool:
        try:
            for step in sequence or []:
                t = (step or {}).get('type')
                if t in ('mouse_move_abs', 'mouse_left_click', 'mouse_right_click', 'mouse_double_click'):
                    return True
        except Exception:
            pass
        return False

    def _get_key_set_for_owner(self, owner: str) -> set:
        key_set = self.sequence_owned_keys.get(owner)
        if key_set is None:
            key_set = set()
            self.sequence_owned_keys[owner] = key_set
        return key_set

    def _press_key_for_owner(self, owner: str, key_object, *, force: bool = False) -> bool:
        if key_object is None:
            return False

        # Quiet 모드: 허용 오너 외 입력 차단
        try:
            if self._quiet_until_ts > 0.0 and time.time() < self._quiet_until_ts:
                if owner not in self._quiet_whitelist:
                    return False
        except Exception:
            pass

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

        # Quiet 모드: 허용 오너 외 입력 차단
        try:
            if self._quiet_until_ts > 0.0 and time.time() < self._quiet_until_ts:
                if owner not in self._quiet_whitelist:
                    return False
        except Exception:
            pass

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

        if force:
            # 강제 해제 시에는 다른 소유자와 글로벌 상태도 함께 정리해야 이후 입력이 정상 동작
            for owner_set in list(self.sequence_owned_keys.values()):
                owner_set.discard(key_object)

            self.global_key_counts.pop(key_object, None)
            self._send_command(CMD_RELEASE, key_object)

            # 기본 해제 경로와 동일하게 해제됐음을 반환
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
            msg = f"{log_action} {self._translate_key_for_logging(self._key_obj_to_str(key_object))}"
            if self.current_command_source_tag:
                msg = f"{self.current_command_source_tag} {msg}"
            self.log_generated.emit(msg, "white")
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

    def _send_clear_all(self) -> None:
        """라즈베리파이에 프로토콜 CLEAR_ALL(0x03)을 전송하여 상태를 강제 초기화."""
        if not self.ser or not self.ser.is_open:
            return
        # _send_command가 CLEAR_ALL 분기 처리함
        self._send_command(CMD_CLEAR_ALL, None)

    # ===================
    # 공개 API (텔레그램 연동용)
    # ===================
    def api_is_serial_ready(self) -> bool:
        """시리얼 연결 준비 상태 반환."""
        try:
            return bool(self.ser and getattr(self.ser, 'is_open', False))
        except Exception:
            return False

    def api_activate_maple_window(self) -> bool:
        """게임 창을 전면 활성화 (실패 시 False)."""
        try:
            return bool(self._activate_mapleland_window())
        except Exception:
            return False

    def api_release_all_keys_global(self) -> None:
        """모든 오너의 모든 키를 강제 해제한다."""
        try:
            for owner, key_set in list(self.sequence_owned_keys.items()):
                for key_obj in list(key_set):
                    try:
                        self._release_key_for_owner(owner, key_obj, force=True)
                    except Exception:
                        pass
            self.global_key_counts.clear()
            try:
                self.keyboard_state_reset.emit()
            except Exception:
                pass
            # 라즈베리 측 상태도 확실히 초기화
            try:
                self._send_clear_all()
            except Exception:
                pass
        except Exception:
            pass

    def api_set_quiet_mode(self, duration_ms: int, whitelist_owners: set[str] | None = None) -> None:
        """quiet 모드 설정: duration_ms 동안 whitelist 외 입력 차단."""
        if duration_ms <= 0:
            self._quiet_until_ts = 0.0
            self._quiet_whitelist = set(whitelist_owners or set())
            return
        try:
            self._quiet_until_ts = time.time() + float(duration_ms) / 1000.0
            self._quiet_whitelist = set(whitelist_owners or set())
        except Exception:
            self._quiet_until_ts = 0.0
            self._quiet_whitelist = set()

    def api_press_key(self, key_repr: str, *, owner: str = 'CHAT', force: bool = False) -> bool:
        """문자열 키 표현을 눌러 전송한다. 예: 'Key.enter', 'Key.ctrl', 'v'"""
        try:
            key_obj = self._str_to_key_obj(key_repr)
            return bool(self._press_key_for_owner(owner, key_obj, force=force))
        except Exception:
            return False

    def api_release_key(self, key_repr: str, *, owner: str = 'CHAT', force: bool = False) -> bool:
        """문자열 키 표현을 떼어 전송한다."""
        try:
            key_obj = self._str_to_key_obj(key_repr)
            return bool(self._release_key_for_owner(owner, key_obj, force=force))
        except Exception:
            return False

    def _abort_sequence_for_recovery(self):
        try:
            self.sequence_timer.stop()
        except Exception:
            pass
        try:
            self.sequence_watchdog.stop()
        except Exception:
            pass
        self._release_all_keys(force=True)
        self.last_sent_timestamps.clear()
        self.is_sequence_running = False
        self.is_processing_step = False
        self.current_sequence = []
        self.current_sequence_index = 0
        self.is_first_key_event_in_sequence = True

    def _reconnect_serial_for_recovery(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.connect_to_pi()

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

        if not self._activate_mapleland_window():
            return
        
        self.status_label.setText("2초 후 테스트를 시작합니다...")
        QTimer.singleShot(2000, lambda: self._start_sequence_execution(sequence, f"TEST: {command_text}", is_test=True))
    
    # --- [핵심 수정] time.sleep()을 QTimer 기반의 비동기 방식으로 변경 ---
    def _start_sequence_execution(self, sequence, command_name, is_test=False, reason=None, source_tag=None):
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

        # EPP 가드: 시퀀스에 마우스 명령이 있으면 필수로 OFF 적용
        try:
            if self._sequence_contains_mouse(sequence):
                ok = self._epp_guard_acquire(tag=f"main:{command_name}")
                if not ok:
                    # 시작 거부
                    msg = f"[EPP] 적용 실패로 '{command_name}' 실행을 중단합니다."
                    if source_tag:
                        msg = f"{source_tag} {msg}"
                    self.log_generated.emit(msg, "red")
                    return
                self._epp_guard_main_active = True
        except Exception as e:
            self.log_generated.emit(f"[EPP] 가드 준비 중 예외: {e}", "red")
            return

        # 이제 새 시퀀스 초기화
        self.status_label.setText(f"'{command_name}' 실행 중.")
        if self.console_log_checkbox.isChecked():
            print(f"--- [AutoControl] 실행 시작: '{command_name}' ---")

        self.current_sequence = sequence
        self.current_command_name = command_name
        self.current_command_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
        raw_reason = self.current_command_reason
        display_reason = raw_reason
        if raw_reason:
            if raw_reason.startswith('status:'):
                parts = raw_reason.split(':')
                resource = parts[1].strip().upper() if len(parts) >= 2 else ''
                percent_text = ''
                if len(parts) >= 3 and parts[2].strip():
                    try:
                        percent_value = int(round(float(parts[2].strip())))
                        percent_text = f" ({percent_value}%)"
                    except ValueError:
                        percent_text = ''
                label = resource or 'STATUS'
                display_reason = f"Status: {label}{percent_text}"
            elif raw_reason.startswith('primary_release'):
                parts = raw_reason.split('|', 1)
                display_reason = parts[1].strip() if len(parts) == 2 else ''
        display_reason = self._translate_reason_for_logging(raw_reason, display_reason)
        self.current_command_reason_display = display_reason or None
        self.is_test_mode = is_test
        self.current_sequence_index = 0
        self.is_sequence_running = True
        self.is_first_key_event_in_sequence = True
        self.last_command_start_time = time.time()
        # [NEW] 출처 태그 저장 (모니터링/자동제어 로그에 prefix로 표시)
        self.current_command_source_tag = source_tag if isinstance(source_tag, str) else None
        
        if self.current_command_reason_display:
            start_msg = f"--- (시작) {self.current_command_name} -원인: {self.current_command_reason_display} ---"
        else:
            start_msg = f"--- (시작) {self.current_command_name} ---"              # <<< (추가) UI에 '(시작)' 로그를 즉시 남기기 위해 생성
        if self.current_command_source_tag:
            start_msg = f"{self.current_command_source_tag} {start_msg}"
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
                if self.current_command_reason_display:
                    log_msg = f"--- (완료) {self.current_command_name} -원인: {self.current_command_reason_display} ---"
                else:
                    log_msg = f"--- (완료) {self.current_command_name} ---"
                if self.current_command_source_tag:
                    log_msg = f"{self.current_command_source_tag} {log_msg}"
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
                    msg = f"오류: 알 수 없는 키 '{step.get('key_str')}'"
                    if self.current_command_source_tag:
                        msg = f"{self.current_command_source_tag} {msg}"
                    self.log_generated.emit(msg, "red")
                elif action_type == "press":
                    force_requested = bool(step.get("force", False))
                    self._press_key(key_obj, force=force_requested)
                else:  # release
                    force_requested = bool(step.get("force", False))
                    released = self._release_key(key_obj, force=force_requested)
                    if released:
                        log_label = "(떼기-forced)" if force_requested else "(떼기)"
                        color = "red" if force_requested else "white"
                        msg = f"{log_label} {self._translate_key_for_logging(step.get('key_str'))}"
                        if self.current_command_source_tag:
                            msg = f"{self.current_command_source_tag} {msg}"
                        self.log_generated.emit(msg, color)
                    else:
                        if force_requested:
                            msg = f"(떼기-forced) {self._translate_key_for_logging(step.get('key_str'))}"
                            if self.current_command_source_tag:
                                msg = f"{self.current_command_source_tag} {msg}"
                            self.log_generated.emit(msg, "red")
                        else:
                            if self.console_log_checkbox.isChecked():
                                print(f"[AutoControl] RELEASE skipped (not held) -> 강제 릴리즈 시도: {key_obj}")
                            self._release_key(key_obj, force=True)
                            msg = f"(떼기-forced) {self._translate_key_for_logging(step.get('key_str'))}"
                            if self.current_command_source_tag:
                                msg = f"{self.current_command_source_tag} {msg}"
                            self.log_generated.emit(msg, "red")

            elif action_type == "delay":
                min_ms = step.get("min_ms", 0)
                max_ms = step.get("max_ms", 0)
                if min_ms >= max_ms: delay_ms = min_ms
                else:
                    mean = (min_ms + max_ms) / 2
                    std_dev = (max_ms - min_ms) / 6
                    delay_ms = int(max(min(random.gauss(mean, std_dev), max_ms), min_ms))
                msg = f"(대기) {delay_ms}ms"
                if self.current_command_source_tag:
                    msg = f"{self.current_command_source_tag} {msg}"
                self.log_generated.emit(msg, "gray")
            
            elif action_type == "mouse_move_abs":
                # 이미지/좌표 모드 분기
                mode = str(step.get('mode', 'coord'))
                if mode == 'image':
                    ok, pos, score, name = self._perform_image_match(step)
                    if ok and pos:
                        try:
                            dur = int(step.get('dur_ms', 240))
                        except Exception:
                            dur = 240
                        tx, ty = int(pos[0]), int(pos[1])
                        cx, cy = self._get_cursor_pos()
                        dx = int(tx) - int(cx)
                        dy = int(ty) - int(cy)
                        sent = self._send_mouse_smooth_move(dx, dy, dur)
                        label = f"(마우스 이동[이미지]: {name} score={score:.2f} → Δ=({dx},{dy}), dur={dur}ms)"
                        if self.current_command_source_tag:
                            label = f"{self.current_command_source_tag} {label}"
                        self.log_generated.emit(label, "white" if sent else "red")
                        # (신규) 클릭 포함이 체크된 경우에만 이동 후 클릭
                        if bool(step.get('click_after', False)):
                            try:
                                extra_ms = random.randint(10, 30)
                                QTimer.singleShot(dur + extra_ms, lambda: self._send_mouse_click_cmd('left'))
                            except Exception:
                                pass
                    else:
                        # 매칭 실패 → 시퀀스 중지 및 로그 출력
                        self.sequence_watchdog.stop()
                        msg = "이미지 매칭 실패: 시퀀스를 중지합니다."
                        if self.current_command_source_tag:
                            msg = f"{self.current_command_source_tag} {msg}"
                        self.log_generated.emit(msg, "red")
                        self._notify_sequence_completed(False)
                        return
                else:
                    # 절대좌표 목표 → 현재 좌표 → Δ 계산 후 전송. 자동 대기 없음.
                    try:
                        tx = int(step.get('x', 0)); ty = int(step.get('y', 0))
                        dur = int(step.get('dur_ms', 240))
                    except Exception:
                        tx, ty, dur = 0, 0, 240
                    cx, cy = self._get_cursor_pos()
                    dx = int(tx) - int(cy)
                    dy = int(ty) - int(cy)
                    # [버그 수정] dx 계산 시 cx 사용
                    dx = int(tx) - int(cx)
                    sent = self._send_mouse_smooth_move(dx, dy, dur)
                    label = f"(마우스 이동: abs→Δ=({dx},{dy}), dur={dur}ms)"
                    if self.current_command_source_tag:
                        label = f"{self.current_command_source_tag} {label}"
                    self.log_generated.emit(label, "white" if sent else "red")

            elif action_type == "mouse_left_click":
                sent = self._send_mouse_click_cmd('left')
                label = "(마우스 좌클릭)"
                if self.current_command_source_tag:
                    label = f"{self.current_command_source_tag} {label}"
                self.log_generated.emit(label, "white" if sent else "red")

            elif action_type == "mouse_right_click":
                sent = self._send_mouse_click_cmd('right')
                label = "(마우스 우클릭)"
                if self.current_command_source_tag:
                    label = f"{self.current_command_source_tag} {label}"
                self.log_generated.emit(label, "white" if sent else "red")

            elif action_type == "mouse_double_click":
                sent = self._send_mouse_click_cmd('double')
                label = "(마우스 더블클릭)"
                if self.current_command_source_tag:
                    label = f"{self.current_command_source_tag} {label}"
                self.log_generated.emit(label, "white" if sent else "red")

            elif action_type == "release_all":
                self._release_all_keys(force=True)
                # '모든 키 떼기' 명령일 때 라즈베리에 CLEAR_ALL 송신으로 하드 초기화
                try:
                    if (self.current_command_name or "").strip() == "모든 키 떼기":
                        self._send_clear_all()
                except Exception:
                    pass
                if self.current_command_reason_display:
                    msg = f"(모든 키 떼기) -원인: {self.current_command_reason_display}"
                else:
                    msg = "(모든 키 떼기)"
                if self.current_command_source_tag:
                    msg = f"{self.current_command_source_tag} {msg}"
                self.log_generated.emit(msg, "white")

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
            msg = f"오류: _process_next_step 예외 발생 - {e}"
            if self.current_command_source_tag:
                msg = f"{self.current_command_source_tag} {msg}"
            self.log_generated.emit(msg, "red")
            self._release_all_keys(force=True)
            self.sequence_watchdog.stop()
            self._notify_sequence_completed(False)
        finally:
            self.is_processing_step = False

    def _start_parallel_sequence(self, sequence, command_name, reason=None, source_tag=None):
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
        reason_display = clean_reason
        if clean_reason:
            if clean_reason.startswith('status:'):
                parts = clean_reason.split(':')
                resource = parts[1].strip().upper() if len(parts) >= 2 else ''
                percent_text = ''
                if len(parts) >= 3 and parts[2].strip():
                    try:
                        percent_value = int(round(float(parts[2].strip())))
                        percent_text = f" ({percent_value}%)"
                    except ValueError:
                        percent_text = ''
                label = resource or 'STATUS'
                reason_display = f"Status: {label}{percent_text}"
            elif clean_reason.startswith('primary_release'):
                parts = clean_reason.split('|', 1)
                reason_display = parts[1].strip() if len(parts) == 2 else ''
        friendly_reason = self._translate_reason_for_logging(clean_reason, reason_display)
        # EPP 가드: 병렬 시퀀스에도 동일 적용
        epp_acquired = False
        try:
            if self._sequence_contains_mouse(sequence_copy):
                ok = self._epp_guard_acquire(tag=f"parallel:{command_name}")
                if not ok:
                    msg = f"[{command_name}] [EPP] 적용 실패로 실행을 중단합니다."
                    if source_tag:
                        msg = f"{source_tag} {msg}"
                    self.log_generated.emit(msg, "red")
                    return
                epp_acquired = True
                self._epp_guard_parallel_active[command_name] = True
        except Exception as e:
            self.log_generated.emit(f"[{command_name}] [EPP] 가드 준비 중 예외: {e}", "red")
            return

        state = {
            "command_name": command_name,
            "sequence": sequence_copy,
            "index": 0,
            "timer": timer,
            "watchdog": watchdog,
            "reason": clean_reason,
            "reason_display": friendly_reason or None,
            "owner": owner,
            "is_processing": False,
            "source_tag": source_tag if isinstance(source_tag, str) else None,
            "epp_guard": epp_acquired,
        }
        self.active_parallel_sequences[command_name] = state

        start_color = "orange" if self._is_skill_profile(command_name) else "cyan"
        if friendly_reason:
            msg = f"[{command_name}] (시작) -원인: {friendly_reason}"
        else:
            msg = f"[{command_name}] (시작)"
        if source_tag:
            msg = f"{source_tag} {msg}"
        self.log_generated.emit(msg, start_color)

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
                    msg = f"[{command_name}] 오류: 알 수 없는 키 '{step.get('key_str')}'"
                    if state.get("source_tag"):
                        msg = f"{state['source_tag']} {msg}"
                    self.log_generated.emit(msg, "red")
                elif action_type == "press":
                    force_requested = bool(step.get("force", False))
                    pressed = self._press_key_for_owner(owner, key_obj, force=force_requested)
                    if pressed:
                        action_label = "(누르기-forced)" if force_requested else "(누르기)"
                        msg = f"[{command_name}] {action_label} {self._translate_key_for_logging(step.get('key_str'))}"
                        if state.get("source_tag"):
                            msg = f"{state['source_tag']} {msg}"
                        self.log_generated.emit(msg, "white")
                    elif self.console_log_checkbox.isChecked():
                        print(f"[AutoControl] 병렬 PRESS skipped (already held): {step.get('key_str')}")
                else:
                    force_requested = bool(step.get("force", False))
                    released = self._release_key_for_owner(owner, key_obj, force=force_requested)
                    if released:
                        action_label = "(떼기-forced)" if force_requested else "(떼기)"
                        color = "red" if force_requested else "white"
                        msg = f"[{command_name}] {action_label} {self._translate_key_for_logging(step.get('key_str'))}"
                        if state.get("source_tag"):
                            msg = f"{state['source_tag']} {msg}"
                        self.log_generated.emit(msg, color)
                    else:
                        if force_requested:
                            msg = f"[{command_name}] (떼기-forced) {self._translate_key_for_logging(step.get('key_str'))}"
                            if state.get("source_tag"):
                                msg = f"{state['source_tag']} {msg}"
                            self.log_generated.emit(msg, "red")
                        else:
                            if self.global_key_counts.get(key_obj, 0) == 0:
                                forced = self._release_key_for_owner(owner, key_obj, force=True)
                                if forced:
                                    msg = f"[{command_name}] (떼기-forced) {self._translate_key_for_logging(step.get('key_str'))}"
                                    if state.get("source_tag"):
                                        msg = f"{state['source_tag']} {msg}"
                                    self.log_generated.emit(msg, "red")
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
                msg = f"[{command_name}] (대기) {delay_ms}ms"
                if state.get("source_tag"):
                    msg = f"{state['source_tag']} {msg}"
                self.log_generated.emit(msg, "gray")

            elif action_type == "mouse_move_abs":
                try:
                    tx = int(step.get('x', 0)); ty = int(step.get('y', 0))
                    dur = int(step.get('dur_ms', 240))
                except Exception:
                    tx, ty, dur = 0, 0, 240
                cx, cy = self._get_cursor_pos()
                dx = int(tx) - int(cx)
                dy = int(ty) - int(cy)
                sent = self._send_mouse_smooth_move(dx, dy, dur)
                label = f"[{command_name}] (마우스 이동: abs→Δ=({dx},{dy}), dur={dur}ms)"
                if state.get("source_tag"):
                    label = f"{state['source_tag']} {label}"
                self.log_generated.emit(label, "white" if sent else "red")

            elif action_type == "mouse_left_click":
                sent = self._send_mouse_click_cmd('left')
                label = f"[{command_name}] (마우스 좌클릭)"
                if state.get("source_tag"):
                    label = f"{state['source_tag']} {label}"
                self.log_generated.emit(label, "white" if sent else "red")

            elif action_type == "mouse_right_click":
                sent = self._send_mouse_click_cmd('right')
                label = f"[{command_name}] (마우스 우클릭)"
                if state.get("source_tag"):
                    label = f"{state['source_tag']} {label}"
                self.log_generated.emit(label, "white" if sent else "red")

            elif action_type == "mouse_double_click":
                sent = self._send_mouse_click_cmd('double')
                label = f"[{command_name}] (마우스 더블클릭)"
                if state.get("source_tag"):
                    label = f"{state['source_tag']} {label}"
                self.log_generated.emit(label, "white" if sent else "red")

            elif action_type == "release_all":
                self._release_all_for_owner(owner, force=True)
                # 병렬에서도 동일하게 '모든 키 떼기'에 한해 CLEAR_ALL 전송
                try:
                    if (command_name or "").strip() == "모든 키 떼기":
                        self._send_clear_all()
                except Exception:
                    pass
                msg = f"[{command_name}] (모든 키 떼기)"
                if state.get("source_tag"):
                    msg = f"{state['source_tag']} {msg}"
                self.log_generated.emit(msg, "white")

            else:
                msg = f"[{command_name}] 경고: 알 수 없는 동작 '{action_type}'"
                if state.get("source_tag"):
                    msg = f"{state['source_tag']} {msg}"
                self.log_generated.emit(msg, "orange")

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
            msg = f"[{command_name}] 오류: 병렬 시퀀스 처리 중 예외 발생 - {exc}"
            if state.get("source_tag"):
                msg = f"{state['source_tag']} {msg}"
            self.log_generated.emit(msg, "red")
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

        # EPP 가드 해제
        try:
            if bool(state.get("epp_guard")):
                self._epp_guard_parallel_active.pop(command_name, None)
                self._epp_guard_release(tag=f"parallel:{command_name}")
        except Exception:
            pass

        display_reason = state.get("reason_display") or state.get("reason")
        suffix = f" -원인: {display_reason}" if display_reason else ""
        if success:
            completion_color = "orange" if self._is_skill_profile(command_name) else "lightgreen"
            msg = f"[{command_name}] (완료){suffix}"
            src = state.get("source_tag")
            if src:
                msg = f"{src} {msg}"
            self.log_generated.emit(msg, completion_color)
        else:
            msg = f"[{command_name}] (중단){suffix}"
            src = state.get("source_tag")
            if src:
                msg = f"{src} {msg}"
            self.log_generated.emit(msg, "orange")

        self._emit_parallel_sequence_completed(command_name, state, success)

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

        # EPP 가드 해제
        try:
            if bool(state.get("epp_guard")):
                self._epp_guard_parallel_active.pop(command_name, None)
                self._epp_guard_release(tag=f"parallel:{command_name}")
        except Exception:
            pass

        if forced:
            msg = f"[{command_name}] 병렬 시퀀스를 강제 종료했습니다."
        else:
            msg = f"[{command_name}] 병렬 시퀀스를 중단했습니다."
        src = state.get("source_tag")
        if src:
            msg = f"{src} {msg}"
        self.log_generated.emit(msg, "orange")

        self._emit_parallel_sequence_completed(command_name, state, success=False)

    def _emit_parallel_sequence_completed(self, command_name: str, state: dict, success: bool) -> None:
        reason = state.get("reason") if isinstance(state, dict) else None
        try:
            self.sequence_completed.emit(command_name, reason, success)
        except Exception:
            pass

    def _stop_all_parallel_sequences(self, forced: bool = False) -> None:
        for name in list(self.active_parallel_sequences.keys()):
            self._stop_parallel_sequence(name, forced=forced)

    def _on_parallel_sequence_stuck(self, command_name: str) -> None:
        if command_name not in self.active_parallel_sequences:
            return
        src = self.active_parallel_sequences.get(command_name, {}).get("source_tag")
        msg = f"경고: '{command_name}' 병렬 시퀀스가 멈춤. 복구 시도 중..."
        if src:
            msg = f"{src} {msg}"
        self.log_generated.emit(msg, "orange")
        self._stop_parallel_sequence(command_name, forced=True)

    @pyqtSlot(str, object)
    def receive_control_command(self, command_text, reason=None):
        # '모든 키 떼기'는 병렬 시퀀스까지 즉시 중단하여 잔여 입력을 없앤다.
        if command_text == "모든 키 떼기":
            try:
                self._stop_all_parallel_sequences(forced=True)
            except Exception:
                pass

        sequence = self.mappings.get(command_text)
        if not sequence:
            print(f"[AutoControl] 경고: '{command_text}'에 대한 매핑이 없습니다.")
            return

        sequence_payload = copy.deepcopy(sequence)
        # [NEW] 출처 태그 추론
        src_tag = None
        try:
            sender_obj = self.sender()
            cls_name = type(sender_obj).__name__ if sender_obj is not None else None
            if cls_name == 'MapTab':
                src_tag = '[맵]'
            elif cls_name == 'HuntTab':
                src_tag = '[사냥]'
        except Exception:
            src_tag = None

        if self.parallel_profile_flags.get(command_text, False):
            self._start_parallel_sequence(sequence_payload, command_text, reason=reason, source_tag=src_tag)
        else:
            # 새 동작: 만약 동일 명령이 이미 실행 중이라면 강제 재시작하도록 _start_sequence_execution이 처리
            self._start_sequence_execution(sequence_payload, command_text, is_test=False, reason=reason, source_tag=src_tag)

    def _on_sequence_stuck(self):
        """(신규) 시퀀스가 일정 시간 진행이 없을 때 호출되어 안전 복구를 시도합니다."""
        if not self.is_sequence_running:
            return

        command_name = self.current_command_name or ""
        reason = self.current_command_reason
        is_test_mode = self.is_test_mode

        print(f"[AutoControl] Sequence watchdog fired for '{command_name}'. Attempting recovery.")
        msg = f"경고: '{command_name}' 시퀀스가 멈춤. 복구 시도 중..."
        if self.current_command_source_tag:
            msg = f"{self.current_command_source_tag} {msg}"
        self.log_generated.emit(msg, "orange")

        self._abort_sequence_for_recovery()

        if is_test_mode or not command_name:
            if command_name:
                msg = f"'{command_name}' 테스트 모드이므로 자동 재시도를 건너뜁니다."
                if self.current_command_source_tag:
                    msg = f"{self.current_command_source_tag} {msg}"
                self.log_generated.emit(msg, "orange")
            self._notify_sequence_completed(False)
            return

        self.sequence_recovery_attempts[command_name] += 1
        attempt = self.sequence_recovery_attempts[command_name]
        if attempt > self.MAX_SEQUENCE_RECOVERY_ATTEMPTS:
            msg = f"경고: '{command_name}' 자동 복구 횟수 초과. 수동 조치가 필요합니다."
            if self.current_command_source_tag:
                msg = f"{self.current_command_source_tag} {msg}"
            self.log_generated.emit(msg, "red")
            self._notify_sequence_completed(False)
            return

        self.status_label.setText(
            f"'{command_name}' 복구 시도 {attempt}/{self.MAX_SEQUENCE_RECOVERY_ATTEMPTS}."
        )

        self._reconnect_serial_for_recovery()

        sequence_template = self.mappings.get(command_name)
        if not isinstance(sequence_template, list) or not sequence_template:
            msg = f"경고: '{command_name}'에 대한 시퀀스 원본을 찾을 수 없어 복구를 중단합니다."
            if self.current_command_source_tag:
                msg = f"{self.current_command_source_tag} {msg}"
            self.log_generated.emit(msg, "red")
            self._notify_sequence_completed(False)
            return

        sequence_payload = copy.deepcopy(sequence_template)
        msg = f"'{command_name}' 자동 재실행을 시작합니다.({attempt}/{self.MAX_SEQUENCE_RECOVERY_ATTEMPTS})"
        if self.current_command_source_tag:
            msg = f"{self.current_command_source_tag} {msg}"
        self.log_generated.emit(msg, "orange")
        self._start_sequence_execution(sequence_payload, command_name, is_test=False, reason=reason, source_tag=self.current_command_source_tag)

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
        if isinstance(key, Key):
            return f"Key.{key.name}"
        # pynput가 Ctrl+<letter> 조합을 제어문자(\x01..\x1A)로 전달하는 경우가 있다.
        # 이때는 사람이 읽을 수 있고 HID로 전송 가능한 형태('a'..'z')로 정규화한다.
        if hasattr(key, 'char'):
            ch = key.char
            try:
                if isinstance(ch, str) and len(ch) == 1:
                    code = ord(ch)
                    if 1 <= code <= 26:
                        return chr(ord('a') + code - 1)
            except Exception:
                pass
            return ch
        return 'N/A'

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
        # 비가시 시 UI 누적 생략
        if not getattr(self, '_ui_runtime_visible', True):
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
        # 비가시 시 UI 누적 생략
        if not getattr(self, '_ui_runtime_visible', True):
            return
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
        # 비가시 시 UI 누적 생략
        if not getattr(self, '_ui_runtime_visible', True):
            return
        self.key_log_list.addItem(item)

        if not self.log_persist_checkbox.isChecked() and self.key_log_list.count() > 200:
            self.key_log_list.takeItem(0)

        self.key_log_list.scrollToBottom()

    # [NEW] 탭 가시성 전파(비가시 시 UI 로그 생략)
    def set_tab_visible(self, visible: bool) -> None:
        self._ui_runtime_visible = bool(visible)

    def _translate_reason_for_logging(self, raw_reason, current_display=None):
        """내부 코드용 원인 문자열을 사용자 친화적인 문구로 변환합니다."""
        if raw_reason is None:
            return current_display

        if isinstance(raw_reason, str):
            reason_text = raw_reason.strip()
        else:
            reason_text = str(raw_reason).strip()

        if not reason_text:
            return current_display

        predefined = {
            "authority:reset": "권한 초기화",
            "authority:resume": "권한 복구 재실행",
            "authority:forced_release": "권한 강제 해제",
            "authority:forced_acquire": "권한 강제 획득",
            "esc:global_stop": "Esc 긴급 정지",
            "ui:emergency_stop": "UI 긴급 정지",
        }

        translated = predefined.get(reason_text)
        if translated:
            return translated

        if reason_text.startswith("authority:"):
            _, detail = reason_text.split(":", 1)
            detail = detail.replace("_", " ").replace("-", " ")
            detail = detail.strip()
            return f"권한 이벤트: {detail}" if detail else "권한 이벤트"

        if current_display:
            return current_display

        return reason_text

    def _translate_key_for_logging(self, key_str):
        # 제어문자(\x01..\x1A)가 문자열로 들어오면 사람이 읽을 수 있도록 'a'..'z' 로 변환
        try:
            if isinstance(key_str, str) and len(key_str) == 1:
                code = ord(key_str)
                if 1 <= code <= 26:
                    key_str = chr(ord('a') + code - 1)
        except Exception:
            pass

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
            try:
                self._send_clear_all()
            except Exception:
                pass
            time.sleep(0.1)
            self.ser.close()
            print("시리얼 포트 연결을 해제했습니다.")
        # EPP 가드 남아있으면 안전 복구
        try:
            while getattr(self, '_epp_guard_refcount', 0) > 0:
                self._epp_guard_release(tag='cleanup')
            self._epp_guard_main_active = False
            self._epp_guard_parallel_active.clear()
        except Exception:
            pass
