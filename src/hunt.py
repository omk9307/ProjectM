from __future__ import annotations

import csv
import json
import os
import random
import time
import math
import ctypes
import signal
import html
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterable, List, Optional, Callable, TextIO

import pygetwindow as gw

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRect, QThread, QAbstractNativeEventFilter, QDateTime, QSignalBlocker
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QDateTimeEdit,
    QDoubleSpinBox,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QInputDialog,
)

from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QBrush, QTextCursor, QGuiApplication

from detection_runtime import DetectionPopup, DetectionThread, ScreenSnipper
from direction_detection import DirectionDetector
from nickname_detection import NicknameDetector
from status_monitor import StatusMonitorThread, StatusMonitorConfig
from control_authority_manager import (
    AuthorityDecisionStatus,
    ControlAuthorityManager,
    HuntConditionSnapshot,
    DEFAULT_MAP_PROTECT_SEC,
    DEFAULT_MAX_FLOOR_HOLD_SEC,
    DEFAULT_MAX_TOTAL_HOLD_SEC,
    DEFAULT_HUNT_PROTECT_SEC,
)

if os.name == 'nt':
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    WM_HOTKEY = 0x0312
    VK_F_KEYS = {f"f{i}": 0x6F + i for i in range(1, 13)}

    class _HuntHotkeyEventFilter(QAbstractNativeEventFilter):
        def __init__(self, hotkey_id: int, callback: Callable[[], None]):
            super().__init__()
            self.hotkey_id = hotkey_id
            self.callback = callback

        def nativeEventFilter(self, event_type, message):
            if event_type == "windows_generic_MSG":
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    self.callback()
            return False, 0

    class _HuntHotkeyManager:
        _NEXT_ID = 100

        def __init__(self):
            self.user32 = ctypes.windll.user32
            self.hotkey_id: Optional[int] = None
            self.current_hotkey_str: Optional[str] = None

        def register_hotkey(self, hotkey_str: str) -> int:
            self.unregister_hotkey()
            hotkey_str = (hotkey_str or '').lower()
            if not hotkey_str or hotkey_str == 'none':
                raise ValueError("hotkey string is empty")

            parts = hotkey_str.split('+')
            mods, vk = 0, None
            for part in parts:
                if part in ("alt", "ctrl", "shift"):
                    mods |= {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "shift": MOD_SHIFT}[part]
                elif part in VK_F_KEYS:
                    vk = VK_F_KEYS[part]

            if vk is None:
                raise ValueError("unsupported hotkey")

            hotkey_id = _HuntHotkeyManager._NEXT_ID
            _HuntHotkeyManager._NEXT_ID += 1

            if not self.user32.RegisterHotKey(None, hotkey_id, mods, vk):
                raise RuntimeError("RegisterHotKey failed")

            self.hotkey_id = hotkey_id
            self.current_hotkey_str = hotkey_str
            return hotkey_id

        def unregister_hotkey(self) -> None:
            if self.hotkey_id is not None:
                self.user32.UnregisterHotKey(None, self.hotkey_id)
                self.hotkey_id = None
                self.current_hotkey_str = None
else:
    _HuntHotkeyManager = None
    _HuntHotkeyEventFilter = None


CHARACTER_CLASS_NAME = "캐릭터"

SRC_ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(SRC_ROOT, '..', 'workspace'))
CONFIG_ROOT = os.path.join(WORKSPACE_ROOT, 'config')
HUNT_SETTINGS_FILE = os.path.join(CONFIG_ROOT, 'hunt_settings.json')

DEFAULT_YOLO_NMS_IOU = 0.40
DEFAULT_YOLO_MAX_DET = 60

HUNT_AREA_COLOR = QColor(0, 170, 255, 70)
HUNT_AREA_EDGE = QPen(QColor(0, 120, 200, 200), 2, Qt.PenStyle.DashLine)
HUNT_AREA_BRUSH = QBrush(HUNT_AREA_COLOR)
PRIMARY_AREA_COLOR = QColor(255, 140, 0, 70)
PRIMARY_AREA_EDGE = QPen(QColor(230, 110, 0, 220), 2, Qt.PenStyle.SolidLine)
PRIMARY_AREA_BRUSH = QBrush(PRIMARY_AREA_COLOR)
FALLBACK_CHARACTER_EDGE = QPen(QColor(0, 255, 120, 220), 2, Qt.PenStyle.SolidLine)
FALLBACK_CHARACTER_BRUSH = QBrush(QColor(0, 255, 120, 60))
NICKNAME_EDGE = QPen(QColor(255, 255, 0, 220), 2, Qt.PenStyle.DotLine)
NICKNAME_RANGE_EDGE = QPen(QColor(120, 220, 255, 200), 1, Qt.PenStyle.DashLine)
DIRECTION_ROI_EDGE = QPen(QColor(170, 80, 255, 200), 1, Qt.PenStyle.DashLine)
DIRECTION_MATCH_EDGE_LEFT = QPen(QColor(0, 200, 255, 220), 2, Qt.PenStyle.SolidLine)
DIRECTION_MATCH_EDGE_RIGHT = QPen(QColor(255, 200, 0, 220), 2, Qt.PenStyle.SolidLine)
NAMEPLATE_ROI_EDGE = QPen(QColor(255, 255, 255, 240), 3, Qt.PenStyle.SolidLine)
NAMEPLATE_MATCH_EDGE = QPen(QColor(0, 255, 120, 240), 3, Qt.PenStyle.SolidLine)
MONSTER_LOSS_GRACE_SEC = 0.1  # 단기 미검출 시 방향 유지용 유예시간(초)
NAMEPLATE_TRACK_EDGE = QPen(QColor(255, 64, 64, 255), 3, Qt.PenStyle.SolidLine)
NAMEPLATE_TRACK_BRUSH = QBrush(QColor(255, 32, 32, 40))
NAMEPLATE_DEADZONE_EDGE = QPen(QColor(20, 20, 20, 230), 3, Qt.PenStyle.SolidLine)
NAMEPLATE_DEADZONE_SIZE = 100  # 사망 모션 무시 영역 크기(px)
LOG_LINE_LIMIT = 200

try:
    COMPOSITION_MODE_DEST_OVER = QPainter.CompositionMode.CompositionMode_DestinationOver
    COMPOSITION_MODE_SOURCE_OVER = QPainter.CompositionMode.CompositionMode_SourceOver
except AttributeError:  # PyQt5 호환성
    COMPOSITION_MODE_DEST_OVER = QPainter.CompositionMode_DestinationOver
    COMPOSITION_MODE_SOURCE_OVER = QPainter.CompositionMode_SourceOver


@dataclass
class DetectionBox:
    x: float
    y: float
    width: float
    height: float
    score: float = 0.0
    label: str = ""

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    def intersects(self, rect: "AreaRect") -> bool:
        return not (
            self.right <= rect.x
            or rect.right <= self.x
            or self.bottom <= rect.y
            or rect.bottom <= self.y
        )


@dataclass
class DetectionSnapshot:
    character_boxes: List[DetectionBox]
    monster_boxes: List[DetectionBox]
    timestamp: float


@dataclass
class AreaRect:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


@dataclass
class AttackSkill:
    name: str
    command: str
    enabled: bool = True
    is_primary: bool = False
    min_monsters: int = 1
    max_monsters: Optional[int] = None
    probability: int = 100
    pre_delay_min: float = 0.0
    pre_delay_max: float = 0.0
    post_delay_min: float = 0.43
    post_delay_max: float = 0.46
    completion_delay_min: float = 0.0
    completion_delay_max: float = 0.0
    primary_reset_min: int = 0
    primary_reset_max: int = 0
    primary_reset_command: str = ""


@dataclass
class BuffSkill:
    name: str
    command: str
    cooldown_seconds: int
    enabled: bool = True
    jitter_percent: int = 15
    last_triggered_ts: float = 0.0
    next_ready_ts: float = 0.0
    pre_delay_min: float = 0.0
    pre_delay_max: float = 0.0
    post_delay_min: float = 0.43
    post_delay_max: float = 0.46
    completion_delay_min: float = 0.0
    completion_delay_max: float = 0.0


@dataclass
class TeleportSettings:
    enabled: bool = False
    distance_px: float = 190.0
    probability: int = 50
    walk_enabled: bool = False
    walk_probability: float = 3.0
    walk_interval: float = 0.5
    walk_bonus_interval: float = 0.5
    walk_bonus_step: float = 20.0
    walk_bonus_max: float = 70.0


class AttackSkillDialog(QDialog):
    """공격 스킬 정보를 입력/수정하기 위한 대화상자."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        skill: Optional[AttackSkill] = None,
        misc_commands: Optional[List[str]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("공격 스킬")

        self._misc_command_options = sorted({str(name) for name in misc_commands or [] if isinstance(name, str)})

        self.name_input = QLineEdit()
        self.command_input = QLineEdit()
        self.enabled_checkbox = QCheckBox("사용")
        self.enabled_checkbox.setChecked(True)
        self.primary_checkbox = QCheckBox("주 공격 스킬로 설정")
        self.primary_checkbox.setChecked(False)

        self.primary_reset_min_spinbox = QSpinBox()
        self.primary_reset_min_spinbox.setRange(0, 999)
        self.primary_reset_min_spinbox.setValue(0)

        self.primary_reset_max_spinbox = QSpinBox()
        self.primary_reset_max_spinbox.setRange(0, 999)
        self.primary_reset_max_spinbox.setValue(0)

        self.primary_reset_min_spinbox.valueChanged.connect(self._sync_primary_reset_bounds)
        self.primary_reset_max_spinbox.valueChanged.connect(self._sync_primary_reset_bounds)

        self.primary_reset_label = QLabel("주 스킬 초기화 횟수")
        self.primary_reset_widget = QWidget()
        reset_layout = QHBoxLayout(self.primary_reset_widget)
        reset_layout.setContentsMargins(0, 0, 0, 0)
        reset_layout.setSpacing(4)
        reset_layout.addWidget(self.primary_reset_min_spinbox)
        reset_layout.addWidget(QLabel(" ~ "))
        reset_layout.addWidget(self.primary_reset_max_spinbox)

        self.primary_release_label = QLabel("주 스킬 해제 명령")
        self.primary_release_combo = QComboBox()
        self.primary_release_combo.addItem("선택 안 함", "")
        for name in self._misc_command_options:
            self.primary_release_combo.addItem(name, name)

        self.min_monsters_spinbox = QSpinBox()
        self.min_monsters_spinbox.setRange(1, 50)
        self.min_monsters_spinbox.setValue(1)

        self.max_monsters_spinbox = QSpinBox()
        self.max_monsters_spinbox.setRange(0, 50)
        self.max_monsters_spinbox.setSpecialValueText("제한 없음")
        self.max_monsters_spinbox.setValue(0)

        self.min_monsters_spinbox.valueChanged.connect(self._sync_monster_bounds)
        self.max_monsters_spinbox.valueChanged.connect(self._sync_monster_bounds)

        self.probability_spinbox = QSpinBox()
        self.probability_spinbox.setRange(0, 100)
        self.probability_spinbox.setValue(100)
        self.probability_spinbox.setSuffix(" %")

        self.pre_delay_min_spinbox = QDoubleSpinBox()
        self.pre_delay_min_spinbox.setRange(0.0, 5.0)
        self.pre_delay_min_spinbox.setSingleStep(0.05)
        self.pre_delay_min_spinbox.setDecimals(3)
        self.pre_delay_min_spinbox.setValue(0.0)
        self.pre_delay_min_spinbox.setSuffix(" s")

        self.pre_delay_max_spinbox = QDoubleSpinBox()
        self.pre_delay_max_spinbox.setRange(0.0, 5.0)
        self.pre_delay_max_spinbox.setSingleStep(0.05)
        self.pre_delay_max_spinbox.setDecimals(3)
        self.pre_delay_max_spinbox.setValue(0.0)
        self.pre_delay_max_spinbox.setSuffix(" s")

        self.delay_min_spinbox = QDoubleSpinBox()
        self.delay_min_spinbox.setRange(0.0, 5.0)
        self.delay_min_spinbox.setSingleStep(0.05)
        self.delay_min_spinbox.setDecimals(3)
        self.delay_min_spinbox.setValue(0.43)
        self.delay_min_spinbox.setSuffix(" s")

        self.delay_max_spinbox = QDoubleSpinBox()
        self.delay_max_spinbox.setRange(0.0, 5.0)
        self.delay_max_spinbox.setSingleStep(0.05)
        self.delay_max_spinbox.setDecimals(3)
        self.delay_max_spinbox.setValue(0.46)
        self.delay_max_spinbox.setSuffix(" s")

        self.completion_min_spinbox = QDoubleSpinBox()
        self.completion_min_spinbox.setRange(0.0, 5.0)
        self.completion_min_spinbox.setSingleStep(0.05)
        self.completion_min_spinbox.setDecimals(3)
        self.completion_min_spinbox.setValue(0.0)
        self.completion_min_spinbox.setSuffix(" s")

        self.completion_max_spinbox = QDoubleSpinBox()
        self.completion_max_spinbox.setRange(0.0, 5.0)
        self.completion_max_spinbox.setSingleStep(0.05)
        self.completion_max_spinbox.setDecimals(3)
        self.completion_max_spinbox.setValue(0.0)
        self.completion_max_spinbox.setSuffix(" s")

        self.primary_checkbox.toggled.connect(self._update_primary_reset_controls)

        if skill:
            self.name_input.setText(skill.name)
            self.command_input.setText(skill.command)
            self.enabled_checkbox.setChecked(skill.enabled)
            self.primary_checkbox.setChecked(skill.is_primary)
            self.min_monsters_spinbox.setValue(skill.min_monsters)
            max_monsters = getattr(skill, 'max_monsters', None)
            if isinstance(max_monsters, int) and max_monsters > 0:
                self.max_monsters_spinbox.setValue(max_monsters)
            else:
                self.max_monsters_spinbox.setValue(0)
            self.probability_spinbox.setValue(skill.probability)
            self.pre_delay_min_spinbox.setValue(getattr(skill, 'pre_delay_min', 0.0))
            self.pre_delay_max_spinbox.setValue(getattr(skill, 'pre_delay_max', 0.0))
            self.delay_min_spinbox.setValue(skill.post_delay_min)
            self.delay_max_spinbox.setValue(skill.post_delay_max)
            self.completion_min_spinbox.setValue(getattr(skill, 'completion_delay_min', 0.0))
            self.completion_max_spinbox.setValue(getattr(skill, 'completion_delay_max', 0.0))
            reset_min = max(0, getattr(skill, 'primary_reset_min', 0))
            reset_max = max(0, getattr(skill, 'primary_reset_max', 0))
            self.primary_reset_min_spinbox.setValue(reset_min)
            self.primary_reset_max_spinbox.setValue(reset_max)
            stored_command = str(getattr(skill, 'primary_reset_command', '') or '')
            if stored_command and stored_command not in self._misc_command_options:
                self.primary_release_combo.addItem(stored_command, stored_command)
            index = self.primary_release_combo.findData(stored_command)
            if index >= 0:
                self.primary_release_combo.setCurrentIndex(index)
        
        form = QFormLayout()
        form.addRow("이름", self.name_input)
        form.addRow("명령", self.command_input)
        form.addRow("사용", self.enabled_checkbox)
        form.addRow("주 스킬", self.primary_checkbox)
        form.addRow(self.primary_reset_label, self.primary_reset_widget)
        form.addRow(self.primary_release_label, self.primary_release_combo)
        form.addRow("사용 최소 몬스터 수", self.min_monsters_spinbox)
        form.addRow("사용 최대 몬스터 수", self.max_monsters_spinbox)
        form.addRow("사용 확률", self.probability_spinbox)
        form.addRow("스킬 발동 전 대기 최소", self.pre_delay_min_spinbox)
        form.addRow("스킬 발동 전 대기 최대", self.pre_delay_max_spinbox)
        form.addRow("스킬 발동 후 대기 최소", self.delay_min_spinbox)
        form.addRow("스킬 발동 후 대기 최대", self.delay_max_spinbox)
        form.addRow("스킬 완료 후 대기 최소", self.completion_min_spinbox)
        form.addRow("스킬 완료 후 대기 최대", self.completion_max_spinbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

        self._update_primary_reset_controls(self.primary_checkbox.isChecked())

    def get_skill(self) -> Optional[AttackSkill]:
        name = self.name_input.text().strip()
        command = self.command_input.text().strip()
        if not name or not command:
            return None
        is_primary = self.primary_checkbox.isChecked()
        reset_min = self.primary_reset_min_spinbox.value() if is_primary else 0
        reset_max = self.primary_reset_max_spinbox.value() if is_primary else 0
        if reset_max < reset_min:
            reset_min, reset_max = reset_max, reset_min
        reset_command = self.primary_release_combo.currentData() if is_primary else ""
        if reset_command is None:
            reset_command = ""
        reset_command = str(reset_command).strip()
        if not is_primary or (reset_min == 0 and reset_max == 0):
            reset_command = ""
        max_monsters_value = self.max_monsters_spinbox.value()
        min_monsters_value = self.min_monsters_spinbox.value()
        if max_monsters_value != 0 and max_monsters_value < min_monsters_value:
            max_monsters_value = min_monsters_value
        return AttackSkill(
            name=name,
            command=command,
            enabled=self.enabled_checkbox.isChecked(),
            is_primary=is_primary,
            min_monsters=self.min_monsters_spinbox.value(),
            max_monsters=max_monsters_value or None,
            probability=self.probability_spinbox.value(),
            pre_delay_min=min(self.pre_delay_min_spinbox.value(), self.pre_delay_max_spinbox.value()),
            pre_delay_max=max(self.pre_delay_min_spinbox.value(), self.pre_delay_max_spinbox.value()),
            post_delay_min=min(self.delay_min_spinbox.value(), self.delay_max_spinbox.value()),
            post_delay_max=max(self.delay_min_spinbox.value(), self.delay_max_spinbox.value()),
            completion_delay_min=min(self.completion_min_spinbox.value(), self.completion_max_spinbox.value()),
            completion_delay_max=max(self.completion_min_spinbox.value(), self.completion_max_spinbox.value()),
            primary_reset_min=reset_min if is_primary else 0,
            primary_reset_max=reset_max if is_primary else 0,
            primary_reset_command=reset_command,
        )

    def _sync_primary_reset_bounds(self) -> None:
        min_val = self.primary_reset_min_spinbox.value()
        max_val = self.primary_reset_max_spinbox.value()
        sender = self.sender()
        if max_val < min_val:
            if sender is self.primary_reset_min_spinbox:
                self.primary_reset_max_spinbox.setValue(min_val)
            else:
                self.primary_reset_min_spinbox.setValue(max_val)

    def _sync_monster_bounds(self) -> None:
        min_val = self.min_monsters_spinbox.value()
        max_val = self.max_monsters_spinbox.value()
        sender = self.sender()
        if max_val == 0:
            return
        if max_val < min_val:
            if sender is self.min_monsters_spinbox:
                self.max_monsters_spinbox.setValue(min_val)
            else:
                self.min_monsters_spinbox.setValue(max_val)

    def _update_primary_reset_controls(self, checked: bool) -> None:
        self.primary_reset_label.setVisible(checked)
        self.primary_reset_widget.setVisible(checked)
        self.primary_release_label.setVisible(checked)
        self.primary_release_combo.setVisible(checked)


class BuffSkillDialog(QDialog):
    """버프 스킬 정보를 입력/수정하기 위한 대화상자."""

    def __init__(self, parent: Optional[QWidget] = None, skill: Optional[BuffSkill] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("버프 스킬")

        self.name_input = QLineEdit()
        self.command_input = QLineEdit()
        self.enabled_checkbox = QCheckBox("사용")
        self.enabled_checkbox.setChecked(True)

        self.cooldown_spinbox = QSpinBox()
        self.cooldown_spinbox.setRange(1, 3600)
        self.cooldown_spinbox.setValue(60)
        self.cooldown_spinbox.setSuffix(" s")

        self.jitter_spinbox = QSpinBox()
        self.jitter_spinbox.setRange(0, 50)
        self.jitter_spinbox.setValue(15)
        self.jitter_spinbox.setSuffix(" %")

        self.pre_delay_min_spinbox = QDoubleSpinBox()
        self.pre_delay_min_spinbox.setRange(0.0, 10.0)
        self.pre_delay_min_spinbox.setSingleStep(0.05)
        self.pre_delay_min_spinbox.setDecimals(3)
        self.pre_delay_min_spinbox.setValue(0.0)
        self.pre_delay_min_spinbox.setSuffix(" s")

        self.pre_delay_max_spinbox = QDoubleSpinBox()
        self.pre_delay_max_spinbox.setRange(0.0, 10.0)
        self.pre_delay_max_spinbox.setSingleStep(0.05)
        self.pre_delay_max_spinbox.setDecimals(3)
        self.pre_delay_max_spinbox.setValue(0.0)
        self.pre_delay_max_spinbox.setSuffix(" s")

        self.delay_min_spinbox = QDoubleSpinBox()
        self.delay_min_spinbox.setRange(0.0, 10.0)
        self.delay_min_spinbox.setSingleStep(0.05)
        self.delay_min_spinbox.setDecimals(3)
        self.delay_min_spinbox.setValue(0.43)
        self.delay_min_spinbox.setSuffix(" s")

        self.delay_max_spinbox = QDoubleSpinBox()
        self.delay_max_spinbox.setRange(0.0, 10.0)
        self.delay_max_spinbox.setSingleStep(0.05)
        self.delay_max_spinbox.setDecimals(3)
        self.delay_max_spinbox.setValue(0.46)
        self.delay_max_spinbox.setSuffix(" s")

        self.completion_min_spinbox = QDoubleSpinBox()
        self.completion_min_spinbox.setRange(0.0, 10.0)
        self.completion_min_spinbox.setSingleStep(0.05)
        self.completion_min_spinbox.setDecimals(3)
        self.completion_min_spinbox.setValue(0.0)
        self.completion_min_spinbox.setSuffix(" s")

        self.completion_max_spinbox = QDoubleSpinBox()
        self.completion_max_spinbox.setRange(0.0, 10.0)
        self.completion_max_spinbox.setSingleStep(0.05)
        self.completion_max_spinbox.setDecimals(3)
        self.completion_max_spinbox.setValue(0.0)
        self.completion_max_spinbox.setSuffix(" s")

        if skill:
            self.name_input.setText(skill.name)
            self.command_input.setText(skill.command)
            self.enabled_checkbox.setChecked(skill.enabled)
            self.cooldown_spinbox.setValue(skill.cooldown_seconds)
            self.jitter_spinbox.setValue(skill.jitter_percent)
            self.pre_delay_min_spinbox.setValue(getattr(skill, 'pre_delay_min', 0.0))
            self.pre_delay_max_spinbox.setValue(getattr(skill, 'pre_delay_max', 0.0))
            self.delay_min_spinbox.setValue(skill.post_delay_min)
            self.delay_max_spinbox.setValue(skill.post_delay_max)
            self.completion_min_spinbox.setValue(getattr(skill, 'completion_delay_min', 0.0))
            self.completion_max_spinbox.setValue(getattr(skill, 'completion_delay_max', 0.0))

        form = QFormLayout()
        form.addRow("이름", self.name_input)
        form.addRow("명령", self.command_input)
        form.addRow("사용", self.enabled_checkbox)
        form.addRow("쿨타임", self.cooldown_spinbox)
        form.addRow("오차 허용", self.jitter_spinbox)
        form.addRow("스킬 발동 전 대기 최소", self.pre_delay_min_spinbox)
        form.addRow("스킬 발동 전 대기 최대", self.pre_delay_max_spinbox)
        form.addRow("스킬 발동 후 대기 최소", self.delay_min_spinbox)
        form.addRow("스킬 발동 후 대기 최대", self.delay_max_spinbox)
        form.addRow("스킬 완료 후 대기 최소", self.completion_min_spinbox)
        form.addRow("스킬 완료 후 대기 최대", self.completion_max_spinbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def get_skill(self) -> Optional[BuffSkill]:
        name = self.name_input.text().strip()
        command = self.command_input.text().strip()
        if not name or not command:
            return None
        return BuffSkill(
            name=name,
            command=command,
            cooldown_seconds=self.cooldown_spinbox.value(),
            enabled=self.enabled_checkbox.isChecked(),
            jitter_percent=self.jitter_spinbox.value(),
            pre_delay_min=min(self.pre_delay_min_spinbox.value(), self.pre_delay_max_spinbox.value()),
            pre_delay_max=max(self.pre_delay_min_spinbox.value(), self.pre_delay_max_spinbox.value()),
            post_delay_min=min(self.delay_min_spinbox.value(), self.delay_max_spinbox.value()),
            post_delay_max=max(self.delay_min_spinbox.value(), self.delay_max_spinbox.value()),
            completion_delay_min=min(self.completion_min_spinbox.value(), self.completion_max_spinbox.value()),
            completion_delay_max=max(self.completion_min_spinbox.value(), self.completion_max_spinbox.value()),
       )


class HuntTab(QWidget):
    """사냥 조건과 스킬 실행을 관리하는 임시 탭."""

    CONTROL_RELEASE_TIMEOUT_SEC = int(DEFAULT_MAX_TOTAL_HOLD_SEC)
    CONDITION_POLL_DEBOUNCE_MS = 10
    CONDITION_POLL_MIN_INTERVAL_SEC = 0.12
    CONTROL_REQUEST_TIMEOUT_MS = 5000
    CHARACTER_PERSISTENCE_SEC = 5.0
    DIRECTION_TIMEOUT_SEC = 1.5

    control_command_issued = pyqtSignal(str, object)
    control_authority_requested = pyqtSignal(dict)
    control_authority_released = pyqtSignal(dict)
    hunt_area_updated = pyqtSignal(object)
    primary_skill_area_updated = pyqtSignal(object)
    monster_stats_updated = pyqtSignal(int, int)
    detection_status_changed = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.data_manager = None
        self.current_authority: str = "map"
        self.attack_skills: List[AttackSkill] = []
        self.buff_skills: List[BuffSkill] = []

        self.latest_snapshot: Optional[DetectionSnapshot] = None
        self.current_hunt_area: Optional[AreaRect] = None
        self.current_primary_area: Optional[AreaRect] = None
        self.latest_monster_count = 0
        self.latest_primary_monster_count = 0
        self.control_release_timeout = self.CONTROL_RELEASE_TIMEOUT_SEC
        self._authority_manager = ControlAuthorityManager.instance()
        self._authority_manager_connected = False
        self.map_link_enabled = False
        self._forbidden_priority_active = False
        self.map_protect_seconds = DEFAULT_MAP_PROTECT_SEC
        self.hunt_protect_seconds = DEFAULT_HUNT_PROTECT_SEC
        self.floor_hold_seconds = DEFAULT_MAX_FLOOR_HOLD_SEC
        self.last_control_acquired_ts = 0.0
        self.last_release_attempt_ts = 0.0
        self.auto_hunt_enabled = True
        self.overlay_preferences = {
            'hunt_area': True,
            'primary_area': True,
            'direction_area': True,
            'nickname_range': True,
            'nameplate_area': True,
            'nameplate_tracking': False,
            'monster_confidence': True,
        }
        self.map_tab = None  # 맵 탭 연동 시 탐지 토글 동기화를 위해 참조 저장
        self._syncing_with_map = False
        self._direction_area_user_pref = True
        self._nickname_range_user_pref = True
        self._nameplate_area_user_pref = True
        self._nameplate_tracking_user_pref = False
        self.downscale_enabled = False
        self.downscale_factor = 0.5
        self._suppress_downscale_prompt = False
        self._last_character_boxes: List[DetectionBox] = []
        self._last_character_details: List[dict] = []
        self._last_character_seen_ts: float = 0.0
        self._using_character_fallback: bool = False
        self._nickname_config: dict = {}
        self._nickname_templates: list[dict] = []
        self._latest_nickname_box: Optional[dict] = None
        self._last_nickname_match: Optional[dict] = None
        self._latest_nickname_search_region: Optional[dict] = None
        self._nameplate_config: dict = {}
        self._nameplate_templates: dict[int, list] = {}
        self._show_nameplate_overlay_config = True
        self._latest_nameplate_rois: list[dict] = []
        self._active_nameplate_track_ids: set[int] = set()
        self._nameplate_enabled = False
        self._nameplate_hold_until = 0.0
        self._nameplate_dead_zones: list[dict] = []
        self._nameplate_dead_zone_duration_sec = 0.2
        self._nameplate_track_missing_grace_sec = 0.12
        self._nameplate_track_max_hold_sec = 2.0
        self._nameplate_visual_debug_enabled = False
        self._visual_tracked_monsters: list[dict] = []
        self._visual_dead_zones: list[dict] = []
        self._last_nameplate_notify_ts: float = 0.0

        self.attack_interval_sec = 0.35
        self.last_attack_ts = 0.0
        self.last_facing: Optional[str] = None
        self.hunting_active = False
        self._pending_skill_timer: Optional[QTimer] = None
        self._pending_skill: Optional[AttackSkill] = None
        self._pending_direction_timer: Optional[QTimer] = None
        self._pending_direction_side: Optional[str] = None
        self._pending_direction_skill: Optional[AttackSkill] = None
        self._pending_direction_confirm_skill: Optional[AttackSkill] = None
        self._pending_direction_confirm_side: Optional[str] = None
        self._pending_direction_confirm_deadline: float = 0.0
        self._pending_direction_confirm_command_ts: float = 0.0
        self._pending_direction_confirm_attempts: int = 0
        self._last_target_side: Optional[str] = None
        self._last_target_distance: Optional[float] = None
        self._last_target_update_ts: float = 0.0
        self._last_direction_change_ts: float = 0.0
        self._last_monster_seen_ts = time.time()
        self._next_command_ready_ts = 0.0
        self._last_condition_poll_ts = 0.0
        self._request_pending = False
        self._cached_monster_boxes: List[DetectionBox] = []
        self._cached_monster_boxes_ts = 0.0
        self._active_monster_confidence_overrides: dict[int, float] = {}

        self.detection_thread: Optional[DetectionThread] = None
        self.detection_popup: Optional[DetectionPopup] = None
        self.is_popup_active = False
        self.last_popup_scale = 50
        self.last_popup_position: Optional[tuple[int, int]] = None
        self.last_popup_size: Optional[tuple[int, int]] = None
        self.manual_capture_region: Optional[dict] = None
        self.manual_capture_regions: list[dict] = []
        self.last_used_model: Optional[str] = None
        self._model_listener_registered = False
        self._authority_request_connected = False
        self._authority_release_connected = False
        self._release_pending = False
        self._settings_path = HUNT_SETTINGS_FILE
        self._suppress_settings_save = False
        self._condition_debounce_timer: Optional[QTimer] = None
        self._request_timeout_timer: Optional[QTimer] = None
        os.makedirs(CONFIG_ROOT, exist_ok=True)
        self.latest_detection_details: dict[str, list] = {
            'characters': [],
            'monsters': [],
            'nickname': None,
            'nickname_search': None,
            'direction': None,
            'nameplates': [],
        }
        self.latest_perf_stats = {
            'fps': 0.0,
            'total_ms': 0.0,
            'yolo_ms': 0.0,
            'yolo_speed_preprocess_ms': 0.0,
            'yolo_speed_inference_ms': 0.0,
            'yolo_speed_postprocess_ms': 0.0,
            'nickname_ms': 0.0,
            'direction_ms': 0.0,
            'nameplate_ms': 0.0,
            'capture_ms': 0.0,
            'preprocess_ms': 0.0,
            'post_ms': 0.0,
            'render_ms': 0.0,
            'emit_ms': 0.0,
            'payload_latency_ms': 0.0,
            'handler_ms': 0.0,
            'downscale_active': 0.0,
            'scale_factor': 1.0,
            'frame_width': 0.0,
            'frame_height': 0.0,
            'input_width': 0.0,
            'input_height': 0.0,
        }
        self._active_target_names: List[str] = []

        self.status_monitor: Optional[StatusMonitorThread] = None
        self._status_config: StatusMonitorConfig = StatusMonitorConfig.default()
        self._status_last_command_ts = {'hp': 0.0, 'mp': 0.0}
        self._status_display_values = {'hp': None, 'mp': None}
        self._status_summary_cache = {
            'hp': 'HP: --',
            'mp': 'MP: --',
            'exp': 'EXP: -- / --',
        }
        self._status_exp_records: list[dict] = []
        self._primary_release_command: str = ""
        self._primary_reset_range: tuple[int, int] = (0, 0)
        self._primary_reset_remaining: Optional[int] = None
        self._primary_reset_current_goal: Optional[int] = None
        self._status_detection_start_ts: Optional[float] = None
        self._status_exp_start_snapshot: Optional[dict] = None
        self._status_ocr_warned = False
        self._hp_guard_active = False
        self._hp_guard_timer = QTimer(self)
        self._hp_guard_timer.setSingleShot(True)
        self._hp_guard_timer.timeout.connect(self._clear_hp_guard)
        self._last_command_issued: Optional[tuple[str, object]] = None
        self._status_mp_saved_command: Optional[tuple[str, object]] = None

        self.teleport_settings = TeleportSettings()
        self.teleport_command_left = "텔레포트(좌)"
        self.teleport_command_right = "텔레포트(우)"
        self.teleport_command_left_v2 = "텔레포트(좌)v2"
        self.teleport_command_right_v2 = "텔레포트(우)v2"
        self.walk_teleport_command = "걷기 중 텔레포트"
        self._walk_teleport_active = False
        self._walk_teleport_walk_started_at = 0.0
        self._last_walk_teleport_check_ts = 0.0
        self._walk_teleport_bonus_percent = 0.0
        self._walk_teleport_direction: Optional[str] = None
        self._walk_teleport_display_percent = 0.0
        self._movement_mode: Optional[str] = None
        self._last_movement_command_ts = 0.0
        self._direction_config: dict = {}
        self._direction_templates: dict[str, list] = {'left': [], 'right': []}
        self._direction_active = False
        self._direction_last_seen_ts = 0.0
        self._direction_last_side: Optional[str] = None
        self._latest_direction_roi: Optional[dict] = None
        self._latest_direction_match: Optional[dict] = None
        self._show_nickname_overlay_config = True
        self._perf_warn_last_ts = 0.0
        self._perf_warn_min_interval = 3.0
        self._perf_log_path: Optional[str] = None
        self._perf_log_handle: Optional[TextIO] = None
        self._perf_log_writer: Optional[csv.writer] = None
        self._perf_logging_enabled = False
        self._detection_status = False
        self.yolo_nms_iou = DEFAULT_YOLO_NMS_IOU
        self.yolo_max_det = DEFAULT_YOLO_MAX_DET
        self._show_direction_overlay_config = True
        self._direction_detector_available = False
        self._last_direction_score: Optional[float] = None
        self._pending_completion_delays: list[dict] = []
        self._pre_delay_timers: dict[str, QTimer] = {}
        self.hotkey_manager = None
        self.hotkey_event_filter = None
        self.detection_hotkey = 'f10'

        # 자동 종료 상태
        self.shutdown_pid_value: Optional[int] = None
        self.shutdown_datetime_target: Optional[float] = None
        self.shutdown_delay_target: Optional[float] = None
        self.shutdown_other_player_enabled = False
        self.shutdown_other_player_detect_since: Optional[float] = None
        self.shutdown_other_player_due: Optional[float] = None
        self.shutdown_other_player_last_count: int = 0
        self._shutdown_last_reason: Optional[str] = None
        self.shutdown_sleep_enabled = False
        self.shutdown_timer = QTimer(self)
        self.shutdown_timer.setInterval(1000)
        self.shutdown_timer.setSingleShot(False)
        self.shutdown_timer.timeout.connect(self._handle_shutdown_timer_tick)

        self._build_ui()
        self._setup_auto_shutdown_ui()
        self._update_facing_label()
        self._load_settings()
        self._setup_timers()
        self._setup_facing_reset_timer()
        self._setup_detection_hotkey()

    def _setup_facing_reset_timer(self) -> None:
        self.facing_reset_timer = QTimer(self)
        self.facing_reset_timer.setSingleShot(True)
        self.facing_reset_timer.timeout.connect(self._handle_facing_reset_timeout)

    def _setup_detection_hotkey(self) -> None:
        if _HuntHotkeyManager is None or _HuntHotkeyEventFilter is None:
            return
        app = QApplication.instance()
        if app is None:
            return
        try:
            self.hotkey_manager = _HuntHotkeyManager()
            hotkey_id = self.hotkey_manager.register_hotkey(self.detection_hotkey)
            self.hotkey_event_filter = _HuntHotkeyEventFilter(hotkey_id, self.detect_btn.click)
            app.installNativeEventFilter(self.hotkey_event_filter)
            if hasattr(self.detect_btn, 'setToolTip'):
                self.detect_btn.setToolTip(f"단축키: {self.detection_hotkey.upper()}")
            self.append_log(f"사냥탭 탐지 단축키가 '{self.detection_hotkey.upper()}'로 설정되었습니다.", "info")
        except Exception as exc:
            if self.hotkey_manager:
                try:
                    self.hotkey_manager.unregister_hotkey()
                except Exception:
                    pass
                self.hotkey_manager = None
            if self.hotkey_event_filter and app:
                try:
                    app.removeNativeEventFilter(self.hotkey_event_filter)
                except Exception:
                    pass
                self.hotkey_event_filter = None
            self.append_log(f"단축키 등록 중 오류가 발생했습니다: {exc}", "warn")

    def _is_detection_active(self) -> bool:
        return bool(self.detect_btn.isChecked())

    def _set_detection_status(self, active: bool) -> None:
        active = bool(active)
        if self._detection_status == active:
            return
        self._detection_status = active
        try:
            self.detection_status_changed.emit(active)
        except Exception:
            pass

    def force_stop_detection(self) -> bool:
        stopped = False
        if not hasattr(self, 'detect_btn'):
            return False

        try:
            is_checked = bool(self.detect_btn.isChecked())
        except Exception:
            is_checked = False

        if is_checked:
            self.detect_btn.setChecked(False)
            self._toggle_detection(False)
            stopped = True
        elif self._is_detection_active():
            self._toggle_detection(False)
            if hasattr(self.detect_btn, 'setChecked'):
                self.detect_btn.setChecked(False)
            stopped = True

        if stopped:
            self.append_log("ESC 단축키로 탐지를 강제 중단했습니다.", "warn")
        return stopped

    def _schedule_facing_reset(self) -> None:
        if not hasattr(self, 'facing_reset_timer'):
            return
        self.facing_reset_timer.stop()
        if not self._is_detection_active():
            return
        if getattr(self, '_direction_active', False):
            return
        min_val = max(0.5, float(self.facing_reset_min_spinbox.value())) if hasattr(self, 'facing_reset_min_spinbox') else 1.0
        max_val = max(min_val, float(self.facing_reset_max_spinbox.value())) if hasattr(self, 'facing_reset_max_spinbox') else 4.0
        interval = random.uniform(min_val, max_val)
        self.facing_reset_timer.start(max(1, int(interval * 1000)))

    def _cancel_facing_reset_timer(self) -> None:
        if hasattr(self, 'facing_reset_timer'):
            self.facing_reset_timer.stop()

    def _handle_facing_reset_timeout(self) -> None:
        if not self._is_detection_active():
            return
        if getattr(self, '_direction_active', False):
            return
        self._set_current_facing(None, save=False)
        self._schedule_facing_reset()

    def _format_timestamp_ms(self) -> str:
        now = time.time()
        local = time.localtime(now)
        millis = int((now - int(now)) * 1000)
        return f"{time.strftime('%H:%M:%S', local)}.{millis:03d}"

    def _configure_log_view(self, widget: QTextEdit, *, minimum_height: int) -> None:
        if widget is None:
            return
        widget.setReadOnly(True)
        widget.setMinimumHeight(minimum_height)
        widget.setStyleSheet(
            "QTextEdit {"
            "background-color: #2E2E2E;"
            "color: #E0E0E0;"
            "border: 1px solid #555;"
            "font-family: Consolas, monospace;"
            "}"
        )

    def _resolve_log_color(self, color: Optional[str]) -> str:
        if not color:
            return "#E0E0E0"
        qcolor = QColor(color)
        if not qcolor.isValid():
            return "#E0E0E0"
        return qcolor.name()

    def _append_colored_text(self, widget: Optional[QTextEdit], message: str, color: Optional[str]) -> None:
        if widget is None:
            return
        color_hex = self._resolve_log_color(color)
        sanitized = html.escape(message)
        widget.append(f'<span style="color:{color_hex}">{sanitized}</span>')
        self._trim_text_edit(widget, LOG_LINE_LIMIT)

    def _trim_text_edit(self, widget: Optional[QTextEdit], max_blocks: int) -> None:
        if widget is None or max_blocks <= 0:
            return
        doc = widget.document()
        while doc.blockCount() > max_blocks:
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def _is_log_enabled(self, checkbox_attr: str) -> bool:
        checkbox = getattr(self, checkbox_attr, None)
        if checkbox is None:
            return True
        return bool(checkbox.isChecked())

    def _is_frame_summary_enabled(self) -> bool:
        checkbox = getattr(self, 'show_frame_summary_checkbox', None)
        if checkbox is None:
            return True
        return bool(checkbox.isChecked())

    def _is_frame_detail_enabled(self) -> bool:
        if not self._is_frame_summary_enabled():
            return False
        checkbox = getattr(self, 'show_frame_detail_checkbox', None)
        if checkbox is None:
            return False
        return bool(checkbox.isChecked())

    def _format_delay_ms(self, delay_sec: float) -> str:
        return f"{max(0.0, delay_sec) * 1000:.0f}ms"

    def _log_delay_message(self, context: str, delay_sec: float) -> None:
        if delay_sec <= 0:
            return
        message = f"{context} 후 대기 {self._format_delay_ms(delay_sec)}"
        self._append_control_log(message, color="gray")

    def _start_perf_logging(self) -> None:
        if not self._perf_logging_enabled:
            return
        if self._perf_log_handle is not None:
            return
        try:
            logs_dir = os.path.join(WORKSPACE_ROOT, 'perf_logs')
            os.makedirs(logs_dir, exist_ok=True)
            file_name = time.strftime('hunt_perf_%Y%m%d_%H%M%S.csv')
            path = os.path.join(logs_dir, file_name)
            handle = open(path, 'w', newline='', encoding='utf-8')
        except Exception as exc:
            self.append_log(f"성능 로그 파일을 생성하지 못했습니다: {exc}", "warn")
            self._perf_log_handle = None
            self._perf_log_writer = None
            self._perf_log_path = None
            return

        writer = csv.writer(handle)
        header = [
            'timestamp',
            'fps',
            'total_ms',
            'capture_ms',
            'preprocess_ms',
            'yolo_ms',
            'yolo_speed_preprocess_ms',
            'yolo_speed_inference_ms',
            'yolo_speed_postprocess_ms',
            'nickname_ms',
            'direction_ms',
            'post_ms',
            'render_ms',
            'emit_ms',
            'payload_latency_ms',
            'handler_ms',
            'downscale_active',
            'scale_factor',
            'frame_width',
            'frame_height',
            'input_width',
            'input_height',
            'monster_count',
            'primary_monster_count',
            'nameplate_detected_count',
            'nameplate_confirmed_count',
            'nameplate_best_score',
            'nameplate_best_class',
            'nameplate_best_template',
            'nameplate_best_track_id',
            'nameplate_best_roi',
            'nameplate_best_match_rect',
            'nameplate_source_breakdown',
            'warning',
        ]
        writer.writerow(header)
        handle.flush()
        self._perf_log_handle = handle
        self._perf_log_writer = writer
        self._perf_log_path = path
        if self._perf_logging_enabled:
            self.append_log(f"성능 로그 기록 시작: {path}", "info")

    def _stop_perf_logging(self) -> None:
        if self._perf_log_handle is None:
            return
        path = self._perf_log_path
        try:
            self._perf_log_handle.flush()
        except Exception:
            pass
        try:
            self._perf_log_handle.close()
        except Exception:
            pass
        finally:
            self._perf_log_handle = None
            self._perf_log_writer = None
            self._perf_log_path = None
        if path and self._perf_logging_enabled:
            self.append_log(f"성능 로그 기록 종료: {path}", "info")

    @staticmethod
    def _format_rect_for_log(rect: Optional[dict]) -> str:
        if not isinstance(rect, dict):
            return ""
        try:
            x = float(rect.get('x', 0.0))
            y = float(rect.get('y', 0.0))
            width = float(rect.get('width', 0.0))
            height = float(rect.get('height', 0.0))
        except (TypeError, ValueError):
            return ""
        return f"x={x:.1f},y={y:.1f},w={width:.1f},h={height:.1f}"

    def _collect_nameplate_log_fields(self) -> list:
        details_raw = {}
        try:
            details_raw = self.latest_detection_details
        except AttributeError:
            details_raw = {}
        nameplate_entries = []
        if isinstance(details_raw, dict):
            raw_entries = details_raw.get('nameplates')
            if isinstance(raw_entries, list):
                nameplate_entries = [entry for entry in raw_entries if isinstance(entry, dict)]

        detected_count = len(nameplate_entries)
        matched_entries = [entry for entry in nameplate_entries if entry.get('matched')]
        confirmed_count = len(matched_entries)

        best_entry: Optional[dict] = None
        best_score = float('-inf')
        for entry in nameplate_entries:
            try:
                score_val = float(entry.get('score', 0.0))
            except (TypeError, ValueError):
                score_val = 0.0
            if best_entry is None or score_val > best_score:
                best_entry = entry
                best_score = score_val

        if best_entry is None:
            best_score = 0.0
        best_class = str(best_entry.get('class_name') or '') if best_entry else ''
        best_template = str(best_entry.get('template_id') or '') if best_entry else ''
        best_track_id = ''
        if best_entry and best_entry.get('track_id') not in (None, ''):
            best_track_id = str(best_entry.get('track_id'))
        best_roi_text = self._format_rect_for_log(best_entry.get('roi')) if best_entry else ''
        best_match_rect_text = self._format_rect_for_log(best_entry.get('match_rect')) if best_entry else ''

        source_counts: dict[str, int] = {}
        for entry in nameplate_entries:
            source_raw = entry.get('source')
            source = source_raw if isinstance(source_raw, str) and source_raw else 'unknown'
            source_counts[source] = source_counts.get(source, 0) + 1
        source_breakdown = ''
        if source_counts:
            ordered = sorted(source_counts.items())
            source_breakdown = '|'.join(f"{key}:{value}" for key, value in ordered)

        return [
            detected_count,
            confirmed_count,
            float(max(0.0, best_score)),
            best_class,
            best_template,
            best_track_id,
            best_roi_text,
            best_match_rect_text,
            source_breakdown,
        ]

    def _append_perf_log(self, warning_text: str = "") -> None:
        if (
            not self._perf_logging_enabled
            or self._perf_log_writer is None
            or self._perf_log_handle is None
        ):
            return
        perf = self.latest_perf_stats or {}
        try:
            row = [
                time.time(),
                float(perf.get('fps', 0.0)),
                float(perf.get('total_ms', 0.0)),
                float(perf.get('capture_ms', 0.0)),
                float(perf.get('preprocess_ms', 0.0)),
                float(perf.get('yolo_ms', 0.0)),
                float(perf.get('yolo_speed_preprocess_ms', 0.0)),
                float(perf.get('yolo_speed_inference_ms', 0.0)),
                float(perf.get('yolo_speed_postprocess_ms', 0.0)),
                float(perf.get('nickname_ms', 0.0)),
                float(perf.get('direction_ms', 0.0)),
                float(perf.get('post_ms', 0.0)),
                float(perf.get('render_ms', 0.0)),
                float(perf.get('emit_ms', 0.0)),
                float(perf.get('payload_latency_ms', 0.0)),
                float(perf.get('handler_ms', 0.0)),
                float(perf.get('downscale_active', 0.0)),
                float(perf.get('scale_factor', 0.0)),
                float(perf.get('frame_width', 0.0)),
                float(perf.get('frame_height', 0.0)),
                float(perf.get('input_width', 0.0)),
                float(perf.get('input_height', 0.0)),
                int(getattr(self, 'latest_monster_count', 0)),
                int(getattr(self, 'latest_primary_monster_count', 0)),
            ]
            nameplate_fields = self._collect_nameplate_log_fields()
            row.extend(nameplate_fields)
            row.append(warning_text or "")
        except Exception as exc:
            self.append_log(f"성능 로그 행 구성 실패: {exc}", "warn")
            return
        try:
            self._perf_log_writer.writerow(row)
            self._perf_log_handle.flush()
        except Exception as exc:
            self.append_log(f"성능 로그 기록 실패: {exc}", "warn")
            self._stop_perf_logging()

    def _normalize_delay_range(self, min_value: float, max_value: float) -> tuple[float, float]:
        try:
            min_val = float(min_value)
            max_val = float(max_value)
        except (TypeError, ValueError):
            return 0.0, 0.0
        if min_val > max_val:
            min_val, max_val = max_val, min_val
        min_val = max(0.0, min_val)
        max_val = max(0.0, max_val)
        return min_val, max_val

    def _sample_delay(self, min_value: float, max_value: float) -> float:
        min_val, max_val = self._normalize_delay_range(min_value, max_value)
        if max_val <= 0.0:
            return 0.0
        if min_val == max_val:
            return min_val
        return random.uniform(min_val, max_val)

    def _start_pre_delay(self, command: str, delay_sec: float, context: str, callback: Callable[[], None]) -> bool:
        delay_sec = max(0.0, float(delay_sec))
        if delay_sec <= 0.0:
            return False
        if not command:
            return False
        if command in self._pre_delay_timers:
            return True

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(max(1, int(delay_sec * 1000)))

        def on_timeout() -> None:
            try:
                self._pre_delay_timers.pop(command, None)
            finally:
                self._next_command_ready_ts = time.time()
                callback()

        timer.timeout.connect(on_timeout)
        self._pre_delay_timers[command] = timer
        timer.start()
        self._set_command_cooldown(delay_sec)
        self.hunting_active = True
        self._append_control_log(
            f"{context} 대기 {self._format_delay_ms(delay_sec)}",
            color="gray",
        )
        return True

    def _queue_completion_delay(
        self,
        command: str,
        min_delay: float,
        max_delay: float,
        context: str,
        *,
        payload: Optional[dict] = None,
    ) -> None:
        if not command:
            return
        try:
            min_val = float(min(min_delay, max_delay))
            max_val = float(max(min_delay, max_delay))
        except (TypeError, ValueError):
            return
        min_val = max(0.0, min_val)
        max_val = max(0.0, max_val)
        if max_val <= 0.0:
            return
        self._pending_completion_delays.append({
            'command': command,
            'min': min_val,
            'max': max_val,
            'context': context,
            'payload': payload,
        })

    def _pop_completion_delay(self, command: str) -> Optional[dict]:
        if not command:
            return None
        for idx, entry in enumerate(self._pending_completion_delays):
            if entry.get('command') == command:
                return self._pending_completion_delays.pop(idx)
        return None

    def on_sequence_completed(self, command_name: str, reason: object, success: bool) -> None:
        if isinstance(reason, str) and reason.startswith('status:'):
            self._handle_status_sequence_completed(command_name, reason, success)
        command = str(command_name) if command_name else ''
        entry = self._pop_completion_delay(command)
        if not entry:
            return

        if success:
            payload = entry.get('payload')
            if payload:
                self._handle_command_completion_payload(payload)
        else:
            return

        delay = random.uniform(entry.get('min', 0.0), entry.get('max', 0.0))
        if delay <= 0:
            return
        self._set_command_cooldown(delay)
        context = entry.get('context') or f"명령 '{command}'"
        self._log_delay_message(f"{context} 완료", delay)

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(12)

        left_column = QVBoxLayout()
        left_column.setSpacing(10)

        detection_group = self._create_detection_group()
        range_group = self._create_range_group()
        condition_group = self._create_condition_group()
        direction_switch_group = self._create_direction_switch_group()
        direction_group = self._create_direction_settings_group()

        left_column.addWidget(detection_group)
        left_column.addStretch(1)

        right_column = QVBoxLayout()
        right_column.setSpacing(10)

        skill_group = self._create_skill_group()
        right_column.addWidget(skill_group, 1)

        config_row = QHBoxLayout()
        config_row.setSpacing(10)
        range_column = QVBoxLayout()
        range_column.setSpacing(10)
        range_group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed))
        range_group.setMaximumWidth(260)
        range_group.setMinimumWidth(200)
        condition_group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed))
        condition_group.setMaximumWidth(260)
        condition_group.setMinimumWidth(200)
        range_column.addWidget(range_group)
        range_column.addWidget(condition_group)

        direction_column = QVBoxLayout()
        direction_column.setSpacing(10)
        for group in (direction_switch_group, direction_group):
            group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed))
            group.setMaximumWidth(260)
            group.setMinimumWidth(200)
            direction_column.addWidget(group)

        config_row.addLayout(range_column, 1)
        config_row.addLayout(direction_column, 1)
        right_column.addLayout(config_row)
        auto_shutdown_group = self._create_auto_shutdown_group()
        right_column.addWidget(auto_shutdown_group)
        right_column.addStretch(1)

        main_layout.addLayout(left_column, 1)
        main_layout.addLayout(right_column, 1)
        main_layout.setStretch(0, 1)
        main_layout.setStretch(1, 1)

        self.setLayout(main_layout)
        self._refresh_attack_tree()
        self._refresh_buff_tree()
        self._update_monster_count_label()
        self._update_detection_summary()
        self._update_authority_ui()

    def _create_range_group(self) -> QGroupBox:
        group = QGroupBox("사냥 범위 설정")
        group.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        )
        group.setMinimumWidth(0)
        area_form = QFormLayout()

        self.enemy_range_spinbox = QSpinBox()
        self.enemy_range_spinbox.setRange(20, 2000)
        self.enemy_range_spinbox.setSingleStep(10)
        self.enemy_range_spinbox.setValue(400)
        area_form.addRow("X 범위(±px)", self.enemy_range_spinbox)

        self.y_band_height_spinbox = QSpinBox()
        self.y_band_height_spinbox.setRange(10, 400)
        self.y_band_height_spinbox.setSingleStep(5)
        self.y_band_height_spinbox.setValue(40)
        area_form.addRow("Y 범위 높이(px)", self.y_band_height_spinbox)

        self.y_band_offset_spinbox = QSpinBox()
        self.y_band_offset_spinbox.setRange(-200, 200)
        self.y_band_offset_spinbox.setSingleStep(5)
        self.y_band_offset_spinbox.setValue(0)
        area_form.addRow("Y 오프셋(px)", self.y_band_offset_spinbox)

        self.primary_skill_range_spinbox = QSpinBox()
        self.primary_skill_range_spinbox.setRange(10, 1200)
        self.primary_skill_range_spinbox.setSingleStep(10)
        self.primary_skill_range_spinbox.setValue(200)
        area_form.addRow("주 스킬 X 범위(±px)", self.primary_skill_range_spinbox)

        area_layout = QVBoxLayout()
        area_layout.addLayout(area_form)
        group.setLayout(area_layout)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))

        for spin in (
            self.enemy_range_spinbox,
            self.y_band_height_spinbox,
            self.y_band_offset_spinbox,
            self.primary_skill_range_spinbox,
        ):
            spin.valueChanged.connect(self._on_area_config_changed)
            spin.valueChanged.connect(self._handle_setting_changed)

        return group

    def _create_condition_group(self) -> QGroupBox:
        group = QGroupBox("사냥 조건")
        group.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        )
        group.setMinimumWidth(0)
        condition_form = QFormLayout()

        self.hunt_monster_threshold_spinbox = QSpinBox()
        self.hunt_monster_threshold_spinbox.setRange(1, 50)
        self.hunt_monster_threshold_spinbox.setValue(3)
        condition_form.addRow("사냥범위 몬스터", self.hunt_monster_threshold_spinbox)
        self.hunt_monster_threshold_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.primary_monster_threshold_spinbox = QSpinBox()
        self.primary_monster_threshold_spinbox.setRange(1, 50)
        self.primary_monster_threshold_spinbox.setValue(1)
        condition_form.addRow("주 스킬 범위 몬스터", self.primary_monster_threshold_spinbox)
        self.primary_monster_threshold_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.idle_release_spinbox = QDoubleSpinBox()
        self.idle_release_spinbox.setRange(0.5, 30.0)
        self.idle_release_spinbox.setSingleStep(0.5)
        self.idle_release_spinbox.setDecimals(1)
        self.idle_release_spinbox.setValue(2.0)
        condition_form.addRow("최근 미탐지 후 반납(초)", self.idle_release_spinbox)
        self.idle_release_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.max_authority_hold_spinbox = QDoubleSpinBox()
        self.max_authority_hold_spinbox.setRange(0.0, 600.0)
        self.max_authority_hold_spinbox.setSingleStep(1.0)
        self.max_authority_hold_spinbox.setDecimals(1)
        self.max_authority_hold_spinbox.setSpecialValueText("사용 안 함")
        self.max_authority_hold_spinbox.setValue(float(self.control_release_timeout))
        condition_form.addRow("전체 최대 이동권한 시간(초)", self.max_authority_hold_spinbox)
        self.max_authority_hold_spinbox.valueChanged.connect(self._handle_max_hold_changed)

        self.floor_hold_spinbox = QDoubleSpinBox()
        self.floor_hold_spinbox.setRange(0.0, 600.0)
        self.floor_hold_spinbox.setSingleStep(5.0)
        self.floor_hold_spinbox.setDecimals(1)
        self.floor_hold_spinbox.setSpecialValueText("사용 안 함")
        self.floor_hold_spinbox.setValue(float(self.floor_hold_seconds))
        condition_form.addRow("층 최대 이동권한 시간(초)", self.floor_hold_spinbox)
        self.floor_hold_spinbox.valueChanged.connect(self._handle_floor_hold_changed)

        self.map_protect_spinbox = QDoubleSpinBox()
        self.map_protect_spinbox.setRange(0.1, 10.0)
        self.map_protect_spinbox.setSingleStep(0.1)
        self.map_protect_spinbox.setDecimals(1)
        self.map_protect_spinbox.setValue(float(self.map_protect_seconds))
        condition_form.addRow("맵탭 조작권한 보호시간(초)", self.map_protect_spinbox)
        self.map_protect_spinbox.valueChanged.connect(self._handle_map_protect_changed)

        self.hunt_protect_spinbox = QDoubleSpinBox()
        self.hunt_protect_spinbox.setRange(0.1, 10.0)
        self.hunt_protect_spinbox.setSingleStep(0.1)
        self.hunt_protect_spinbox.setDecimals(1)
        self.hunt_protect_spinbox.setValue(float(self.hunt_protect_seconds))
        condition_form.addRow("사냥탭 조작권한 보호시간(초)", self.hunt_protect_spinbox)
        self.hunt_protect_spinbox.valueChanged.connect(self._handle_hunt_protect_changed)

        group.setLayout(condition_form)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        return group

    def _create_direction_switch_group(self) -> QGroupBox:
        group = QGroupBox("방향 전환")
        group.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        )
        group.setMinimumWidth(0)

        form = QFormLayout()

        self.direction_threshold_spinbox = QSpinBox()
        self.direction_threshold_spinbox.setRange(0, 1000)
        self.direction_threshold_spinbox.setSingleStep(5)
        self.direction_threshold_spinbox.setValue(50)
        self.direction_threshold_spinbox.setSuffix(" px")
        form.addRow("방향전환 Threshold", self.direction_threshold_spinbox)
        self.direction_threshold_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.direction_cooldown_spinbox = QDoubleSpinBox()
        self.direction_cooldown_spinbox.setRange(0.0, 10.0)
        self.direction_cooldown_spinbox.setSingleStep(0.1)
        self.direction_cooldown_spinbox.setDecimals(2)
        self.direction_cooldown_spinbox.setValue(0.2)
        self.direction_cooldown_spinbox.setSuffix(" s")
        form.addRow("방향전환 최소 시간", self.direction_cooldown_spinbox)
        self.direction_cooldown_spinbox.valueChanged.connect(self._handle_setting_changed)

        group.setLayout(form)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        return group

    def _create_direction_settings_group(self) -> QGroupBox:
        group = QGroupBox("방향 설정")
        group.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        )
        group.setMinimumWidth(0)
        misc_form = QFormLayout()

        self.facing_reset_min_spinbox = QDoubleSpinBox()
        self.facing_reset_min_spinbox.setRange(1.0, 10.0)
        self.facing_reset_min_spinbox.setSingleStep(0.5)
        self.facing_reset_min_spinbox.setDecimals(1)
        self.facing_reset_min_spinbox.setValue(1.0)
        self.facing_reset_min_spinbox.setSuffix(" s")

        self.facing_reset_max_spinbox = QDoubleSpinBox()
        self.facing_reset_max_spinbox.setRange(1.0, 10.0)
        self.facing_reset_max_spinbox.setSingleStep(0.5)
        self.facing_reset_max_spinbox.setDecimals(1)
        self.facing_reset_max_spinbox.setValue(4.0)
        self.facing_reset_max_spinbox.setSuffix(" s")

        misc_form.addRow("방향 초기화 최소", self.facing_reset_min_spinbox)
        misc_form.addRow("방향 초기화 최대", self.facing_reset_max_spinbox)
        self.facing_reset_min_spinbox.valueChanged.connect(self._handle_facing_reset_changed)
        self.facing_reset_max_spinbox.valueChanged.connect(self._handle_facing_reset_changed)

        self.direction_delay_min_spinbox = QDoubleSpinBox()
        self.direction_delay_min_spinbox.setRange(0.01, 5.0)
        self.direction_delay_min_spinbox.setSingleStep(0.01)
        self.direction_delay_min_spinbox.setDecimals(3)
        self.direction_delay_min_spinbox.setValue(0.035)
        self.direction_delay_min_spinbox.setSuffix(" s")

        self.direction_delay_max_spinbox = QDoubleSpinBox()
        self.direction_delay_max_spinbox.setRange(0.01, 5.0)
        self.direction_delay_max_spinbox.setSingleStep(0.01)
        self.direction_delay_max_spinbox.setDecimals(3)
        self.direction_delay_max_spinbox.setValue(0.050)
        self.direction_delay_max_spinbox.setSuffix(" s")

        misc_form.addRow("방향설정 후 대기 최소", self.direction_delay_min_spinbox)
        misc_form.addRow("방향설정 후 대기 최대", self.direction_delay_max_spinbox)
        self.direction_delay_min_spinbox.valueChanged.connect(self._handle_setting_changed)
        self.direction_delay_max_spinbox.valueChanged.connect(self._handle_setting_changed)

        group.setLayout(misc_form)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        return group

    def _create_auto_shutdown_group(self) -> QGroupBox:
        group = QGroupBox("자동 종료")
        group.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(8)

        pid_row = QHBoxLayout()
        pid_row.setSpacing(6)
        pid_row.addWidget(QLabel("PID:"))
        self.shutdown_pid_input = QLineEdit()
        self.shutdown_pid_input.setPlaceholderText("예: 12345")
        self.shutdown_pid_input.setMaximumWidth(120)
        pid_row.addWidget(self.shutdown_pid_input)
        pid_row.addStretch(1)
        outer_layout.addLayout(pid_row)

        sleep_row = QHBoxLayout()
        sleep_row.setSpacing(6)
        self.shutdown_sleep_checkbox = QCheckBox("종료 성공 시 절전 모드")
        self.shutdown_sleep_checkbox.setToolTip("PID 종료 후 Windows 절전 모드를 시도합니다.")
        sleep_row.addWidget(self.shutdown_sleep_checkbox)
        sleep_row.addStretch(1)
        outer_layout.addLayout(sleep_row)

        schedule_group = QGroupBox("특정 일시 종료")
        schedule_layout = QHBoxLayout()
        schedule_layout.setSpacing(6)
        self.shutdown_datetime_edit = QDateTimeEdit()
        self.shutdown_datetime_edit.setCalendarPopup(True)
        self.shutdown_datetime_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.shutdown_datetime_edit.setMinimumDateTime(QDateTime.currentDateTime())
        schedule_layout.addWidget(self.shutdown_datetime_edit, 1)
        self.shutdown_datetime_start_btn = QPushButton("예약")
        schedule_layout.addWidget(self.shutdown_datetime_start_btn)
        self.shutdown_datetime_cancel_btn = QPushButton("취소")
        schedule_layout.addWidget(self.shutdown_datetime_cancel_btn)
        self.shutdown_datetime_status = QLabel("--")
        self.shutdown_datetime_status.setMinimumWidth(110)
        schedule_layout.addWidget(self.shutdown_datetime_status)
        schedule_group.setLayout(schedule_layout)
        outer_layout.addWidget(schedule_group)

        delay_group = QGroupBox("N시간 N분 후 종료")
        delay_layout = QHBoxLayout()
        delay_layout.setSpacing(6)
        self.shutdown_delay_hours_spin = QSpinBox()
        self.shutdown_delay_hours_spin.setRange(0, 72)
        self.shutdown_delay_hours_spin.setSuffix(" 시간")
        delay_layout.addWidget(self.shutdown_delay_hours_spin)
        self.shutdown_delay_minutes_spin = QSpinBox()
        self.shutdown_delay_minutes_spin.setRange(0, 59)
        self.shutdown_delay_minutes_spin.setSuffix(" 분")
        delay_layout.addWidget(self.shutdown_delay_minutes_spin)
        self.shutdown_delay_start_btn = QPushButton("예약")
        delay_layout.addWidget(self.shutdown_delay_start_btn)
        self.shutdown_delay_cancel_btn = QPushButton("취소")
        delay_layout.addWidget(self.shutdown_delay_cancel_btn)
        self.shutdown_delay_status = QLabel("--")
        self.shutdown_delay_status.setMinimumWidth(110)
        delay_layout.addWidget(self.shutdown_delay_status)
        delay_group.setLayout(delay_layout)
        outer_layout.addWidget(delay_group)

        other_group = QGroupBox("다른 캐릭터 감지")
        other_layout = QHBoxLayout()
        other_layout.setSpacing(6)
        self.shutdown_other_player_checkbox = QCheckBox("감지 시")
        other_layout.addWidget(self.shutdown_other_player_checkbox)
        other_layout.addWidget(QLabel("N분 지속"))
        self.shutdown_other_player_minutes_spin = QSpinBox()
        self.shutdown_other_player_minutes_spin.setRange(1, 120)
        self.shutdown_other_player_minutes_spin.setValue(5)
        self.shutdown_other_player_minutes_spin.setSuffix(" 분")
        other_layout.addWidget(self.shutdown_other_player_minutes_spin)
        self.shutdown_other_player_reset_btn = QPushButton("초기화")
        other_layout.addWidget(self.shutdown_other_player_reset_btn)
        self.shutdown_other_player_status = QLabel("--")
        self.shutdown_other_player_status.setMinimumWidth(140)
        other_layout.addWidget(self.shutdown_other_player_status)
        other_group.setLayout(other_layout)
        outer_layout.addWidget(other_group)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        status_row.addWidget(QLabel("총 상태:"))
        self.shutdown_summary_label = QLabel("대기 중")
        status_row.addWidget(self.shutdown_summary_label, 1)
        outer_layout.addLayout(status_row)

        group.setLayout(outer_layout)
        return group

    def _setup_auto_shutdown_ui(self) -> None:
        if not hasattr(self, 'shutdown_datetime_edit'):
            return

        try:
            default_dt = QDateTime.currentDateTime().addSecs(600)
            self.shutdown_datetime_edit.setDateTime(default_dt)
        except Exception:
            pass

        self.shutdown_datetime_start_btn.clicked.connect(self._schedule_absolute_shutdown)
        self.shutdown_datetime_cancel_btn.clicked.connect(lambda: self._cancel_shutdown_mode('absolute'))
        self.shutdown_delay_start_btn.clicked.connect(self._schedule_delay_shutdown)
        self.shutdown_delay_cancel_btn.clicked.connect(lambda: self._cancel_shutdown_mode('delay'))
        self.shutdown_other_player_checkbox.toggled.connect(self._toggle_other_player_mode)
        self.shutdown_other_player_reset_btn.clicked.connect(self._reset_other_player_progress)
        self.shutdown_pid_input.editingFinished.connect(self._sync_shutdown_pid_from_input)
        self.shutdown_other_player_minutes_spin.valueChanged.connect(self._handle_other_player_minutes_changed)
        self.shutdown_sleep_checkbox.toggled.connect(self._on_shutdown_sleep_toggled)

        self._update_shutdown_labels()

    def _sync_shutdown_pid_from_input(self) -> None:
        text = self.shutdown_pid_input.text().strip() if hasattr(self, 'shutdown_pid_input') else ''
        if not text:
            self.shutdown_pid_value = None
            return
        try:
            pid = int(text, 10)
            if pid <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "PID 오류", "PID는 양의 정수여야 합니다.")
            self.shutdown_pid_input.setFocus()
            self.shutdown_pid_input.selectAll()
            return
        self.shutdown_pid_value = pid
        self.shutdown_pid_input.setText(str(pid))

    def _require_shutdown_pid(self) -> Optional[int]:
        self._sync_shutdown_pid_from_input()
        if self.shutdown_pid_value is None:
            QMessageBox.warning(self, "PID 필요", "자동 종료를 위해 PID를 입력해주세요.")
        return self.shutdown_pid_value

    def _schedule_absolute_shutdown(self) -> None:
        pid = self._require_shutdown_pid()
        if pid is None:
            return

        try:
            target_dt = self.shutdown_datetime_edit.dateTime()
        except Exception:
            target_dt = None
        if target_dt is None or not target_dt.isValid():
            QMessageBox.warning(self, "시간 오류", "유효한 종료 일시를 선택해주세요.")
            return
        target_ts = float(target_dt.toSecsSinceEpoch())
        now = time.time()
        if target_ts <= now:
            QMessageBox.warning(self, "시간 오류", "종료 예약 시간은 현재보다 이후여야 합니다.")
            return
        self.shutdown_pid_value = pid
        self.shutdown_datetime_target = target_ts
        self._ensure_shutdown_timer_running()
        self._update_shutdown_labels()

    def _schedule_delay_shutdown(self) -> None:
        pid = self._require_shutdown_pid()
        if pid is None:
            return
        hours = int(self.shutdown_delay_hours_spin.value()) if hasattr(self, 'shutdown_delay_hours_spin') else 0
        minutes = int(self.shutdown_delay_minutes_spin.value()) if hasattr(self, 'shutdown_delay_minutes_spin') else 0
        total_seconds = hours * 3600 + minutes * 60
        if total_seconds <= 0:
            QMessageBox.warning(self, "시간 오류", "1분 이상으로 설정해주세요.")
            return
        self.shutdown_pid_value = pid
        self.shutdown_delay_target = time.time() + total_seconds
        self._ensure_shutdown_timer_running()
        self._update_shutdown_labels()

    def _cancel_shutdown_mode(self, mode: str) -> None:
        mode = (mode or '').lower()
        if mode == 'absolute':
            self.shutdown_datetime_target = None
            self.shutdown_datetime_status.setText("--")
        elif mode == 'delay':
            self.shutdown_delay_target = None
            self.shutdown_delay_status.setText("--")
        elif mode == 'other':
            self._reset_other_player_progress()
            if hasattr(self, 'shutdown_other_player_checkbox'):
                blocker = QSignalBlocker(self.shutdown_other_player_checkbox)
                self.shutdown_other_player_checkbox.setChecked(False)
                del blocker
        self._update_shutdown_labels()
        self._stop_shutdown_timer_if_idle()

    def _toggle_other_player_mode(self, checked: bool) -> None:
        checked = bool(checked)
        if checked:
            pid = self._require_shutdown_pid()
            if pid is None:
                blocker = QSignalBlocker(self.shutdown_other_player_checkbox)
                self.shutdown_other_player_checkbox.setChecked(False)
                del blocker
                return
            self.shutdown_pid_value = pid
            self.shutdown_other_player_enabled = True
            self._ensure_shutdown_timer_running()
        else:
            self.shutdown_other_player_enabled = False
            self._reset_other_player_progress()
        self._update_shutdown_labels()

    def _reset_other_player_progress(self) -> None:
        self.shutdown_other_player_detect_since = None
        self.shutdown_other_player_due = None
        if hasattr(self, 'shutdown_other_player_status'):
            self.shutdown_other_player_status.setText("--")
        self._stop_shutdown_timer_if_idle()

    def _handle_other_player_minutes_changed(self, value: int) -> None:
        if not self.shutdown_other_player_detect_since:
            return
        minutes = max(1, int(value))
        self.shutdown_other_player_due = self.shutdown_other_player_detect_since + minutes * 60
        self._ensure_shutdown_timer_running()
        self._update_shutdown_labels()

    def _on_shutdown_sleep_toggled(self, checked: bool) -> None:
        self.shutdown_sleep_enabled = bool(checked)
        self._update_shutdown_labels()
        self._handle_setting_changed()

    def _ensure_shutdown_timer_running(self) -> None:
        if not self.shutdown_timer.isActive():
            self.shutdown_timer.start()

    def _stop_shutdown_timer_if_idle(self) -> None:
        if (
            self.shutdown_datetime_target is None
            and self.shutdown_delay_target is None
            and (not self.shutdown_other_player_enabled or self.shutdown_other_player_due is None)
        ):
            self.shutdown_timer.stop()

    def _handle_shutdown_timer_tick(self) -> None:
        now = time.time()
        triggered_modes: list[str] = []

        if self.shutdown_datetime_target is not None:
            remaining = self.shutdown_datetime_target - now
            if remaining <= 0:
                triggered_modes.append('absolute')
            else:
                self.shutdown_datetime_status.setText(self._format_remaining_text(remaining))

        if self.shutdown_delay_target is not None:
            remaining = self.shutdown_delay_target - now
            if remaining <= 0:
                triggered_modes.append('delay')
            else:
                self.shutdown_delay_status.setText(self._format_remaining_text(remaining))

        if self.shutdown_other_player_enabled and self.shutdown_other_player_due is not None:
            remaining = self.shutdown_other_player_due - now
            if remaining <= 0:
                triggered_modes.append('other')
            else:
                self.shutdown_other_player_status.setText(self._format_remaining_text(remaining))

        if not triggered_modes:
            self._update_shutdown_labels()
            self._stop_shutdown_timer_if_idle()
            return

        for mode in triggered_modes:
            self._trigger_shutdown(mode)
            if self.shutdown_pid_value is None:
                break

    def _format_remaining_text(self, seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        mins, secs = divmod(int(round(seconds)), 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def _update_shutdown_labels(self) -> None:
        parts: list[str] = []
        now = time.time()
        if self.shutdown_datetime_target is not None:
            parts.append("일시 예약")
            self.shutdown_datetime_status.setText(
                self._format_remaining_text(self.shutdown_datetime_target - now)
            )
        else:
            self.shutdown_datetime_status.setText("--")

        if self.shutdown_delay_target is not None:
            parts.append("지연 예약")
            self.shutdown_delay_status.setText(
                self._format_remaining_text(self.shutdown_delay_target - now)
            )
        else:
            self.shutdown_delay_status.setText("--")

        if self.shutdown_other_player_enabled:
            parts.append("다른 캐릭터 감시")
            if self.shutdown_other_player_due is not None:
                text = self._format_remaining_text(self.shutdown_other_player_due - now)
                count = max(0, int(self.shutdown_other_player_last_count))
                if count > 0:
                    text = f"{text} ({count}명)"
                self.shutdown_other_player_status.setText(text)
            else:
                self.shutdown_other_player_status.setText("감지 대기")
        else:
            self.shutdown_other_player_status.setText("--")

        if self.shutdown_sleep_enabled and (
            self.shutdown_datetime_target is not None
            or self.shutdown_delay_target is not None
            or self.shutdown_other_player_enabled
        ):
            parts.append("절전 모드")

        summary = ', '.join(parts) if parts else '대기 중'
        self.shutdown_summary_label.setText(summary)

        if hasattr(self, 'shutdown_sleep_checkbox'):
            blocker = QSignalBlocker(self.shutdown_sleep_checkbox)
            self.shutdown_sleep_checkbox.setChecked(self.shutdown_sleep_enabled)
            del blocker


    def _trigger_shutdown(self, mode: str) -> None:
        mode_key = (mode or '').lower()
        if mode_key == 'absolute':
            self.shutdown_datetime_target = None
        elif mode_key == 'delay':
            self.shutdown_delay_target = None
        elif mode_key == 'other':
            self.shutdown_other_player_due = None
            self.shutdown_other_player_detect_since = None
        self._stop_shutdown_timer_if_idle()
        self._update_shutdown_labels()

        pid = self.shutdown_pid_value
        reason_map = {
            'absolute': '특정 일시',
            'delay': 'N시간/N분',
            'other': '다른 캐릭터 감지',
        }
        reason_label = reason_map.get(mode_key, '자동 종료')
        self._shutdown_last_reason = reason_label

        if pid is None:
            self.append_log(f"자동 종료[{reason_label}] 시도 실패: PID가 설정되어 있지 않습니다.", 'warn')
            self._log_map_shutdown(f"자동 종료[{reason_label}] 시도 실패: PID 입력 필요", 'orange')
            return

        success, detail, signal_used = self._perform_process_kill(pid)
        if success:
            signal_text = f" ({signal_used})" if signal_used else ''
            message = f"자동 종료[{reason_label}] 조건 충족 - PID {pid} 프로세스를 종료했습니다{signal_text}."
            self.append_log(message, 'warn')
            self._log_map_shutdown(message, 'orange')
            self._cancel_all_shutdown_modes()
            self.shutdown_pid_value = None
            if hasattr(self, 'shutdown_pid_input'):
                self.shutdown_pid_input.setText('')
            self._issue_all_keys_release('shutdown')
            self.force_stop_detection()
            if getattr(self, 'map_tab', None) and hasattr(self.map_tab, 'force_stop_detection'):
                try:
                    self.map_tab.force_stop_detection()
                except Exception:
                    pass
            if self.shutdown_sleep_enabled:
                self._attempt_system_sleep()
        else:
            detail_text = f": {detail}" if detail else ''
            message = f"자동 종료[{reason_label}] PID {pid} 종료 실패{detail_text}"
            self.append_log(message, 'warn')
            self._log_map_shutdown(message, 'red')

    def _perform_process_kill(self, pid: int) -> tuple[bool, str, str]:
        try:
            os.kill(pid, signal.SIGTERM)
            return True, '', 'SIGTERM'
        except ProcessLookupError:
            return True, '프로세스가 이미 종료되었습니다.', 'SIGTERM'
        except PermissionError as exc:
            return False, str(exc), 'SIGTERM'
        except Exception as exc:
            term_error = str(exc)
        else:
            term_error = ''

        if not term_error:
            return True, '', 'SIGTERM'

        sigkill = getattr(signal, 'SIGKILL', None)
        if sigkill is None:
            return False, term_error, 'SIGTERM'
        try:
            os.kill(pid, sigkill)
            return True, '', 'SIGKILL'
        except ProcessLookupError:
            return True, '프로세스가 이미 종료되었습니다.', 'SIGKILL'
        except Exception as exc:
            return False, f"{term_error}; SIGKILL 실패: {exc}", 'SIGKILL'

    def _attempt_system_sleep(self) -> None:
        message: Optional[str] = None
        if os.name != 'nt':
            message = "절전 모드는 Windows에서만 지원되어 시도하지 않았습니다."
            self.append_log(message, 'warn')
            self._log_map_shutdown(message, 'orange')
            return

        try:
            powrprof = ctypes.windll.powrprof
        except Exception as exc:
            message = f"절전 모드 API 접근 실패: {exc}"
            self.append_log(message, 'warn')
            self._log_map_shutdown(message, 'red')
            return

        try:
            result = powrprof.SetSuspendState(False, False, False)
        except Exception as exc:
            message = f"절전 모드 진입 실패: {exc}"
            self.append_log(message, 'warn')
            self._log_map_shutdown(message, 'red')
            return

        if result == 0:
            message = "절전 모드 진입 요청이 거부되었습니다."
            self.append_log(message, 'warn')
            self._log_map_shutdown(message, 'orange')
            return

        message = "절전 모드 진입을 요청했습니다."
        self.append_log(message, 'info')
        self._log_map_shutdown(message, 'orange')

    def _cancel_all_shutdown_modes(self) -> None:
        self.shutdown_datetime_target = None
        self.shutdown_delay_target = None
        self.shutdown_other_player_due = None
        self.shutdown_other_player_detect_since = None
        self.shutdown_other_player_last_count = 0
        self.shutdown_other_player_enabled = False
        if hasattr(self, 'shutdown_other_player_checkbox') and self.shutdown_other_player_checkbox.isChecked():
            blocker = QSignalBlocker(self.shutdown_other_player_checkbox)
            self.shutdown_other_player_checkbox.setChecked(False)
            del blocker
        if hasattr(self, 'shutdown_datetime_status'):
            self.shutdown_datetime_status.setText("--")
        if hasattr(self, 'shutdown_delay_status'):
            self.shutdown_delay_status.setText("--")
        if hasattr(self, 'shutdown_other_player_status'):
            self.shutdown_other_player_status.setText("--")
        self.shutdown_timer.stop()
        self._update_shutdown_labels()

    def _log_map_shutdown(self, message: str, color: str) -> None:
        map_tab = getattr(self, 'map_tab', None)
        if map_tab and hasattr(map_tab, 'update_general_log'):
            try:
                map_tab.update_general_log(message, color)
            except Exception:
                pass

    def handle_other_player_presence(self, has_other: bool, count: int, timestamp: Optional[float] = None) -> None:
        if not self.shutdown_other_player_enabled:
            return
        now = float(timestamp) if isinstance(timestamp, (int, float)) else time.time()
        count = max(0, int(count))
        if has_other and count > 0:
            if self.shutdown_other_player_detect_since is None:
                self.shutdown_other_player_detect_since = now
            minutes = max(1, int(self.shutdown_other_player_minutes_spin.value()))
            self.shutdown_other_player_due = self.shutdown_other_player_detect_since + minutes * 60
            self.shutdown_other_player_last_count = count
            remaining = self.shutdown_other_player_due - now if self.shutdown_other_player_due else None
            if remaining is not None:
                text = self._format_remaining_text(remaining)
                if count > 0:
                    text = f"{text} ({count}명)"
                self.shutdown_other_player_status.setText(text)
            self._ensure_shutdown_timer_running()
        else:
            self.shutdown_other_player_last_count = 0
            self._reset_other_player_progress()
        self._update_shutdown_labels()

    def _create_detection_group(self) -> QGroupBox:
        group = QGroupBox("탐지 실행")
        group.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        )
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(8)

        control_container = QWidget()
        control_layout = QVBoxLayout(control_container)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(8)

        self.set_area_btn = QPushButton("영역 지정")
        self.set_area_btn.setEnabled(True)
        self.set_area_btn.clicked.connect(self._set_manual_area)

        control_row = QHBoxLayout()
        control_row.setSpacing(12)

        self.detect_btn = QPushButton("사냥시작")
        self.detect_btn.setCheckable(True)
        self.detect_btn.setToolTip("단축키: F10")
        self.detect_btn.clicked.connect(self._toggle_detection)
        control_row.addWidget(self.detect_btn)

        control_row.addWidget(self.set_area_btn)

        self.add_area_btn = QPushButton("+")
        self.add_area_btn.setEnabled(False)
        self.add_area_btn.setFixedWidth(28)
        self.add_area_btn.clicked.connect(self._add_manual_area)
        control_row.addWidget(self.add_area_btn)

        control_row.addWidget(QLabel(f"{CHARACTER_CLASS_NAME} 신뢰도:"))
        self.conf_char_spinbox = QDoubleSpinBox()
        self.conf_char_spinbox.setRange(0.05, 0.95)
        self.conf_char_spinbox.setSingleStep(0.05)
        self.conf_char_spinbox.setValue(0.5)
        self.conf_char_spinbox.valueChanged.connect(self._on_conf_char_changed)
        control_row.addWidget(self.conf_char_spinbox)

        control_row.addWidget(QLabel("몬스터 신뢰도:"))
        self.conf_monster_spinbox = QDoubleSpinBox()
        self.conf_monster_spinbox.setRange(0.05, 0.95)
        self.conf_monster_spinbox.setSingleStep(0.05)
        self.conf_monster_spinbox.setValue(0.5)
        self.conf_monster_spinbox.valueChanged.connect(self._handle_setting_changed)
        control_row.addWidget(self.conf_monster_spinbox)

        self.screen_output_checkbox = QCheckBox("화면출력")
        self.screen_output_checkbox.setChecked(False)
        self.screen_output_checkbox.toggled.connect(self._on_screen_output_toggled)

        self.auto_request_checkbox = QCheckBox("자동사냥")
        self.auto_request_checkbox.toggled.connect(self._handle_setting_changed)
        for checkbox in (self.screen_output_checkbox, self.auto_request_checkbox):
            checkbox.setSizePolicy(
                QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            )

        control_row.addWidget(self.screen_output_checkbox)
        control_row.addWidget(self.auto_request_checkbox)

        self.map_link_checkbox = QCheckBox("맵 탭 연동")
        self.map_link_checkbox.setChecked(self.map_link_enabled)
        self.map_link_checkbox.toggled.connect(self._on_map_link_toggled)
        self.map_link_checkbox.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        )
        control_row.addWidget(self.map_link_checkbox)

        self.downscale_checkbox = QCheckBox("다운스케일")
        self.downscale_checkbox.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        )
        self.downscale_checkbox.toggled.connect(self._on_downscale_toggled)
        control_row.addWidget(self.downscale_checkbox)
        self._update_downscale_checkbox_text()

        control_row.addStretch(1)
        control_layout.addLayout(control_row)

        self.show_hunt_area_checkbox = QCheckBox("사냥 범위")
        self.show_hunt_area_checkbox.setChecked(True)
        self.show_hunt_area_checkbox.toggled.connect(self._on_overlay_toggle_changed)

        self.show_primary_skill_checkbox = QCheckBox("주스킬 범위")
        self.show_primary_skill_checkbox.setChecked(True)
        self.show_primary_skill_checkbox.toggled.connect(self._on_overlay_toggle_changed)

        self.show_direction_checkbox = QCheckBox("캐릭터방향 범위")
        self.show_direction_checkbox.setChecked(True)
        self.show_direction_checkbox.toggled.connect(self._on_overlay_toggle_changed)

        self.show_nickname_range_checkbox = QCheckBox("닉네임 범위")
        self.show_nickname_range_checkbox.setChecked(True)
        self.show_nickname_range_checkbox.toggled.connect(self._on_overlay_toggle_changed)

        self.show_nameplate_checkbox = QCheckBox("몬스터 이름표 범위")
        self.show_nameplate_checkbox.setChecked(True)
        self.show_nameplate_checkbox.toggled.connect(self._on_overlay_toggle_changed)
        self.show_nameplate_tracking_checkbox = QCheckBox("몬스터 이름표 시각화")
        self.show_nameplate_tracking_checkbox.setChecked(self.overlay_preferences.get('nameplate_tracking', False))
        self.show_nameplate_tracking_checkbox.toggled.connect(self._on_nameplate_tracking_toggle_changed)
        self.show_monster_confidence_checkbox = QCheckBox("몬스터 신뢰도 표시")
        self.show_monster_confidence_checkbox.setChecked(self.overlay_preferences.get('monster_confidence', True))
        self.show_monster_confidence_checkbox.toggled.connect(self._on_monster_confidence_toggle_changed)

        for checkbox in (
            self.show_hunt_area_checkbox,
            self.show_primary_skill_checkbox,
            self.show_direction_checkbox,
            self.show_nickname_range_checkbox,
            self.show_nameplate_checkbox,
            self.show_nameplate_tracking_checkbox,
            self.show_monster_confidence_checkbox,
        ):
            checkbox.setSizePolicy(
                QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            )

        button_row = QHBoxLayout()
        button_row.setSpacing(12)
        button_row.addWidget(self.show_hunt_area_checkbox)
        button_row.addWidget(self.show_primary_skill_checkbox)
        button_row.addWidget(self.show_direction_checkbox)
        button_row.addWidget(self.show_nickname_range_checkbox)
        button_row.addWidget(self.show_nameplate_checkbox)
        button_row.addWidget(self.show_nameplate_tracking_checkbox)
        button_row.addWidget(self.show_monster_confidence_checkbox)

        button_row.addStretch(1)
        control_layout.addLayout(button_row)

        control_container.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        outer_layout.addWidget(control_container)

        self.detection_view = None

        control_log_section = QWidget()
        control_log_layout = QVBoxLayout()
        control_log_layout.setContentsMargins(0, 0, 0, 0)
        control_log_layout.setSpacing(4)
        control_log_section.setLayout(control_log_layout)
        control_log_section.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        )
        control_log_header = QHBoxLayout()
        control_log_label = QLabel("입력 로그")
        self.control_log_checkbox = QCheckBox()
        self.control_log_checkbox.setChecked(False)
        self.control_log_checkbox.toggled.connect(self._on_log_checkbox_toggled)
        control_log_header.addWidget(control_log_label)
        control_log_header.addWidget(self.control_log_checkbox)
        control_log_header.addStretch(1)
        control_log_layout.addLayout(control_log_header)
        self.control_log_view = QTextEdit()
        self._configure_log_view(self.control_log_view, minimum_height=160)
        control_log_layout.addWidget(self.control_log_view)
        outer_layout.addWidget(control_log_section)
        self.control_log_section = control_log_section

        keyboard_log_container = QVBoxLayout()
        keyboard_log_header = QHBoxLayout()
        keyboard_log_label = QLabel("키보드 입력 로그")
        self.keyboard_log_checkbox = QCheckBox()
        self.keyboard_log_checkbox.setChecked(True)
        self.keyboard_log_checkbox.toggled.connect(self._on_log_checkbox_toggled)
        keyboard_log_header.addWidget(keyboard_log_label)
        keyboard_log_header.addWidget(self.keyboard_log_checkbox)
        keyboard_log_header.addStretch(1)
        keyboard_log_container.addLayout(keyboard_log_header)
        self.keyboard_log_view = QTextEdit()
        self._configure_log_view(self.keyboard_log_view, minimum_height=160)
        keyboard_log_container.addWidget(self.keyboard_log_view)
        outer_layout.addLayout(keyboard_log_container)

        log_container = QVBoxLayout()
        log_header = QHBoxLayout()
        log_label = QLabel("로그")
        self.main_log_checkbox = QCheckBox()
        self.main_log_checkbox.setChecked(True)
        self.main_log_checkbox.toggled.connect(self._on_log_checkbox_toggled)
        log_header.addWidget(log_label)
        log_header.addWidget(self.main_log_checkbox)
        log_header.addStretch(1)
        log_container.addLayout(log_header)
        self.log_view = QTextEdit()
        self._configure_log_view(self.log_view, minimum_height=200)
        log_container.addWidget(self.log_view)
        outer_layout.addLayout(log_container)

        self._log_base_heights = {
            'control': self.control_log_view.minimumHeight(),
            'keyboard': self.keyboard_log_view.minimumHeight(),
            'main': self.log_view.minimumHeight(),
        }

        self._update_log_visibility_state()

        summary_group = self._create_detection_summary_group()
        outer_layout.addWidget(summary_group)

        group.setLayout(outer_layout)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding))
        return group

    def _resolve_detection_targets(self) -> tuple[List[int], int]:
        if not self.data_manager or not hasattr(self.data_manager, "get_class_list"):
            self._active_target_names = []
            return [], -1
        class_list = self.data_manager.get_class_list()
        target_indices = list(range(len(class_list)))
        checked_names: list[str] = []
        if hasattr(self.data_manager, "load_settings"):
            try:
                settings = self.data_manager.load_settings()
                checked_names = list(settings.get('hunt_checked_classes', []))
            except Exception:
                checked_names = []
        if checked_names:
            name_to_index = {name: idx for idx, name in enumerate(class_list)}
            target_indices = [name_to_index[name] for name in checked_names if name in name_to_index]
        char_index = (
            class_list.index(CHARACTER_CLASS_NAME)
            if CHARACTER_CLASS_NAME in class_list
            else -1
        )
        if char_index != -1:
            target_indices = [idx for idx in target_indices if idx != char_index]
        target_indices = sorted({idx for idx in target_indices if 0 <= idx < len(class_list)})
        self._active_target_names = [class_list[idx] for idx in target_indices]
        return target_indices, char_index

    def _resolve_monster_confidence_overrides(self, target_indices: Iterable[int]) -> dict[int, float]:
        if not self.data_manager or not hasattr(self.data_manager, "get_monster_confidence_overrides"):
            return {}
        try:
            overrides_by_name = self.data_manager.get_monster_confidence_overrides()
        except Exception:
            return {}
        if not overrides_by_name:
            return {}
        try:
            class_list = self.data_manager.get_class_list()
        except Exception:
            return {}
        name_to_index = {name: idx for idx, name in enumerate(class_list)}
        valid_indices = {int(idx) for idx in target_indices}
        resolved: dict[int, float] = {}
        for name, value in overrides_by_name.items():
            index = name_to_index.get(name)
            if index is None or index not in valid_indices:
                continue
            try:
                resolved[index] = max(0.05, min(0.95, float(value)))
            except (TypeError, ValueError):
                continue
        return resolved

    def _log_monster_confidence_overrides(self, overrides: dict[int, float]) -> None:
        if not overrides:
            return
        class_names: List[str] = []
        if self.data_manager and hasattr(self.data_manager, "get_class_list"):
            try:
                class_list = self.data_manager.get_class_list()
            except Exception:
                class_list = []
        else:
            class_list = []
        for index, value in sorted(overrides.items()):
            if 0 <= index < len(class_list):
                label = class_list[index]
            else:
                label = f"클래스#{index}"
            class_names.append(f"{label}={value:.2f}")
        summary = ', '.join(class_names) if class_names else '사용'
        self.append_log(f"몬스터 개별 신뢰도 적용: {summary}", "info")

    def _set_manual_area(self) -> None:
        snipper = ScreenSnipper(self)
        if snipper.exec():
            roi = snipper.get_roi()
            new_region = {
                'top': roi.top(),
                'left': roi.left(),
                'width': roi.width(),
                'height': roi.height(),
            }
            if new_region['width'] <= 0 or new_region['height'] <= 0:
                self.append_log('지정한 영역의 크기가 유효하지 않아 무시합니다.', 'warn')
                return
            self.manual_capture_region = dict(new_region)
            self.manual_capture_regions = [dict(new_region)]
            if hasattr(self, 'add_area_btn'):
                self.add_area_btn.setEnabled(True)
            self.append_log(f"수동 탐지 영역 초기화: {self.manual_capture_region}")
            self._update_manual_area_summary()
            self._save_settings()
        else:
            # 취소(우클릭) 시 기존 영역 유지
            self.append_log('영역 지정이 취소되어 기존 영역을 유지합니다.', 'info')

    def _add_manual_area(self) -> None:
        if not self.manual_capture_region:
            self.append_log('기본 영역이 없어 영역을 추가할 수 없습니다. 먼저 "영역 지정"을 실행하세요.', 'warn')
            return
        snipper = ScreenSnipper(self)
        if snipper.exec():
            roi = snipper.get_roi()
            new_region = {
                'top': roi.top(),
                'left': roi.left(),
                'width': roi.width(),
                'height': roi.height(),
            }
            if new_region['width'] <= 0 or new_region['height'] <= 0:
                self.append_log('추가한 영역의 크기가 유효하지 않아 무시합니다.', 'warn')
                return
            self.manual_capture_regions.append(dict(new_region))
            self.manual_capture_region = self._merge_manual_capture_regions()
            if hasattr(self, 'add_area_btn') and not self.add_area_btn.isEnabled():
                self.add_area_btn.setEnabled(True)
            self.append_log(f"영역 추가 완료. 합성 영역: {self.manual_capture_region}")
            self._update_manual_area_summary()
            self._save_settings()
        else:
            self.append_log('영역 추가가 취소되었습니다.', 'info')

    def _merge_manual_capture_regions(self) -> Optional[dict]:
        if not self.manual_capture_regions:
            return self.manual_capture_region
        top_values = [region['top'] for region in self.manual_capture_regions]
        left_values = [region['left'] for region in self.manual_capture_regions]
        bottoms = [region['top'] + region['height'] for region in self.manual_capture_regions]
        rights = [region['left'] + region['width'] for region in self.manual_capture_regions]
        merged = {
            'top': min(top_values),
            'left': min(left_values),
            'width': max(rights) - min(left_values),
            'height': max(bottoms) - min(top_values),
        }
        return merged

    def _resolve_manual_subregions(self, capture_region: dict) -> Optional[list[dict]]:
        if not isinstance(capture_region, dict):
            return None
        if not self.manual_capture_regions or len(self.manual_capture_regions) <= 1:
            return None
        try:
            base_top = int(capture_region['top'])
            base_left = int(capture_region['left'])
            base_width = int(capture_region['width'])
            base_height = int(capture_region['height'])
        except (KeyError, TypeError, ValueError):
            return None
        if base_width <= 0 or base_height <= 0:
            return None
        subregions: list[dict] = []
        for region in self.manual_capture_regions:
            try:
                top = int(region['top']) - base_top
                left = int(region['left']) - base_left
                width = int(region['width'])
                height = int(region['height'])
            except (KeyError, TypeError, ValueError):
                continue
            if width <= 0 or height <= 0:
                continue
            rel_top = max(0, min(base_height, top))
            rel_left = max(0, min(base_width, left))
            rel_bottom = max(rel_top, min(base_height, rel_top + height))
            rel_right = max(rel_left, min(base_width, rel_left + width))
            if rel_top >= rel_bottom or rel_left >= rel_right:
                continue
            subregions.append(
                {
                    'top': rel_top,
                    'left': rel_left,
                    'width': rel_right - rel_left,
                    'height': rel_bottom - rel_top,
                }
            )
        return subregions or None

    def _update_manual_area_summary(self) -> None:
        count = len(self.manual_capture_regions)
        if count <= 1:
            return
        self.append_log(
            f"추가된 영역 수: {count}, 합성 캡처 범위: {self.manual_capture_region}."
            " 합성 범위 내부에서도 지정된 영역만 탐지에 사용됩니다."
        )

    def _activate_maple_window(self) -> Optional[object]:
        try:
            maple_windows = gw.getWindowsWithTitle('Mapleland')
        except Exception as exc:
            self.append_log(f"게임 창 검색 실패: {exc}", "warn")
            return None

        if not maple_windows:
            return None

        target_window = maple_windows[0]
        try:
            if target_window.isMinimized:
                target_window.restore()
                QThread.msleep(200)
            target_window.activate()
            QThread.msleep(120)
            self.append_log(
                f"게임 창 활성화: '{target_window.title}'",
                "debug",
            )
        except Exception as exc:
            self.append_log(f"게임 창 활성화 중 오류 발생: {exc}", "warn")
            return None

        return target_window

    def _get_active_model_name(self) -> Optional[str]:
        model_name: Optional[str] = None
        if self.data_manager and hasattr(self.data_manager, 'get_last_used_model'):
            try:
                model_name = self.data_manager.get_last_used_model()
            except Exception:
                model_name = None
        if not model_name and self.data_manager and hasattr(self.data_manager, 'load_settings'):
            try:
                settings = self.data_manager.load_settings()
            except Exception:
                settings = {}
            if isinstance(settings, dict):
                model_name = settings.get('last_used_model') or settings.get('model')
        if not model_name and isinstance(self.last_used_model, str):
            model_name = self.last_used_model
        if isinstance(model_name, str):
            model_name = model_name.strip()
            if model_name:
                self.last_used_model = model_name
                return model_name
        return None

    def _handle_model_changed(self, model_name: Optional[str]) -> None:
        normalized = model_name.strip() if isinstance(model_name, str) else None
        if normalized and normalized != self.last_used_model:
            self.last_used_model = normalized
            self.append_log(f"모델 변경 감지: '{normalized}'", "info")
        elif not normalized:
            self.last_used_model = None

    def _toggle_detection(self, checked: bool) -> None:
        if checked:
            if not self.data_manager:
                QMessageBox.warning(self, "오류", "학습 탭과의 연동이 필요합니다.")
                self.detect_btn.setChecked(False)
                return

            selected_model = self._get_active_model_name()
            if not selected_model:
                QMessageBox.warning(self, "오류", "학습 탭에서 사용할 모델을 먼저 지정하세요.")
                self.detect_btn.setChecked(False)
                return

            models_root = getattr(self.data_manager, 'models_path', None)
            if not models_root:
                QMessageBox.warning(self, "오류", "모델 경로를 찾을 수 없습니다.")
                self.detect_btn.setChecked(False)
                return

            model_weights_dir = os.path.join(models_root, selected_model, 'weights')
            engine_path = os.path.join(model_weights_dir, 'best.engine')
            pt_path = os.path.join(model_weights_dir, 'best.pt')
            model_path = engine_path if os.path.exists(engine_path) else pt_path
            if not os.path.exists(model_path):
                QMessageBox.warning(self, "오류", "가중치 파일을 찾을 수 없습니다.")
                self.detect_btn.setChecked(False)
                return

            target_indices, _char_index = self._resolve_detection_targets()
            if not target_indices:
                QMessageBox.warning(self, "오류", "탐지할 몬스터 클래스를 하나 이상 확보하세요.")
                self.detect_btn.setChecked(False)
                return

            maple_window = self._activate_maple_window()
            if not maple_window:
                QMessageBox.warning(self, '오류', '메이플스토리 창을 찾을 수 없습니다.')
                self.detect_btn.setChecked(False)
                return

            if not self.manual_capture_region:
                QMessageBox.warning(self, '오류', "'영역 지정'으로 탐지 영역을 설정해주세요.")
                self.detect_btn.setChecked(False)
                return
            capture_region = dict(self.manual_capture_region)

            if capture_region['width'] <= 0 or capture_region['height'] <= 0:
                QMessageBox.warning(self, '오류', '탐지 영역 크기가 유효하지 않습니다.')
                self.detect_btn.setChecked(False)
                return

            capture_subregions = None
            capture_subregions = self._resolve_manual_subregions(capture_region)

            self._load_nickname_configuration()
            nickname_detector_instance = self._build_thread_nickname_detector()
            if nickname_detector_instance is None:
                self.append_log("닉네임 템플릿을 찾을 수 없어 탐지를 시작할 수 없습니다.", "warn")
                QMessageBox.warning(self, "오류", "닉네임 템플릿을 찾을 수 없어 탐지를 시작할 수 없습니다.")
                self.detect_btn.setChecked(False)
                return

            self._load_direction_configuration()
            direction_detector_instance = self._build_thread_direction_detector()
            if direction_detector_instance is None:
                self.append_log("방향 템플릿이 없어 이미지 기반 방향 탐지를 비활성화합니다.", "info")

            self._load_nameplate_configuration()
            nameplate_config_payload: Optional[dict] = None
            nameplate_templates_payload: Optional[dict[int, list[dict]]] = None
            nameplate_thresholds_payload: Optional[dict[int, float]] = None
            if self._nameplate_enabled and self._nameplate_templates:
                try:
                    class_list = self.data_manager.get_class_list()
                except Exception:
                    class_list = []
                name_to_index = {name: idx for idx, name in enumerate(class_list)}
                relevant_templates: dict[int, list[dict]] = {}
                total_templates = 0
                for class_name, entries in self._nameplate_templates.items():
                    index = name_to_index.get(class_name)
                    if index is None or index not in target_indices:
                        continue
                    sanitized_entries: list[dict] = []
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        path = entry.get('path')
                        if not path or not os.path.exists(path):
                            continue
                        sanitized_entries.append({'id': entry.get('id'), 'path': path})
                    if sanitized_entries:
                        relevant_templates[index] = sanitized_entries
                        total_templates += len(sanitized_entries)
                if relevant_templates:
                    nameplate_config_payload = dict(self._nameplate_config)
                    nameplate_templates_payload = relevant_templates
                    thresholds: dict[int, float] = {}
                    per_class_cfg = self._nameplate_config.get('per_class', {}) if isinstance(self._nameplate_config.get('per_class'), dict) else {}
                    for class_name, entry in per_class_cfg.items():
                        index = name_to_index.get(class_name)
                        if index is None or index not in relevant_templates:
                            continue
                        threshold_value = entry.get('threshold') if isinstance(entry, dict) else None
                        if threshold_value is None:
                            continue
                        try:
                            thresholds[index] = float(threshold_value)
                        except (TypeError, ValueError):
                            continue
                    nameplate_thresholds_payload = thresholds if thresholds else None
                    if total_templates > 0:
                        self.append_log(f"이름표 템플릿 {total_templates}개 로드", "info")
                else:
                    self._nameplate_enabled = False

            self._reset_character_cache()
            self._direction_active = False
            self._direction_last_seen_ts = 0.0
            self._direction_last_side = None
            self._latest_direction_roi = None
            self._latest_direction_match = None
            self._direction_detector_available = direction_detector_instance is not None
            self.append_log("YOLO 캐릭터 탐지를 사용하지 않고 닉네임 기반 탐지에 의존합니다.", "info")

            runtime_settings = {}
            if self.data_manager and hasattr(self.data_manager, 'get_detection_runtime_settings'):
                try:
                    runtime_settings = self.data_manager.get_detection_runtime_settings() or {}
                except Exception as exc:
                    self.append_log(f"사냥 탐지 설정을 불러오지 못했습니다: {exc}", "warn")
                    runtime_settings = {}
            nms_iou = runtime_settings.get('yolo_nms_iou', self.yolo_nms_iou)
            max_det_value = runtime_settings.get('yolo_max_det', self.yolo_max_det)
            try:
                nms_iou = max(0.05, min(0.95, float(nms_iou)))
            except (TypeError, ValueError):
                nms_iou = self.yolo_nms_iou
            try:
                max_det_value = max(1, int(max_det_value))
            except (TypeError, ValueError):
                max_det_value = self.yolo_max_det
            self.yolo_nms_iou = nms_iou
            self.yolo_max_det = max_det_value
            self.append_log(
                f"YOLO NMS IoU={self.yolo_nms_iou:.2f}, 최대 박스={self.yolo_max_det}",
                "info",
            )

            monster_conf_overrides = self._resolve_monster_confidence_overrides(target_indices)
            if monster_conf_overrides:
                self._active_monster_confidence_overrides = monster_conf_overrides
                self._log_monster_confidence_overrides(monster_conf_overrides)
            else:
                self._active_monster_confidence_overrides = {}

            try:
                self.detection_thread = DetectionThread(
                    model_path=model_path,
                    capture_region=capture_region,
                    target_class_indices=target_indices,
                    conf_char=self.conf_char_spinbox.value(),
                    conf_monster=self.conf_monster_spinbox.value(),
                    char_class_index=-1,
                    is_debug_mode=False,
                    nickname_detector=nickname_detector_instance,
                    direction_detector=direction_detector_instance,
                    show_nickname_overlay=self._is_nickname_overlay_active(),
                    show_nickname_range_overlay=self._is_nickname_range_overlay_active(),
                    show_direction_overlay=self._is_direction_range_overlay_active(),
                    nameplate_config=nameplate_config_payload,
                    nameplate_templates=nameplate_templates_payload,
                    nameplate_thresholds=nameplate_thresholds_payload,
                    show_nameplate_overlay=self._is_nameplate_overlay_active(),
                    show_monster_confidence=self._is_monster_confidence_display_active(),
                    screen_output_enabled=self.screen_output_checkbox.isChecked(),
                    nms_iou=self.yolo_nms_iou,
                    max_det=self.yolo_max_det,
                    allowed_subregions=capture_subregions,
                    monster_confidence_overrides=monster_conf_overrides,
                    scale_factor=self.downscale_factor if self.downscale_enabled else 1.0,
                )
            except TypeError:
                # 구버전 런타임과의 호환성 확보
                self.append_log("방향 탐지 통합을 지원하지 않는 런타임 감지 → 기본 모드로 전환합니다.", "warn")
                self.detection_thread = DetectionThread(
                    model_path=model_path,
                    capture_region=capture_region,
                    target_class_indices=target_indices,
                    conf_char=self.conf_char_spinbox.value(),
                    conf_monster=self.conf_monster_spinbox.value(),
                    char_class_index=-1,
                    is_debug_mode=False,
                    nickname_detector=nickname_detector_instance,
                    show_nickname_overlay=self._is_nickname_overlay_active(),
                    show_nickname_range_overlay=self._is_nickname_range_overlay_active(),
                    nameplate_config=nameplate_config_payload,
                    nameplate_templates=nameplate_templates_payload,
                    nameplate_thresholds=nameplate_thresholds_payload,
                    show_nameplate_overlay=self._is_nameplate_overlay_active(),
                    show_monster_confidence=self._is_monster_confidence_display_active(),
                    screen_output_enabled=self.screen_output_checkbox.isChecked(),
                    nms_iou=self.yolo_nms_iou,
                    max_det=self.yolo_max_det,
                    allowed_subregions=capture_subregions,
                    monster_confidence_overrides=monster_conf_overrides,
                    scale_factor=self.downscale_factor if self.downscale_enabled else 1.0,
                )
                # 방향 감지를 비활성화하고 상태 초기화
                direction_detector_instance = None
                self._direction_active = False
                self._direction_last_seen_ts = 0.0
                self._direction_last_side = None
                self._latest_direction_roi = None
                self._latest_direction_match = None
                self._direction_detector_available = False

            self.detection_thread.frame_ready.connect(self._handle_detection_frame)

            self.detection_thread.detections_ready.connect(self.handle_detection_payload)
            self.detection_thread.detection_logged.connect(self._handle_detection_log)
            self.detection_thread.finished.connect(self._on_detection_thread_finished)

            self.detection_thread.start()
            self._set_detection_status(True)
            self._start_perf_logging()
            self._update_detection_thread_overlay_flags()
            self._sync_detection_thread_status()
            if self.detection_view:
                self.detection_view.setText("탐지 준비 중...")
                self.detection_view.setPixmap(QPixmap())
            self.detect_btn.setText("사냥중지")
            if self.status_monitor:
                self.status_monitor.set_tab_active(hunt=True)
            self._status_detection_start_ts = time.time()
            self._status_exp_records = []
            self._status_exp_start_snapshot = None
            self._status_ocr_warned = False
            self._hp_guard_active = False
            self._hp_guard_timer.stop()
            self._status_display_values = {'hp': None, 'mp': None}
            self._update_status_summary_cache()
            self._last_command_issued = None
            self._status_mp_saved_command = None

            self.last_used_model = selected_model
            self.append_log(f"탐지 시작: 모델={selected_model}, 범위={capture_region}")
            if self._active_target_names:
                target_list_text = ", ".join(self._active_target_names)
                self.append_log(f"탐지 대상: {target_list_text}", "info")
            self._set_current_facing(None, save=False)
            self._schedule_facing_reset()

            if self.screen_output_checkbox.isChecked() and not self.is_popup_active:
                self._toggle_detection_popup()

            if self.map_link_enabled and self.map_tab and not self._syncing_with_map:
                self._syncing_with_map = True
                try:
                    if hasattr(self.map_tab, 'detect_anchor_btn') and not self.map_tab.detect_anchor_btn.isChecked():
                        self.map_tab.detect_anchor_btn.setChecked(True)
                        self.map_tab.toggle_anchor_detection(True)
                finally:
                    self._syncing_with_map = False
        else:
            thread_active = self.detection_thread is not None and self.detection_thread.isRunning()
            self._release_pending = True
            self._stop_perf_logging()
            self._stop_detection_thread()
            self._set_detection_status(False)
            self.detect_btn.setText("사냥시작")
            if self.detection_view:
                self.detection_view.setText("탐지 중단됨")
                self.detection_view.setPixmap(QPixmap())
            self.clear_detection_snapshot()
            self._cancel_facing_reset_timer()
            if self._release_pending:
                self._issue_all_keys_release("사냥중지")

            if self.map_link_enabled and self.map_tab and not self._syncing_with_map:
                self._syncing_with_map = True
                try:
                    if hasattr(self.map_tab, 'detect_anchor_btn') and self.map_tab.detect_anchor_btn.isChecked():
                        self.map_tab.detect_anchor_btn.setChecked(False)
                        self.map_tab.toggle_anchor_detection(False)
                finally:
                    self._syncing_with_map = False

    def _on_conf_char_changed(self, value: float) -> None:
        self._sync_nickname_threshold_from_spinbox(float(value))
        self._handle_setting_changed()

    def _sync_nickname_threshold_from_spinbox(self, value: float) -> None:
        spinbox = getattr(self, 'conf_char_spinbox', None)
        if spinbox is not None:
            value = max(spinbox.minimum(), min(spinbox.maximum(), float(value)))
        try:
            clamped_value = float(value)
        except (TypeError, ValueError):
            return

        if self._nickname_config is None:
            self._nickname_config = {}
        self._nickname_config['match_threshold'] = clamped_value

        if not self.data_manager or not hasattr(self.data_manager, 'update_nickname_config'):
            return

        try:
            updated_config = self.data_manager.update_nickname_config({'match_threshold': clamped_value})
        except Exception as exc:
            self.append_log(f"닉네임 임계값을 업데이트하지 못했습니다: {exc}", "warn")
            return

        if isinstance(updated_config, dict):
            self._nickname_config = updated_config

    def _apply_nickname_threshold_to_char_conf(self) -> None:
        spinbox = getattr(self, 'conf_char_spinbox', None)
        if spinbox is None:
            return
        config = getattr(self, '_nickname_config', {}) or {}
        threshold = config.get('match_threshold')
        try:
            threshold_value = float(threshold)
        except (TypeError, ValueError):
            return

        clamped = max(spinbox.minimum(), min(spinbox.maximum(), threshold_value))
        if abs(spinbox.value() - clamped) <= 1e-6:
            return

        previous_state = spinbox.blockSignals(True)
        spinbox.setValue(clamped)
        spinbox.blockSignals(previous_state)
        self._save_settings()

    def _stop_detection_thread(self) -> None:
        if self.status_monitor:
            self.status_monitor.set_tab_active(hunt=False)
        self._finalize_exp_tracking()
        self._status_exp_records = []
        self._status_exp_start_snapshot = None
        self._status_detection_start_ts = None
        self._update_status_summary_cache()
        self._status_mp_saved_command = None
        self._set_detection_status(False)
        if self.detection_thread:
            try:
                self.detection_thread.frame_ready.disconnect(self._handle_detection_frame)
            except TypeError:
                pass
            try:
                self.detection_thread.detections_ready.disconnect(self.handle_detection_payload)
            except TypeError:
                pass
            try:
                self.detection_thread.detection_logged.disconnect(self._handle_detection_log)
            except TypeError:
                pass
            try:
                self.detection_thread.finished.disconnect(self._on_detection_thread_finished)
            except TypeError:
                pass
            self.detection_thread.stop()
            self.detection_thread.wait()
            self.detection_thread = None

        if self.detection_popup:
            self.detection_popup.close()
        self._clear_pending_skill()
        self._clear_pending_direction()
        self._clear_direction_confirmation()
        self._cancel_facing_reset_timer()
        self._last_target_side = None
        self._last_target_distance = None
        self._last_target_update_ts = 0.0
        self._last_direction_change_ts = 0.0

    def _on_detection_thread_finished(self) -> None:
        self.detect_btn.setChecked(False)
        self.detect_btn.setText("사냥시작")
        if not self.is_popup_active and self.detection_view:
            self.detection_view.setText("탐지 중단됨")
            self.detection_view.setPixmap(QPixmap())
        self.detection_thread = None
        self._stop_perf_logging()
        self._cancel_facing_reset_timer()
        self._issue_all_keys_release("탐지 스레드 종료")
        self.clear_detection_snapshot()
        self._active_monster_confidence_overrides = {}
        self._set_detection_status(False)

    def _handle_detection_log(self, messages: List[str]) -> None:
        for msg in messages:
            self.append_log(msg, "debug")

    def _handle_detection_frame(self, q_image) -> None:
        if not self._is_screen_output_enabled():
            return
        image = q_image.copy()
        self._paint_overlays(image)
        if self.is_popup_active and self.detection_popup:
            self.detection_popup.update_frame(image)
        elif self.detection_view:
            self._update_detection_frame(image)

    def _paint_overlays(self, image) -> None:
        if image is None or image.isNull():
            return
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            painter.setCompositionMode(COMPOSITION_MODE_SOURCE_OVER)
            if (
                self.current_hunt_area
                and self.overlay_preferences.get('hunt_area', True)
                and self.show_hunt_area_checkbox.isChecked()
            ):
                rect = self._area_to_rect(self.current_hunt_area, image.width(), image.height())
                if not rect.isNull():
                    painter.setPen(HUNT_AREA_EDGE)
                    painter.setBrush(HUNT_AREA_BRUSH)
                    painter.drawRect(rect)
            if (
                self.current_primary_area
                and self.overlay_preferences.get('primary_area', True)
                and self.show_primary_skill_checkbox.isChecked()
            ):
                rect = self._area_to_rect(self.current_primary_area, image.width(), image.height())
                if not rect.isNull():
                    painter.setPen(PRIMARY_AREA_EDGE)
                    painter.setBrush(PRIMARY_AREA_BRUSH)
                    painter.drawRect(rect)
            painter.setCompositionMode(COMPOSITION_MODE_SOURCE_OVER)
            if self._is_nickname_overlay_active() and self._latest_nickname_box:
                nick_rect = self._dict_to_rect(self._latest_nickname_box, image.width(), image.height())
                if not nick_rect.isNull():
                    painter.setPen(NICKNAME_EDGE)
                    painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    painter.drawRect(nick_rect)
            if (
                self._is_nickname_range_overlay_active()
                and self._latest_nickname_search_region
            ):
                range_rect = self._dict_to_rect(
                    self._latest_nickname_search_region,
                    image.width(),
                    image.height(),
                )
                if not range_rect.isNull():
                    painter.setPen(NICKNAME_RANGE_EDGE)
                    painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    painter.drawRect(range_rect)
            if self._using_character_fallback and self._last_character_boxes:
                painter.setPen(FALLBACK_CHARACTER_EDGE)
                painter.setBrush(FALLBACK_CHARACTER_BRUSH)
                for box in self._last_character_boxes:
                    rect = self._box_to_rect(box, image.width(), image.height())
                    if not rect.isNull():
                        painter.drawRect(rect)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self._is_direction_range_overlay_active() and self._latest_direction_roi:
                rect = self._dict_to_rect(self._latest_direction_roi, image.width(), image.height())
                if not rect.isNull():
                    painter.setPen(DIRECTION_ROI_EDGE)
                    painter.drawRect(rect)
            if self._is_direction_match_overlay_active() and self._latest_direction_match:
                rect = self._dict_to_rect(self._latest_direction_match, image.width(), image.height())
                if not rect.isNull():
                    pen = DIRECTION_MATCH_EDGE_LEFT if self._direction_last_side == 'left' else DIRECTION_MATCH_EDGE_RIGHT
                    painter.setPen(pen)
                    painter.drawRect(rect)
            if self._is_nameplate_overlay_active() and self._latest_nameplate_rois:
                for entry in self._latest_nameplate_rois:
                    roi_info = entry.get('roi') if isinstance(entry, dict) else entry
                    rect = self._dict_to_rect(roi_info, image.width(), image.height())
                    if rect.isNull():
                        continue
                    painter.setPen(NAMEPLATE_ROI_EDGE)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(rect)
                    match_rect_info = entry.get('match_rect') if isinstance(entry, dict) else None
                    if isinstance(match_rect_info, dict):
                        match_rect = self._dict_to_rect(match_rect_info, image.width(), image.height())
                        if not match_rect.isNull():
                            painter.setPen(NAMEPLATE_MATCH_EDGE)
                            painter.drawRect(match_rect)
            if self._nameplate_visual_debug_enabled and self._visual_tracked_monsters:
                for entry in self._visual_tracked_monsters:
                    rect = self._dict_to_rect(entry, image.width(), image.height())
                    if rect.isNull():
                        continue
                    grace_only = bool(entry.get('grace_active')) and not bool(entry.get('nameplate_detected'))
                    if grace_only:
                        painter.setPen(NAMEPLATE_TRACK_EDGE)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                    else:
                        painter.setPen(NAMEPLATE_TRACK_EDGE)
                        painter.setBrush(NAMEPLATE_TRACK_BRUSH)
                    painter.drawRect(rect)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            if self._nameplate_visual_debug_enabled and self._visual_dead_zones:
                painter.setPen(NAMEPLATE_DEADZONE_EDGE)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for entry in self._visual_dead_zones:
                    rect = self._dict_to_rect(entry, image.width(), image.height())
                    if rect.isNull():
                        continue
                    painter.drawRect(rect)
        finally:
            painter.end()

    @staticmethod
    def _area_to_rect(area: AreaRect, max_width: int, max_height: int) -> QRect:
        width = max(0.0, area.width)
        height = max(0.0, area.height)
        x1 = max(0.0, area.x)
        y1 = max(0.0, area.y)
        x2 = min(float(max_width), area.x + width)
        y2 = min(float(max_height), area.y + height)
        if x2 <= x1 or y2 <= y1:
            return QRect()
        return QRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))

    @staticmethod
    def _box_to_rect(box: DetectionBox, max_width: int, max_height: int) -> QRect:
        width = max(0.0, box.width)
        height = max(0.0, box.height)
        x1 = max(0.0, box.x)
        y1 = max(0.0, box.y)
        x2 = min(float(max_width), box.x + width)
        y2 = min(float(max_height), box.y + height)
        if x2 <= x1 or y2 <= y1:
            return QRect()
        return QRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))

    @staticmethod
    def _dict_to_rect(box_data: dict, max_width: int, max_height: int) -> QRect:
        try:
            x = float(box_data.get('x', 0.0))
            y = float(box_data.get('y', 0.0))
            width = float(box_data.get('width', 0.0))
            height = float(box_data.get('height', 0.0))
        except (TypeError, ValueError):
            return QRect()
        x1 = max(0.0, x)
        y1 = max(0.0, y)
        x2 = min(float(max_width), x + max(0.0, width))
        y2 = min(float(max_height), y + max(0.0, height))
        if x2 <= x1 or y2 <= y1:
            return QRect()
        return QRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))

    def _update_detection_summary(self) -> None:
        if not hasattr(self, 'confidence_summary_view'):
            return

        show_confidence = self.show_confidence_summary_checkbox.isChecked()
        show_frame = self._is_frame_summary_enabled()
        show_frame_detail = self._is_frame_detail_enabled()
        show_info = self.show_info_summary_checkbox.isChecked()

        if show_confidence:
            characters = self.latest_detection_details.get('characters', [])
            monsters = self.latest_detection_details.get('monsters', [])
            nameplates = self.latest_detection_details.get('nameplates', [])

            lines: List[str] = []

            if characters:
                best_char = max(characters, key=lambda item: float(item.get('score', 0.0)))
                lines.append(
                    f"캐릭터: 신뢰도 {float(best_char.get('score', 0.0)):.2f}"
                )
                if self._last_direction_score is not None:
                    lines.append(
                        f"캐릭터 방향: 신뢰도 {self._last_direction_score:.2f}"
                    )
            else:
                lines.append("캐릭터 없음")

            if monsters:
                grouped: dict[str, List[float]] = {}
                for item in monsters:
                    name = str(item.get('class_name', '???'))
                    grouped.setdefault(name, []).append(float(item.get('score', 0.0)))
                for name in sorted(grouped.keys()):
                    scores = grouped[name]
                    score_text = ', '.join(f"{score:.2f}" for score in scores)
                    lines.append(
                        f"{name}: {len(scores)}마리 (신뢰도: {score_text})"
                    )
            else:
                lines.append("몬스터 없음")

            if nameplates:
                nameplate_summaries = []
                for entry in nameplates:
                    monster_name = str(entry.get('class_name') or '이름표')
                    score = float(entry.get('score', 0.0))
                    nameplate_summaries.append(f"{monster_name}({score:.2f})")
                lines.append("이름표: " + ", ".join(nameplate_summaries))
            else:
                lines.append("이름표 없음")

            self.confidence_summary_view.setPlainText('\n'.join(lines))
        elif self.confidence_summary_view.toPlainText():
            self.confidence_summary_view.clear()

        if show_frame:
            perf = getattr(self, 'latest_perf_stats', {}) or {}
            fps = float(perf.get('fps', 0.0))
            total_ms = float(perf.get('total_ms', 0.0))
            capture_ms = float(perf.get('capture_ms', 0.0))
            yolo_ms = float(perf.get('yolo_ms', 0.0))
            nickname_ms = float(perf.get('nickname_ms', 0.0))
            nameplate_ms = float(perf.get('nameplate_ms', 0.0))

            frame_lines = [
                f"FPS: {fps:.0f}",
                f"Total: {total_ms:.1f} ms",
                f"Capture {capture_ms:.1f} ms / YOLO {yolo_ms:.1f} ms",
                f"Nickname {nickname_ms:.1f} ms / Nameplate {nameplate_ms:.1f} ms",
            ]

            if show_frame_detail:
                preprocess_ms = float(perf.get('preprocess_ms', 0.0))
                direction_ms = float(perf.get('direction_ms', 0.0))
                post_ms = float(perf.get('post_ms', 0.0))
                render_ms = float(perf.get('render_ms', 0.0))
                emit_ms = float(perf.get('emit_ms', 0.0))
                latency_ms = float(perf.get('payload_latency_ms', 0.0))
                handler_ms = float(perf.get('handler_ms', 0.0))

                frame_lines.append(
                    f"Latency {latency_ms:.1f} ms / Handler {handler_ms:.1f} ms"
                )
                frame_lines.append(
                    f"Pre {preprocess_ms:.1f} ms / Direction {direction_ms:.1f} ms / Post {post_ms:.1f} ms"
                )
                frame_lines.append(
                    f"Render {render_ms:.1f} ms / Emit {emit_ms:.1f} ms"
                )

            self.frame_summary_view.setPlainText('\n'.join(frame_lines))
        elif self.frame_summary_view.toPlainText():
            self.frame_summary_view.clear()

        if show_info:
            if self.current_authority == "hunt":
                authority_text = "사냥 탭"
            elif self.current_authority == "map":
                authority_text = "Map 탭"
            else:
                authority_text = str(self.current_authority)

            direction_detail = self.latest_detection_details.get('direction') or {}
            direction_mode = "이미지 기반" if self._direction_detector_available else "랜덤 시간"
            if direction_detail.get('matched') and direction_detail.get('side') in ('left', 'right'):
                side_text = '왼쪽' if direction_detail.get('side') == 'left' else '오른쪽'
                score_val = float(direction_detail.get('score', 0.0))
                direction_line = f"방향 탐지: {side_text} ({score_val:.2f}) - {direction_mode}"
            elif self._direction_active and self._direction_last_side in ('left', 'right'):
                side_text = '왼쪽' if self._direction_last_side == 'left' else '오른쪽'
                direction_line = f"방향 탐지: 유지 ({side_text}) - {direction_mode}"
            else:
                direction_line = f"방향 탐지: 비활성 - {direction_mode}"

            teleport_percent = self._get_walk_teleport_display_percent()
            teleport_line = f"텔레포트 확률: {teleport_percent:.1f}%"
            matched_nameplates = [
                entry
                for entry in (self.latest_detection_details.get('nameplates') or [])
                if entry.get('matched')
            ]
            if matched_nameplates:
                nameplate_line = f"이름표 탐지: {len(matched_nameplates)}건"
            else:
                nameplate_line = "이름표 탐지: 없음"

            info_lines = [
                f"이동권한: {authority_text}",
                f"X축 범위 내 몬스터: {self.latest_monster_count}",
                f"스킬 범위 몬스터: {self.latest_primary_monster_count}",
                direction_line,
                teleport_line,
                nameplate_line,
                self._status_summary_cache.get('hp', 'HP: --'),
                self._status_summary_cache.get('mp', 'MP: --'),
                self._status_summary_cache.get('exp', 'EXP: -- / --'),
            ]

            self.info_summary_view.setPlainText('\n'.join(info_lines))
        elif self.info_summary_view.toPlainText():
            self.info_summary_view.clear()

    def _on_summary_checkbox_changed(self, _checked: bool) -> None:
        self._sync_frame_detail_checkbox_state()
        self._update_detection_summary()
        self._save_settings()

    def _update_log_visibility_state(self) -> None:
        base_heights = getattr(self, '_log_base_heights', None)
        if not base_heights:
            return

        control_enabled = self._is_log_enabled('control_log_checkbox')
        if hasattr(self, 'control_log_section') and self.control_log_section:
            self.control_log_section.setVisible(control_enabled)
        if hasattr(self, 'control_log_view') and self.control_log_view:
            self.control_log_view.setVisible(control_enabled)

        keyboard_view = getattr(self, 'keyboard_log_view', None)
        main_view = getattr(self, 'log_view', None)
        if not keyboard_view or not main_view:
            return

        extra_height = int(base_heights.get('control', 0))
        keyboard_base = int(base_heights.get('keyboard', keyboard_view.minimumHeight()))
        main_base = int(base_heights.get('main', main_view.minimumHeight()))

        if control_enabled:
            keyboard_height = keyboard_base
            main_height = main_base
        else:
            keyboard_bonus = extra_height // 2
            keyboard_height = keyboard_base + keyboard_bonus
            main_height = main_base + (extra_height - keyboard_bonus)

        keyboard_view.setMinimumHeight(keyboard_height)
        main_view.setMinimumHeight(main_height)
        keyboard_view.updateGeometry()
        main_view.updateGeometry()

    def _on_log_checkbox_toggled(self, _checked: bool) -> None:
        self._update_log_visibility_state()
        self._save_settings()

    def _on_frame_detail_toggled(self, _checked: bool) -> None:
        self._update_detection_summary()
        self._save_settings()

    def _on_perf_logging_toggled(self, checked: bool) -> None:
        self._perf_logging_enabled = bool(checked)
        if not self._perf_logging_enabled:
            self._stop_perf_logging()
        else:
            if self._is_detection_active():
                self._start_perf_logging()
        self._save_settings()

    def _sync_frame_detail_checkbox_state(self) -> None:
        if not hasattr(self, 'show_frame_detail_checkbox'):
            return
        show_frame = bool(self.show_frame_summary_checkbox.isChecked()) if hasattr(self, 'show_frame_summary_checkbox') else True
        self.show_frame_detail_checkbox.setEnabled(show_frame)

    def _on_screen_output_toggled(self, checked: bool) -> None:
        if self.detection_thread and hasattr(self.detection_thread, 'set_screen_output_enabled'):
            try:
                self.detection_thread.set_screen_output_enabled(bool(checked))
            except Exception:
                pass
        if not checked and self.is_popup_active:
            self._toggle_detection_popup()
        if not checked and self.detection_view:
            self.detection_view.setText("화면출력이 비활성화되었습니다.")
            self.detection_view.setPixmap(QPixmap())
        if checked and self.detect_btn.isChecked() and not self.is_popup_active:
            self._toggle_detection_popup()
        self._handle_setting_changed()

    def _update_detection_frame(self, q_image) -> None:
        if not self.detection_view:
            return

        self.detection_view.setPixmap(
            QPixmap.fromImage(q_image).scaled(
                self.detection_view.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _is_screen_output_enabled(self) -> bool:
        checkbox = getattr(self, 'screen_output_checkbox', None)
        if checkbox is None:
            return True
        return bool(checkbox.isChecked())

    def _is_nickname_overlay_active(self) -> bool:
        return bool(self._show_nickname_overlay_config)

    def _is_nickname_range_overlay_active(self) -> bool:
        if not self._show_nickname_overlay_config:
            return False
        if not self.overlay_preferences.get('nickname_range', True):
            return False
        checkbox = getattr(self, 'show_nickname_range_checkbox', None)
        if checkbox is not None:
            if not checkbox.isEnabled() or not checkbox.isChecked():
                return False
        return True

    def _is_direction_range_overlay_active(self) -> bool:
        if not self._show_direction_overlay_config:
            return False
        if not self.overlay_preferences.get('direction_area', True):
            return False
        checkbox = getattr(self, 'show_direction_checkbox', None)
        if checkbox is None:
            return True
        if not checkbox.isEnabled():
            return False
        return checkbox.isChecked()

    def _is_direction_match_overlay_active(self) -> bool:
        return bool(self._show_direction_overlay_config)

    def _is_nameplate_overlay_active(self) -> bool:
        if not self._show_nameplate_overlay_config:
            return False
        if not self.overlay_preferences.get('nameplate_area', True):
            return False
        checkbox = getattr(self, 'show_nameplate_checkbox', None)
        if checkbox is not None:
            if not checkbox.isEnabled() or not checkbox.isChecked():
                return False
        return bool(self._nameplate_config.get('show_overlay', True))

    def _is_monster_confidence_display_active(self) -> bool:
        if not self.overlay_preferences.get('monster_confidence', True):
            return False
        checkbox = getattr(self, 'show_monster_confidence_checkbox', None)
        if checkbox is not None:
            if not checkbox.isEnabled():
                return False
            return bool(checkbox.isChecked())
        return True

    def _toggle_detection_popup(self) -> None:
        if self.is_popup_active:
            if self.detection_popup:
                self.detection_popup.close()
            return

        self.is_popup_active = True
        popup_button = getattr(self, 'popup_btn', None)
        if popup_button is not None:
            popup_button.setText("↙")
            popup_button.setToolTip("탐지 화면을 메인 창으로 복귀")

        if not self.detection_popup:
            popup_size = self.last_popup_size if self.last_popup_size else None
            self.detection_popup = DetectionPopup(
                self.last_popup_scale,
                self,
                initial_size=popup_size,
            )
            self.detection_popup.closed.connect(self._handle_popup_closed)
            self.detection_popup.scale_changed.connect(self._on_popup_scale_changed)
            self.detection_popup.size_changed.connect(self._on_popup_size_changed)

        self._restore_popup_position()
        self.detection_popup.set_waiting_message()
        if self.detection_view:
            self.detection_view.setText("탐지 화면이 팝업으로 표시 중입니다.")
            self.detection_view.setPixmap(QPixmap())
        self.detection_popup.show()

    def _on_popup_scale_changed(self, value: int) -> None:
        self.last_popup_scale = value
        self._save_settings()

    def _on_popup_size_changed(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        self.last_popup_size = (int(width), int(height))
        self._save_settings()

    def _handle_popup_closed(self) -> None:
        if self.detection_popup:
            self.last_popup_position = (self.detection_popup.x(), self.detection_popup.y())
            self.last_popup_size = (self.detection_popup.width(), self.detection_popup.height())
            self._save_settings()
        self.is_popup_active = False
        popup_button = getattr(self, 'popup_btn', None)
        if popup_button is not None:
            popup_button.setText("↗")
            popup_button.setToolTip("탐지 화면을 팝업으로 열기")
        if self.detection_view:
            if self.detect_btn.isChecked():
                self.detection_view.setText("탐지 준비 중...")
                self.detection_view.setPixmap(QPixmap())
            else:
                self.detection_view.setText("탐지 중단됨")
                self.detection_view.setPixmap(QPixmap())

        self.detection_popup = None

    def _restore_popup_position(self) -> None:
        if not self.detection_popup or not self.last_popup_position:
            return
        x, y = self.last_popup_position
        target_rect = QRect(
            x,
            y,
            max(self.detection_popup.width(), 1),
            max(self.detection_popup.height(), 1),
        )
        app = QGuiApplication.instance()
        if app is not None:
            screens = QGuiApplication.screens()
            if screens:
                # 화면 안에 일부라도 들어오는지 확인
                if not any(screen.geometry().intersects(target_rect) for screen in screens):
                    return
        self.detection_popup.move(x, y)

    def _create_skill_group(self) -> QGroupBox:
        group = QGroupBox("스킬 관리")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        attack_section = self._create_attack_section()
        buff_section = self._create_buff_section()
        teleport_section = self._create_teleport_section()
        attack_section.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred))
        buff_section.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred))
        teleport_section.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        layout.addWidget(attack_section)
        layout.addWidget(buff_section)
        layout.addWidget(teleport_section)

        group.setLayout(layout)
        return group

    def _create_detection_summary_group(self) -> QGroupBox:
        group = QGroupBox()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_label = QLabel("탐지 요약")
        header_label.setStyleSheet("font-weight: bold;")
        self.perf_logging_checkbox = QCheckBox("CSV 기록")
        self.perf_logging_checkbox.setChecked(self._perf_logging_enabled)
        self.perf_logging_checkbox.toggled.connect(self._on_perf_logging_toggled)
        header_layout.addWidget(header_label)
        header_layout.addSpacing(6)
        header_layout.addWidget(self.perf_logging_checkbox)
        header_layout.addStretch(1)
        layout.addLayout(header_layout)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)

        self.summary_left_container = QWidget()
        left_layout = QVBoxLayout(self.summary_left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.summary_confidence_container = QWidget()
        confidence_layout = QVBoxLayout(self.summary_confidence_container)
        confidence_layout.setContentsMargins(0, 0, 0, 0)
        confidence_layout.setSpacing(4)
        confidence_header = QHBoxLayout()
        confidence_label = QLabel("탐지 신뢰도")
        self.show_confidence_summary_checkbox = QCheckBox()
        self.show_confidence_summary_checkbox.setChecked(True)
        self.show_confidence_summary_checkbox.toggled.connect(self._on_summary_checkbox_changed)
        confidence_header.addWidget(confidence_label)
        confidence_header.addWidget(self.show_confidence_summary_checkbox)
        confidence_header.addStretch(1)
        self.confidence_summary_view = QTextEdit()
        self.confidence_summary_view.setReadOnly(True)
        self.confidence_summary_view.setMinimumHeight(90)
        self.confidence_summary_view.setStyleSheet("font-family: Consolas, monospace;")
        confidence_layout.addLayout(confidence_header)
        confidence_layout.addWidget(self.confidence_summary_view)

        self.summary_frame_container = QWidget()
        frame_layout = QVBoxLayout(self.summary_frame_container)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(4)
        frame_header = QHBoxLayout()
        frame_label = QLabel("프레임 정보")
        self.show_frame_summary_checkbox = QCheckBox()
        self.show_frame_summary_checkbox.setChecked(True)
        self.show_frame_summary_checkbox.toggled.connect(self._on_summary_checkbox_changed)
        self.show_frame_detail_checkbox = QCheckBox("상세")
        self.show_frame_detail_checkbox.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.show_frame_detail_checkbox.setChecked(False)
        self.show_frame_detail_checkbox.toggled.connect(self._on_frame_detail_toggled)
        frame_header.addWidget(frame_label)
        frame_header.addWidget(self.show_frame_summary_checkbox)
        frame_header.addWidget(self.show_frame_detail_checkbox)
        frame_header.addStretch(1)
        self.frame_summary_view = QTextEdit()
        self.frame_summary_view.setReadOnly(True)
        self.frame_summary_view.setMinimumHeight(140)
        self.frame_summary_view.setStyleSheet("font-family: Consolas, monospace;")
        frame_layout.addLayout(frame_header)
        frame_layout.addWidget(self.frame_summary_view)

        left_layout.addWidget(self.summary_confidence_container)
        left_layout.addWidget(self.summary_frame_container)
        left_layout.addStretch(1)

        content_layout.addWidget(self.summary_left_container, 1)

        self.summary_info_container = QWidget()
        info_layout = QVBoxLayout(self.summary_info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        info_header = QHBoxLayout()
        info_label = QLabel("탐지 정보")
        self.show_info_summary_checkbox = QCheckBox()
        self.show_info_summary_checkbox.setChecked(True)
        self.show_info_summary_checkbox.toggled.connect(self._on_summary_checkbox_changed)
        info_header.addWidget(info_label)
        info_header.addWidget(self.show_info_summary_checkbox)
        info_header.addStretch(1)
        self.info_summary_view = QTextEdit()
        self.info_summary_view.setReadOnly(True)
        self.info_summary_view.setMinimumHeight(140)
        self.info_summary_view.setStyleSheet("font-family: Consolas, monospace;")
        info_layout.addLayout(info_header)
        info_layout.addWidget(self.info_summary_view)
        content_layout.addWidget(self.summary_info_container, 1)

        layout.addLayout(content_layout)
        self._sync_frame_detail_checkbox_state()
        return group

    def _create_attack_section(self) -> QGroupBox:
        box = QGroupBox("공격 스킬")
        layout = QVBoxLayout()

        self.attack_tree = QTreeWidget()
        self.attack_tree.setColumnCount(5)
        self.attack_tree.setHeaderLabels(["사용", "이름", "명령", "주 공격", "조건"])
        self.attack_tree.setRootIsDecorated(False)
        self.attack_tree.setAlternatingRowColors(True)
        self.attack_tree.itemChanged.connect(self._handle_attack_item_changed)
        self.attack_tree.itemSelectionChanged.connect(self._update_attack_buttons)
        layout.addWidget(self.attack_tree)

        button_layout = QHBoxLayout()
        self.add_attack_btn = QPushButton("추가")
        self.add_attack_btn.clicked.connect(self.add_attack_skill)
        self.edit_attack_btn = QPushButton("편집")
        self.edit_attack_btn.clicked.connect(self.edit_attack_skill)
        self.remove_attack_btn = QPushButton("삭제")
        self.remove_attack_btn.clicked.connect(self.remove_attack_skill)
        self.set_primary_attack_btn = QPushButton("주 스킬 지정")
        self.set_primary_attack_btn.clicked.connect(self.set_primary_attack_skill)
        self.test_attack_btn = QPushButton("테스트 실행")
        self.test_attack_btn.clicked.connect(self.run_attack_skill)
        button_layout.addWidget(self.add_attack_btn)
        button_layout.addWidget(self.edit_attack_btn)
        button_layout.addWidget(self.remove_attack_btn)
        button_layout.addWidget(self.set_primary_attack_btn)
        button_layout.addWidget(self.test_attack_btn)
        button_layout.addStretch(1)
        layout.addLayout(button_layout)

        box.setLayout(layout)
        return box

    def _create_buff_section(self) -> QGroupBox:
        box = QGroupBox("버프 스킬")
        layout = QVBoxLayout()

        self.buff_tree = QTreeWidget()
        self.buff_tree.setColumnCount(5)
        self.buff_tree.setHeaderLabels(["사용", "이름", "명령", "쿨타임(s)", "오차(%)"])
        self.buff_tree.setRootIsDecorated(False)
        self.buff_tree.setAlternatingRowColors(True)
        self.buff_tree.itemChanged.connect(self._handle_buff_item_changed)
        self.buff_tree.itemSelectionChanged.connect(self._update_buff_buttons)
        layout.addWidget(self.buff_tree)

        button_layout = QHBoxLayout()
        self.add_buff_btn = QPushButton("추가")
        self.add_buff_btn.clicked.connect(self.add_buff_skill)
        self.edit_buff_btn = QPushButton("편집")
        self.edit_buff_btn.clicked.connect(self.edit_buff_skill)
        self.remove_buff_btn = QPushButton("삭제")
        self.remove_buff_btn.clicked.connect(self.remove_buff_skill)
        self.test_buff_btn = QPushButton("테스트 실행")
        self.test_buff_btn.clicked.connect(self.run_buff_skill)
        button_layout.addWidget(self.add_buff_btn)
        button_layout.addWidget(self.edit_buff_btn)
        button_layout.addWidget(self.remove_buff_btn)
        button_layout.addWidget(self.test_buff_btn)
        button_layout.addStretch(1)
        layout.addLayout(button_layout)

        box.setLayout(layout)
        return box

    def _create_teleport_section(self) -> QGroupBox:
        box = QGroupBox("텔레포트 설정")

        self.teleport_enabled_checkbox = QCheckBox()
        self.teleport_enabled_checkbox.setChecked(self.teleport_settings.enabled)
        self.teleport_enabled_checkbox.setToolTip("텔레포트 기본 동작 사용 여부")
        self.teleport_enabled_checkbox.toggled.connect(self._on_base_teleport_toggled)

        self.teleport_distance_spinbox = QSpinBox()
        self.teleport_distance_spinbox.setRange(50, 600)
        self.teleport_distance_spinbox.setSingleStep(10)
        self.teleport_distance_spinbox.setValue(int(self.teleport_settings.distance_px))
        self.teleport_distance_spinbox.setSuffix(" px")
        self.teleport_distance_spinbox.setMaximumWidth(90)
        self.teleport_distance_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.teleport_probability_spinbox = QSpinBox()
        self.teleport_probability_spinbox.setRange(0, 100)
        self.teleport_probability_spinbox.setValue(int(self.teleport_settings.probability))
        self.teleport_probability_spinbox.setSuffix(" %")
        self.teleport_probability_spinbox.setMaximumWidth(90)
        self.teleport_probability_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.walk_teleport_checkbox = QCheckBox()
        self.walk_teleport_checkbox.setChecked(self.teleport_settings.walk_enabled)
        self.walk_teleport_checkbox.setToolTip("걷기 중 텔레포트 사용 여부")
        self.walk_teleport_checkbox.toggled.connect(self._on_walk_teleport_toggled)

        self.walk_teleport_probability_spinbox = QDoubleSpinBox()
        self.walk_teleport_probability_spinbox.setRange(0.0, 100.0)
        self.walk_teleport_probability_spinbox.setDecimals(1)
        self.walk_teleport_probability_spinbox.setSingleStep(0.5)
        self.walk_teleport_probability_spinbox.setValue(float(self.teleport_settings.walk_probability))
        self.walk_teleport_probability_spinbox.setSuffix(" %")
        self.walk_teleport_probability_spinbox.setMaximumWidth(90)
        self.walk_teleport_probability_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.walk_teleport_interval_spinbox = QDoubleSpinBox()
        self.walk_teleport_interval_spinbox.setRange(0.1, 10.0)
        self.walk_teleport_interval_spinbox.setDecimals(2)
        self.walk_teleport_interval_spinbox.setSingleStep(0.1)
        self.walk_teleport_interval_spinbox.setValue(float(self.teleport_settings.walk_interval))
        self.walk_teleport_interval_spinbox.setSuffix(" s")
        self.walk_teleport_interval_spinbox.setMaximumWidth(90)
        self.walk_teleport_interval_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.walk_teleport_bonus_interval_spinbox = QDoubleSpinBox()
        self.walk_teleport_bonus_interval_spinbox.setRange(0.1, 10.0)
        self.walk_teleport_bonus_interval_spinbox.setDecimals(2)
        self.walk_teleport_bonus_interval_spinbox.setSingleStep(0.1)
        self.walk_teleport_bonus_interval_spinbox.setValue(float(self.teleport_settings.walk_bonus_interval))
        self.walk_teleport_bonus_interval_spinbox.setSuffix(" s")
        self.walk_teleport_bonus_interval_spinbox.setMaximumWidth(90)
        self.walk_teleport_bonus_interval_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.walk_teleport_bonus_step_spinbox = QDoubleSpinBox()
        self.walk_teleport_bonus_step_spinbox.setRange(0.0, 100.0)
        self.walk_teleport_bonus_step_spinbox.setDecimals(1)
        self.walk_teleport_bonus_step_spinbox.setSingleStep(1.0)
        self.walk_teleport_bonus_step_spinbox.setValue(float(self.teleport_settings.walk_bonus_step))
        self.walk_teleport_bonus_step_spinbox.setSuffix(" %")
        self.walk_teleport_bonus_step_spinbox.setMaximumWidth(90)
        self.walk_teleport_bonus_step_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.walk_teleport_bonus_max_spinbox = QDoubleSpinBox()
        self.walk_teleport_bonus_max_spinbox.setRange(0.0, 100.0)
        self.walk_teleport_bonus_max_spinbox.setDecimals(1)
        self.walk_teleport_bonus_max_spinbox.setSingleStep(1.0)
        self.walk_teleport_bonus_max_spinbox.setValue(float(self.teleport_settings.walk_bonus_max))
        self.walk_teleport_bonus_max_spinbox.setSuffix(" %")
        self.walk_teleport_bonus_max_spinbox.setMaximumWidth(90)
        self.walk_teleport_bonus_max_spinbox.valueChanged.connect(self._handle_setting_changed)

        # 좌측: 기본 텔레포트 설정
        left_column = QVBoxLayout()
        left_column.setSpacing(6)
        base_header = QHBoxLayout()
        base_header.setSpacing(6)
        base_label = QLabel("텔레포트 기본설정")
        base_header.addWidget(base_label)
        base_header.addStretch(1)
        base_header.addWidget(self.teleport_enabled_checkbox)
        left_column.addLayout(base_header)

        base_row = QHBoxLayout()
        base_row.setSpacing(6)
        base_row.addWidget(QLabel("이동(px)"))
        base_row.addWidget(self.teleport_distance_spinbox)
        base_row.addSpacing(8)
        base_row.addWidget(QLabel("확률(%)"))
        base_row.addWidget(self.teleport_probability_spinbox)
        base_row.addStretch(1)
        left_column.addLayout(base_row)
        left_column.addStretch(1)

        # 우측: 걷기 중 텔레포트 설정
        right_column = QVBoxLayout()
        right_column.setSpacing(6)
        walk_header = QHBoxLayout()
        walk_header.setSpacing(6)
        walk_header.addWidget(QLabel("텔레포트(걷기 중)"))
        walk_header.addStretch(1)
        walk_header.addWidget(self.walk_teleport_checkbox)
        right_column.addLayout(walk_header)

        walk_top_row = QHBoxLayout()
        walk_top_row.setSpacing(6)
        walk_top_row.addWidget(QLabel("확률(%)"))
        walk_top_row.addWidget(self.walk_teleport_probability_spinbox)
        walk_top_row.addSpacing(6)
        walk_top_row.addWidget(QLabel("판정주기(s)"))
        walk_top_row.addWidget(self.walk_teleport_interval_spinbox)
        walk_top_row.addStretch(1)
        right_column.addLayout(walk_top_row)

        walk_bottom_row = QHBoxLayout()
        walk_bottom_row.setSpacing(6)
        walk_bottom_row.addWidget(QLabel("보너스 간격(s)"))
        walk_bottom_row.addWidget(self.walk_teleport_bonus_interval_spinbox)
        walk_bottom_row.addSpacing(6)
        walk_bottom_row.addWidget(QLabel("보너스 증가율(%)"))
        walk_bottom_row.addWidget(self.walk_teleport_bonus_step_spinbox)
        walk_bottom_row.addSpacing(6)
        walk_bottom_row.addWidget(QLabel("보너스 최대(%)"))
        walk_bottom_row.addWidget(self.walk_teleport_bonus_max_spinbox)
        walk_bottom_row.addStretch(1)
        right_column.addLayout(walk_bottom_row)
        right_column.addStretch(1)

        columns_layout = QHBoxLayout()
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.setSpacing(16)
        columns_layout.addLayout(left_column, 1)
        columns_layout.addLayout(right_column, 1)

        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(6)
        outer_layout.addLayout(columns_layout)

        box.setLayout(outer_layout)
        self._update_base_teleport_inputs_enabled()
        self._update_walk_teleport_inputs_enabled()
        return box

    def _update_walk_teleport_inputs_enabled(self) -> None:
        enabled = getattr(self, 'walk_teleport_checkbox', None)
        if enabled is None:
            return
        state = self.walk_teleport_checkbox.isChecked()
        for widget in (
            self.walk_teleport_probability_spinbox,
            self.walk_teleport_interval_spinbox,
            self.walk_teleport_bonus_interval_spinbox,
            self.walk_teleport_bonus_step_spinbox,
            self.walk_teleport_bonus_max_spinbox,
        ):
            widget.setEnabled(state)
        if not state:
            self._reset_walk_teleport_state()
        self._update_detection_summary()

    def _on_walk_teleport_toggled(self, checked: bool) -> None:
        self.teleport_settings.walk_enabled = bool(checked)
        self._update_walk_teleport_inputs_enabled()
        self._handle_setting_changed()

    def _update_base_teleport_inputs_enabled(self) -> None:
        checkbox = getattr(self, 'teleport_enabled_checkbox', None)
        if checkbox is None:
            return
        state = checkbox.isChecked()
        for widget in (
            self.teleport_distance_spinbox,
            self.teleport_probability_spinbox,
        ):
            widget.setEnabled(state)

    def _on_base_teleport_toggled(self, checked: bool) -> None:
        self.teleport_settings.enabled = bool(checked)
        self._update_base_teleport_inputs_enabled()
        self._handle_setting_changed()

    def _on_area_config_changed(self) -> None:
        if self.latest_snapshot:
            self._recalculate_hunt_metrics()
        else:
            self._emit_area_overlays()

    def _emit_area_overlays(self) -> None:
        if not hasattr(self, "show_hunt_area_checkbox"):
            return
        show_hunt = self.overlay_preferences.get('hunt_area', True)
        show_primary = self.overlay_preferences.get('primary_area', True)
        hunt_rect = None
        primary_rect = None
        if self.current_hunt_area and self.show_hunt_area_checkbox.isChecked() and show_hunt:
            hunt_rect = self.current_hunt_area
        if self.current_primary_area and self.show_primary_skill_checkbox.isChecked() and show_primary:
            primary_rect = self.current_primary_area
        self.hunt_area_updated.emit(hunt_rect)
        self.primary_skill_area_updated.emit(primary_rect)

    def _on_overlay_toggle_changed(self, _checked: bool) -> None:
        self.overlay_preferences['hunt_area'] = self.show_hunt_area_checkbox.isChecked()
        self.overlay_preferences['primary_area'] = self.show_primary_skill_checkbox.isChecked()
        direction_state = self.show_direction_checkbox.isChecked()
        self.overlay_preferences['direction_area'] = direction_state
        self._direction_area_user_pref = direction_state
        nickname_range_state = self.show_nickname_range_checkbox.isChecked()
        self.overlay_preferences['nickname_range'] = nickname_range_state
        self._nickname_range_user_pref = nickname_range_state
        nameplate_state = self.show_nameplate_checkbox.isChecked()
        self.overlay_preferences['nameplate_area'] = nameplate_state
        self._nameplate_area_user_pref = nameplate_state
        self._emit_area_overlays()
        self._update_detection_thread_overlay_flags()
        self._save_settings()

    def _on_nameplate_tracking_toggle_changed(self, checked: bool) -> None:
        state = bool(checked)
        self.overlay_preferences['nameplate_tracking'] = state
        self._nameplate_visual_debug_enabled = state
        self._nameplate_tracking_user_pref = state
        if not state:
            self._visual_tracked_monsters = []
            self._visual_dead_zones = []
        self._update_detection_thread_overlay_flags()
        self._save_settings()

    def _on_monster_confidence_toggle_changed(self, checked: bool) -> None:
        state = bool(checked)
        self.overlay_preferences['monster_confidence'] = state
        self._update_detection_thread_overlay_flags()
        self._save_settings()

    def _update_detection_thread_overlay_flags(self) -> None:
        if not self.detection_thread:
            return
        self.detection_thread.show_nickname_overlay = bool(self._is_nickname_overlay_active())
        if hasattr(self.detection_thread, 'show_nickname_range_overlay'):
            self.detection_thread.show_nickname_range_overlay = bool(self._is_nickname_range_overlay_active())
        self.detection_thread.show_direction_overlay = bool(self._is_direction_range_overlay_active())
        if hasattr(self.detection_thread, 'show_nameplate_overlay'):
            overlay_active = self._is_nameplate_overlay_active() and self.overlay_preferences.get('nameplate_area', True)
            if hasattr(self, 'show_nameplate_checkbox') and not self.show_nameplate_checkbox.isEnabled():
                overlay_active = False
            debug_active = bool(self._nameplate_visual_debug_enabled and getattr(self, '_nameplate_enabled', False))
            detection_active = overlay_active or debug_active
            self.detection_thread.show_nameplate_overlay = bool(detection_active)
        if hasattr(self.detection_thread, 'show_monster_confidence'):
            self.detection_thread.show_monster_confidence = bool(
                self._is_monster_confidence_display_active()
            )

    def _sync_detection_thread_status(self) -> None:
        if not self.detection_thread:
            return
        try:
            self.detection_thread.set_authority(self.current_authority)
            self.detection_thread.set_facing(self.last_facing)
        except AttributeError:
            pass

    def set_overlay_preferences(self, options: dict | None) -> None:
        if not isinstance(options, dict):
            return
        if 'hunt_area' in options:
            new_state = bool(options['hunt_area'])
            self.overlay_preferences['hunt_area'] = new_state
            if hasattr(self, 'show_hunt_area_checkbox') and self.show_hunt_area_checkbox.isChecked() != new_state:
                self.show_hunt_area_checkbox.blockSignals(True)
                self.show_hunt_area_checkbox.setChecked(new_state)
                self.show_hunt_area_checkbox.blockSignals(False)
        if 'primary_area' in options:
            new_state = bool(options['primary_area'])
            self.overlay_preferences['primary_area'] = new_state
            if hasattr(self, 'show_primary_skill_checkbox') and self.show_primary_skill_checkbox.isChecked() != new_state:
                self.show_primary_skill_checkbox.blockSignals(True)
                self.show_primary_skill_checkbox.setChecked(new_state)
                self.show_primary_skill_checkbox.blockSignals(False)
        direction_value = None
        if 'direction_area' in options:
            direction_value = bool(options['direction_area'])
        elif 'nickname_area' in options:  # backward compatibility
            direction_value = bool(options['nickname_area'])
        if direction_value is not None:
            self.overlay_preferences['direction_area'] = direction_value
            self._direction_area_user_pref = direction_value
            if hasattr(self, 'show_direction_checkbox') and self.show_direction_checkbox.isChecked() != direction_value:
                self.show_direction_checkbox.blockSignals(True)
                self.show_direction_checkbox.setChecked(direction_value)
                self.show_direction_checkbox.blockSignals(False)
        if 'nickname_range' in options:
            nickname_range_value = bool(options['nickname_range'])
            self.overlay_preferences['nickname_range'] = nickname_range_value
            self._nickname_range_user_pref = nickname_range_value
            if hasattr(self, 'show_nickname_range_checkbox') and self.show_nickname_range_checkbox.isChecked() != nickname_range_value:
                self.show_nickname_range_checkbox.blockSignals(True)
                self.show_nickname_range_checkbox.setChecked(nickname_range_value)
                self.show_nickname_range_checkbox.blockSignals(False)
        if 'nameplate_tracking' in options:
            tracking_state = bool(options['nameplate_tracking'])
            self.overlay_preferences['nameplate_tracking'] = tracking_state
            self._nameplate_visual_debug_enabled = tracking_state
            if not tracking_state:
                self._visual_tracked_monsters = []
                self._visual_dead_zones = []
            if (
                hasattr(self, 'show_nameplate_tracking_checkbox')
                and self.show_nameplate_tracking_checkbox.isChecked() != tracking_state
            ):
                self.show_nameplate_tracking_checkbox.blockSignals(True)
                self.show_nameplate_tracking_checkbox.setChecked(tracking_state)
                self.show_nameplate_tracking_checkbox.blockSignals(False)
        if 'monster_confidence' in options:
            monster_conf_state = bool(options['monster_confidence'])
            self.overlay_preferences['monster_confidence'] = monster_conf_state
            if (
                hasattr(self, 'show_monster_confidence_checkbox')
                and self.show_monster_confidence_checkbox.isChecked() != monster_conf_state
            ):
                self.show_monster_confidence_checkbox.blockSignals(True)
                self.show_monster_confidence_checkbox.setChecked(monster_conf_state)
                self.show_monster_confidence_checkbox.blockSignals(False)
        self._emit_area_overlays()
        self._update_detection_thread_overlay_flags()
        self._save_settings()

    def _log_control_request(self, payload: dict, reason: str | None) -> None:
        hunt_threshold = payload.get("hunt_monster_threshold")
        if hunt_threshold is None:
            hunt_threshold = payload.get("monster_threshold")
        primary_threshold = payload.get("primary_monster_threshold")
        range_px = payload.get("range_px")
        primary_range = payload.get("primary_skill_range")
        model = payload.get("model") or "-"
        attack_count = payload.get("attack_skill_count", 0)
        buff_count = payload.get("buff_skill_count", 0)
        latest_total = payload.get("latest_monster_count")
        latest_primary = payload.get("latest_primary_monster_count")

        detail_parts = [
            f"현재 몬스터 {latest_total}마리 / 주 스킬 {latest_primary}마리",
            f"사냥범위 기준 {hunt_threshold}마리, 주 스킬 기준 {primary_threshold}마리",
            f"사냥범위 ±{range_px}px, 주 스킬 범위 ±{primary_range}px",
            f"모델 '{model}', 공격 스킬 {attack_count}개, 버프 스킬 {buff_count}개",
        ]
        if reason:
            detail_parts.append(f"요청 사유: {reason}")
        self.append_log("사냥 권한 요청", "info")
        for line in detail_parts:
            self._append_log_detail(line)

    def _handle_setting_changed(self, *args, **kwargs) -> None:
        self._save_settings()
        self._update_detection_summary()

    def _describe_authority_pending_reasons(
        self,
        failed_codes: Iterable[str],
        detail_payload: dict,
    ) -> list[str]:
        descriptions: list[str] = []
        map_snapshot = detail_payload.get("map_snapshot") or {}
        hunt_snapshot = detail_payload.get("hunt_snapshot") or {}
        request_meta = detail_payload.get("meta") or {}
        map_protect_seconds = request_meta.get("map_protect_sec")
        if not isinstance(map_protect_seconds, (int, float)):
            map_protect_seconds = None
        hunt_protect_seconds = request_meta.get("hunt_protect_sec")
        if not isinstance(hunt_protect_seconds, (int, float)):
            hunt_protect_seconds = None

        map_meta = map_snapshot.get("metadata") if isinstance(map_snapshot.get("metadata"), dict) else {}
        monster_count = hunt_snapshot.get("monster_count")
        primary_monster_count = hunt_snapshot.get("primary_monster_count")
        hunt_threshold = hunt_snapshot.get("hunt_monster_threshold")
        primary_threshold = hunt_snapshot.get("primary_monster_threshold")
        now = time.time()

        for code in failed_codes:
            if code == "MAP_SNAPSHOT_MISSING":
                descriptions.append(
                    "MAP_SNAPSHOT_MISSING: 맵 탭이 최신 상태 스냅샷을 전달하지 않아 캐릭터 상태를 파악할 수 없습니다. (맵 탐지 실행 여부 확인 필요)"
                )
                continue

            if code == "MAP_NOT_WALKING":
                state = map_snapshot.get("player_state") or "알 수 없음"
                descriptions.append(
                    f"MAP_NOT_WALKING: 캐릭터가 지상(on_terrain), 대기(idle), 점프(jumping) 상태 중 하나가 아닙니다. 현재 상태={state}."
                )
                continue

            if code == "MAP_STATE_ACTIVE":
                state = map_snapshot.get("player_state") or "알 수 없음"
                extras: list[str] = []
                if map_snapshot.get("is_event_active"):
                    extras.append("이벤트 처리 중")
                if map_snapshot.get("is_forbidden_active"):
                    extras.append("금지벽 수행 중")
                if map_snapshot.get("priority_override"):
                    extras.append("우선 잠금 활성")
                if map_meta.get("navigation_locked"):
                    extras.append("경로 잠금 상태")
                extra_text = f" ({', '.join(extras)})" if extras else ""
                descriptions.append(
                    f"MAP_STATE_ACTIVE: 맵 탭 캐릭터가 아직 안정 상태가 아닙니다. 현재 상태={state}{extra_text}."
                )
                continue

            if code == "MAP_PROTECT_ACTIVE":
                if map_protect_seconds is not None:
                    descriptions.append(
                        f"MAP_PROTECT_ACTIVE: 맵 탭 권한 보호 시간 {map_protect_seconds:.1f}초가 아직 끝나지 않아 대기합니다."
                    )
                else:
                    descriptions.append(
                        "MAP_PROTECT_ACTIVE: 맵 탭이 권한을 되찾은 직후 보호 시간이 아직 끝나지 않아 대기합니다."
                    )
                continue

            if code == "MAP_PRIORITY_LOCK":
                extras: list[str] = []
                if map_snapshot.get("is_event_active"):
                    extras.append("이벤트 진행 중")
                if map_snapshot.get("is_forbidden_active"):
                    extras.append("금지벽 처리 중")
                if request_meta.get("priority_reason"):
                    extras.append(f"요청 사유={request_meta.get('priority_reason')}")
                extra_text = f" ({', '.join(extras)})" if extras else ""
                descriptions.append(
                    f"MAP_PRIORITY_LOCK: 맵 탭이 우선 처리 작업을 진행하고 있어 권한을 유지해야 합니다{extra_text}."
                )
                continue

            if code == "FLOOR_CHANGE_PENDING":
                lock_reason = request_meta.get("floor_lock_reason")
                reason_lookup = {
                    "MAX_TOTAL_HOLD_EXCEEDED": "전체 최대 이동권한 시간 초과",
                    "FLOOR_HOLD_EXCEEDED": "층별 최대 이동권한 시간 초과",
                }
                if isinstance(lock_reason, str):
                    lock_reason = reason_lookup.get(lock_reason, lock_reason)
                lock_floor = request_meta.get("floor_lock_floor")
                lock_set_at = request_meta.get("floor_lock_set_at")
                elapsed_text = ""
                if isinstance(lock_set_at, (int, float)):
                    elapsed = now - float(lock_set_at)
                    if elapsed >= 0:
                        elapsed_text = f" (잠금 경과 {elapsed:.1f}s)"
                floor_text = ""
                if isinstance(lock_floor, (int, float, str)):
                    floor_text = f", 기준 층={lock_floor}"
                reason_text = f" (사유: {lock_reason})" if lock_reason else ""
                descriptions.append(
                    "FLOOR_CHANGE_PENDING: 강제 반납 이후 캐릭터가 다른 층으로 이동하기 전까지 맵 탭 권한을 유지합니다." + reason_text + floor_text + elapsed_text
                )
                continue

            if code == "HUNT_PROTECT_ACTIVE":
                if hunt_protect_seconds is not None:
                    descriptions.append(
                        f"HUNT_PROTECT_ACTIVE: 사냥 탭 권한 보호 시간 {hunt_protect_seconds:.1f}초가 지나지 않아 권한을 유지합니다."
                    )
                else:
                    descriptions.append(
                        "HUNT_PROTECT_ACTIVE: 사냥 탭이 권한을 획득한 직후 보호 시간 내에 있어 맵 탭 요청을 대기합니다."
                    )
                continue

            if code == "HUNT_SNAPSHOT_OUTDATED":
                timestamp = hunt_snapshot.get("timestamp")
                if isinstance(timestamp, (int, float)):
                    elapsed = now - timestamp
                    descriptions.append(
                        f"HUNT_SNAPSHOT_OUTDATED: 사냥 스냅샷이 {elapsed:.1f}초 동안 갱신되지 않아 안전을 위해 대기합니다."
                    )
                else:
                    descriptions.append(
                        "HUNT_SNAPSHOT_OUTDATED: 사냥 스냅샷이 최신이 아니어서 대기합니다."
                    )
                continue

            if code == "HUNT_MONSTER_SHORTAGE":
                shortage_bits: list[str] = []
                if isinstance(hunt_threshold, (int, float)) and isinstance(monster_count, (int, float)):
                    if monster_count < hunt_threshold:
                        shortage_bits.append(
                            f"전체 몬스터 {monster_count}마리 < 기준 {hunt_threshold}마리"
                        )
                if isinstance(primary_threshold, (int, float)) and isinstance(primary_monster_count, (int, float)):
                    if primary_monster_count < primary_threshold:
                        shortage_bits.append(
                            f"주 스킬 대상 {primary_monster_count}마리 < 기준 {primary_threshold}마리"
                        )
                if not shortage_bits:
                    shortage_bits.append("사냥 조건 미충족")
                descriptions.append(
                    "HUNT_MONSTER_SHORTAGE: 사냥 조건을 충족하지 못했습니다. " + ", ".join(shortage_bits) + "."
                )
                continue

            if code == "HUNT_SNAPSHOT_MISSING":
                descriptions.append(
                    "HUNT_SNAPSHOT_MISSING: 사냥 탭이 최신 몬스터 정보를 전달하지 않아 요청을 보류합니다. (사냥 탐지 실행 여부 확인)"
                )
                continue

            if code == "MAP_ALREADY_OWNER":
                descriptions.append(
                    "MAP_ALREADY_OWNER: 이미 맵 탭이 조작 권한을 보유 중입니다."
                )
                continue

            if code == "HOLD_LIMIT_NOT_REACHED":
                descriptions.append(
                    "HOLD_LIMIT_NOT_REACHED: 설정된 권한 유지 시간에 아직 도달하지 않아 사냥 탭으로 넘길 수 없습니다."
                )
                continue

            descriptions.append(f"{code}: 추가 정보 없이 대기 중입니다.")

        return descriptions

    def _on_downscale_toggled(self, checked: bool) -> None:
        if self._suppress_downscale_prompt:
            self.downscale_enabled = bool(checked)
            self._update_downscale_checkbox_text()
            self._handle_setting_changed()
            return

        if checked:
            base_factor = self.downscale_factor if self.downscale_factor else 0.5
            new_factor = self._prompt_downscale_factor(base_factor)
            if new_factor is None:
                self.downscale_checkbox.blockSignals(True)
                self.downscale_checkbox.setChecked(False)
                self.downscale_checkbox.blockSignals(False)
                return
            self.downscale_enabled = True
            self.downscale_factor = new_factor
            self.append_log(f"다운스케일 {self.downscale_factor:.2f}x 적용", "info")
        else:
            self.downscale_enabled = False
            self.append_log("다운스케일을 비활성화했습니다.", "info")

        self._update_downscale_checkbox_text()
        if self.detection_thread and self.detection_thread.isRunning():
            self.append_log("변경 내용은 탐지를 다시 시작하면 반영됩니다.", "warn")
        self._handle_setting_changed()

    def _prompt_downscale_factor(self, initial: float) -> Optional[float]:
        clamped_initial = max(0.1, min(1.0, float(initial)))
        value, ok = QInputDialog.getDouble(
            self,
            "다운스케일 배율",
            "YOLO 입력에 적용할 배율 (0.10~1.00):",
            clamped_initial,
            0.1,
            1.0,
            decimals=2,
        )
        if not ok:
            return None
        return max(0.1, min(1.0, float(value)))

    def _update_downscale_checkbox_text(self) -> None:
        if not hasattr(self, 'downscale_checkbox'):
            return
        if self.downscale_enabled:
            self.downscale_checkbox.setText(f"다운스케일 ({self.downscale_factor:.2f}x)")
            self.downscale_checkbox.setToolTip("YOLO 입력 프레임을 지정한 배율로 축소합니다.")
        else:
            self.downscale_checkbox.setText("다운스케일")
            self.downscale_checkbox.setToolTip("YOLO 입력을 축소해 성능을 개선합니다.")

    def _schedule_condition_poll(self, delay_ms: Optional[int] = None) -> None:
        if not self._condition_debounce_timer:
            return
        if delay_ms is None:
            delay_ms = self.CONDITION_POLL_DEBOUNCE_MS
        self._condition_debounce_timer.stop()
        self._condition_debounce_timer.start(max(1, int(delay_ms)))

    def _on_condition_debounce_timeout(self) -> None:
        self._poll_hunt_conditions()

    def _handle_request_timeout(self) -> None:
        self._request_pending = False
        if self.current_authority != "hunt":
            self.append_log("사냥 권한 요청 응답이 지연되어 재평가합니다.", "warn")
            self._poll_hunt_conditions(force=True)

    def _handle_max_hold_changed(self, value: float) -> None:
        self.control_release_timeout = max(0.0, float(value))
        self._apply_authority_settings_to_manager()
        self._save_settings()

    def _handle_floor_hold_changed(self, value: float) -> None:
        self.floor_hold_seconds = max(0.0, float(value))
        self._apply_authority_settings_to_manager()
        self._save_settings()

    def _handle_map_protect_changed(self, value: float) -> None:
        self.map_protect_seconds = max(0.1, float(value))
        self._apply_authority_settings_to_manager()
        self._save_settings()

    def _handle_hunt_protect_changed(self, value: float) -> None:
        self.hunt_protect_seconds = max(0.1, float(value))
        self._apply_authority_settings_to_manager()
        self._save_settings()

    def _apply_authority_settings_to_manager(self) -> None:
        if not self.map_link_enabled or not self._authority_manager_connected:
            return
        try:
            map_protect = float(self.map_protect_spinbox.value()) if hasattr(self, 'map_protect_spinbox') else float(self.map_protect_seconds)
            floor_hold = float(self.floor_hold_spinbox.value()) if hasattr(self, 'floor_hold_spinbox') else float(self.floor_hold_seconds)
            max_total = float(self.max_authority_hold_spinbox.value()) if hasattr(self, 'max_authority_hold_spinbox') else float(self.control_release_timeout)
            hunt_protect = float(self.hunt_protect_spinbox.value()) if hasattr(self, 'hunt_protect_spinbox') else float(self.hunt_protect_seconds)
            self._authority_manager.update_hunt_settings(
                map_protect_sec=map_protect,
                floor_hold_sec=floor_hold,
                max_total_hold_sec=max_total,
                hunt_protect_sec=hunt_protect,
            )
        except Exception as exc:
            self.append_log(f"권한 매니저 설정 갱신 실패: {exc}", "warn")

    def _connect_authority_manager(self) -> None:
        if self._authority_manager_connected:
            return
        manager = self._authority_manager
        manager.authority_changed.connect(self._on_authority_changed_from_manager)
        manager.request_evaluated.connect(self._on_authority_request_evaluated)
        manager.priority_event_triggered.connect(self._on_priority_event_from_manager)
        manager.priority_event_cleared.connect(self._on_priority_event_cleared_from_manager)
        self._authority_manager_connected = True

    def _disconnect_authority_manager(self) -> None:
        if not self._authority_manager_connected:
            return
        manager = self._authority_manager
        try:
            manager.authority_changed.disconnect(self._on_authority_changed_from_manager)
        except TypeError:
            pass
        try:
            manager.request_evaluated.disconnect(self._on_authority_request_evaluated)
        except TypeError:
            pass
        try:
            manager.priority_event_triggered.disconnect(self._on_priority_event_from_manager)
        except TypeError:
            pass
        try:
            manager.priority_event_cleared.disconnect(self._on_priority_event_cleared_from_manager)
        except TypeError:
            pass
        self._authority_manager_connected = False

    def _activate_map_link(self, *, initial: bool = False) -> None:
        self.map_link_enabled = True
        self._connect_authority_manager()
        self._apply_authority_settings_to_manager()
        self._authority_request_connected = True
        self._authority_release_connected = True
        state = self._authority_manager.current_state()
        if not initial:
            self.append_log("맵 탭 연동 모드를 활성화했습니다.", "info")
        self.on_map_authority_changed(state.owner, {"source": "manager", "state": state.as_payload(), "silent": initial})

    def _deactivate_map_link(self, *, initial: bool = False) -> None:
        self.map_link_enabled = False
        self._disconnect_authority_manager()
        self._authority_request_connected = False
        self._authority_release_connected = False
        self._request_pending = False
        self._forbidden_priority_active = False
        if not initial:
            self.append_log("맵 탭 연동 모드를 비활성화했습니다.", "info")
        self.on_map_authority_changed("hunt", {"source": "local", "reason": "map_link_disabled", "silent": initial})

    def _on_map_link_toggled(self, checked: bool) -> None:
        if checked:
            self._activate_map_link(initial=False)
        else:
            self._deactivate_map_link(initial=False)
        self._save_settings()
        if checked and self.map_tab:
            self._sync_detection_state_with_map()

    def _on_authority_changed_from_manager(self, owner: str, payload: dict) -> None:
        if not self.map_link_enabled:
            return
        self.on_map_authority_changed(owner, payload)

    def _on_authority_request_evaluated(self, requester: str, payload: dict) -> None:
        if requester != "hunt" or not self.map_link_enabled:
            return
        status = payload.get("status", "")
        reason = payload.get("reason")
        details = payload.get("payload") or {}
        if status == AuthorityDecisionStatus.PENDING.value:
            failed = details.get("failed") or []
            if failed:
                failed_codes = ", ".join(str(item) for item in failed)
                self.append_log(
                    f"사냥 권한 요청 대기: {failed_codes}",
                    "warn",
                )
                for line in self._describe_authority_pending_reasons(failed, details):
                    self._append_log_detail(line)
        elif status == AuthorityDecisionStatus.REJECTED.value:
            message = reason or "사유 없음"
            self.append_log(f"사냥 권한 요청 거부: {message}", "warn")

    def _on_priority_event_from_manager(self, kind: str, metadata: dict) -> None:
        if not self.map_link_enabled:
            return
        if kind == "FORBIDDEN_WALL":
            self._forbidden_priority_active = True
        detail_parts = []
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                detail_parts.append(f"{key}={value}")
        detail_text = f" ({', '.join(detail_parts)})" if detail_parts else ""
        self.append_log(f"맵 탭 우선 이벤트 감지: {kind}{detail_text}", "warn")

    def _on_priority_event_cleared_from_manager(self, kind: str, metadata: dict) -> None:
        if not self.map_link_enabled:
            return
        if kind != "FORBIDDEN_WALL":
            return
        self._forbidden_priority_active = False
        self.append_log("금지벽 우선 이벤트가 종료되었습니다.", "info")
        self._poll_hunt_conditions(force=True)

    def _build_hunt_condition_snapshot(self) -> HuntConditionSnapshot:
        return HuntConditionSnapshot(
            timestamp=time.time(),
            monster_count=int(self.latest_monster_count),
            primary_monster_count=int(self.latest_primary_monster_count),
            hunt_monster_threshold=int(self.hunt_monster_threshold_spinbox.value()),
            primary_monster_threshold=int(self.primary_monster_threshold_spinbox.value()),
            idle_release_seconds=float(self.idle_release_spinbox.value()),
            metadata={
                "hunting_active": bool(self.hunting_active),
                "auto_hunt_enabled": bool(self.auto_hunt_enabled),
            },
        )

    def _handle_map_detection_status_changed(self, running: bool) -> None:
        if not self.map_link_enabled or self._syncing_with_map:
            return
        if not hasattr(self, 'detect_btn'):
            return
        try:
            hunt_running = bool(self.detect_btn.isChecked())
        except Exception:
            hunt_running = False
        if running == hunt_running:
            return
        self._syncing_with_map = True
        try:
            if running and not hunt_running:
                if hasattr(self.detect_btn, 'setChecked'):
                    self.detect_btn.setChecked(True)
                self._toggle_detection(True)
            elif not running and hunt_running:
                if hasattr(self.detect_btn, 'setChecked'):
                    self.detect_btn.setChecked(False)
                self._toggle_detection(False)
        finally:
            self._syncing_with_map = False

    def _sync_detection_state_with_map(self) -> None:
        if not self.map_link_enabled or not self.map_tab:
            return
        try:
            map_running = bool(self.map_tab.detect_anchor_btn.isChecked())
        except Exception:
            map_running = False
        self._handle_map_detection_status_changed(map_running)

    def _build_hunt_request_meta(self) -> dict:
        hunt_threshold = self.hunt_monster_threshold_spinbox.value()
        primary_threshold = self.primary_monster_threshold_spinbox.value()
        return {
            "hunt_monster_threshold": hunt_threshold,
            "primary_monster_threshold": primary_threshold,
            "monster_threshold": hunt_threshold,
            "range_px": self.enemy_range_spinbox.value(),
            "y_band_height": self.y_band_height_spinbox.value(),
            "y_offset": self.y_band_offset_spinbox.value(),
            "primary_skill_range": self.primary_skill_range_spinbox.value(),
            "model": self._get_active_model_name() or "-",
            "attack_skill_count": len(self.attack_skills),
            "buff_skill_count": len(self.buff_skills),
            "latest_monster_count": self.latest_monster_count,
            "latest_primary_monster_count": self.latest_primary_monster_count,
            "map_protect_sec": float(self.map_protect_spinbox.value()) if hasattr(self, 'map_protect_spinbox') else float(self.map_protect_seconds),
            "hunt_protect_sec": float(self.hunt_protect_spinbox.value()) if hasattr(self, 'hunt_protect_spinbox') else float(self.hunt_protect_seconds),
        }

    def _handle_facing_reset_changed(self, value: float) -> None:
        min_val = self.facing_reset_min_spinbox.value()
        max_val = self.facing_reset_max_spinbox.value()
        if min_val > max_val:
            if value == min_val:
                self.facing_reset_max_spinbox.setValue(min_val)
            else:
                self.facing_reset_min_spinbox.setValue(max_val)
        self._schedule_facing_reset()
        self._save_settings()

    def _emit_control_command(self, command: str, reason: Optional[str] = None) -> None:
        normalized = str(command).strip()
        if not command:
            return
        if not normalized:
            return

        reason_str = str(reason) if isinstance(reason, str) else ""
        is_status_command = reason_str.startswith('status:')
        is_primary_release_command = reason_str.startswith('primary_release')
        allow_during_cooldown = False
        status_resource = ''
        status_percent: Optional[float] = None
        if is_status_command:
            status_parts = reason_str.split(':')
            if len(status_parts) >= 2:
                status_resource = status_parts[1].strip().lower()
            if len(status_parts) >= 3:
                try:
                    status_percent = float(status_parts[2])
                except ValueError:
                    status_percent = None
            if status_resource == 'hp':
                allow_during_cooldown = True
        elif is_primary_release_command:
            allow_during_cooldown = True

        if (
            self._get_command_delay_remaining() > 0
            and normalized != "모든 키 떼기"
            and not normalized.startswith("방향설정(")
            and not allow_during_cooldown
        ):
            return

        if normalized.startswith("방향설정("):
            if "좌" in normalized:
                self._set_current_facing('left')
            elif "우" in normalized:
                self._set_current_facing('right')
        else:
            lower = normalized.lower()
            if "key.left" in lower and "key.right" not in lower:
                self._set_current_facing('left', save=False)
            elif "key.right" in lower and "key.left" not in lower:
                self._set_current_facing('right', save=False)
        self.control_command_issued.emit(command, reason)
        if not is_status_command and not is_primary_release_command and normalized != "모든 키 떼기":
            self._last_command_issued = (command, reason)

        reason_text = reason_str.strip()
        if is_status_command:
            resource_label = status_resource.upper() if status_resource else 'STATUS'
            if status_percent is not None:
                reason_text = f"Status: {resource_label} ({int(round(status_percent))}%)"
            else:
                reason_text = f"Status: {resource_label}"
        elif reason_text.startswith('primary_release'):
            parts = reason_text.split('|', 1)
            reason_text = parts[1].strip() if len(parts) == 2 else ""
        if not is_primary_release_command:
            formatted_message = None
            if reason_text.startswith('사용원인'):
                reason_body = reason_text[len('사용원인'):].strip()
                if reason_body.startswith('(') and reason_body.endswith(')'):
                    reason_body = reason_body[1:-1].strip()
                formatted_message = f"{normalized} -원인: {reason_body}" if reason_body else None
            elif reason_text:
                formatted_message = f"{normalized} -원인: {reason_text}"

            log_message = formatted_message or (f"{normalized} -원인: {reason_text}" if reason_text else normalized)
            self._append_control_log(log_message)

    def _append_control_log(self, message: str, color: Optional[str] = None) -> None:
        timestamp = self._format_timestamp_ms()
        line = f"[{timestamp}] {message}"
        if (
            hasattr(self, 'control_log_view')
            and self.control_log_view
            and self._is_log_enabled('control_log_checkbox')
        ):
            self._append_colored_text(self.control_log_view, line, color or "white")
        self._append_keyboard_log(message, timestamp=timestamp, color=color)

    def _set_command_cooldown(self, delay_sec: float) -> None:
        delay_sec = max(0.0, float(delay_sec))
        if delay_sec <= 0.0:
            self._next_command_ready_ts = max(self._next_command_ready_ts, time.time())
            return
        ready_time = time.time() + delay_sec
        self._next_command_ready_ts = max(self._next_command_ready_ts, ready_time)

    def _get_command_delay_remaining(self) -> float:
        return max(0.0, self._next_command_ready_ts - time.time())

    def _append_keyboard_log(
        self,
        message: str,
        *,
        timestamp: Optional[str] = None,
        color: Optional[str] = None,
    ) -> None:
        if not hasattr(self, 'keyboard_log_view') or not self.keyboard_log_view:
            return
        if not self._is_log_enabled('keyboard_log_checkbox'):
            return
        if timestamp is None:
            timestamp = self._format_timestamp_ms()
        line = f"[{timestamp}] {message}"
        self._append_colored_text(self.keyboard_log_view, line, color or "white")

    def _handle_status_config_update(self, config: StatusMonitorConfig) -> None:
        self._status_config = config
        if not getattr(config.hp, 'enabled', True):
            self._status_display_values['hp'] = None
        if not getattr(config.mp, 'enabled', True):
            self._status_display_values['mp'] = None
        if not getattr(config.exp, 'enabled', True):
            self._status_exp_records.clear()
        self._update_status_summary_cache()
        self._update_detection_summary()

    def _handle_status_snapshot(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        if not getattr(self, 'detect_btn', None) or not self.detect_btn.isChecked():
            return
        timestamp = float(payload.get('timestamp', time.time()))

        hp_cfg = getattr(self._status_config, 'hp', None)
        mp_cfg = getattr(self._status_config, 'mp', None)
        exp_cfg = getattr(self._status_config, 'exp', None)

        if hp_cfg and getattr(hp_cfg, 'enabled', True):
            hp_info = payload.get('hp')
            if isinstance(hp_info, dict):
                hp_value = hp_info.get('percentage')
                if isinstance(hp_value, (int, float)):
                    self._status_display_values['hp'] = float(hp_value)
                    self._maybe_trigger_status_command('hp', float(hp_value), timestamp)
        else:
            self._status_display_values['hp'] = None

        if mp_cfg and getattr(mp_cfg, 'enabled', True):
            mp_info = payload.get('mp')
            if isinstance(mp_info, dict):
                mp_value = mp_info.get('percentage')
                if isinstance(mp_value, (int, float)):
                    self._status_display_values['mp'] = float(mp_value)
                    self._maybe_trigger_status_command('mp', float(mp_value), timestamp)
        else:
            self._status_display_values['mp'] = None

        if exp_cfg and getattr(exp_cfg, 'enabled', True):
            exp_info = payload.get('exp')
            if isinstance(exp_info, dict):
                self._record_exp_snapshot(exp_info)
        else:
            self._status_exp_records.clear()

        self._update_status_summary_cache()
        self._update_detection_summary()

    def _handle_status_ocr_unavailable(self) -> None:
        if self._status_ocr_warned:
            return
        self._status_ocr_warned = True
        self.append_log('경고: pytesseract가 설치되지 않아 EXP 인식을 사용할 수 없습니다.', 'warn')

    def _handle_exp_status_log(self, level: str, message: str) -> None:
        if not message:
            return
        level = (level or 'info').lower()
        self.append_log(message, level)

    def _maybe_trigger_status_command(self, resource: str, percentage: float, timestamp: float) -> None:
        if self.current_authority != 'hunt':
            return
        cfg = getattr(self._status_config, resource, None)
        if cfg is None:
            return
        if not getattr(cfg, 'enabled', True):
            return
        threshold = getattr(cfg, 'recovery_threshold', None)
        if threshold is None:
            return
        command_name = getattr(cfg, 'command_profile', None) or ''
        command_name = command_name.strip()
        if not command_name:
            return
        if percentage > threshold:
            return
        last_ts = self._status_last_command_ts.get(resource, 0.0)
        interval = max(0.1, getattr(cfg, 'interval_sec', 1.0))
        if (timestamp - last_ts) < interval:
            return

        if resource == 'hp':
            if self._hp_guard_active:
                return
            self._issue_status_command(resource, command_name, percentage)
            guard_delay = random.uniform(0.370, 0.400)
            self._hp_guard_active = True
            self._hp_guard_timer.start(int(guard_delay * 1000))
        else:
            if (
                self._last_command_issued
                and (
                    not isinstance(self._last_command_issued[1], str)
                    or not str(self._last_command_issued[1]).startswith('status:')
                )
            ):
                self._status_mp_saved_command = self._last_command_issued
            else:
                self._status_mp_saved_command = None
            self._issue_status_command(resource, command_name, percentage)

        self._status_last_command_ts[resource] = timestamp

    def _issue_status_command(self, resource: str, command_name: str, percentage: Optional[float] = None) -> None:
        percent_text = ''
        if isinstance(percentage, (int, float)):
            percent_value = max(0, min(100, int(round(float(percentage)))))
            percent_text = f":{percent_value}"
        reason = f'status:{resource}{percent_text}'
        self._emit_control_command(command_name, reason=reason)
        if percent_text:
            self.append_log(
                f"[{resource.upper()}] 자동 명령 '{command_name}' 실행 (현재 {percent_text.lstrip(':')}%)",
                'info',
            )
        else:
            self.append_log(f"[{resource.upper()}] 자동 명령 '{command_name}' 실행", 'info')

    def _handle_status_sequence_completed(self, command_name: str, reason: str, success: bool) -> None:
        resource = ''
        if isinstance(reason, str) and reason.startswith('status:'):
            parts = reason.split(':')
            if len(parts) >= 2:
                resource = parts[1].strip()
        if resource == 'mp' and self._status_mp_saved_command:
            command, saved_reason = self._status_mp_saved_command
            self._status_mp_saved_command = None
            self._emit_control_command(command, saved_reason)
        elif resource == 'hp':
            if success:
                self.append_log(f"[HP] 회복 명령 '{command_name}' 완료", 'debug')

    def _clear_hp_guard(self) -> None:
        self._hp_guard_active = False

    def _update_status_summary_cache(self) -> None:
        hp_cfg = getattr(self._status_config, 'hp', None)
        mp_cfg = getattr(self._status_config, 'mp', None)
        exp_cfg = getattr(self._status_config, 'exp', None)

        hp = self._status_display_values.get('hp')
        mp = self._status_display_values.get('mp')

        hp_enabled = hp_cfg.enabled if hp_cfg else True
        mp_enabled = mp_cfg.enabled if mp_cfg else True
        exp_enabled = exp_cfg.enabled if exp_cfg else True

        def _format_percent(value: float) -> str:
            rounded = round(value)
            if abs(value - rounded) < 0.05:
                return f"{rounded}%"
            return f"{value:.1f}%"

        def _format_resource_text(percent_value, cfg) -> str:
            if not isinstance(percent_value, (int, float)):
                return '--'
            percent_text = _format_percent(float(percent_value))
            maximum = getattr(cfg, 'maximum_value', None) if cfg else None
            if isinstance(maximum, (int, float)) and maximum > 0:
                current_value = int(round(float(maximum) * float(percent_value) / 100.0))
                return f"{percent_text} ({current_value})"
            return percent_text

        hp_text = '비활성' if not hp_enabled else _format_resource_text(hp, hp_cfg)
        mp_text = '비활성' if not mp_enabled else _format_resource_text(mp, mp_cfg)
        exp_text = '비활성'
        if self._status_exp_records:
            latest = self._status_exp_records[-1]
            amount = latest.get('amount')
            percent = latest.get('percent')
            if amount is not None and percent is not None:
                exp_text = f"{amount} / {percent:.2f}%"
        elif exp_enabled:
            exp_text = '-- / --'
        else:
            exp_text = '비활성'
        self._status_summary_cache = {
            'hp': f"HP: {hp_text}",
            'mp': f"MP: {mp_text}",
            'exp': f"EXP: {exp_text}",
        }

    def _record_exp_snapshot(self, record: dict) -> None:
        if record is None or not getattr(self._status_config.exp, 'enabled', True):
            return
        amount_raw = record.get('amount')
        percent_raw = record.get('percent')
        try:
            amount_val = int(str(amount_raw)) if amount_raw is not None else None
        except ValueError:
            amount_val = None
        try:
            percent_val = float(percent_raw) if percent_raw is not None else None
        except (TypeError, ValueError):
            percent_val = None
        if amount_val is None or percent_val is None:
            return
        entry = {
            'timestamp': float(record.get('timestamp', time.time())),
            'amount': amount_val,
            'percent': percent_val,
        }
        if self._status_exp_start_snapshot is None:
            self._status_exp_start_snapshot = entry
        self._status_exp_records.append(entry)

    def _finalize_exp_tracking(self, end_timestamp: Optional[float] = None) -> None:
        if not self._status_exp_start_snapshot or not self._status_exp_records:
            return
        processed_records: list[dict] = []
        for entry in self._status_exp_records:
            if not isinstance(entry, dict):
                continue
            amount_raw = entry.get('amount')
            percent_raw = entry.get('percent')
            try:
                amount_val = max(0, int(str(amount_raw)))
                percent_val = max(0.0, float(percent_raw))
            except (TypeError, ValueError):
                continue
            processed_records.append({
                'timestamp': float(entry.get('timestamp', time.time())),
                'amount': amount_val,
                'percent': percent_val,
            })

        if not processed_records:
            return

        processed_records.sort(key=lambda item: item.get('timestamp', 0.0))

        start_snapshot = self._status_exp_start_snapshot
        start_amount: Optional[int] = None
        start_percent: Optional[float] = None
        start_timestamp: float = processed_records[0].get('timestamp', time.time())
        if isinstance(start_snapshot, dict):
            try:
                start_amount = max(0, int(str(start_snapshot.get('amount'))))
                start_percent = max(0.0, float(start_snapshot.get('percent')))
                start_timestamp = float(start_snapshot.get('timestamp', start_timestamp))
            except (TypeError, ValueError):
                start_amount = None
                start_percent = None

        if start_amount is None or start_percent is None:
            start_amount = processed_records[0]['amount']
            start_percent = processed_records[0]['percent']
        else:
            first = processed_records[0]
            if (
                start_amount != first['amount']
                or abs(start_percent - first['percent']) > 1e-6
            ):
                processed_records.insert(0, {
                    'timestamp': start_timestamp,
                    'amount': start_amount,
                    'percent': start_percent,
                })
            else:
                first['timestamp'] = min(first.get('timestamp', start_timestamp), start_timestamp)

        start_entry = processed_records[0]
        end_entry = processed_records[-1]
        if end_timestamp is None:
            end_timestamp = time.time()

        start_amount = start_entry['amount']
        start_percent = start_entry['percent']
        end_amount = end_entry['amount']
        end_percent = end_entry['percent']

        total_amount_gain = 0
        total_percent_gain = 0.0

        prev_amount = start_amount
        prev_percent = start_percent

        LEVELUP_AMOUNT_DROP_MIN = 10
        LEVELUP_PERCENT_DROP_MIN = 0.2
        LEVELUP_PERCENT_RESET_THRESHOLD = 5.0
        LEVELUP_AMOUNT_RATIO_THRESHOLD = 0.2
        LEVELUP_PERCENT_RATIO_THRESHOLD = 0.5
        POSITIVE_PERCENT_EPS = 0.001

        for entry in processed_records[1:]:
            amount = entry['amount']
            percent = entry['percent']

            amount_delta = amount - prev_amount
            percent_delta = percent - prev_percent
            amount_drop = prev_amount - amount
            percent_drop = prev_percent - percent

            level_up_detected = (
                amount_drop > LEVELUP_AMOUNT_DROP_MIN
                and percent_drop > LEVELUP_PERCENT_DROP_MIN
                and (
                    percent <= LEVELUP_PERCENT_RESET_THRESHOLD
                    or amount <= max(0.0, prev_amount * LEVELUP_AMOUNT_RATIO_THRESHOLD)
                    or percent <= prev_percent * LEVELUP_PERCENT_RATIO_THRESHOLD
                )
            )

            if level_up_detected:
                if amount > 0:
                    total_amount_gain += amount
                if percent > 0:
                    total_percent_gain += percent
            else:
                if amount_delta > 0:
                    total_amount_gain += amount_delta
                if percent_delta > POSITIVE_PERCENT_EPS:
                    total_percent_gain += percent_delta

            prev_amount = amount
            prev_percent = percent

        total_amount_gain = max(0, int(total_amount_gain))
        total_percent_gain = max(0.0, total_percent_gain)

        duration_start_ts = self._status_detection_start_ts
        if not duration_start_ts:
            duration_start_ts = start_entry.get('timestamp', time.time())
        duration = max(0.0, float(end_timestamp) - float(duration_start_ts))
        minutes = max(1.0 / 60.0, duration / 60.0)
        per_minute_amount = int(total_amount_gain / minutes) if minutes > 0 else total_amount_gain
        per_minute_percent_gain = total_percent_gain / minutes if minutes > 0 else total_percent_gain

        def _format_percent_value(value: float) -> str:
            text = f"{value:.2f}"
            if '.' in text:
                text = text.rstrip('0').rstrip('.')
            return text

        total_percent_text = _format_percent_value(total_percent_gain)
        per_minute_percent_text = _format_percent_value(per_minute_percent_gain)
        start_percent_text = _format_percent_value(start_percent)
        end_percent_text = _format_percent_value(end_percent)

        duration_text = self._format_duration_text(duration)
        self.append_log(
            (
                "사냥 종료 - 사냥시간: "
                f"{duration_text}, 분당 경험치: {per_minute_amount} / {per_minute_percent_text}%, "
                f"획득 경험치: {total_amount_gain} ({start_amount} > {end_amount}) / "
                f"{total_percent_text}% ({start_percent_text}% > {end_percent_text}%)"
            ),
            'info',
        )

    @staticmethod
    def _format_duration_text(seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours}시간 {minutes}분 {secs}초"

    def handle_detection_payload(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return

        handler_start = time.perf_counter()
        received_ts = time.time()
        payload_ts_raw = payload.get('timestamp', received_ts)
        try:
            payload_ts = float(payload_ts_raw)
        except (TypeError, ValueError):
            payload_ts = received_ts
        latency_ms = max(0.0, (received_ts - payload_ts) * 1000.0)
        collect_frame_stats = self._is_frame_summary_enabled()
        collect_detail_stats = self._is_frame_detail_enabled()
        if collect_detail_stats:
            self.latest_perf_stats['payload_latency_ms'] = latency_ms
        else:
            self.latest_perf_stats.pop('payload_latency_ms', None)

        characters_data = payload.get('characters') or []
        monsters_data = payload.get('monsters') or []
        nickname_data = payload.get('nickname')
        raw_nickname_search = payload.get('nickname_search')
        nameplate_data = payload.get('nameplates') or []
        track_events = payload.get('nameplate_track_events') or []
        perf_data = payload.get('perf') or {}

        self._expire_nameplate_dead_zones(received_ts)
        if track_events:
            self._handle_nameplate_track_events(track_events, received_ts)

        filtered_monster_entries: List[dict] = []
        visual_tracked_entries: List[dict] = []
        active_track_ids_snapshot = set(self._active_nameplate_track_ids)
        for entry in monsters_data:
            if not isinstance(entry, dict):
                continue
            source = str(entry.get('source') or 'yolo')
            if source == 'nameplate_track':
                track_id_raw = entry.get('track_id')
                track_id_int: Optional[int] = None
                if track_id_raw is not None:
                    try:
                        track_id_int = int(track_id_raw)
                    except (TypeError, ValueError):
                        track_id_int = None
                grace_active = bool(entry.get('grace_active'))
                nameplate_detected = bool(
                    entry.get('nameplate_confirmed')
                    or entry.get('nameplate_detected')
                )
                if track_id_int is not None:
                    entry['track_id'] = track_id_int
                keep = False
                if track_id_int is not None and track_id_int in active_track_ids_snapshot:
                    keep = True
                elif grace_active:
                    keep = True
                if not keep:
                    continue
                entry['yolo_missing'] = True
                entry['nameplate_detected'] = nameplate_detected
                filtered_monster_entries.append(entry)
                if self._nameplate_visual_debug_enabled:
                    visual_tracked_entries.append(
                        {
                            'x': float(entry.get('x', 0.0)),
                            'y': float(entry.get('y', 0.0)),
                            'width': float(entry.get('width', 0.0)),
                            'height': float(entry.get('height', 0.0)),
                            'nameplate_detected': bool(
                                track_id_int is not None and track_id_int in active_track_ids_snapshot
                            ),
                            'grace_active': grace_active,
                        }
                    )
                continue
            if self._monitored_by_dead_zone(entry):
                continue
            filtered_monster_entries.append(entry)
        monsters_data = filtered_monster_entries

        if self._nameplate_visual_debug_enabled:
            self._visual_tracked_monsters = visual_tracked_entries
            self._visual_dead_zones = [dict(zone.get('rect', {})) for zone in self._nameplate_dead_zones]
        else:
            self._visual_tracked_monsters = []
            self._visual_dead_zones = []

        if isinstance(perf_data, dict):
            base_keys = (
                'fps',
                'total_ms',
                'capture_ms',
                'yolo_ms',
                'nickname_ms',
                'nameplate_ms',
                'downscale_active',
                'scale_factor',
                'frame_width',
                'frame_height',
                'input_width',
                'input_height',
            )
            detail_keys = (
                'preprocess_ms',
                'direction_ms',
                'post_ms',
                'render_ms',
                'emit_ms',
            )

            if collect_frame_stats:
                for key in base_keys:
                    if key not in perf_data:
                        continue
                    try:
                        self.latest_perf_stats[key] = float(perf_data.get(key, self.latest_perf_stats.get(key, 0.0)))
                    except (TypeError, ValueError):
                        continue

                speed_keys = (
                    'yolo_speed_preprocess_ms',
                    'yolo_speed_inference_ms',
                    'yolo_speed_postprocess_ms',
                )
                for key in speed_keys:
                    if key not in perf_data:
                        continue
                    try:
                        self.latest_perf_stats[key] = float(
                            perf_data.get(key, self.latest_perf_stats.get(key, 0.0))
                        )
                    except (TypeError, ValueError):
                        continue

                if collect_detail_stats:
                    for key in detail_keys:
                        if key not in perf_data:
                            continue
                        try:
                            self.latest_perf_stats[key] = float(perf_data.get(key, self.latest_perf_stats.get(key, 0.0)))
                        except (TypeError, ValueError):
                            continue
                else:
                    for key in detail_keys:
                        self.latest_perf_stats.pop(key, None)
            else:
                for key in base_keys + detail_keys:
                    self.latest_perf_stats.pop(key, None)
        direction_data = payload.get('direction')

        def _to_box(data):
            try:
                return DetectionBox(
                    x=float(data.get('x', 0.0)),
                    y=float(data.get('y', 0.0)),
                    width=float(data.get('width', 0.0)),
                    height=float(data.get('height', 0.0)),
                    score=float(data.get('score', 0.0)),
                    label=str(data.get('class_name', '')),
                )
            except Exception:
                return None

        characters = [box for box in (_to_box(item) for item in characters_data) if box]
        monsters = [box for box in (_to_box(item) for item in monsters_data) if box]

        now = time.time()
        filtered_nameplate_details: List[dict] = []
        overlay_nameplates: List[dict] = []
        new_active_track_ids: set[int] = set()
        nameplate_confirmed = False
        fallback_used = False
        nickname_used = False
        nickname_record = None
        nickname_search_region: Optional[dict] = None

        if isinstance(raw_nickname_search, dict):
            try:
                nickname_search_region = {
                    'x': float(raw_nickname_search.get('x', 0.0)),
                    'y': float(raw_nickname_search.get('y', 0.0)),
                    'width': float(raw_nickname_search.get('width', 0.0)),
                    'height': float(raw_nickname_search.get('height', 0.0)),
                }
            except (TypeError, ValueError):
                nickname_search_region = None
            else:
                mode = raw_nickname_search.get('mode')
                if isinstance(mode, str):
                    nickname_search_region['mode'] = mode

        if isinstance(nickname_data, dict):
            char_box_info = nickname_data.get('character_box') or {}
            if char_box_info and char_box_info.get('width', 0) and char_box_info.get('height', 0):
                try:
                    nickname_box = DetectionBox(
                        x=float(char_box_info.get('x', 0.0)),
                        y=float(char_box_info.get('y', 0.0)),
                        width=float(char_box_info.get('width', 0.0)),
                        height=float(char_box_info.get('height', 0.0)),
                        score=float(nickname_data.get('score', 0.0)),
                        label='nickname',
                    )
                except Exception:
                    nickname_box = None
                if nickname_box is not None:
                    characters = [nickname_box]
                    characters_data = [{
                        'x': nickname_box.x,
                        'y': nickname_box.y,
                        'width': nickname_box.width,
                        'height': nickname_box.height,
                        'score': nickname_box.score,
                        'class_name': '닉네임',
                    }]
                    self._update_character_cache(characters, characters_data, seen_ts=now)
                    fallback_used = False
                    nickname_used = True
                    nickname_record = nickname_data
                    self._latest_nickname_box = nickname_data.get('nickname_box')
                else:
                    self._latest_nickname_box = None
            else:
                self._latest_nickname_box = None
        else:
            self._latest_nickname_box = None

        self._latest_nickname_search_region = nickname_search_region

        if not nickname_used:
            if characters:
                self._update_character_cache(characters, characters_data, seen_ts=now)
            else:
                if (
                    self._last_character_boxes
                    and now - self._last_character_seen_ts <= self.CHARACTER_PERSISTENCE_SEC
                ):
                    characters = [DetectionBox(**vars(box)) for box in self._last_character_boxes]
                    if not characters_data and self._last_character_details:
                        characters_data = [dict(item) for item in self._last_character_details]
                    fallback_used = True
                else:
                    self._reset_character_cache()

        rely_message: Optional[str] = None
        best_nameplate_entry: Optional[dict] = None

        if isinstance(nameplate_data, list) and nameplate_data:
            reference_character: Optional[DetectionBox] = None
            if characters:
                reference_character = self._select_reference_character_box(characters)
            elif self._last_character_boxes:
                reference_character = self._select_reference_character_box(self._last_character_boxes)
            primary_area: Optional[AreaRect] = None
            char_center_x: Optional[float] = None
            if reference_character is not None:
                hunt_area_tmp = self._compute_hunt_area_rect(reference_character)
                primary_area = self._compute_primary_skill_rect(reference_character, hunt_area_tmp)
                char_center_x = reference_character.center_x
            facing = self.last_facing if self.last_facing in ('left', 'right') else None
            for entry in nameplate_data:
                if not isinstance(entry, dict):
                    continue
                roi_dict = entry.get('roi')
                if not isinstance(roi_dict, dict):
                    continue
                try:
                    left = float(roi_dict.get('x', 0.0))
                    top = float(roi_dict.get('y', 0.0))
                    width = float(roi_dict.get('width', 0.0))
                    height = float(roi_dict.get('height', 0.0))
                except (TypeError, ValueError):
                    continue
                if width <= 0 or height <= 0:
                    continue

                source_box = entry.get('source_box')
                box_center_x: Optional[float] = None
                box_center_y: Optional[float] = None
                if isinstance(source_box, dict):
                    try:
                        box_x = float(source_box.get('x', 0.0))
                        box_y = float(source_box.get('y', 0.0))
                        box_w = float(source_box.get('width', 0.0))
                        box_h = float(source_box.get('height', 0.0))
                    except (TypeError, ValueError):
                        box_w = box_h = 0.0
                    else:
                        if box_w > 0 and box_h > 0:
                            box_center_x = box_x + box_w / 2.0
                            box_center_y = box_y + box_h / 2.0

                if box_center_x is None or box_center_y is None:
                    box_center_x = left + width / 2.0
                    box_center_y = top + height / 2.0

                passes_area = True
                if primary_area is not None:
                    if not (
                        primary_area.x <= box_center_x <= primary_area.right
                        and primary_area.y <= box_center_y <= primary_area.bottom
                    ):
                        passes_area = False
                passes_direction = True
                if facing and char_center_x is not None:
                    if facing == 'left' and box_center_x > char_center_x:
                        passes_direction = False
                    elif facing == 'right' and box_center_x < char_center_x:
                        passes_direction = False
                matched = bool(entry.get('matched'))
                overlay_entry: dict = {
                    'roi': {
                        'x': left,
                        'y': top,
                        'width': width,
                        'height': height,
                    },
                    'matched': matched,
                    'score': float(entry.get('score', 0.0)),
                    'threshold': float(entry.get('threshold', 0.0)),
                }
                if passes_area and passes_direction:
                    filtered_entry = dict(entry)
                    filtered_entry['passes_filters'] = True
                    track_id_raw = filtered_entry.get('track_id')
                    track_id_int: Optional[int] = None
                    if track_id_raw is not None:
                        try:
                            track_id_int = int(track_id_raw)
                        except (TypeError, ValueError):
                            track_id_int = None
                    if track_id_int is not None:
                        filtered_entry['track_id'] = track_id_int
                    filtered_nameplate_details.append(filtered_entry)
                    if matched:
                        nameplate_confirmed = True
                        if (
                            best_nameplate_entry is None
                            or float(filtered_entry.get('score', 0.0)) > float(best_nameplate_entry.get('score', 0.0))
                        ):
                            best_nameplate_entry = filtered_entry
                        if track_id_int is not None:
                            new_active_track_ids.add(track_id_int)
                            overlay_entry['track_id'] = track_id_int
                    match_rect_info = filtered_entry.get('match_rect')
                    if isinstance(match_rect_info, dict):
                        overlay_entry['match_rect'] = match_rect_info
                    if self._is_nameplate_overlay_active():
                        overlay_nameplates.append(overlay_entry)
        else:
            overlay_nameplates = []
            new_active_track_ids.clear()

        snapshot_ts = float(payload.get('timestamp', now))
        if fallback_used and self._last_character_seen_ts:
            snapshot_ts = max(snapshot_ts, self._last_character_seen_ts)

        snapshot = DetectionSnapshot(
            character_boxes=characters,
            monster_boxes=monsters,
            timestamp=snapshot_ts,
        )
        direction_record = direction_data if isinstance(direction_data, dict) else None
        self.latest_detection_details = {
            'characters': characters_data if characters_data else [],
            'monsters': monsters_data,
            'nickname': nickname_record,
            'nickname_search': nickname_search_region,
            'direction': direction_record,
            'nameplates': filtered_nameplate_details,
        }
        self._active_nameplate_track_ids = new_active_track_ids
        if self._is_nameplate_overlay_active():
            self._latest_nameplate_rois = overlay_nameplates
        else:
            self._latest_nameplate_rois = []
        self._nameplate_hold_until = 0.0

        if best_nameplate_entry is not None:
            class_name = str(best_nameplate_entry.get('class_name') or '이름표')
            score_val = float(best_nameplate_entry.get('score', 0.0))
            if not (self.latest_snapshot and self.latest_snapshot.monster_boxes):
                rely_message = f"이름표 기반 몬스터 유지: {class_name} (점수 {score_val:.2f})"

        if fallback_used and not characters_data and self._last_character_details:
            self.latest_detection_details['characters'] = [dict(item) for item in self._last_character_details]
        if nickname_used:
            self._last_nickname_match = nickname_data
        elif not fallback_used:
            self._last_nickname_match = None
        if fallback_used and not nickname_used and self._last_nickname_match:
            self.latest_detection_details['nickname'] = self._last_nickname_match
            if not self._latest_nickname_box:
                self._latest_nickname_box = self._last_nickname_match.get('nickname_box')
        if not nickname_used and not fallback_used:
            if self._last_nickname_match is None:
                self.latest_detection_details['nickname'] = None
            self._latest_nickname_box = None
        self._using_character_fallback = fallback_used
        if nickname_used:
            self._last_nickname_match = nickname_record
        elif not fallback_used and nickname_record is None:
            self._last_nickname_match = None

        if isinstance(direction_record, dict):
            roi_rect = direction_record.get('roi_rect')
            self._latest_direction_roi = dict(roi_rect) if isinstance(roi_rect, dict) else None
            match_rect = direction_record.get('match_rect')
            self._latest_direction_match = dict(match_rect) if isinstance(match_rect, dict) else None
            if direction_record.get('matched') and direction_record.get('side') in ('left', 'right'):
                self._apply_detected_direction(direction_record.get('side'), float(direction_record.get('score', 0.0)))
            else:
                # 유지하되 최신 탐지 갱신은 하지 않음
                pass
        else:
            self._latest_direction_roi = None
            self._latest_direction_match = None

        self._evaluate_direction_timeout()

        self.update_detection_snapshot(snapshot)

        if rely_message and (now - self._last_nameplate_notify_ts) > 0.5:
            self.append_log(rely_message, 'info')
            self._last_nameplate_notify_ts = now

        handler_elapsed_ms = (time.perf_counter() - handler_start) * 1000.0
        if collect_detail_stats:
            self.latest_perf_stats['handler_ms'] = handler_elapsed_ms
        else:
            self.latest_perf_stats.pop('handler_ms', None)

        warn_messages: List[str] = []
        total_ms = float(self.latest_perf_stats.get('total_ms', 0.0)) if collect_frame_stats else 0.0
        if collect_frame_stats and total_ms > 70.0:
            warn_messages.append(f"total {total_ms:.1f}ms")
        if collect_detail_stats:
            latency_val = float(self.latest_perf_stats.get('payload_latency_ms', latency_ms))
            if latency_val > 120.0:
                warn_messages.append(f"latency {latency_val:.1f}ms")
            if handler_elapsed_ms > 25.0:
                warn_messages.append(f"handler {handler_elapsed_ms:.1f}ms")
        if warn_messages and (time.time() - self._perf_warn_last_ts) >= self._perf_warn_min_interval:
            self.append_log("성능 경고: " + ", ".join(warn_messages), "warn")
            self._perf_warn_last_ts = time.time()

        warning_text = ", ".join(warn_messages)
        self._append_perf_log(warning_text)

        self._update_detection_summary()
        self._schedule_condition_poll()

    def _update_character_cache(
        self,
        characters: List[DetectionBox],
        details: List[dict],
        *,
        seen_ts: Optional[float] = None,
    ) -> None:
        self._last_character_boxes = [DetectionBox(**vars(box)) for box in characters]
        self._last_character_details = [dict(item) for item in details] if details else []
        self._last_character_seen_ts = float(seen_ts) if seen_ts is not None else time.time()
        self._using_character_fallback = False

    def _reset_character_cache(self) -> None:
        self._last_character_boxes = []
        self._last_character_details = []
        self._last_character_seen_ts = 0.0
        self._using_character_fallback = False

    def update_detection_snapshot(self, snapshot: DetectionSnapshot) -> None:
        self.latest_snapshot = snapshot
        self._recalculate_hunt_metrics()

    def clear_detection_snapshot(self) -> None:
        self.latest_snapshot = None
        self._clear_detection_metrics()
        self.latest_detection_details = {'characters': [], 'monsters': [], 'nickname': None, 'direction': None, 'nameplates': []}
        self._reset_character_cache()
        self._direction_active = False
        self._direction_last_side = None
        self._direction_last_seen_ts = 0.0
        self._last_direction_score = None
        self._latest_nameplate_rois = []
        self._active_nameplate_track_ids = set()
        self._nameplate_hold_until = 0.0
        self._update_detection_summary()

    def _recalculate_hunt_metrics(self) -> None:
        if not self.latest_snapshot or not self.latest_snapshot.character_boxes:
            self._clear_detection_metrics()
            return

        character_box = self._select_reference_character_box(self.latest_snapshot.character_boxes)
        hunt_area = self._compute_hunt_area_rect(character_box)
        primary_area = self._compute_primary_skill_rect(character_box, hunt_area)

        self.current_hunt_area = hunt_area
        self.current_primary_area = primary_area

        now = time.time()
        raw_monsters = self.latest_snapshot.monster_boxes or []
        nameplate_active = now <= self._nameplate_hold_until

        if raw_monsters:
            effective_monsters = raw_monsters
            self._cached_monster_boxes = [DetectionBox(**vars(box)) for box in raw_monsters]
            self._cached_monster_boxes_ts = now
        else:
            grace_active = now - self._cached_monster_boxes_ts <= MONSTER_LOSS_GRACE_SEC
            if nameplate_active:
                effective_monsters = [DetectionBox(**vars(box)) for box in self._cached_monster_boxes]
            elif grace_active and self._cached_monster_boxes:
                effective_monsters = [DetectionBox(**vars(box)) for box in self._cached_monster_boxes]
            else:
                effective_monsters = []
                self._cached_monster_boxes = []
                self._cached_monster_boxes_ts = 0.0
                if now > self._nameplate_hold_until:
                    self._nameplate_hold_until = 0.0

        hunt_count = sum(1 for box in effective_monsters if box.intersects(hunt_area))
        primary_count = sum(
            1 for box in effective_monsters if primary_area and box.intersects(primary_area)
        )

        self.latest_monster_count = hunt_count
        self.latest_primary_monster_count = primary_count

        hunt_threshold_widget = getattr(self, 'hunt_monster_threshold_spinbox', None)
        primary_threshold_widget = getattr(self, 'primary_monster_threshold_spinbox', None)
        hunt_threshold = hunt_threshold_widget.value() if hunt_threshold_widget else 1
        primary_threshold = primary_threshold_widget.value() if primary_threshold_widget else 1

        primary_ready = primary_threshold <= 0 or primary_count >= primary_threshold
        hunt_ready = hunt_threshold <= 0 or self.latest_monster_count >= hunt_threshold

        if primary_ready or hunt_ready:
            self._last_monster_seen_ts = time.time()

        self._update_monster_count_label()
        self._emit_area_overlays()
        self.monster_stats_updated.emit(hunt_count, primary_count)

    def _clear_detection_metrics(self) -> None:
        self.current_hunt_area = None
        self.current_primary_area = None
        self.latest_monster_count = 0
        self.latest_primary_monster_count = 0
        self._cached_monster_boxes = []
        self._cached_monster_boxes_ts = 0.0
        self._latest_nickname_box = None
        self._latest_direction_roi = None
        self._latest_direction_match = None
        self._latest_nameplate_rois = []
        self._active_nameplate_track_ids = set()
        self._nameplate_hold_until = 0.0
        self._update_monster_count_label()
        self._emit_area_overlays()
        self.monster_stats_updated.emit(0, 0)

    def _get_recent_monster_boxes(self) -> List[DetectionBox]:
        if self.latest_snapshot and self.latest_snapshot.monster_boxes:
            return self.latest_snapshot.monster_boxes
        now = time.time()
        if (
            self._cached_monster_boxes
            and (
                now - self._cached_monster_boxes_ts <= MONSTER_LOSS_GRACE_SEC
                or now <= self._nameplate_hold_until
            )
        ):
            return [DetectionBox(**vars(box)) for box in self._cached_monster_boxes]
        if now > self._nameplate_hold_until:
            self._nameplate_hold_until = 0.0
        return []

    def _expire_nameplate_dead_zones(self, now: float) -> None:
        if not self._nameplate_dead_zones:
            return
        self._nameplate_dead_zones = [
            zone for zone in self._nameplate_dead_zones if float(zone.get('expires_at', 0.0)) > now
        ]

    def _handle_nameplate_track_events(self, events: List[dict], now: float) -> None:
        if not events:
            return
        for entry in events:
            if not isinstance(entry, dict):
                continue
            event_type = str(entry.get('event') or '').lower()
            center_info = entry.get('center') or {}
            try:
                center_x = float(center_info.get('x', 0.0))
                center_y = float(center_info.get('y', 0.0))
            except (TypeError, ValueError):
                continue
            if event_type == 'ended':
                box_info = entry.get('box') if isinstance(entry.get('box'), dict) else None
                rect = self._build_dead_zone_rect(center_x, center_y, box_info)
                expires_at = now + max(0.0, float(self._nameplate_dead_zone_duration_sec))
                zone = {
                    'center': (center_x, center_y),
                    'rect': rect,
                    'expires_at': expires_at,
                    'class_id': entry.get('class_id'),
                    'class_name': entry.get('class_name'),
                }
                self._nameplate_dead_zones.append(zone)
            elif event_type == 'started':
                self._remove_dead_zones_near(center_x, center_y)

    def _remove_dead_zones_near(self, center_x: float, center_y: float) -> None:
        if not self._nameplate_dead_zones:
            return
        remaining: List[dict] = []
        for zone in self._nameplate_dead_zones:
            rect = zone.get('rect')
            if not self._point_in_rect(center_x, center_y, rect):
                remaining.append(zone)
        self._nameplate_dead_zones = remaining

    @staticmethod
    def _point_in_rect(x: float, y: float, rect: Optional[dict]) -> bool:
        if not isinstance(rect, dict):
            return False
        try:
            left = float(rect.get('x', 0.0))
            top = float(rect.get('y', 0.0))
            width = float(rect.get('width', 0.0))
            height = float(rect.get('height', 0.0))
        except (TypeError, ValueError):
            return False
        if width <= 0 or height <= 0:
            return False
        right = left + width
        bottom = top + height
        return left <= x <= right and top <= y <= bottom

    def _build_dead_zone_rect(self, center_x: float, center_y: float, box: Optional[dict]) -> dict:
        if isinstance(box, dict):
            try:
                x = float(box.get('x', center_x))
                y = float(box.get('y', center_y))
                width = float(box.get('width', 0.0))
                height = float(box.get('height', 0.0))
            except (TypeError, ValueError):
                width = height = 0.0
            else:
                if width > 0 and height > 0:
                    margin = 12.0
                    return {
                        'x': float(x - margin),
                        'y': float(y - margin),
                        'width': float(width + margin * 2.0),
                        'height': float(height + margin * 2.0),
                    }
        half = NAMEPLATE_DEADZONE_SIZE / 2.0
        return {
            'x': float(center_x - half),
            'y': float(center_y - half),
            'width': float(NAMEPLATE_DEADZONE_SIZE),
            'height': float(NAMEPLATE_DEADZONE_SIZE),
        }

    def _monitored_by_dead_zone(self, entry: dict) -> bool:
        if not self._nameplate_dead_zones:
            return False
        try:
            x = float(entry.get('x', 0.0))
            y = float(entry.get('y', 0.0))
            width = float(entry.get('width', 0.0))
            height = float(entry.get('height', 0.0))
        except (TypeError, ValueError):
            return False
        if width <= 0 or height <= 0:
            return False
        det_rect = {
            'x': x,
            'y': y,
            'width': width,
            'height': height,
        }
        for zone in self._nameplate_dead_zones:
            zone_rect = zone.get('rect')
            if self._rects_intersect(det_rect, zone_rect):
                return True
        return False

    @staticmethod
    def _rects_intersect(rect_a: Optional[dict], rect_b: Optional[dict]) -> bool:
        if not isinstance(rect_a, dict) or not isinstance(rect_b, dict):
            return False
        try:
            ax = float(rect_a.get('x', 0.0))
            ay = float(rect_a.get('y', 0.0))
            aw = float(rect_a.get('width', 0.0))
            ah = float(rect_a.get('height', 0.0))
            bx = float(rect_b.get('x', 0.0))
            by = float(rect_b.get('y', 0.0))
            bw = float(rect_b.get('width', 0.0))
            bh = float(rect_b.get('height', 0.0))
        except (TypeError, ValueError):
            return False
        if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
            return False
        aright = ax + aw
        abottom = ay + ah
        bright = bx + bw
        bbottom = by + bh
        if aright <= bx or bright <= ax:
            return False
        if abottom <= by or bbottom <= ay:
            return False
        return True

    def _apply_detected_direction(self, side: str, score: float) -> None:
        if side not in ('left', 'right'):
            return
        self._direction_active = True
        self._direction_last_seen_ts = time.time()
        self._direction_last_side = side
        self._last_direction_score = float(score)
        self._cancel_facing_reset_timer()
        self._set_current_facing(side, save=False, from_direction=True)
        self._maybe_complete_direction_confirmation()

    def _evaluate_direction_timeout(self) -> None:
        if not self._direction_active:
            return
        if time.time() - self._direction_last_seen_ts > self.DIRECTION_TIMEOUT_SEC:
            self._direction_active = False
            self._direction_last_side = None
            self._last_direction_score = None
            if self._is_detection_active():
                self._schedule_facing_reset()

    def _select_reference_character_box(self, boxes: List[DetectionBox]) -> DetectionBox:
        return max(boxes, key=lambda box: box.score)

    def _compute_hunt_area_rect(self, character_box: DetectionBox) -> AreaRect:
        radius_x = float(self.enemy_range_spinbox.value())
        width = max(1.0, radius_x * 2.0)
        height = max(1.0, float(self.y_band_height_spinbox.value()))
        offset = float(self.y_band_offset_spinbox.value())
        base_y = character_box.bottom
        top = base_y - height + offset
        return AreaRect(x=character_box.center_x - radius_x, y=top, width=width, height=height)

    def _compute_primary_skill_rect(self, character_box: DetectionBox, hunt_area: AreaRect) -> Optional[AreaRect]:
        radius = float(self.primary_skill_range_spinbox.value())
        if radius <= 0:
            return None
        width = max(1.0, radius * 2.0)
        return AreaRect(x=character_box.center_x - radius, y=hunt_area.y, width=width, height=hunt_area.height)

    def _update_monster_count_label(self) -> None:
        self._update_detection_summary()

    def _update_facing_label(self) -> None:
        self._update_detection_summary()

    def _format_facing_text(self) -> str:
        if self.last_facing == 'left':
            base = "왼쪽"
        if self.last_facing == 'right':
            base = "오른쪽"
        else:
            return "미정"
        if self._last_direction_score is not None:
            return f"{base} ({self._last_direction_score:.2f})"
        return base

    def _set_current_facing(self, side: Optional[str], *, save: bool = True, from_direction: bool = False) -> None:
        if side not in ('left', 'right'):
            self.last_facing = None
        else:
            self.last_facing = side
        if not from_direction:
            self._last_direction_score = None
        self._update_facing_label()
        if side in ('left', 'right') and not from_direction and not getattr(self, '_direction_active', False):
            self._schedule_facing_reset()
        self._sync_detection_thread_status()
        if save and not from_direction:
            self._save_settings()

    def _setup_timers(self) -> None:
        self.condition_timer = QTimer(self)
        self.condition_timer.setInterval(2000)
        self.condition_timer.timeout.connect(self._poll_hunt_conditions)
        self.condition_timer.start()

        self.hunt_loop_timer = QTimer(self)
        self.hunt_loop_timer.setInterval(300)
        self.hunt_loop_timer.timeout.connect(self._run_hunt_loop)
        self.hunt_loop_timer.start()

        self._condition_debounce_timer = QTimer(self)
        self._condition_debounce_timer.setSingleShot(True)
        self._condition_debounce_timer.timeout.connect(self._on_condition_debounce_timeout)

        self._request_timeout_timer = QTimer(self)
        self._request_timeout_timer.setSingleShot(True)
        self._request_timeout_timer.timeout.connect(self._handle_request_timeout)

    def _load_nickname_configuration(self) -> None:
        if not self.data_manager or not hasattr(self.data_manager, 'get_nickname_config'):
            self._nickname_config = {}
            self._nickname_templates = []
            self._latest_nickname_box = None
            return
        try:
            self._nickname_config = self.data_manager.get_nickname_config()
            templates = self.data_manager.list_nickname_templates()
            self._nickname_templates = templates if isinstance(templates, list) else []
            self._show_nickname_overlay_config = bool(self._nickname_config.get('show_overlay', True))
        except Exception as exc:  # pragma: no cover - 안전장치
            self._nickname_config = {}
            self._nickname_templates = []
            self.append_log(f"닉네임 설정을 불러오지 못했습니다: {exc}", "warn")
        if not self._nickname_templates:
            self._latest_nickname_box = None

        self._apply_nickname_threshold_to_char_conf()
        self._update_detection_thread_overlay_flags()

    def _load_direction_configuration(self) -> None:
        if not self.data_manager or not hasattr(self.data_manager, 'get_direction_config'):
            self._direction_config = {}
            self._direction_templates = {'left': [], 'right': []}
            checkbox = getattr(self, 'show_direction_checkbox', None)
            if checkbox is not None:
                checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.setEnabled(False)
                checkbox.blockSignals(False)
            self.overlay_preferences['direction_area'] = False
            return
        try:
            self._direction_config = self.data_manager.get_direction_config()
            left_templates = self.data_manager.list_direction_templates('left')
            right_templates = self.data_manager.list_direction_templates('right')
            self._direction_templates = {
                'left': left_templates if isinstance(left_templates, list) else [],
                'right': right_templates if isinstance(right_templates, list) else [],
            }
            self._show_direction_overlay_config = bool(self._direction_config.get('show_overlay', True))
        except Exception as exc:
            self._direction_config = {}
            self._direction_templates = {'left': [], 'right': []}
            self.append_log(f"방향 설정을 불러오지 못했습니다: {exc}", "warn")
        checkbox = getattr(self, 'show_direction_checkbox', None)
        if checkbox is not None:
            checkbox.blockSignals(True)
            if not self._show_direction_overlay_config:
                self._direction_area_user_pref = self.overlay_preferences.get('direction_area', True)
                self.overlay_preferences['direction_area'] = False
                checkbox.setChecked(False)
                checkbox.setEnabled(False)
            else:
                if not checkbox.isEnabled():
                    checkbox.setEnabled(True)
                restored_state = self._direction_area_user_pref if isinstance(self._direction_area_user_pref, bool) else True
                self.overlay_preferences['direction_area'] = restored_state
                checkbox.setChecked(restored_state)
            checkbox.blockSignals(False)
        self._update_detection_thread_overlay_flags()

    def _load_nameplate_configuration(self) -> None:
        if not self.data_manager or not hasattr(self.data_manager, 'get_monster_nameplate_resources'):
            self._nameplate_config = {}
            self._nameplate_templates = {}
            self._nameplate_enabled = False
            self._latest_nameplate_rois = []
            return
        try:
            config, templates = self.data_manager.get_monster_nameplate_resources()
        except Exception as exc:
            self._nameplate_config = {}
            self._nameplate_templates = {}
            self._nameplate_enabled = False
            self._latest_nameplate_rois = []
            self.append_log(f"이름표 설정을 불러오지 못했습니다: {exc}", "warn")
            return
        self._nameplate_config = config or {}
        self._nameplate_templates = templates if isinstance(templates, dict) else {}
        self._show_nameplate_overlay_config = bool(self._nameplate_config.get('show_overlay', True))
        self._nameplate_enabled = bool(self._nameplate_config.get('enabled', False) and self._nameplate_templates)
        try:
            dead_zone_value = float(self._nameplate_config.get('dead_zone_sec', 0.2))
        except (TypeError, ValueError):
            dead_zone_value = 0.2
        try:
            track_grace_value = float(self._nameplate_config.get('track_missing_grace_sec', 0.12))
        except (TypeError, ValueError):
            track_grace_value = 0.12
        try:
            track_hold_value = float(self._nameplate_config.get('track_max_hold_sec', 2.0))
        except (TypeError, ValueError):
            track_hold_value = 2.0
        self._nameplate_dead_zone_duration_sec = max(0.0, min(2.0, dead_zone_value))
        self._nameplate_track_missing_grace_sec = max(0.0, min(2.0, track_grace_value))
        self._nameplate_track_max_hold_sec = max(0.0, min(5.0, track_hold_value))
        if not self._nameplate_enabled:
            self._nameplate_dead_zones = []
            self._visual_dead_zones = []
            self._visual_tracked_monsters = []
            self._active_nameplate_track_ids = set()
        checkbox = getattr(self, 'show_nameplate_checkbox', None)
        if checkbox is not None:
            checkbox.blockSignals(True)
            if not self._show_nameplate_overlay_config:
                self._nameplate_area_user_pref = self.overlay_preferences.get('nameplate_area', True)
                self.overlay_preferences['nameplate_area'] = False
                checkbox.setChecked(False)
                checkbox.setEnabled(False)
            else:
                if not checkbox.isEnabled():
                    checkbox.setEnabled(True)
                restored_state = self._nameplate_area_user_pref if isinstance(self._nameplate_area_user_pref, bool) else True
                self.overlay_preferences['nameplate_area'] = restored_state
                checkbox.setChecked(restored_state)
            checkbox.blockSignals(False)
        tracking_checkbox = getattr(self, 'show_nameplate_tracking_checkbox', None)
        if tracking_checkbox is not None:
            tracking_checkbox.blockSignals(True)
            if not self._nameplate_enabled:
                self._nameplate_tracking_user_pref = self.overlay_preferences.get('nameplate_tracking', False)
                self.overlay_preferences['nameplate_tracking'] = False
                self._nameplate_visual_debug_enabled = False
                tracking_checkbox.setChecked(False)
                tracking_checkbox.setEnabled(False)
            else:
                tracking_checkbox.setEnabled(True)
                restored_tracking = self.overlay_preferences.get(
                    'nameplate_tracking', self._nameplate_tracking_user_pref
                )
                tracking_checkbox.setChecked(bool(restored_tracking))
                self.overlay_preferences['nameplate_tracking'] = bool(restored_tracking)
                self._nameplate_visual_debug_enabled = bool(restored_tracking)
            tracking_checkbox.blockSignals(False)
        self._update_detection_thread_overlay_flags()

    def _handle_overlay_config_update(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        target = payload.get('target')
        show_overlay = bool(payload.get('show_overlay', True))
        if 'dead_zone_sec' in payload:
            try:
                dz_value = float(payload.get('dead_zone_sec', self._nameplate_dead_zone_duration_sec))
            except (TypeError, ValueError):
                dz_value = self._nameplate_dead_zone_duration_sec
            self._nameplate_dead_zone_duration_sec = max(0.0, min(2.0, dz_value))
        if 'track_missing_grace_sec' in payload:
            try:
                grace_value = float(payload.get('track_missing_grace_sec', self._nameplate_track_missing_grace_sec))
            except (TypeError, ValueError):
                grace_value = self._nameplate_track_missing_grace_sec
            self._nameplate_track_missing_grace_sec = max(0.0, min(2.0, grace_value))
        if 'track_max_hold_sec' in payload:
            try:
                hold_value = float(payload.get('track_max_hold_sec', self._nameplate_track_max_hold_sec))
            except (TypeError, ValueError):
                hold_value = self._nameplate_track_max_hold_sec
            self._nameplate_track_max_hold_sec = max(0.0, min(5.0, hold_value))
        if target == 'nickname':
            self._show_nickname_overlay_config = show_overlay
            if not show_overlay:
                self._nickname_range_user_pref = self.overlay_preferences.get('nickname_range', True)
                self.overlay_preferences['nickname_range'] = False
            else:
                restored_range = self._nickname_range_user_pref if isinstance(self._nickname_range_user_pref, bool) else True
                self.overlay_preferences['nickname_range'] = restored_range
            checkbox = getattr(self, 'show_nickname_range_checkbox', None)
            if checkbox is not None:
                previous = checkbox.blockSignals(True)
                if show_overlay:
                    checkbox.setChecked(self.overlay_preferences.get('nickname_range', True))
                    checkbox.setEnabled(True)
                else:
                    checkbox.setChecked(False)
                    checkbox.setEnabled(False)
                checkbox.blockSignals(previous)
            if not show_overlay:
                self._latest_nickname_box = None
                self._latest_nickname_search_region = None
        elif target == 'direction':
            if not show_overlay:
                self._direction_area_user_pref = self.overlay_preferences.get('direction_area', True)
                self.overlay_preferences['direction_area'] = False
            else:
                restored_state = self._direction_area_user_pref if isinstance(self._direction_area_user_pref, bool) else True
                self.overlay_preferences['direction_area'] = restored_state
            self._show_direction_overlay_config = show_overlay
            checkbox = getattr(self, 'show_direction_checkbox', None)
            if checkbox is not None:
                previous = checkbox.blockSignals(True)
                if show_overlay:
                    checkbox.setChecked(self.overlay_preferences.get('direction_area', True))
                    checkbox.setEnabled(True)
                else:
                    checkbox.setChecked(False)
                    checkbox.setEnabled(False)
                checkbox.blockSignals(previous)
            if not show_overlay:
                self._latest_direction_roi = None
                self._latest_direction_match = None
        elif target == 'monster_nameplate':
            if not show_overlay:
                self._nameplate_area_user_pref = self.overlay_preferences.get('nameplate_area', True)
                self.overlay_preferences['nameplate_area'] = False
            else:
                restored = self._nameplate_area_user_pref if isinstance(self._nameplate_area_user_pref, bool) else True
                self.overlay_preferences['nameplate_area'] = restored
            self._show_nameplate_overlay_config = show_overlay
            checkbox = getattr(self, 'show_nameplate_checkbox', None)
            if checkbox is not None:
                previous = checkbox.blockSignals(True)
                if show_overlay:
                    checkbox.setChecked(self.overlay_preferences.get('nameplate_area', True))
                    checkbox.setEnabled(True)
                else:
                    checkbox.setChecked(False)
                    checkbox.setEnabled(False)
                checkbox.blockSignals(previous)
            if not show_overlay:
                self._latest_nameplate_rois = []
        else:
            return
        self._update_detection_thread_overlay_flags()
        self._update_detection_summary()
        self._emit_area_overlays()

    def _build_thread_nickname_detector(self) -> Optional[NicknameDetector]:
        if not self._nickname_templates:
            return None
        config = self._nickname_config or {}
        try:
            detector = NicknameDetector(
                target_text=config.get('target_text', ''),
                match_threshold=float(config.get('match_threshold', 0.72)),
                offset_x=float(config.get('char_offset_x', 0.0)),
                offset_y=float(config.get('char_offset_y', 0.0)),
                search_margin_x=float(config.get('search_margin_x', config.get('search_margin', NicknameDetector.DEFAULT_MARGIN_X))),
                search_margin_top=float(config.get('search_margin_top', config.get('search_margin_vertical', NicknameDetector.DEFAULT_MARGIN_TOP))),
                search_margin_bottom=float(config.get('search_margin_bottom', config.get('search_margin_vertical', NicknameDetector.DEFAULT_MARGIN_BOTTOM))),
                full_scan_delay_sec=float(config.get('full_scan_delay_sec', 0.0)),
            )
            detector.load_templates(self._nickname_templates)
            return detector
        except Exception as exc:
            self.append_log(f"닉네임 탐지기를 초기화하지 못했습니다: {exc}", "warn")
            return None

    def _build_thread_direction_detector(self) -> Optional[DirectionDetector]:
        left_templates = self._direction_templates.get('left', [])
        right_templates = self._direction_templates.get('right', [])
        if not left_templates and not right_templates:
            return None
        config = self._direction_config or {}
        try:
            detector = DirectionDetector(
                match_threshold=float(config.get('match_threshold', 0.72)),
                search_offset_y=float(config.get('search_offset_y', 60.0)),
                search_height=float(config.get('search_height', 20.0)),
                search_half_width=float(config.get('search_half_width', 30.0)),
            )
            detector.load_templates(left_templates, right_templates)
            return detector
        except Exception as exc:
            self.append_log(f"방향 탐지기를 초기화하지 못했습니다: {exc}", "warn")
            return None

    def attach_data_manager(self, data_manager) -> None:
        self.data_manager = data_manager
        if hasattr(self.data_manager, 'register_overlay_listener'):
            try:
                self.data_manager.register_overlay_listener(self._handle_overlay_config_update)
            except Exception:
                pass
        if hasattr(self.data_manager, 'register_model_listener') and not self._model_listener_registered:
            try:
                self.data_manager.register_model_listener(self._handle_model_changed)
                self._model_listener_registered = True
            except Exception:
                self._model_listener_registered = False
        self.last_used_model = self._get_active_model_name()
        if self.last_used_model:
            self.append_log(f"학습 탭 모델 연동: '{self.last_used_model}'", "info")
        self.append_log("학습 데이터 연동 완료", "info")
        self._save_settings()
        self._load_nickname_configuration()
        self._load_direction_configuration()
        self._load_nameplate_configuration()
        if hasattr(self.data_manager, 'register_status_config_listener'):
            try:
                self.data_manager.register_status_config_listener(self._handle_status_config_update)
            except Exception:
                pass
        if hasattr(self.data_manager, 'load_status_monitor_config'):
            try:
                self._status_config = self.data_manager.load_status_monitor_config()
            except Exception:
                self._status_config = StatusMonitorConfig.default()

    def attach_status_monitor(self, monitor: StatusMonitorThread) -> None:
        self.status_monitor = monitor
        monitor.status_captured.connect(self._handle_status_snapshot)
        monitor.ocr_unavailable.connect(self._handle_status_ocr_unavailable)
        if hasattr(monitor, 'exp_status_logged'):
            monitor.exp_status_logged.connect(self._handle_exp_status_log)

    def attach_map_tab(self, map_tab) -> None:
        self.map_tab = map_tab
        if hasattr(map_tab, 'detection_status_changed'):
            try:
                map_tab.detection_status_changed.connect(self._handle_map_detection_status_changed)
            except Exception:
                pass

    def set_authority_bridge_active(self, request_connected: bool, release_connected: bool) -> None:
        self._authority_request_connected = bool(request_connected)
        self._authority_release_connected = bool(release_connected)

    def _load_settings(self) -> None:
        self._suppress_settings_save = True
        self._suppress_downscale_prompt = True
        data = {}
        try:
            with open(self._settings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}
        except json.JSONDecodeError as exc:
            self.append_log(f"사냥 설정 파일 파싱 실패: {exc}", "warn")
            data = {}

        ranges = data.get('ranges', {})
        if ranges:
            self.enemy_range_spinbox.setValue(int(ranges.get('enemy_range', self.enemy_range_spinbox.value())))
            self.y_band_height_spinbox.setValue(int(ranges.get('y_band_height', self.y_band_height_spinbox.value())))
            self.y_band_offset_spinbox.setValue(int(ranges.get('y_band_offset', self.y_band_offset_spinbox.value())))
            self.primary_skill_range_spinbox.setValue(int(ranges.get('primary_range', self.primary_skill_range_spinbox.value())))

        confidence = data.get('confidence', {})
        if confidence:
            self.conf_char_spinbox.setValue(float(confidence.get('char', self.conf_char_spinbox.value())))
            self.conf_monster_spinbox.setValue(float(confidence.get('monster', self.conf_monster_spinbox.value())))

        conditions = data.get('conditions', {})
        if conditions:
            hunt_threshold_val = conditions.get('hunt_monster_threshold')
            primary_threshold_val = conditions.get('primary_monster_threshold')
            legacy_threshold_val = conditions.get('monster_threshold')

            if hunt_threshold_val is None:
                hunt_threshold_val = legacy_threshold_val
            if primary_threshold_val is None:
                primary_threshold_val = legacy_threshold_val

            try:
                if hunt_threshold_val is not None:
                    self.hunt_monster_threshold_spinbox.setValue(int(hunt_threshold_val))
            except (TypeError, ValueError):
                pass

            try:
                if primary_threshold_val is not None:
                    self.primary_monster_threshold_spinbox.setValue(int(primary_threshold_val))
            except (TypeError, ValueError):
                pass

            self.auto_request_checkbox.setChecked(bool(conditions.get('auto_request', self.auto_request_checkbox.isChecked())))
            idle_value = conditions.get('idle_release_sec')
            if idle_value is not None:
                try:
                    self.idle_release_spinbox.setValue(float(idle_value))
                except (TypeError, ValueError):
                    pass
            max_hold = conditions.get('max_authority_hold_sec')
            if max_hold is not None:
                try:
                    self.max_authority_hold_spinbox.setValue(float(max_hold))
                except (TypeError, ValueError):
                    pass
            map_link_flag = conditions.get('map_link_enabled')
            if map_link_flag is not None and hasattr(self, 'map_link_checkbox'):
                previous = self.map_link_checkbox.blockSignals(True)
                self.map_link_checkbox.setChecked(bool(map_link_flag))
                self.map_link_checkbox.blockSignals(previous)
                self.map_link_enabled = bool(map_link_flag)
            map_protect = conditions.get('map_protect_sec')
            if map_protect is not None and hasattr(self, 'map_protect_spinbox'):
                prev = self.map_protect_spinbox.blockSignals(True)
                try:
                    value = float(map_protect)
                    self.map_protect_spinbox.setValue(value)
                    self.map_protect_seconds = float(self.map_protect_spinbox.value())
                except (TypeError, ValueError):
                    pass
                finally:
                    self.map_protect_spinbox.blockSignals(prev)
            hunt_protect = conditions.get('hunt_protect_sec')
            if hunt_protect is not None and hasattr(self, 'hunt_protect_spinbox'):
                prev = self.hunt_protect_spinbox.blockSignals(True)
                try:
                    value = float(hunt_protect)
                    self.hunt_protect_spinbox.setValue(value)
                    self.hunt_protect_seconds = float(self.hunt_protect_spinbox.value())
                except (TypeError, ValueError):
                    pass
                finally:
                    self.hunt_protect_spinbox.blockSignals(prev)
            floor_hold = conditions.get('floor_hold_sec')
            if floor_hold is not None and hasattr(self, 'floor_hold_spinbox'):
                prev = self.floor_hold_spinbox.blockSignals(True)
                try:
                    value = float(floor_hold)
                    self.floor_hold_spinbox.setValue(value)
                    self.floor_hold_seconds = float(self.floor_hold_spinbox.value())
                except (TypeError, ValueError):
                    pass
                finally:
                    self.floor_hold_spinbox.blockSignals(prev)

        display = data.get('display', {})
        if display:
            show_hunt = bool(display.get('show_hunt_area', self.show_hunt_area_checkbox.isChecked()))
            show_primary = bool(display.get('show_primary_area', self.show_primary_skill_checkbox.isChecked()))
            if 'show_direction_area' in display:
                show_direction = bool(display.get('show_direction_area'))
            elif 'show_nickname_area' in display:
                show_direction = bool(display.get('show_nickname_area'))
            else:
                show_direction = self.show_direction_checkbox.isChecked()
            show_nickname_range = bool(
                display.get(
                    'show_nickname_range_area',
                    self.show_nickname_range_checkbox.isChecked(),
                )
            )
            show_nameplate = bool(display.get('show_nameplate_area', self.show_nameplate_checkbox.isChecked()))
            show_nameplate_tracking = bool(
                display.get(
                    'show_nameplate_tracking',
                    self.show_nameplate_tracking_checkbox.isChecked()
                    if hasattr(self, 'show_nameplate_tracking_checkbox')
                    else self.overlay_preferences.get('nameplate_tracking', False),
                )
            )
            show_monster_confidence = bool(
                display.get(
                    'show_monster_confidence',
                    self.show_monster_confidence_checkbox.isChecked()
                    if hasattr(self, 'show_monster_confidence_checkbox')
                    else self.overlay_preferences.get('monster_confidence', True),
                )
            )
            screen_output_enabled = bool(
                display.get(
                    'screen_output',
                    display.get('debug', self.screen_output_checkbox.isChecked()),
                )
            )
            summary_confidence = bool(display.get('summary_confidence', self.show_confidence_summary_checkbox.isChecked()))
            summary_frame = bool(display.get('summary_frame', self.show_frame_summary_checkbox.isChecked()))
            summary_info = bool(display.get('summary_info', self.show_info_summary_checkbox.isChecked()))
            summary_frame_detail = bool(
                display.get(
                    'summary_frame_detail',
                    self.show_frame_detail_checkbox.isChecked(),
                )
            )
            control_log_enabled = bool(display.get('log_control', self.control_log_checkbox.isChecked()))
            keyboard_log_enabled = bool(display.get('log_keyboard', self.keyboard_log_checkbox.isChecked()))
            main_log_enabled = bool(display.get('log_main', self.main_log_checkbox.isChecked()))

            self.show_hunt_area_checkbox.setChecked(show_hunt)
            self.show_primary_skill_checkbox.setChecked(show_primary)
            self.show_direction_checkbox.setChecked(show_direction)
            self.show_nickname_range_checkbox.setChecked(show_nickname_range)
            self.show_nameplate_checkbox.setChecked(show_nameplate)
            if hasattr(self, 'show_nameplate_tracking_checkbox'):
                self.show_nameplate_tracking_checkbox.setChecked(show_nameplate_tracking)
            if hasattr(self, 'show_monster_confidence_checkbox'):
                self.show_monster_confidence_checkbox.setChecked(show_monster_confidence)
            self.screen_output_checkbox.setChecked(screen_output_enabled)
            self.show_confidence_summary_checkbox.setChecked(summary_confidence)
            self.show_frame_summary_checkbox.setChecked(summary_frame)
            self.show_info_summary_checkbox.setChecked(summary_info)
            self.show_frame_detail_checkbox.setChecked(summary_frame_detail)
            self.control_log_checkbox.setChecked(control_log_enabled)
            self.keyboard_log_checkbox.setChecked(keyboard_log_enabled)
            self.main_log_checkbox.setChecked(main_log_enabled)

        downscale_cfg = data.get('downscale')
        if isinstance(downscale_cfg, dict):
            try:
                self.downscale_factor = max(0.1, min(1.0, float(downscale_cfg.get('factor', self.downscale_factor))))
            except (TypeError, ValueError):
                self.downscale_factor = max(0.1, min(1.0, self.downscale_factor))
            self.downscale_enabled = bool(downscale_cfg.get('enabled', self.downscale_enabled))
            if hasattr(self, 'downscale_checkbox'):
                self.downscale_checkbox.blockSignals(True)
                self.downscale_checkbox.setChecked(self.downscale_enabled)
                self.downscale_checkbox.blockSignals(False)
                self._update_downscale_checkbox_text()

        self._sync_frame_detail_checkbox_state()

        perf_settings = data.get('perf', {})
        if isinstance(perf_settings, dict):
            self._perf_logging_enabled = bool(perf_settings.get('logging_enabled', False))
        else:
            self._perf_logging_enabled = False

        if hasattr(self, 'perf_logging_checkbox'):
            block_state = self.perf_logging_checkbox.blockSignals(True)
            self.perf_logging_checkbox.setChecked(self._perf_logging_enabled)
            self.perf_logging_checkbox.blockSignals(block_state)

        detection_cfg = data.get('detection', {})
        if isinstance(detection_cfg, dict):
            nms_val = detection_cfg.get('yolo_nms_iou', self.yolo_nms_iou)
            max_det_val = detection_cfg.get('yolo_max_det', self.yolo_max_det)
            try:
                self.yolo_nms_iou = max(0.05, min(0.95, float(nms_val)))
            except (TypeError, ValueError):
                self.yolo_nms_iou = DEFAULT_YOLO_NMS_IOU
            try:
                self.yolo_max_det = max(1, int(max_det_val))
            except (TypeError, ValueError):
                self.yolo_max_det = DEFAULT_YOLO_MAX_DET

        auto_shutdown_cfg = data.get('auto_shutdown')
        if isinstance(auto_shutdown_cfg, dict) and hasattr(self, 'shutdown_pid_input'):
            pid_text = str(auto_shutdown_cfg.get('pid', '') or '').strip()
            blocker = QSignalBlocker(self.shutdown_pid_input)
            self.shutdown_pid_input.setText(pid_text)
            del blocker
            try:
                self.shutdown_pid_value = int(pid_text) if pid_text else None
            except ValueError:
                self.shutdown_pid_value = None

            sleep_enabled = bool(auto_shutdown_cfg.get('sleep_enabled', False))
            self.shutdown_sleep_enabled = sleep_enabled
            if hasattr(self, 'shutdown_sleep_checkbox'):
                blocker = QSignalBlocker(self.shutdown_sleep_checkbox)
                self.shutdown_sleep_checkbox.setChecked(sleep_enabled)
                del blocker

            dt_epoch = auto_shutdown_cfg.get('datetime_epoch')
            if dt_epoch is not None:
                try:
                    epoch_int = int(dt_epoch)
                    dt_value = QDateTime.fromSecsSinceEpoch(epoch_int)
                    blocker = QSignalBlocker(self.shutdown_datetime_edit)
                    self.shutdown_datetime_edit.setDateTime(dt_value)
                    del blocker
                except Exception:
                    pass

            delay_hours = auto_shutdown_cfg.get('delay_hours')
            if delay_hours is not None and hasattr(self, 'shutdown_delay_hours_spin'):
                try:
                    blocker = QSignalBlocker(self.shutdown_delay_hours_spin)
                    self.shutdown_delay_hours_spin.setValue(int(delay_hours))
                    del blocker
                except Exception:
                    pass

            delay_minutes = auto_shutdown_cfg.get('delay_minutes')
            if delay_minutes is not None and hasattr(self, 'shutdown_delay_minutes_spin'):
                try:
                    blocker = QSignalBlocker(self.shutdown_delay_minutes_spin)
                    self.shutdown_delay_minutes_spin.setValue(int(delay_minutes))
                    del blocker
                except Exception:
                    pass

            other_minutes = auto_shutdown_cfg.get('other_minutes')
            if other_minutes is not None and hasattr(self, 'shutdown_other_player_minutes_spin'):
                try:
                    blocker = QSignalBlocker(self.shutdown_other_player_minutes_spin)
                    self.shutdown_other_player_minutes_spin.setValue(int(other_minutes))
                    del blocker
                except Exception:
                    pass

            now = time.time()
            datetime_target = auto_shutdown_cfg.get('datetime_target')
            if isinstance(datetime_target, (int, float)) and float(datetime_target) > now:
                self.shutdown_datetime_target = float(datetime_target)

            delay_target = auto_shutdown_cfg.get('delay_target')
            if isinstance(delay_target, (int, float)) and float(delay_target) > now:
                self.shutdown_delay_target = float(delay_target)

            other_enabled = bool(auto_shutdown_cfg.get('other_enabled', False))
            if hasattr(self, 'shutdown_other_player_checkbox'):
                blocker = QSignalBlocker(self.shutdown_other_player_checkbox)
                self.shutdown_other_player_checkbox.setChecked(other_enabled)
                del blocker
            self.shutdown_other_player_enabled = other_enabled
            self.shutdown_other_player_detect_since = None
            self.shutdown_other_player_due = None
            self.shutdown_other_player_last_count = 0
            if self.shutdown_datetime_target or self.shutdown_delay_target or self.shutdown_other_player_enabled:
                self._ensure_shutdown_timer_running()
            self._update_shutdown_labels()
            self._stop_shutdown_timer_if_idle()

        regions_data = data.get('manual_capture_regions', [])
        valid_regions: list[dict] = []
        if isinstance(regions_data, list):
            for region in regions_data:
                if not isinstance(region, dict):
                    continue
                try:
                    top = int(region['top'])
                    left = int(region['left'])
                    width = int(region['width'])
                    height = int(region['height'])
                except (KeyError, TypeError, ValueError):
                    continue
                if width <= 0 or height <= 0:
                    continue
                valid_regions.append({'top': top, 'left': left, 'width': width, 'height': height})

        legacy_region = data.get('manual_capture_region')
        if not valid_regions and isinstance(legacy_region, dict):
            try:
                top = int(legacy_region['top'])
                left = int(legacy_region['left'])
                width = int(legacy_region['width'])
                height = int(legacy_region['height'])
            except (KeyError, TypeError, ValueError):
                legacy_region = None
            else:
                if width > 0 and height > 0:
                    valid_regions = [{'top': top, 'left': left, 'width': width, 'height': height}]

        self.manual_capture_regions = valid_regions
        if self.manual_capture_regions:
            self.manual_capture_region = self._merge_manual_capture_regions()
        else:
            self.manual_capture_region = None

        self.set_area_btn.setEnabled(True)
        if hasattr(self, 'add_area_btn'):
            self.add_area_btn.setEnabled(bool(self.manual_capture_region))

        self.overlay_preferences['hunt_area'] = self.show_hunt_area_checkbox.isChecked()
        self.overlay_preferences['primary_area'] = self.show_primary_skill_checkbox.isChecked()
        self.overlay_preferences['direction_area'] = self.show_direction_checkbox.isChecked()
        self._direction_area_user_pref = self.overlay_preferences['direction_area']
        self.overlay_preferences['nameplate_area'] = self.show_nameplate_checkbox.isChecked()
        self._nameplate_area_user_pref = self.overlay_preferences['nameplate_area']
        if hasattr(self, 'show_nameplate_tracking_checkbox'):
            tracking_state = self.show_nameplate_tracking_checkbox.isChecked()
        else:
            tracking_state = self.overlay_preferences.get('nameplate_tracking', False)
        self.overlay_preferences['nameplate_tracking'] = tracking_state
        self._nameplate_tracking_user_pref = tracking_state

        misc = data.get('misc', {})
        if misc:
            try:
                self.direction_delay_min_spinbox.setValue(float(misc.get('direction_delay_min', self.direction_delay_min_spinbox.value())))
            except (TypeError, ValueError):
                pass
            try:
                self.direction_delay_max_spinbox.setValue(float(misc.get('direction_delay_max', self.direction_delay_max_spinbox.value())))
            except (TypeError, ValueError):
                pass
            try:
                self.facing_reset_min_spinbox.setValue(float(misc.get('facing_reset_min_sec', self.facing_reset_min_spinbox.value())))
            except (TypeError, ValueError):
                pass
            try:
                self.facing_reset_max_spinbox.setValue(float(misc.get('facing_reset_max_sec', self.facing_reset_max_spinbox.value())))
            except (TypeError, ValueError):
                pass
            try:
                self.direction_threshold_spinbox.setValue(int(misc.get('direction_switch_threshold_px', self.direction_threshold_spinbox.value())))
            except (TypeError, ValueError):
                pass
            try:
                self.direction_cooldown_spinbox.setValue(float(misc.get('direction_switch_cooldown_sec', self.direction_cooldown_spinbox.value())))
            except (TypeError, ValueError):
                pass

        teleport = data.get('teleport', {})
        if teleport:
            self.teleport_settings.enabled = bool(teleport.get('enabled', self.teleport_settings.enabled))
            self.teleport_settings.distance_px = float(teleport.get('distance_px', self.teleport_settings.distance_px))
            self.teleport_settings.probability = int(teleport.get('probability', self.teleport_settings.probability))
            self.teleport_settings.walk_enabled = bool(teleport.get('walk_enabled', self.teleport_settings.walk_enabled))
            self.teleport_settings.walk_probability = float(teleport.get('walk_probability', self.teleport_settings.walk_probability))
            self.teleport_settings.walk_interval = float(teleport.get('walk_interval', self.teleport_settings.walk_interval))
            self.teleport_settings.walk_bonus_interval = float(teleport.get('walk_bonus_interval', self.teleport_settings.walk_bonus_interval))
            self.teleport_settings.walk_bonus_step = float(teleport.get('walk_bonus_step', self.teleport_settings.walk_bonus_step))
            self.teleport_settings.walk_bonus_max = float(teleport.get('walk_bonus_max', self.teleport_settings.walk_bonus_max))
            self.teleport_command_left = teleport.get('command_left', self.teleport_command_left)
            self.teleport_command_right = teleport.get('command_right', self.teleport_command_right)
            self.teleport_command_left_v2 = teleport.get('command_left_v2', self.teleport_command_left_v2)
            self.teleport_command_right_v2 = teleport.get('command_right_v2', self.teleport_command_right_v2)
            self.teleport_enabled_checkbox.setChecked(self.teleport_settings.enabled)
            self.teleport_distance_spinbox.setValue(int(self.teleport_settings.distance_px))
            self.teleport_probability_spinbox.setValue(int(self.teleport_settings.probability))
            self.walk_teleport_checkbox.setChecked(self.teleport_settings.walk_enabled)
            self.walk_teleport_probability_spinbox.setValue(self.teleport_settings.walk_probability)
            self.walk_teleport_interval_spinbox.setValue(self.teleport_settings.walk_interval)
            self.walk_teleport_bonus_interval_spinbox.setValue(self.teleport_settings.walk_bonus_interval)
            self.walk_teleport_bonus_step_spinbox.setValue(self.teleport_settings.walk_bonus_step)
            self.walk_teleport_bonus_max_spinbox.setValue(self.teleport_settings.walk_bonus_max)
            self._update_walk_teleport_inputs_enabled()

        facing_state = data.get('last_facing')
        self._set_current_facing(facing_state if facing_state in ('left', 'right') else None, save=False)
        self.control_release_timeout = max(0.0, float(self.max_authority_hold_spinbox.value()))

        attack_skill_data = data.get('attack_skills', [])
        if attack_skill_data:
            self.attack_skills = []
            for item in attack_skill_data:
                name = item.get('name')
                command = item.get('command')
                if not name or not command:
                    continue
                try:
                    reset_min = int(item.get('primary_reset_min', 0))
                except (TypeError, ValueError):
                    reset_min = 0
                try:
                    reset_max = int(item.get('primary_reset_max', 0))
                except (TypeError, ValueError):
                    reset_max = 0
                reset_command = str(item.get('primary_reset_command', '') or '')
                self.attack_skills.append(
                    AttackSkill(
                        name=name,
                        command=command,
                        enabled=bool(item.get('enabled', True)),
                        is_primary=bool(item.get('is_primary', False)),
                        min_monsters=int(item.get('min_monsters', 1)),
                        max_monsters=self._parse_max_monsters(item.get('max_monsters')),
                        probability=int(item.get('probability', 100)),
                        pre_delay_min=float(item.get('pre_delay_min', 0.0)),
                        pre_delay_max=float(item.get('pre_delay_max', 0.0)),
                        post_delay_min=float(item.get('post_delay_min', 0.43)),
                        post_delay_max=float(item.get('post_delay_max', 0.46)),
                        completion_delay_min=float(item.get('completion_delay_min', 0.0)),
                        completion_delay_max=float(item.get('completion_delay_max', 0.0)),
                        primary_reset_min=reset_min,
                        primary_reset_max=reset_max,
                        primary_reset_command=reset_command,
                    )
                )
            self._ensure_primary_skill()
            self._refresh_attack_tree()

        buff_skill_data = data.get('buff_skills', [])
        if buff_skill_data:
            self.buff_skills = []
            for item in buff_skill_data:
                name = item.get('name')
                command = item.get('command')
                if not name or not command:
                    continue
                self.buff_skills.append(
                    BuffSkill(
                        name=name,
                        command=command,
                        cooldown_seconds=int(item.get('cooldown_seconds', 60)),
                        enabled=bool(item.get('enabled', True)),
                        jitter_percent=int(item.get('jitter_percent', 15)),
                        pre_delay_min=float(item.get('pre_delay_min', 0.0)),
                        pre_delay_max=float(item.get('pre_delay_max', 0.0)),
                        post_delay_min=float(item.get('post_delay_min', 0.43)),
                        post_delay_max=float(item.get('post_delay_max', 0.46)),
                        completion_delay_min=float(item.get('completion_delay_min', 0.0)),
                        completion_delay_max=float(item.get('completion_delay_max', 0.0)),
                    )
                )
            self._refresh_buff_tree()

        self.auto_hunt_enabled = bool(data.get('auto_hunt_enabled', self.auto_hunt_enabled))
        interval = data.get('attack_interval_sec')
        if interval is not None:
            try:
                self.attack_interval_sec = float(interval)
            except (TypeError, ValueError):
                pass

        self.last_popup_scale = int(data.get('last_popup_scale', self.last_popup_scale))

        self.last_popup_position = None
        popup_pos = data.get('last_popup_position')
        if isinstance(popup_pos, (list, tuple)) and len(popup_pos) == 2:
            try:
                x_pos = int(popup_pos[0])
                y_pos = int(popup_pos[1])
            except (TypeError, ValueError):
                pass
            else:
                self.last_popup_position = (x_pos, y_pos)

        self.last_popup_size = None
        popup_size = data.get('last_popup_size')
        if isinstance(popup_size, (list, tuple)) and len(popup_size) == 2:
            try:
                width = int(popup_size[0])
                height = int(popup_size[1])
            except (TypeError, ValueError):
                pass
            else:
                if width > 0 and height > 0:
                    self.last_popup_size = (width, height)

        if getattr(self, 'map_link_enabled', False):
            self._activate_map_link(initial=True)
        else:
            self._deactivate_map_link(initial=True)

        self._suppress_settings_save = False
        self._suppress_downscale_prompt = False
        self._emit_area_overlays()
        self._save_settings()

    def _save_settings(self) -> None:
        if getattr(self, '_suppress_settings_save', False):
            return

        self.teleport_settings.enabled = bool(self.teleport_enabled_checkbox.isChecked())
        self.teleport_settings.distance_px = float(self.teleport_distance_spinbox.value())
        self.teleport_settings.probability = int(self.teleport_probability_spinbox.value())
        self.teleport_settings.walk_enabled = bool(self.walk_teleport_checkbox.isChecked())
        self.teleport_settings.walk_probability = float(self.walk_teleport_probability_spinbox.value())
        self.teleport_settings.walk_interval = float(self.walk_teleport_interval_spinbox.value())
        self.teleport_settings.walk_bonus_interval = float(self.walk_teleport_bonus_interval_spinbox.value())
        self.teleport_settings.walk_bonus_step = float(self.walk_teleport_bonus_step_spinbox.value())
        self.teleport_settings.walk_bonus_max = float(self.walk_teleport_bonus_max_spinbox.value())

        settings_data = {
            'ranges': {
                'enemy_range': self.enemy_range_spinbox.value(),
                'y_band_height': self.y_band_height_spinbox.value(),
                'y_band_offset': self.y_band_offset_spinbox.value(),
                'primary_range': self.primary_skill_range_spinbox.value(),
            },
            'confidence': {
                'char': self.conf_char_spinbox.value(),
                'monster': self.conf_monster_spinbox.value(),
            },
            'conditions': {
                'hunt_monster_threshold': self.hunt_monster_threshold_spinbox.value(),
                'primary_monster_threshold': self.primary_monster_threshold_spinbox.value(),
                'monster_threshold': self.hunt_monster_threshold_spinbox.value(),
                'auto_request': self.auto_request_checkbox.isChecked(),
                'idle_release_sec': self.idle_release_spinbox.value(),
                'max_authority_hold_sec': self.max_authority_hold_spinbox.value(),
                'map_link_enabled': self.map_link_checkbox.isChecked(),
                'map_protect_sec': self.map_protect_spinbox.value(),
                'floor_hold_sec': self.floor_hold_spinbox.value(),
                'hunt_protect_sec': self.hunt_protect_spinbox.value(),
            },
            'display': {
                'show_hunt_area': self.show_hunt_area_checkbox.isChecked(),
                'show_primary_area': self.show_primary_skill_checkbox.isChecked(),
                'show_direction_area': self.show_direction_checkbox.isChecked(),
                'show_nickname_range_area': self.show_nickname_range_checkbox.isChecked(),
                'show_nameplate_area': self.show_nameplate_checkbox.isChecked(),
                'show_nameplate_tracking': bool(
                    self.show_nameplate_tracking_checkbox.isChecked()
                ) if hasattr(self, 'show_nameplate_tracking_checkbox') else bool(
                    self.overlay_preferences.get('nameplate_tracking', False)
                ),
                'show_monster_confidence': bool(
                    self.show_monster_confidence_checkbox.isChecked()
                ) if hasattr(self, 'show_monster_confidence_checkbox') else bool(
                    self.overlay_preferences.get('monster_confidence', True)
                ),
                'screen_output': self.screen_output_checkbox.isChecked(),
                'summary_confidence': self.show_confidence_summary_checkbox.isChecked(),
                'summary_frame': self.show_frame_summary_checkbox.isChecked(),
                'summary_info': self.show_info_summary_checkbox.isChecked(),
                'summary_frame_detail': self.show_frame_detail_checkbox.isChecked(),
                'log_control': bool(self.control_log_checkbox.isChecked()) if hasattr(self, 'control_log_checkbox') else True,
                'log_keyboard': bool(self.keyboard_log_checkbox.isChecked()) if hasattr(self, 'keyboard_log_checkbox') else True,
                'log_main': bool(self.main_log_checkbox.isChecked()) if hasattr(self, 'main_log_checkbox') else True,
            },
            'downscale': {
                'enabled': bool(self.downscale_enabled and self.downscale_checkbox.isChecked()),
                'factor': float(self.downscale_factor),
            },
            'misc': {
                'direction_delay_min': self.direction_delay_min_spinbox.value(),
                'direction_delay_max': self.direction_delay_max_spinbox.value(),
                'facing_reset_min_sec': self.facing_reset_min_spinbox.value(),
                'facing_reset_max_sec': self.facing_reset_max_spinbox.value(),
                'direction_switch_threshold_px': self.direction_threshold_spinbox.value(),
                'direction_switch_cooldown_sec': self.direction_cooldown_spinbox.value(),
            },
            'teleport': {
                'enabled': self.teleport_settings.enabled,
                'distance_px': self.teleport_settings.distance_px,
                'probability': self.teleport_settings.probability,
                'walk_enabled': self.teleport_settings.walk_enabled,
                'walk_probability': self.teleport_settings.walk_probability,
                'walk_interval': self.teleport_settings.walk_interval,
                'walk_bonus_interval': self.teleport_settings.walk_bonus_interval,
                'walk_bonus_step': self.teleport_settings.walk_bonus_step,
                'walk_bonus_max': self.teleport_settings.walk_bonus_max,
                'command_left': self.teleport_command_left,
                'command_right': self.teleport_command_right,
                'command_left_v2': self.teleport_command_left_v2,
                'command_right_v2': self.teleport_command_right_v2,
            },
            'perf': {
                'logging_enabled': bool(self._perf_logging_enabled),
            },
            'attack_skills': [
                {
                    'name': skill.name,
                    'command': skill.command,
                    'enabled': skill.enabled,
                    'is_primary': skill.is_primary,
                    'min_monsters': skill.min_monsters,
                    'max_monsters': skill.max_monsters,
                    'probability': skill.probability,
                    'pre_delay_min': getattr(skill, 'pre_delay_min', 0.0),
                    'pre_delay_max': getattr(skill, 'pre_delay_max', 0.0),
                    'post_delay_min': skill.post_delay_min,
                    'post_delay_max': skill.post_delay_max,
                    'completion_delay_min': getattr(skill, 'completion_delay_min', 0.0),
                    'completion_delay_max': getattr(skill, 'completion_delay_max', 0.0),
                    'primary_reset_min': getattr(skill, 'primary_reset_min', 0),
                    'primary_reset_max': getattr(skill, 'primary_reset_max', 0),
                    'primary_reset_command': getattr(skill, 'primary_reset_command', ''),
                }
                for skill in self.attack_skills
            ],
            'buff_skills': [
                {
                    'name': skill.name,
                    'command': skill.command,
                    'enabled': skill.enabled,
                    'cooldown_seconds': skill.cooldown_seconds,
                    'jitter_percent': skill.jitter_percent,
                    'pre_delay_min': getattr(skill, 'pre_delay_min', 0.0),
                    'pre_delay_max': getattr(skill, 'pre_delay_max', 0.0),
                    'post_delay_min': skill.post_delay_min,
                    'post_delay_max': skill.post_delay_max,
                    'completion_delay_min': getattr(skill, 'completion_delay_min', 0.0),
                    'completion_delay_max': getattr(skill, 'completion_delay_max', 0.0),
                }
                for skill in self.buff_skills
            ],
            'manual_capture_region': self.manual_capture_region,
            'manual_capture_regions': self.manual_capture_regions,
            'auto_hunt_enabled': self.auto_hunt_enabled,
            'attack_interval_sec': self.attack_interval_sec,
            'last_popup_scale': self.last_popup_scale,
            'last_facing': self.last_facing,
            'last_popup_position': list(self.last_popup_position) if self.last_popup_position else None,
            'last_popup_size': list(self.last_popup_size) if self.last_popup_size else None,
            'auto_shutdown': self._build_auto_shutdown_settings(),
        }

        try:
            with open(self._settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings_data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.append_log(f"설정 저장 실패: {exc}", "warn")

    def _build_auto_shutdown_settings(self) -> dict[str, object]:
        if not hasattr(self, 'shutdown_pid_input'):
            return {}
        pid_text = self.shutdown_pid_input.text().strip() if self.shutdown_pid_input else ''
        data: dict[str, object] = {
            'pid': pid_text,
            'datetime_target': float(self.shutdown_datetime_target) if self.shutdown_datetime_target else None,
            'delay_target': float(self.shutdown_delay_target) if self.shutdown_delay_target else None,
            'other_enabled': bool(self.shutdown_other_player_enabled),
            'sleep_enabled': bool(self.shutdown_sleep_enabled),
        }

        if hasattr(self, 'shutdown_datetime_edit') and self.shutdown_datetime_edit:
            try:
                dt_value = self.shutdown_datetime_edit.dateTime()
                data['datetime_epoch'] = int(dt_value.toSecsSinceEpoch())
            except Exception:
                data['datetime_epoch'] = None

        if hasattr(self, 'shutdown_delay_hours_spin') and self.shutdown_delay_hours_spin:
            data['delay_hours'] = int(self.shutdown_delay_hours_spin.value())

        if hasattr(self, 'shutdown_delay_minutes_spin') and self.shutdown_delay_minutes_spin:
            data['delay_minutes'] = int(self.shutdown_delay_minutes_spin.value())

        if hasattr(self, 'shutdown_other_player_minutes_spin') and self.shutdown_other_player_minutes_spin:
            data['other_minutes'] = int(self.shutdown_other_player_minutes_spin.value())

        return data

    def request_control(self, reason: str | None = None) -> None:
        if self.current_authority == "hunt":
            self.append_log("이미 사냥 권한을 보유 중입니다.", "warn")
            return
        if self._request_pending:
            return

        reason_text = str(reason) if reason else "auto"
        payload = self._build_hunt_request_meta()
        self.control_authority_requested.emit(payload)
        self._log_control_request(payload, reason_text)

        if not self.map_link_enabled:
            self.on_map_authority_changed("hunt", {"reason": reason_text, "source": "local"})
            return

        self._request_pending = True
        if self._request_timeout_timer:
            self._request_timeout_timer.start(self.CONTROL_REQUEST_TIMEOUT_MS)

        snapshot = self._build_hunt_condition_snapshot()
        decision = self._authority_manager.request_control(
            "hunt",
            reason=reason_text,
            meta=payload,
            hunt_snapshot=snapshot,
        )

        if decision.status != AuthorityDecisionStatus.PENDING:
            self._request_pending = False
        if decision.status == AuthorityDecisionStatus.REJECTED:
            self.append_log(f"사냥 권한 요청 거부: {decision.reason}", "warn")

    def release_control(self, reason: str | None = None) -> None:
        if self.current_authority != "hunt":
            self.append_log("현재 사냥 권한이 없습니다.", "warn")
            return
        if self._request_timeout_timer:
            self._request_timeout_timer.stop()
        self._request_pending = False

        reason_text = str(reason) if reason else "manual"
        payload = {"reason": reason_text}
        self.control_authority_released.emit(payload)
        if reason:
            self.append_log(f"사냥 권한 반환 요청 ({reason})", "info")
        else:
            self.append_log("사냥 권한 반환 요청", "info")

        if not self.map_link_enabled:
            self.on_map_authority_changed("map", {"reason": reason_text, "source": "local"})
            return

        decision = self._authority_manager.release_control(
            "hunt",
            reason=reason_text,
            meta=payload,
        )
        if decision.status != AuthorityDecisionStatus.ACCEPTED:
            self.append_log(f"사냥 권한 반환 실패: {decision.reason}", "warn")

    def on_map_authority_changed(self, owner: str, payload: Optional[dict] = None) -> None:
        payload = payload or {}
        if self._request_timeout_timer:
            self._request_timeout_timer.stop()
        self._request_pending = False
        self.current_authority = owner
        if owner == "hunt":
            self.last_control_acquired_ts = time.time()
            self.last_release_attempt_ts = 0.0
            self._last_monster_seen_ts = time.time()
        else:
            self.last_control_acquired_ts = 0.0
            self.last_release_attempt_ts = 0.0
            self._last_monster_seen_ts = time.time()
        self._update_authority_ui()
        self._sync_detection_thread_status()
        reason_text = payload.get('reason')
        silent = bool(payload.get('silent'))
        if owner == "hunt":
            if not silent:
                message = "사냥 탭이 조작 권한을 획득했습니다."
                if reason_text:
                    message += f" (사유: {reason_text})"
                self.append_log(message, "success")
        elif owner == "map":
            if not silent:
                message = "맵 탭으로 권한이 반환되었습니다."
                if reason_text:
                    message += f" (사유: {reason_text})"
                self.append_log(message, "info")
        else:
            if not silent:
                self.append_log(f"권한 소유자 변경: {owner}", "info")
        if owner != "hunt":
            self._schedule_condition_poll()

    def _update_authority_ui(self) -> None:
        self._update_detection_summary()
        self._update_attack_buttons()
        self._update_buff_buttons()

    def _poll_hunt_conditions(self, *, force: bool = False) -> None:
        now = time.time()
        if not force:
            if self._request_pending:
                return
            if now - self._last_condition_poll_ts < self.CONDITION_POLL_MIN_INTERVAL_SEC:
                return
        self._last_condition_poll_ts = now

        if not self.auto_request_checkbox.isChecked():
            return
        if not self.auto_hunt_enabled:
            return

        hunt_threshold = self.hunt_monster_threshold_spinbox.value()
        primary_threshold = self.primary_monster_threshold_spinbox.value()

        primary_ready = (
            primary_threshold <= 0
            or self.latest_primary_monster_count >= primary_threshold
        )
        hunt_ready = (
            hunt_threshold <= 0
            or self.latest_monster_count >= hunt_threshold
        )

        if primary_ready or hunt_ready:
            self._last_monster_seen_ts = time.time()

        if self.current_authority == "hunt":
            elapsed = time.time() - self.last_control_acquired_ts if self.last_control_acquired_ts else 0.0
            idle_elapsed = (
                time.time() - self._last_monster_seen_ts
                if self._last_monster_seen_ts
                else float("inf")
            )
            should_release = False
            release_reason_code = None
            idle_limit = self.idle_release_spinbox.value()
            if not primary_ready and not hunt_ready:
                if idle_elapsed >= idle_limit:
                    should_release = True
                    release_reason_code = "MONSTER_SHORTAGE"
            timeout = self.control_release_timeout or 0
            if timeout and elapsed >= timeout:
                should_release = True
                release_reason_code = "MAX_HOLD_EXCEEDED"
            if should_release and (time.time() - self.last_release_attempt_ts) >= 1.0:
                self.last_release_attempt_ts = time.time()
                reason_parts = []
                if not primary_ready and primary_threshold > 0:
                    reason_parts.append(
                        f"주 스킬 {self.latest_primary_monster_count}마리 < 기준 {primary_threshold}"
                    )
                if not hunt_ready and hunt_threshold > 0:
                    reason_parts.append(
                        f"사냥범위 {self.latest_monster_count}마리 < 기준 {hunt_threshold}"
                    )
                reason_parts.append(f"최근 몬스터 미탐지 {idle_elapsed:.1f}s (기준 {idle_limit:.1f}s)")
                if timeout and elapsed >= timeout:
                    reason_parts.append(f"타임아웃 {timeout}s 초과")
                reason_text = ", ".join(reason_parts)
                self.append_log(f"자동 조건 해제 → 사냥 권한 반환 ({reason_text})", "info")
                release_reason = release_reason_code if (self.map_link_enabled and release_reason_code) else reason_text
                self.release_control(release_reason)
            return

        if hunt_ready or primary_ready:
            reason_parts = []
            if hunt_ready and hunt_threshold > 0:
                reason_parts.append(
                    f"사냥범위 {self.latest_monster_count}마리 ≥ 기준 {hunt_threshold}"
                )
            if primary_ready and primary_threshold > 0:
                reason_parts.append(
                    f"주 스킬 {self.latest_primary_monster_count}마리 ≥ 기준 {primary_threshold}"
                )
            if not reason_parts:
                reason_parts.append("몬스터 조건 충족")
            reason_text = ", ".join(reason_parts)
            self.append_log(f"자동 조건 충족 → 사냥 권한 요청 ({reason_text})", "info")
            request_reason = "MONSTER_READY" if self.map_link_enabled else reason_text
            self.request_control(request_reason)

    def _run_hunt_loop(self) -> None:
        if not self.auto_hunt_enabled:
            self._ensure_idle_keys("자동 사냥 비활성화")
            return
        if self.current_authority != "hunt":
            self._ensure_idle_keys("사냥 권한 없음")
            return
        if self._pending_skill_timer or self._pending_direction_timer:
            return
        if self._get_command_delay_remaining() > 0:
            return
        if self._direction_confirmation_pending():
            if self._maybe_complete_direction_confirmation():
                return
            pending_skill = self._pending_direction_confirm_skill
            pending_side = self._pending_direction_confirm_side
            if self._direction_confirmation_expired() and pending_skill is not None:
                if pending_side in ('left', 'right'):
                    if self._pending_direction_confirm_attempts >= 2:
                        self.append_log("방향 확인 실패 → 스킬 강행", 'warn')
                        skill_to_fire = pending_skill
                        self._clear_direction_confirmation()
                        self._schedule_skill_after_direction(skill_to_fire)
                        return
                    self.append_log("방향 확인 지연 → 재시도", 'warn')
                    self._register_direction_retry()
                    self._schedule_direction_command(pending_side, pending_skill)
                    return
                self._clear_direction_confirmation()
            return
        now = time.time()
        if self._evaluate_buff_usage(now):
            return
        if not self.attack_skills:
            self._ensure_idle_keys("공격 스킬 미등록")
            return
        if self.latest_monster_count == 0:
            self._ensure_idle_keys("감지 범위 몬스터 없음")
            return
        primary_threshold_widget = getattr(self, 'primary_monster_threshold_spinbox', None)
        primary_threshold = max(1, primary_threshold_widget.value()) if primary_threshold_widget else 1
        if self.latest_primary_monster_count < primary_threshold:
            if self._handle_monster_approach():
                return
            if self.latest_monster_count == 0:
                self._ensure_idle_keys("감지 범위 몬스터 없음")
            return
        if not self.latest_snapshot or not self.latest_snapshot.character_boxes:
            self._ensure_idle_keys("탐지 데이터 없음")
            return

        if now - self.last_attack_ts < self.attack_interval_sec:
            return

        if self._movement_mode:
            self._movement_mode = None
            self._reset_walk_teleport_state()

        skill = self._select_attack_skill()
        if not skill:
            self._ensure_idle_keys("공격 스킬 선택 실패")
            return

        character_box = self._select_reference_character_box(self.latest_snapshot.character_boxes)
        target_box = self._select_target_monster(character_box)
        if not target_box:
            self._ensure_idle_keys("목표 몬스터 탐지 실패")
            return

        target_side = 'left' if target_box.center_x < character_box.center_x else 'right'
        direction_changed = self._ensure_direction(target_side, skill)
        if direction_changed:
            return

        self._execute_attack_skill(skill)

    def _handle_monster_approach(self) -> bool:
        if not self.latest_snapshot or not self.latest_snapshot.character_boxes:
            return False
        if not self.current_hunt_area:
            return False
        monsters = self._get_recent_monster_boxes()
        if not monsters:
            return False

        hunt_monsters = [box for box in monsters if box.intersects(self.current_hunt_area)]
        if not hunt_monsters:
            return False

        character_box = self._select_reference_character_box(self.latest_snapshot.character_boxes)
        target = min(hunt_monsters, key=lambda box: abs(box.center_x - character_box.center_x))
        target_side = 'left' if target.center_x < character_box.center_x else 'right'
        distance = abs(target.center_x - character_box.center_x)

        teleport_enabled = bool(self.teleport_enabled_checkbox.isChecked())
        teleport_distance = float(self.teleport_distance_spinbox.value())
        teleport_probability = max(0, min(100, int(self.teleport_probability_spinbox.value())))

        if teleport_enabled and distance > teleport_distance:
            roll = random.randint(1, 100)
            if roll <= teleport_probability:
                if self._issue_teleport_command(target_side, distance):
                    self._reset_walk_teleport_state()
                    return True
        walk_issued = self._issue_walk_command(target_side, distance)
        if walk_issued:
            self._maybe_trigger_walk_teleport(target_side, distance)
            return True
        self._maybe_trigger_walk_teleport(target_side, distance)
        return walk_issued

    def _issue_walk_command(self, side: str, distance: float) -> bool:
        if side not in ('left', 'right'):
            return False
        mode_key = f"walk_{side}"
        if self._movement_mode == mode_key:
            self._mark_walk_teleport_started(side)
            return True
        command = "걷기(좌)" if side == 'left' else "걷기(우)"
        reason = f"몬스터 접근 ({'좌' if side == 'left' else '우'}, {distance:.0f}px)"
        self._emit_control_command(command, reason=reason)
        self._movement_mode = mode_key
        self.hunting_active = True
        self._last_movement_command_ts = time.time()
        self._mark_walk_teleport_started(side)
        return True

    def _issue_teleport_command(self, side: str, distance: float) -> bool:
        if side not in ('left', 'right'):
            return False
        if side == 'left':
            candidates = [self.teleport_command_left, self.teleport_command_left_v2]
        else:
            candidates = [self.teleport_command_right, self.teleport_command_right_v2]
        available = [cmd for cmd in candidates if isinstance(cmd, str) and cmd.strip()]
        command = random.choice(available) if available else (self.teleport_command_left if side == 'left' else self.teleport_command_right)
        reason = f"몬스터에게 이동 ({distance:.0f}px)"
        self._emit_control_command(command, reason=reason)
        self._movement_mode = None
        self._reset_walk_teleport_state()
        self._set_current_facing(side, save=False)
        self.hunting_active = True
        self._last_movement_command_ts = time.time()
        delay = random.uniform(0.12, 0.22)
        self._set_command_cooldown(delay)
        self._log_delay_message("텔레포트 이동", delay)
        return True

    def _mark_walk_teleport_started(self, side: str) -> None:
        if not getattr(self, 'walk_teleport_checkbox', None):
            return
        if not self.walk_teleport_checkbox.isChecked():
            self._reset_walk_teleport_state()
            return
        now = time.time()
        if not self._walk_teleport_active or self._walk_teleport_direction != side:
            self._walk_teleport_active = True
            self._walk_teleport_walk_started_at = now
            self._walk_teleport_bonus_percent = 0.0
            self._last_walk_teleport_check_ts = 0.0
        self._walk_teleport_direction = side
        if self._last_walk_teleport_check_ts <= 0.0:
            self._last_walk_teleport_check_ts = now
        self._update_detection_summary()

    def _maybe_trigger_walk_teleport(self, side: str, distance: float) -> bool:
        if not getattr(self, 'walk_teleport_checkbox', None):
            return False
        if not self.walk_teleport_checkbox.isChecked():
            return False
        if side not in ('left', 'right'):
            return False
        mode_key = f"walk_{side}"
        if self._movement_mode != mode_key:
            return False
        if self._get_command_delay_remaining() > 0:
            return False
        teleport_distance = float(self.teleport_distance_spinbox.value())
        if distance <= teleport_distance:
            return False
        now = time.time()
        if not self._walk_teleport_active or self._walk_teleport_direction != side:
            self._mark_walk_teleport_started(side)
            return False
        interval = max(0.1, float(self.walk_teleport_interval_spinbox.value()))
        if (now - self._last_walk_teleport_check_ts) < interval:
            return False
        self._last_walk_teleport_check_ts = now

        elapsed = max(0.0, now - self._walk_teleport_walk_started_at)
        bonus_interval = max(0.1, float(self.walk_teleport_bonus_interval_spinbox.value()))
        bonus_step = max(0.0, float(self.walk_teleport_bonus_step_spinbox.value()))
        bonus_max = max(0.0, float(self.walk_teleport_bonus_max_spinbox.value()))
        bonus_percent = 0.0
        if bonus_step > 0.0:
            bonus_steps = math.floor(elapsed / bonus_interval)
            bonus_percent = min(bonus_max, bonus_steps * bonus_step)
        self._walk_teleport_bonus_percent = bonus_percent

        base_percent = max(0.0, min(100.0, float(self.walk_teleport_probability_spinbox.value())))
        effective_percent = min(100.0, base_percent + bonus_percent)
        if effective_percent <= 0.0:
            self._update_detection_summary()
            return False

        roll = random.uniform(0.0, 100.0)
        if roll > effective_percent:
            self._update_detection_summary()
            return False

        direction_text = '좌' if side == 'left' else '우'
        reason = f"걷기({direction_text}, {distance:.0f}px) 유지"
        self._emit_control_command(self.walk_teleport_command, reason=reason)
        self._update_detection_summary()
        return True

    def _reset_walk_teleport_state(self) -> None:
        self._walk_teleport_active = False
        self._walk_teleport_walk_started_at = 0.0
        self._last_walk_teleport_check_ts = 0.0
        self._walk_teleport_bonus_percent = 0.0
        self._walk_teleport_direction = None
        self._update_detection_summary()

    def _get_walk_teleport_display_percent(self) -> float:
        checkbox = getattr(self, 'walk_teleport_checkbox', None)
        if checkbox is None or not checkbox.isChecked():
            return 0.0
        base_percent = 0.0
        try:
            base_percent = float(self.walk_teleport_probability_spinbox.value())
        except Exception:
            base_percent = 0.0
        base_percent = max(0.0, min(100.0, base_percent))
        bonus = self._walk_teleport_bonus_percent if self._walk_teleport_active else 0.0
        return min(100.0, base_percent + max(0.0, bonus))

    def _evaluate_buff_usage(self, now: float) -> bool:
        if self._get_command_delay_remaining() > 0:
            return False
        for buff in self.buff_skills:
            if not buff.enabled or buff.cooldown_seconds <= 0:
                continue

            if buff.command in self._pre_delay_timers:
                return True

            ready_ts = buff.next_ready_ts or 0.0
            if buff.last_triggered_ts == 0.0 or now >= ready_ts:
                if self._trigger_buff_skill(buff):
                    return True

        return False

    def _skill_meets_monster_conditions(self, skill: AttackSkill, monster_count: int) -> bool:
        min_required = max(1, getattr(skill, 'min_monsters', 1))
        if monster_count < min_required:
            return False
        max_allowed = getattr(skill, 'max_monsters', None)
        if isinstance(max_allowed, int) and max_allowed > 0 and monster_count > max_allowed:
            return False
        return True

    def _build_attack_usage_reason(
        self,
        skill: AttackSkill,
        *,
        monster_count: int,
        total_monster_count: int,
    ) -> str:
        """사냥 탭 키보드 로그에 남길 공격 스킬 사용 사유 문자열을 생성합니다."""

        normalized_primary_count = max(0, int(monster_count))
        normalized_total_count = max(0, int(total_monster_count))

        detail_parts: list[str] = []
        detail_parts.append(f"주 스킬 범위 몬스터 {normalized_primary_count}마리")

        if (
            normalized_total_count > 0
            and normalized_total_count != normalized_primary_count
        ):
            detail_parts.append(f"전체 감지 {normalized_total_count}마리")

        min_required = max(1, getattr(skill, 'min_monsters', 1))
        if min_required > 1:
            detail_parts.append(f"최소 조건 {min_required}마리 충족")

        max_allowed = getattr(skill, 'max_monsters', None)
        if isinstance(max_allowed, int) and max_allowed > 0:
            detail_parts.append(f"최대 {max_allowed}마리 이하 유지")

        target_side = getattr(self, '_last_target_side', None)
        target_distance = getattr(self, '_last_target_distance', None)
        if target_side in ('left', 'right'):
            direction_label = '좌' if target_side == 'left' else '우'
            if isinstance(target_distance, (int, float)) and target_distance > 0:
                detail_parts.append(f"목표 {direction_label} {int(round(target_distance))}px")
            else:
                detail_parts.append(f"목표 {direction_label}측")

        facing_side: Optional[str] = None
        if self.last_facing in ('left', 'right'):
            facing_side = self.last_facing
        elif getattr(self, '_direction_last_side', None) in ('left', 'right'):
            facing_side = getattr(self, '_direction_last_side')
        if facing_side:
            facing_label = '좌' if facing_side == 'left' else '우'
            detail_parts.append(f"캐릭터 방향 : {facing_label}")

        return ', '.join(detail_parts) if detail_parts else '조건 충족'

    def _execute_attack_skill(self, skill: AttackSkill, *, skip_pre_delay: bool = False) -> None:
        if not skill.enabled:
            return
        if not self.auto_hunt_enabled or self.current_authority != "hunt":
            return
        monster_count = self.latest_primary_monster_count
        if not self._skill_meets_monster_conditions(skill, monster_count):
            return

        remaining = self._get_command_delay_remaining()
        if remaining > 0:
            self._schedule_skill_execution(skill, remaining)
            return

        if not skip_pre_delay:
            pre_delay = self._sample_delay(getattr(skill, 'pre_delay_min', 0.0), getattr(skill, 'pre_delay_max', 0.0))
            if pre_delay > 0.0:
                if self._start_pre_delay(
                    skill.command,
                    pre_delay,
                    f"스킬 '{skill.name}' 발동 전",
                    lambda s=skill: self._execute_attack_skill(s, skip_pre_delay=True),
                ):
                    return

        self._next_command_ready_ts = max(self._next_command_ready_ts, time.time())
        usage_reason = self._build_attack_usage_reason(
            skill,
            monster_count=monster_count,
            total_monster_count=self.latest_monster_count,
        )
        self._emit_control_command(skill.command, reason=usage_reason)
        self._queue_completion_delay(
            skill.command,
            skill.completion_delay_min,
            skill.completion_delay_max,
            f"스킬 '{skill.name}'",
            payload={'type': 'attack', 'skill': skill},
        )
        self.last_attack_ts = time.time()
        self.hunting_active = True
        post_delay = self._sample_delay(skill.post_delay_min, skill.post_delay_max)
        if post_delay > 0.0:
            self._set_command_cooldown(post_delay)
            self._log_delay_message(f"스킬 '{skill.name}'", post_delay)
        # 주 스킬 회전 카운터는 시퀀스 완료 시점에 갱신합니다.

    def _trigger_buff_skill(self, buff: BuffSkill, *, is_test: bool = False) -> bool:
        if not buff.enabled:
            return False
        command = buff.command
        if not command:
            return False
        if command in self._pre_delay_timers:
            return True

        context_label = f"테스트 버프 '{buff.name}'" if is_test else f"버프 '{buff.name}'"

        def emit() -> None:
            exec_time = time.time()
            self._next_command_ready_ts = max(self._next_command_ready_ts, exec_time)
            self._emit_control_command(command)
            self._queue_completion_delay(command, buff.completion_delay_min, buff.completion_delay_max, context_label)

            jitter_ratio = max(0, min(buff.jitter_percent, 90)) / 100.0
            jitter_window = buff.cooldown_seconds * jitter_ratio

            if is_test:
                if jitter_window > 0:
                    next_delay = buff.cooldown_seconds - random.uniform(0, jitter_window)
                else:
                    next_delay = buff.cooldown_seconds
                buff.next_ready_ts = exec_time + max(0.0, next_delay)
            else:
                if jitter_window > 0:
                    mean = jitter_window / 2.0
                    std_dev = jitter_window / 6.0
                    reduction = None
                    for _ in range(5):
                        candidate = random.gauss(mean, std_dev)
                        if 0.0 <= candidate <= jitter_window:
                            reduction = candidate
                            break
                    if reduction is None:
                        candidate = random.gauss(mean, std_dev)
                        reduction = min(max(candidate, 0.0), jitter_window)
                else:
                    reduction = 0.0
                next_delay = buff.cooldown_seconds - reduction
                wait_seconds = max(0.0, next_delay)
                buff.next_ready_ts = exec_time + wait_seconds
                self.append_log(f"버프 사용: {buff.name} - {wait_seconds:.1f}초 후 사용예정", "info")
                self.last_attack_ts = exec_time
                self.hunting_active = True

            buff.last_triggered_ts = exec_time

            post_delay = self._sample_delay(buff.post_delay_min, buff.post_delay_max)
            if post_delay > 0.0:
                self._set_command_cooldown(post_delay)
                self._log_delay_message(context_label, post_delay)

        pre_delay = self._sample_delay(getattr(buff, 'pre_delay_min', 0.0), getattr(buff, 'pre_delay_max', 0.0))
        if pre_delay > 0.0:
            if self._start_pre_delay(command, pre_delay, f"{context_label} 발동 전", emit):
                return True

        emit()
        return True

    def _select_attack_skill(self) -> Optional[AttackSkill]:
        enabled_skills = [s for s in self.attack_skills if s.enabled]
        if not enabled_skills:
            return None

        primary_skill = next((s for s in enabled_skills if s.is_primary), None)
        primary_count = self.latest_primary_monster_count
        fallback_skill: Optional[AttackSkill] = None
        if primary_skill and self._skill_meets_monster_conditions(primary_skill, primary_count):
            fallback_skill = primary_skill

        for skill in enabled_skills:
            if skill.is_primary:
                continue
            if not self._skill_meets_monster_conditions(skill, primary_count):
                continue
            probability = max(0, min(skill.probability, 100))
            if random.randint(1, 100) <= probability:
                return skill
            if fallback_skill is None:
                fallback_skill = skill

        if fallback_skill:
            return fallback_skill

        if primary_skill and primary_skill.enabled:
            return primary_skill if self._skill_meets_monster_conditions(primary_skill, primary_count) else None
        return None

    def _select_target_monster(self, character_box: DetectionBox) -> Optional[DetectionBox]:
        if not self.latest_snapshot:
            return None
        monsters = self._get_recent_monster_boxes()
        if not monsters:
            self._last_target_side = None
            self._last_target_distance = None
            return None
        candidates = monsters
        if self.current_primary_area:
            primary_monsters = [box for box in monsters if box.intersects(self.current_primary_area)]
            if primary_monsters:
                candidates = primary_monsters
            else:
                self._last_target_side = None
                self._last_target_distance = None
                return None
        char_x = character_box.center_x
        facing = self.last_facing if self.last_facing in ('left', 'right') else None
        if facing:
            if facing == 'left':
                same_side = [box for box in candidates if box.center_x <= char_x]
            else:
                same_side = [box for box in candidates if box.center_x >= char_x]
            if same_side:
                candidates = same_side

        selected = min(candidates, key=lambda box: abs(box.center_x - char_x))
        selected_distance = abs(selected.center_x - char_x)
        selected_side = 'left' if selected.center_x < char_x else 'right'

        previous_side = self._last_target_side
        prev_candidate = None
        prev_distance = None
        if previous_side:
            if previous_side == 'left':
                prev_candidates = [box for box in candidates if box.center_x <= char_x]
            else:
                prev_candidates = [box for box in candidates if box.center_x >= char_x]
            if prev_candidates:
                prev_candidate = min(prev_candidates, key=lambda box: abs(box.center_x - char_x))
                prev_distance = abs(prev_candidate.center_x - char_x)

        if previous_side and prev_candidate and previous_side != selected_side:
            threshold_spin = getattr(self, 'direction_threshold_spinbox', None)
            cooldown_spin = getattr(self, 'direction_cooldown_spinbox', None)
            threshold_px = float(threshold_spin.value()) if threshold_spin else 0.0
            cooldown_sec = float(cooldown_spin.value()) if cooldown_spin else 0.0
            now = time.time()
            within_cooldown = cooldown_sec > 0.0 and (now - self._last_direction_change_ts) < cooldown_sec

            if within_cooldown:
                selected = prev_candidate
                selected_side = previous_side
                selected_distance = prev_distance if prev_distance is not None else selected_distance
            else:
                if prev_distance is not None and (selected_distance + threshold_px) >= prev_distance:
                    selected = prev_candidate
                    selected_side = previous_side
                    selected_distance = prev_distance

        self._last_target_side = selected_side
        self._last_target_distance = selected_distance
        self._last_target_update_ts = time.time()
        return selected

    def _ensure_direction(self, target_side: str, next_skill: Optional[AttackSkill] = None) -> bool:
        current = self.last_facing if self.last_facing in ('left', 'right') else None
        if current == target_side:
            if next_skill is not None:
                self._clear_direction_confirmation(skill=next_skill)
            return False
        self._schedule_direction_command(target_side, next_skill)
        self._last_direction_change_ts = time.time()
        return True

    def _schedule_direction_command(self, target_side: str, next_skill: Optional[AttackSkill]) -> None:
        self._clear_pending_direction()
        remaining = self._get_command_delay_remaining()
        if remaining <= 0.0:
            self._execute_direction_command(target_side, next_skill)
            return

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(max(1, int(remaining * 1000)))
        timer.timeout.connect(lambda side=target_side, skill=next_skill: self._on_direction_timer_timeout(side, skill))
        timer.start()
        self._pending_direction_timer = timer
        self._pending_direction_side = target_side
        self._pending_direction_skill = next_skill
        self.hunting_active = True

    def _on_direction_timer_timeout(self, target_side: str, next_skill: Optional[AttackSkill]) -> None:
        self._pending_direction_timer = None
        self._pending_direction_side = None
        self._pending_direction_skill = None
        self._execute_direction_command(target_side, next_skill)

    def _execute_direction_command(self, target_side: str, next_skill: Optional[AttackSkill]) -> None:
        self._pending_direction_timer = None
        self._pending_direction_side = None
        self._pending_direction_skill = None
        command = '방향설정(좌)' if target_side == 'left' else '방향설정(우)'
        now = time.time()
        self._last_direction_change_ts = now
        self._emit_control_command(command)
        delay_min = min(self.direction_delay_min_spinbox.value(), self.direction_delay_max_spinbox.value())
        delay_max = max(self.direction_delay_min_spinbox.value(), self.direction_delay_max_spinbox.value())
        delay_sec = random.uniform(delay_min, delay_max)
        self._set_command_cooldown(delay_sec)
        self._log_delay_message("방향설정", delay_sec)
        if next_skill:
            if self._direction_detector_available:
                self._start_direction_confirmation(target_side, next_skill, now)
            else:
                self._clear_direction_confirmation()
                self._schedule_skill_after_direction(next_skill)
        else:
            self._clear_direction_confirmation()
        self.hunting_active = True

    def _schedule_skill_after_direction(self, skill: AttackSkill) -> None:
        delay_sec = random.uniform(0.035, 0.050)
        self._schedule_skill_execution(skill, delay_sec)

    def _schedule_skill_execution(self, skill: AttackSkill, delay_sec: float) -> None:
        self._clear_pending_skill()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(max(1, int(max(0.0, delay_sec) * 1000)))
        timer.timeout.connect(lambda skill=skill: self._execute_scheduled_skill(skill))
        timer.start()
        self._pending_skill_timer = timer
        self._pending_skill = skill
        self.hunting_active = True

    def _execute_scheduled_skill(self, skill: AttackSkill) -> None:
        pending_skill = self._pending_skill
        self._clear_pending_skill()
        if pending_skill is not None and pending_skill is not skill:
            return
        remaining = self._get_command_delay_remaining()
        if remaining > 0:
            self._schedule_skill_execution(skill, remaining)
            return
        if not self.auto_hunt_enabled or self.current_authority != "hunt":
            return
        if self.latest_primary_monster_count == 0:
            return
        if skill not in self.attack_skills or not skill.enabled:
            return
        self._execute_attack_skill(skill)

    def _clear_pending_skill(self) -> None:
        if self._pending_skill_timer:
            try:
                self._pending_skill_timer.stop()
            finally:
                self._pending_skill_timer.deleteLater()
        self._pending_skill_timer = None
        self._pending_skill = None

    def _clear_pending_direction(self) -> None:
        if self._pending_direction_timer:
            try:
                self._pending_direction_timer.stop()
            finally:
                self._pending_direction_timer.deleteLater()
        self._pending_direction_timer = None
        self._pending_direction_side = None
        self._pending_direction_skill = None

    def _start_direction_confirmation(self, side: str, skill: AttackSkill, command_ts: float) -> None:
        if side not in ('left', 'right'):
            return
        if skill is None:
            return
        attempts = 0
        if (
            self._pending_direction_confirm_skill is skill
            and self._pending_direction_confirm_side == side
            and self._pending_direction_confirm_attempts > 0
        ):
            attempts = self._pending_direction_confirm_attempts
        self._pending_direction_confirm_skill = skill
        self._pending_direction_confirm_side = side
        self._pending_direction_confirm_command_ts = command_ts
        self._pending_direction_confirm_deadline = command_ts + max(0.75, self.DIRECTION_TIMEOUT_SEC)
        self._pending_direction_confirm_attempts = attempts

    def _register_direction_retry(self) -> None:
        if self._pending_direction_confirm_skill is None:
            return
        now = time.time()
        self._pending_direction_confirm_attempts += 1
        self._pending_direction_confirm_command_ts = now
        self._pending_direction_confirm_deadline = now + max(0.75, self.DIRECTION_TIMEOUT_SEC)

    def _clear_direction_confirmation(self, *, skill: Optional[AttackSkill] = None) -> None:
        if skill is not None and skill is not self._pending_direction_confirm_skill:
            return
        self._pending_direction_confirm_skill = None
        self._pending_direction_confirm_side = None
        self._pending_direction_confirm_command_ts = 0.0
        self._pending_direction_confirm_deadline = 0.0
        self._pending_direction_confirm_attempts = 0

    def _direction_confirmation_pending(self) -> bool:
        return self._pending_direction_confirm_skill is not None

    def _direction_confirmation_expired(self) -> bool:
        if not self._direction_confirmation_pending():
            return False
        return time.time() > self._pending_direction_confirm_deadline

    def _direction_confirmation_met(self) -> bool:
        if not self._direction_confirmation_pending():
            return True
        if not self._direction_detector_available:
            return True
        expected_side = self._pending_direction_confirm_side
        if expected_side not in ('left', 'right'):
            return True
        if not getattr(self, '_direction_active', False):
            return False
        if self._direction_last_side != expected_side:
            return False
        if self._direction_last_seen_ts < self._pending_direction_confirm_command_ts:
            return False
        if (time.time() - self._direction_last_seen_ts) > self.DIRECTION_TIMEOUT_SEC:
            return False
        return True

    def _maybe_complete_direction_confirmation(self) -> bool:
        if not self._direction_confirmation_pending():
            return False
        skill = self._pending_direction_confirm_skill
        if skill is None:
            self._clear_direction_confirmation()
            return False
        if not self._direction_confirmation_met():
            return False
        side = self._pending_direction_confirm_side
        self._clear_direction_confirmation()
        self._schedule_skill_after_direction(skill)
        if side in ('left', 'right'):
            direction_text = '좌' if side == 'left' else '우'
            self.append_log(f"방향 확인 완료 → 스킬 대기 ({direction_text})", 'debug')
        return True

    def set_auto_hunt_enabled(self, enabled: bool) -> None:
        self.auto_hunt_enabled = bool(enabled)
        state = "ON" if self.auto_hunt_enabled else "OFF"
        self.append_log(f"자동 사냥 모드 {state}", "info")
        if not self.auto_hunt_enabled and self.current_authority == "hunt":
            self.release_control("사용자에 의해 자동 사냥 비활성화")
        self._save_settings()

    def add_attack_skill(self) -> None:
        dialog = AttackSkillDialog(self, misc_commands=self._get_misc_command_profiles())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            skill = dialog.get_skill()
            if not skill:
                return
            if not self.attack_skills:
                skill.is_primary = True
            elif skill.is_primary:
                for existing in self.attack_skills:
                    existing.is_primary = False
            self.attack_skills.append(skill)
            self._ensure_primary_skill()
            self._refresh_attack_tree()
            self._save_settings()

    def edit_attack_skill(self) -> None:
        index = self._get_selected_attack_index()
        if index is None:
            return
        dialog = AttackSkillDialog(
            self,
            skill=self.attack_skills[index],
            misc_commands=self._get_misc_command_profiles(),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.get_skill()
            if not updated:
                return
            if updated.is_primary:
                for existing in self.attack_skills:
                    existing.is_primary = False
            self.attack_skills[index] = updated
            self._ensure_primary_skill()
            self._refresh_attack_tree()
            self._save_settings()

    def remove_attack_skill(self) -> None:
        index = self._get_selected_attack_index()
        if index is None:
            return
        del self.attack_skills[index]
        self._ensure_primary_skill()
        self._refresh_attack_tree()
        self._save_settings()

    def set_primary_attack_skill(self) -> None:
        index = self._get_selected_attack_index()
        if index is None:
            return
        for i, skill in enumerate(self.attack_skills):
            skill.is_primary = i == index
            if skill.is_primary:
                skill.enabled = True
        self._refresh_attack_tree()
        self._save_settings()

    def run_attack_skill(self) -> None:
        index = self._get_selected_attack_index()
        if index is None:
            return
        skill = self.attack_skills[index]
        self.append_log(f"테스트 실행 (공격): {skill.name}", "info")
        self._trigger_manual_attack_skill(skill)

    def _trigger_manual_attack_skill(self, skill: AttackSkill) -> None:
        command = skill.command
        if not command:
            return
        if command in self._pre_delay_timers:
            return

        context_label = f"테스트 스킬 '{skill.name}'"

        def emit() -> None:
            exec_time = time.time()
            self._next_command_ready_ts = max(self._next_command_ready_ts, exec_time)
            self._emit_control_command(command)
            self._queue_completion_delay(
                command,
                skill.completion_delay_min,
                skill.completion_delay_max,
                context_label,
                payload={'type': 'attack', 'skill': skill},
            )
            post_delay = self._sample_delay(skill.post_delay_min, skill.post_delay_max)
            if post_delay > 0.0:
                self._set_command_cooldown(post_delay)
                self._log_delay_message(context_label, post_delay)
            # 주 스킬 회전 카운터는 시퀀스 완료 시점에 갱신합니다.

        pre_delay = self._sample_delay(getattr(skill, 'pre_delay_min', 0.0), getattr(skill, 'pre_delay_max', 0.0))
        if pre_delay > 0.0:
            if self._start_pre_delay(command, pre_delay, f"{context_label} 발동 전", emit):
                return

        emit()

    def add_buff_skill(self) -> None:
        dialog = BuffSkillDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            skill = dialog.get_skill()
            if skill:
                self.buff_skills.append(skill)
                self._refresh_buff_tree()
                self._save_settings()

    def edit_buff_skill(self) -> None:
        index = self._get_selected_buff_index()
        if index is None:
            return
        dialog = BuffSkillDialog(self, self.buff_skills[index])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.get_skill()
            if updated:
                updated.last_triggered_ts = self.buff_skills[index].last_triggered_ts
                updated.next_ready_ts = self.buff_skills[index].next_ready_ts
                self.buff_skills[index] = updated
                self._refresh_buff_tree()
                self._save_settings()

    def remove_buff_skill(self) -> None:
        index = self._get_selected_buff_index()
        if index is None:
            return
        del self.buff_skills[index]
        self._refresh_buff_tree()
        self._save_settings()

    def run_buff_skill(self) -> None:
        index = self._get_selected_buff_index()
        if index is None:
            return
        skill = self.buff_skills[index]
        self.append_log(f"테스트 실행 (버프): {skill.name}", "info")
        self._trigger_buff_skill(skill, is_test=True)

    def _refresh_attack_tree(self) -> None:
        if not hasattr(self, "attack_tree"):
            return
        self._ensure_primary_skill()
        self.attack_tree.blockSignals(True)
        self.attack_tree.clear()
        for idx, skill in enumerate(self.attack_skills):
            item = QTreeWidgetItem(self.attack_tree)
            item.setData(0, Qt.ItemDataRole.UserRole, idx)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(0, Qt.CheckState.Checked if skill.enabled else Qt.CheckState.Unchecked)
            item.setText(1, skill.name)
            item.setText(2, skill.command)
            item.setText(3, "주 스킬" if skill.is_primary else "-")
            condition_label = self._format_skill_condition(skill)
            item.setText(4, f"{condition_label} | {skill.probability}%")
        self.attack_tree.blockSignals(False)
        self._update_attack_buttons()

    def _refresh_buff_tree(self) -> None:
        if not hasattr(self, "buff_tree"):
            return
        self.buff_tree.blockSignals(True)
        self.buff_tree.clear()
        for idx, skill in enumerate(self.buff_skills):
            item = QTreeWidgetItem(self.buff_tree)
            item.setData(0, Qt.ItemDataRole.UserRole, idx)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(0, Qt.CheckState.Checked if skill.enabled else Qt.CheckState.Unchecked)
            item.setText(1, skill.name)
            item.setText(2, skill.command)
            item.setText(3, str(skill.cooldown_seconds))
            item.setText(4, f"{skill.jitter_percent}%")
        self.buff_tree.blockSignals(False)
        self._update_buff_buttons()

    def _format_skill_condition(self, skill: AttackSkill) -> str:
        min_count = max(1, getattr(skill, 'min_monsters', 1))
        max_count = getattr(skill, 'max_monsters', None)
        if isinstance(max_count, int) and max_count > 0:
            if max_count <= min_count:
                return f"= {min_count}마리"
            return f"{min_count}~{max_count}마리"
        return f">= {min_count}마리"

    def _parse_max_monsters(self, value) -> Optional[int]:
        if value in (None, "", False):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        if parsed <= 0:
            return None
        return parsed

    def _get_selected_attack_index(self) -> Optional[int]:
        if not hasattr(self, "attack_tree"):
            return None
        item = self.attack_tree.currentItem()
        if item is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _get_misc_command_profiles(self) -> List[str]:
        if not self.data_manager or not hasattr(self.data_manager, 'list_command_profiles'):
            return []
        try:
            profiles = self.data_manager.list_command_profiles(('기타',))
        except Exception:
            return []
        if isinstance(profiles, dict):
            names = profiles.get('기타', [])
        else:
            names = []
        return [str(name) for name in names if isinstance(name, str) and name]

    def _get_selected_buff_index(self) -> Optional[int]:
        if not hasattr(self, "buff_tree"):
            return None
        item = self.buff_tree.currentItem()
        if item is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _ensure_primary_skill(self) -> None:
        if not self.attack_skills:
            return
        primary_indices = [i for i, s in enumerate(self.attack_skills) if s.is_primary]
        if not primary_indices:
            self.attack_skills[0].is_primary = True
            self.attack_skills[0].enabled = True
        else:
            first = primary_indices[0]
            self.attack_skills[first].enabled = True
            for i in primary_indices[1:]:
                self.attack_skills[i].is_primary = False
        self._update_primary_release_settings()

    def _update_primary_release_settings(self) -> None:
        primary_skill = None
        for skill in self.attack_skills:
            if skill.is_primary and skill.enabled:
                primary_skill = skill
                break
        if not primary_skill:
            self._primary_release_command = ""
            self._primary_reset_range = (0, 0)
            self._primary_reset_remaining = None
            self._primary_reset_current_goal = None
            return

        min_val = max(0, getattr(primary_skill, 'primary_reset_min', 0))
        max_val = max(0, getattr(primary_skill, 'primary_reset_max', 0))
        command = str(getattr(primary_skill, 'primary_reset_command', '') or '').strip()

        if not command or (min_val <= 0 and max_val <= 0):
            self._primary_release_command = ""
            self._primary_reset_range = (0, 0)
            self._primary_reset_remaining = None
            self._primary_reset_current_goal = None
            return

        if max_val < min_val:
            min_val, max_val = max_val, min_val

        # 최소 1회 이상은 사용하도록 강제
        min_val = max(1, min_val)
        max_val = max(min_val, max_val)

        self._primary_release_command = command
        self._primary_reset_range = (min_val, max_val)
        self._primary_reset_remaining = None
        self._primary_reset_current_goal = None

    def _update_attack_buttons(self) -> None:
        if not hasattr(self, "add_attack_btn"):
            return
        index = self._get_selected_attack_index()
        has_selection = index is not None
        self.edit_attack_btn.setEnabled(has_selection)
        self.remove_attack_btn.setEnabled(has_selection)
        if has_selection:
            skill = self.attack_skills[index]
            self.set_primary_attack_btn.setEnabled(not skill.is_primary)
            self.test_attack_btn.setEnabled(self.current_authority == "hunt")
        else:
            self.set_primary_attack_btn.setEnabled(False)
            self.test_attack_btn.setEnabled(False)

    def _initialize_primary_reset_counter(self) -> None:
        command = self._primary_release_command
        min_val, max_val = self._primary_reset_range
        if not command or min_val <= 0 or max_val <= 0:
            self._primary_reset_remaining = None
            self._primary_reset_current_goal = None
            return
        goal = random.randint(min_val, max_val)
        self._primary_reset_current_goal = goal
        self._primary_reset_remaining = goal

    def _maybe_trigger_primary_release(self, skill: AttackSkill) -> None:
        if not getattr(skill, 'is_primary', False):
            return
        command = self._primary_release_command
        if not command:
            return
        if self._primary_reset_remaining is None:
            self._initialize_primary_reset_counter()
        if self._primary_reset_remaining is None:
            return
        if self._primary_reset_remaining > 0:
            return

        usage_count = self._primary_reset_current_goal or 1
        reason_suffix = f"주 스킬 사용 {usage_count}회"
        reason = f"primary_release|{reason_suffix}"
        self._emit_control_command(command, reason=reason)
        self._initialize_primary_reset_counter()

    def _decrement_primary_reset_counter(self, skill: AttackSkill) -> None:
        if not getattr(skill, 'is_primary', False):
            return
        if self._primary_reset_remaining is None:
            self._initialize_primary_reset_counter()
        if self._primary_reset_remaining is None:
            return
        if self._primary_reset_remaining <= 0:
            return
        self._primary_reset_remaining = max(0, self._primary_reset_remaining - 1)

    def _handle_command_completion_payload(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        payload_type = payload.get('type')
        if payload_type == 'attack':
            skill = payload.get('skill')
            if not isinstance(skill, AttackSkill):
                return
            if skill not in self.attack_skills:
                return
            if not skill.enabled:
                return
            self._decrement_primary_reset_counter(skill)
            self._maybe_trigger_primary_release(skill)

    def _update_buff_buttons(self) -> None:
        if not hasattr(self, "add_buff_btn"):
            return
        index = self._get_selected_buff_index()
        has_selection = index is not None
        self.edit_buff_btn.setEnabled(has_selection)
        self.remove_buff_btn.setEnabled(has_selection)
        self.test_buff_btn.setEnabled(has_selection and self.current_authority == "hunt")

    def _handle_attack_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is None:
            return
        idx = int(index)
        if 0 <= idx < len(self.attack_skills):
            self.attack_skills[idx].enabled = item.checkState(0) == Qt.CheckState.Checked
            if self.attack_skills[idx].is_primary and not self.attack_skills[idx].enabled:
                self.attack_skills[idx].enabled = True
                self.attack_tree.blockSignals(True)
                item.setCheckState(0, Qt.CheckState.Checked)
                self.attack_tree.blockSignals(False)
            self._update_attack_buttons()
            self._save_settings()

    def _handle_buff_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is None:
            return
        idx = int(index)
        if 0 <= idx < len(self.buff_skills):
            self.buff_skills[idx].enabled = item.checkState(0) == Qt.CheckState.Checked
            self._update_buff_buttons()
            self._save_settings()

    def append_log(self, message: str, level: str = "info") -> None:
        if level == "debug":
            return

        valid_levels = {"info", "warn", "success"}
        if level not in valid_levels:
            self._append_keyboard_log(message, color=level)
            return

        if level == "info" and message.lstrip().startswith("("):
            self._append_keyboard_log(message)
            return

        prefix_map = {
            "info": "[INFO]",
            "warn": "[WARN]",
            "success": "[OK]",
        }
        color_map = {
            "info": "cyan",
            "warn": "orange",
            "success": "lightgreen",
        }
        prefix = prefix_map.get(level, "[INFO]")
        timestamp = self._format_timestamp_ms()
        line = f"[{timestamp}] {prefix} {message}"
        if (
            hasattr(self, 'log_view')
            and self.log_view
            and self._is_log_enabled('main_log_checkbox')
        ):
            self._append_colored_text(self.log_view, line, color_map.get(level))

    def _append_log_detail(self, message: str) -> None:
        if (
            not hasattr(self, 'log_view')
            or not self.log_view
            or not self._is_log_enabled('main_log_checkbox')
        ):
            return
        timestamp = self._format_timestamp_ms()
        line = f"[{timestamp}]    {message}"
        self._append_colored_text(self.log_view, line, "gray")

    def cleanup_on_close(self) -> None:
        self.condition_timer.stop()
        if hasattr(self, 'hunt_loop_timer'):
            self.hunt_loop_timer.stop()
        self._cancel_facing_reset_timer()
        if self._condition_debounce_timer:
            self._condition_debounce_timer.stop()
        if self._request_timeout_timer:
            self._request_timeout_timer.stop()
        self._request_pending = False
        self._stop_perf_logging()
        for timer in list(self._pre_delay_timers.values()):
            try:
                timer.stop()
            except Exception:
                pass
            timer.deleteLater()
        self._pre_delay_timers.clear()
        self._pending_completion_delays.clear()
        self._stop_detection_thread()
        if self.data_manager and self._model_listener_registered and hasattr(self.data_manager, 'unregister_model_listener'):
            try:
                self.data_manager.unregister_model_listener(self._handle_model_changed)
            except Exception:
                pass
            self._model_listener_registered = False
        if self.status_monitor:
            try:
                self.status_monitor.status_captured.disconnect(self._handle_status_snapshot)
            except Exception:
                pass
            try:
                self.status_monitor.ocr_unavailable.disconnect(self._handle_status_ocr_unavailable)
            except Exception:
                pass
            try:
                self.status_monitor.exp_status_logged.disconnect(self._handle_exp_status_log)
            except Exception:
                pass
            self.status_monitor = None
        app = QApplication.instance()
        if app and getattr(self, 'hotkey_event_filter', None):
            try:
                app.removeNativeEventFilter(self.hotkey_event_filter)
            except Exception:
                pass
            self.hotkey_event_filter = None
        if getattr(self, 'hotkey_manager', None):
            try:
                self.hotkey_manager.unregister_hotkey()
            except Exception:
                pass
            self.hotkey_manager = None
        if hasattr(self, 'detect_btn'):
            self.detect_btn.setChecked(False)
            self.detect_btn.setText("사냥시작")
        self._authority_request_connected = False
        self._authority_release_connected = False
        self._save_settings()

    def _issue_all_keys_release(self, reason: Optional[str] = None) -> None:
        if not getattr(self, 'control_command_issued', None):
            return
        self._clear_pending_skill()
        self._clear_pending_direction()
        self._clear_direction_confirmation()
        send_release = not self._forbidden_priority_active
        if send_release:
            self._emit_control_command("모든 키 떼기", reason=reason)
            if isinstance(reason, str) and reason.strip():
                reason_text = reason.strip()
                if reason_text.startswith('status:'):
                    parts = reason_text.split(':')
                    resource = parts[1].strip().upper() if len(parts) >= 2 else ''
                    percent_text = ''
                    if len(parts) >= 3 and parts[2].strip():
                        try:
                            percent_value = int(round(float(parts[2].strip())))
                            percent_text = f" ({percent_value}%)"
                        except ValueError:
                            percent_text = ''
                    label = resource or 'STATUS'
                    reason_text = f"Status: {label}{percent_text}"
                elif reason_text.startswith('primary_release'):
                    parts = reason_text.split('|', 1)
                    reason_text = parts[1].strip() if len(parts) == 2 else ''
                if reason_text:
                    self.append_log(f"모든 키 떼기 명령 전송 (원인: {reason_text})", "debug")
                else:
                    self.append_log("모든 키 떼기 명령 전송", "debug")
            else:
                self.append_log("모든 키 떼기 명령 전송", "debug")
        else:
            self.append_log("금지벽 우선 이벤트 진행 중이라 '모든 키 떼기' 전송을 보류합니다.", "debug")
        self._release_pending = False
        self.hunting_active = False
        self._movement_mode = None
        self._reset_walk_teleport_state()

    def _ensure_idle_keys(self, reason: Optional[str] = None) -> None:
        self._clear_pending_skill()
        self._clear_pending_direction()
        self._clear_direction_confirmation()
        self._reset_walk_teleport_state()
        if self.hunting_active:
            self._issue_all_keys_release(reason)
