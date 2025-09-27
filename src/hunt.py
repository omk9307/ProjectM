from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
import time
from typing import List, Optional

import pygetwindow as gw

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRect
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QDoubleSpinBox,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QBrush

from detection_runtime import DetectionPopup, DetectionThread, ScreenSnipper
from direction_detection import DirectionDetector
from nickname_detection import NicknameDetector


CHARACTER_CLASS_NAME = "캐릭터"

SRC_ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(SRC_ROOT, '..', 'workspace'))
CONFIG_ROOT = os.path.join(WORKSPACE_ROOT, 'config')
HUNT_SETTINGS_FILE = os.path.join(CONFIG_ROOT, 'hunt_settings.json')

HUNT_AREA_COLOR = QColor(0, 170, 255, 70)
HUNT_AREA_EDGE = QPen(QColor(0, 120, 200, 200), 2, Qt.PenStyle.DashLine)
HUNT_AREA_BRUSH = QBrush(HUNT_AREA_COLOR)
PRIMARY_AREA_COLOR = QColor(255, 140, 0, 70)
PRIMARY_AREA_EDGE = QPen(QColor(230, 110, 0, 220), 2, Qt.PenStyle.SolidLine)
PRIMARY_AREA_BRUSH = QBrush(PRIMARY_AREA_COLOR)
FALLBACK_CHARACTER_EDGE = QPen(QColor(0, 255, 120, 220), 2, Qt.PenStyle.SolidLine)
FALLBACK_CHARACTER_BRUSH = QBrush(QColor(0, 255, 120, 60))
NICKNAME_EDGE = QPen(QColor(255, 255, 0, 220), 2, Qt.PenStyle.DotLine)
DIRECTION_ROI_EDGE = QPen(QColor(170, 80, 255, 200), 1, Qt.PenStyle.DashLine)
DIRECTION_MATCH_EDGE_LEFT = QPen(QColor(0, 200, 255, 220), 2, Qt.PenStyle.SolidLine)
DIRECTION_MATCH_EDGE_RIGHT = QPen(QColor(255, 200, 0, 220), 2, Qt.PenStyle.SolidLine)
MONSTER_LOSS_GRACE_SEC = 0.2  # 단기 미검출 시 방향 유지용 유예시간(초)

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
    probability: int = 100
    post_delay_min: float = 0.43
    post_delay_max: float = 0.46
    completion_delay_min: float = 0.0
    completion_delay_max: float = 0.0


@dataclass
class BuffSkill:
    name: str
    command: str
    cooldown_seconds: int
    enabled: bool = True
    jitter_percent: int = 15
    last_triggered_ts: float = 0.0
    next_ready_ts: float = 0.0
    post_delay_min: float = 0.43
    post_delay_max: float = 0.46
    completion_delay_min: float = 0.0
    completion_delay_max: float = 0.0


@dataclass
class TeleportSettings:
    enabled: bool = False
    distance_px: float = 190.0
    probability: int = 50


class AttackSkillDialog(QDialog):
    """공격 스킬 정보를 입력/수정하기 위한 대화상자."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        skill: Optional[AttackSkill] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("공격 스킬")

        self.name_input = QLineEdit()
        self.command_input = QLineEdit()
        self.enabled_checkbox = QCheckBox("사용")
        self.enabled_checkbox.setChecked(True)
        self.primary_checkbox = QCheckBox("주 공격 스킬로 설정")
        self.primary_checkbox.setChecked(False)

        self.min_monsters_spinbox = QSpinBox()
        self.min_monsters_spinbox.setRange(1, 50)
        self.min_monsters_spinbox.setValue(1)

        self.probability_spinbox = QSpinBox()
        self.probability_spinbox.setRange(0, 100)
        self.probability_spinbox.setValue(100)
        self.probability_spinbox.setSuffix(" %")

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

        if skill:
            self.name_input.setText(skill.name)
            self.command_input.setText(skill.command)
            self.enabled_checkbox.setChecked(skill.enabled)
            self.primary_checkbox.setChecked(skill.is_primary)
            self.min_monsters_spinbox.setValue(skill.min_monsters)
            self.probability_spinbox.setValue(skill.probability)
            self.delay_min_spinbox.setValue(skill.post_delay_min)
            self.delay_max_spinbox.setValue(skill.post_delay_max)
            self.completion_min_spinbox.setValue(getattr(skill, 'completion_delay_min', 0.0))
            self.completion_max_spinbox.setValue(getattr(skill, 'completion_delay_max', 0.0))

        form = QFormLayout()
        form.addRow("이름", self.name_input)
        form.addRow("명령", self.command_input)
        form.addRow("사용", self.enabled_checkbox)
        form.addRow("주 스킬", self.primary_checkbox)
        form.addRow("사용 최소 몬스터 수", self.min_monsters_spinbox)
        form.addRow("사용 확률", self.probability_spinbox)
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

    def get_skill(self) -> Optional[AttackSkill]:
        name = self.name_input.text().strip()
        command = self.command_input.text().strip()
        if not name or not command:
            return None
        return AttackSkill(
            name=name,
            command=command,
            enabled=self.enabled_checkbox.isChecked(),
            is_primary=self.primary_checkbox.isChecked(),
            min_monsters=self.min_monsters_spinbox.value(),
            probability=self.probability_spinbox.value(),
            post_delay_min=min(self.delay_min_spinbox.value(), self.delay_max_spinbox.value()),
            post_delay_max=max(self.delay_min_spinbox.value(), self.delay_max_spinbox.value()),
            completion_delay_min=min(self.completion_min_spinbox.value(), self.completion_max_spinbox.value()),
            completion_delay_max=max(self.completion_min_spinbox.value(), self.completion_max_spinbox.value()),
        )


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
            post_delay_min=min(self.delay_min_spinbox.value(), self.delay_max_spinbox.value()),
            post_delay_max=max(self.delay_min_spinbox.value(), self.delay_max_spinbox.value()),
            completion_delay_min=min(self.completion_min_spinbox.value(), self.completion_max_spinbox.value()),
            completion_delay_max=max(self.completion_min_spinbox.value(), self.completion_max_spinbox.value()),
       )


class HuntTab(QWidget):
    """사냥 조건과 스킬 실행을 관리하는 임시 탭."""

    CONTROL_RELEASE_TIMEOUT_SEC = 30
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
        self.last_control_acquired_ts = 0.0
        self.last_release_attempt_ts = 0.0
        self.auto_hunt_enabled = True
        self.overlay_preferences = {
            'hunt_area': True,
            'primary_area': True,
            'direction_area': True,
        }
        self._direction_area_user_pref = True
        self._last_character_boxes: List[DetectionBox] = []
        self._last_character_details: List[dict] = []
        self._last_character_seen_ts: float = 0.0
        self._using_character_fallback: bool = False
        self._nickname_config: dict = {}
        self._nickname_templates: list[dict] = []
        self._latest_nickname_box: Optional[dict] = None
        self._last_nickname_match: Optional[dict] = None

        self.attack_interval_sec = 0.35
        self.last_attack_ts = 0.0
        self.last_facing: Optional[str] = None
        self.hunting_active = False
        self._pending_skill_timer: Optional[QTimer] = None
        self._pending_skill: Optional[AttackSkill] = None
        self._pending_direction_timer: Optional[QTimer] = None
        self._pending_direction_side: Optional[str] = None
        self._pending_direction_skill: Optional[AttackSkill] = None
        self._last_monster_seen_ts = time.time()
        self._next_command_ready_ts = 0.0
        self._last_condition_poll_ts = 0.0
        self._request_pending = False
        self._cached_monster_boxes: List[DetectionBox] = []
        self._cached_monster_boxes_ts = 0.0

        self.detection_thread: Optional[DetectionThread] = None
        self.detection_popup: Optional[DetectionPopup] = None
        self.is_popup_active = False
        self.last_popup_scale = 50
        self.manual_capture_region: Optional[dict] = None
        self.last_used_model: Optional[str] = None
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
            'direction': None,
        }
        self.latest_perf_stats = {
            'fps': 0.0,
            'total_ms': 0.0,
            'yolo_ms': 0.0,
            'nickname_ms': 0.0,
            'direction_ms': 0.0,
        }
        self._active_target_names: List[str] = []

        self.teleport_settings = TeleportSettings()
        self.teleport_command_left = "텔레포트(좌)"
        self.teleport_command_right = "텔레포트(우)"
        self.teleport_command_left_v2 = "텔레포트(좌)v2"
        self.teleport_command_right_v2 = "텔레포트(우)v2"
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
        self._show_direction_overlay_config = True
        self._direction_detector_available = False
        self._last_direction_score: Optional[float] = None
        self._pending_completion_delays: list[dict] = []

        self._build_ui()
        self._update_facing_label()
        self._load_settings()
        self._setup_timers()
        self._setup_facing_reset_timer()

    def _setup_facing_reset_timer(self) -> None:
        self.facing_reset_timer = QTimer(self)
        self.facing_reset_timer.setSingleShot(True)
        self.facing_reset_timer.timeout.connect(self._handle_facing_reset_timeout)

    def _is_detection_active(self) -> bool:
        return bool(self.detect_btn.isChecked())

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

    def _format_delay_ms(self, delay_sec: float) -> str:
        return f"{max(0.0, delay_sec) * 1000:.0f}ms"

    def _log_delay_message(self, context: str, delay_sec: float) -> None:
        if delay_sec <= 0:
            return
        message = f"{context} 후 대기 {self._format_delay_ms(delay_sec)}"
        self._append_control_log(message)

    def _queue_completion_delay(self, command: str, min_delay: float, max_delay: float, context: str) -> None:
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
        })

    def _pop_completion_delay(self, command: str) -> Optional[dict]:
        if not command:
            return None
        for idx, entry in enumerate(self._pending_completion_delays):
            if entry.get('command') == command:
                return self._pending_completion_delays.pop(idx)
        return None

    def on_sequence_completed(self, command_name: str, _reason: object, success: bool) -> None:
        command = str(command_name) if command_name else ''
        entry = self._pop_completion_delay(command)
        if not entry:
            return
        if not success:
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
        misc_group = self._create_misc_group()

        left_column.addWidget(detection_group)

        range_misc_row = QHBoxLayout()
        range_misc_row.setSpacing(10)
        range_misc_row.addWidget(range_group, 1)
        range_misc_row.addWidget(misc_group, 1)
        left_column.addLayout(range_misc_row)

        condition_row = QHBoxLayout()
        condition_row.setSpacing(10)
        condition_row.addWidget(condition_group, 1)
        condition_row.addStretch(1)
        left_column.addLayout(condition_row)
        left_column.addStretch(1)

        right_column = QVBoxLayout()
        right_column.setSpacing(10)

        model_group = self._create_model_group()
        skill_group = self._create_skill_group()

        right_column.addWidget(model_group)
        right_column.addWidget(skill_group, 1)
        right_column.addStretch(1)

        main_layout.addLayout(left_column, 5)
        main_layout.addLayout(right_column, 5)
        main_layout.setStretch(0, 5)
        main_layout.setStretch(1, 5)

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

        self.monster_threshold_spinbox = QSpinBox()
        self.monster_threshold_spinbox.setRange(1, 50)
        self.monster_threshold_spinbox.setValue(3)
        condition_form.addRow("기준 몬스터 수", self.monster_threshold_spinbox)
        self.monster_threshold_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.idle_release_spinbox = QDoubleSpinBox()
        self.idle_release_spinbox.setRange(0.5, 30.0)
        self.idle_release_spinbox.setSingleStep(0.5)
        self.idle_release_spinbox.setDecimals(1)
        self.idle_release_spinbox.setValue(2.0)
        condition_form.addRow("최근 미탐지 후 반납(초)", self.idle_release_spinbox)
        self.idle_release_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.max_authority_hold_spinbox = QDoubleSpinBox()
        self.max_authority_hold_spinbox.setRange(1.0, 600.0)
        self.max_authority_hold_spinbox.setSingleStep(1.0)
        self.max_authority_hold_spinbox.setDecimals(1)
        self.max_authority_hold_spinbox.setValue(float(self.CONTROL_RELEASE_TIMEOUT_SEC))
        condition_form.addRow("최대 이동권한 보유 시간(초)", self.max_authority_hold_spinbox)
        self.max_authority_hold_spinbox.valueChanged.connect(self._handle_max_hold_changed)

        group.setLayout(condition_form)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        return group

    def _create_misc_group(self) -> QGroupBox:
        group = QGroupBox("기타 조건")
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

    def _create_model_group(self) -> QGroupBox:
        group = QGroupBox("사용 모델")
        model_layout = QHBoxLayout()
        self.model_selector = QComboBox()
        self.model_selector.setPlaceholderText("학습 탭과 연동 필요")
        self.refresh_model_btn = QPushButton("새로고침")
        self.refresh_model_btn.clicked.connect(self.refresh_model_choices)
        model_layout.addWidget(self.model_selector, 1)
        model_layout.addWidget(self.refresh_model_btn)
        group.setLayout(model_layout)
        return group

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

        target_layout = QHBoxLayout()
        self.auto_target_radio = QRadioButton("자동 (Maple 창)")
        self.auto_target_radio.setChecked(True)
        self.manual_target_radio = QRadioButton("수동 (영역 지정)")
        target_layout.addWidget(self.auto_target_radio)
        target_layout.addWidget(self.manual_target_radio)

        self.set_area_btn = QPushButton("영역 지정")
        self.set_area_btn.setEnabled(False)
        self.set_area_btn.clicked.connect(self._set_manual_area)
        self.manual_target_radio.toggled.connect(self._handle_capture_mode_toggle)
        self.auto_target_radio.toggled.connect(self._handle_setting_changed)
        target_layout.addWidget(self.set_area_btn)

        control_row = QHBoxLayout()
        control_row.setSpacing(12)

        control_row.addLayout(target_layout)

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

        control_row.addStretch(1)
        control_layout.addLayout(control_row)

        self.screen_output_checkbox = QCheckBox("화면 출력")
        self.screen_output_checkbox.setChecked(False)
        self.screen_output_checkbox.toggled.connect(self._on_screen_output_toggled)

        self.show_hunt_area_checkbox = QCheckBox("사냥범위")
        self.show_hunt_area_checkbox.setChecked(True)
        self.show_hunt_area_checkbox.toggled.connect(self._on_overlay_toggle_changed)

        self.show_primary_skill_checkbox = QCheckBox("스킬범위")
        self.show_primary_skill_checkbox.setChecked(True)
        self.show_primary_skill_checkbox.toggled.connect(self._on_overlay_toggle_changed)

        self.show_direction_checkbox = QCheckBox("방향범위")
        self.show_direction_checkbox.setChecked(True)
        self.show_direction_checkbox.toggled.connect(self._on_overlay_toggle_changed)

        self.auto_request_checkbox = QCheckBox("자동사냥")
        self.auto_request_checkbox.toggled.connect(self._handle_setting_changed)

        for checkbox in (
            self.screen_output_checkbox,
            self.show_hunt_area_checkbox,
            self.show_primary_skill_checkbox,
            self.show_direction_checkbox,
            self.auto_request_checkbox,
        ):
            checkbox.setSizePolicy(
                QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            )

        button_row = QHBoxLayout()
        self.detect_btn = QPushButton("실시간 탐지 시작")
        self.detect_btn.setCheckable(True)
        self.detect_btn.clicked.connect(self._toggle_detection)
        button_row.addWidget(self.detect_btn)

        self.popup_btn = QPushButton("↗")
        self.popup_btn.setFixedSize(24, 24)
        self.popup_btn.setToolTip("탐지 화면을 팝업으로 열기")
        self.popup_btn.clicked.connect(self._toggle_detection_popup)
        button_row.addWidget(self.popup_btn)

        button_row.addSpacing(12)
        button_row.addWidget(self.screen_output_checkbox)
        button_row.addWidget(self.show_hunt_area_checkbox)
        button_row.addWidget(self.show_primary_skill_checkbox)
        button_row.addWidget(self.show_direction_checkbox)
        button_row.addWidget(self.auto_request_checkbox)

        button_row.addStretch(1)
        control_layout.addLayout(button_row)

        control_container.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        outer_layout.addWidget(control_container)

        self.detection_view = None

        control_log_container = QVBoxLayout()
        control_log_label = QLabel("입력 로그")
        self.control_log_view = QTextEdit()
        self.control_log_view.setReadOnly(True)
        self.control_log_view.setMinimumHeight(100)
        self.control_log_view.setStyleSheet("font-family: Consolas, monospace;")
        control_log_container.addWidget(control_log_label)
        control_log_container.addWidget(self.control_log_view)
        outer_layout.addLayout(control_log_container)

        keyboard_log_container = QVBoxLayout()
        keyboard_log_label = QLabel("키보드 입력 로그")
        self.keyboard_log_view = QTextEdit()
        self.keyboard_log_view.setReadOnly(True)
        self.keyboard_log_view.setMinimumHeight(100)
        self.keyboard_log_view.setStyleSheet("font-family: Consolas, monospace;")
        keyboard_log_container.addWidget(keyboard_log_label)
        keyboard_log_container.addWidget(self.keyboard_log_view)
        outer_layout.addLayout(keyboard_log_container)

        log_container = QVBoxLayout()
        log_label = QLabel("로그")
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(120)
        self.log_view.setStyleSheet("font-family: Consolas, monospace;")
        log_container.addWidget(log_label)
        log_container.addWidget(self.log_view)
        outer_layout.addLayout(log_container)

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

    def _set_manual_area(self) -> None:
        snipper = ScreenSnipper(self)
        if snipper.exec():
            roi = snipper.get_roi()
            self.manual_capture_region = {
                'top': roi.top(),
                'left': roi.left(),
                'width': roi.width(),
                'height': roi.height(),
            }
            self.append_log(f"수동 탐지 영역 설정 완료: {self.manual_capture_region}")
            self._save_settings()

    def _toggle_detection(self, checked: bool) -> None:
        if checked:
            if not self.data_manager:
                QMessageBox.warning(self, "오류", "학습 탭과의 연동이 필요합니다.")
                self.detect_btn.setChecked(False)
                return

            selected_model = self.model_selector.currentText().strip()
            if not selected_model or not self.model_selector.isEnabled():
                QMessageBox.warning(self, "오류", "사용할 모델을 선택하세요.")
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

            if self.auto_target_radio.isChecked():
                target_windows = gw.getWindowsWithTitle('Maple') or gw.getWindowsWithTitle('메이플')
                if not target_windows:
                    QMessageBox.warning(self, '오류', '메이플스토리 창을 찾을 수 없습니다.')
                    self.detect_btn.setChecked(False)
                    return
                win = target_windows[0]
                if win.isMinimized:
                    win.restore()
                capture_region = {
                    'top': win.top,
                    'left': win.left,
                    'width': win.width,
                    'height': win.height,
                }
            else:
                if not self.manual_capture_region:
                    QMessageBox.warning(self, '오류', "'영역 지정'으로 탐지 영역을 설정해주세요.")
                    self.detect_btn.setChecked(False)
                    return
                capture_region = self.manual_capture_region

            if capture_region['width'] <= 0 or capture_region['height'] <= 0:
                QMessageBox.warning(self, '오류', '탐지 영역 크기가 유효하지 않습니다.')
                self.detect_btn.setChecked(False)
                return

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

            self._reset_character_cache()
            self._direction_active = False
            self._direction_last_seen_ts = 0.0
            self._direction_last_side = None
            self._latest_direction_roi = None
            self._latest_direction_match = None
            self._direction_detector_available = direction_detector_instance is not None
            self.append_log("YOLO 캐릭터 탐지를 사용하지 않고 닉네임 기반 탐지에 의존합니다.", "info")

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
                    show_direction_overlay=self._is_direction_range_overlay_active(),
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
            self._update_detection_thread_overlay_flags()
            self._sync_detection_thread_status()
            if self.detection_view:
                self.detection_view.setText("탐지 준비 중...")
                self.detection_view.setPixmap(QPixmap())
            self.detect_btn.setText("실시간 탐지 중단")

            if hasattr(self.data_manager, 'save_settings'):
                self.data_manager.save_settings({'last_used_model': selected_model})
            self.last_used_model = selected_model
            self.append_log(f"탐지 시작: 모델={selected_model}, 범위={capture_region}")
            if self._active_target_names:
                target_list_text = ", ".join(self._active_target_names)
                self.append_log(f"탐지 대상: {target_list_text}", "info")
            self._set_current_facing(None, save=False)
            self._schedule_facing_reset()

            if self.screen_output_checkbox.isChecked() and not self.is_popup_active:
                self._toggle_detection_popup()
        else:
            thread_active = self.detection_thread is not None and self.detection_thread.isRunning()
            self._release_pending = True
            self._stop_detection_thread()
            self.detect_btn.setText("실시간 탐지 시작")
            if self.detection_view:
                self.detection_view.setText("탐지 중단됨")
                self.detection_view.setPixmap(QPixmap())
            self.clear_detection_snapshot()
            self._cancel_facing_reset_timer()
            if not thread_active:
                self._issue_all_keys_release("실시간 탐지 중단")

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
        self._cancel_facing_reset_timer()

    def _on_detection_thread_finished(self) -> None:
        self.detect_btn.setChecked(False)
        self.detect_btn.setText("실시간 탐지 시작")
        if not self.is_popup_active and self.detection_view:
            self.detection_view.setText("탐지 중단됨")
            self.detection_view.setPixmap(QPixmap())
        self.detection_thread = None
        self._cancel_facing_reset_timer()
        self._issue_all_keys_release("탐지 스레드 종료")
        self.clear_detection_snapshot()

    def _handle_detection_log(self, messages: List[str]) -> None:
        for msg in messages:
            self.append_log(msg, "debug")

    def _handle_detection_frame(self, q_image) -> None:
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
        show_info = self.show_info_summary_checkbox.isChecked()

        if show_confidence:
            characters = self.latest_detection_details.get('characters', [])
            monsters = self.latest_detection_details.get('monsters', [])

            lines: List[str] = []

            if characters:
                best_char = max(characters, key=lambda item: float(item.get('score', 0.0)))
                lines.append(
                    f"캐릭터: 신뢰도 {float(best_char.get('score', 0.0)):.2f}"
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

            self.confidence_summary_view.setPlainText('\n'.join(lines))
        else:
            self.confidence_summary_view.clear()

        if show_info:
            perf = getattr(self, 'latest_perf_stats', {}) or {}
            fps = float(perf.get('fps', 0.0))
            total_ms = float(perf.get('total_ms', 0.0))
            yolo_ms = float(perf.get('yolo_ms', 0.0))
            nickname_ms = float(perf.get('nickname_ms', 0.0))
            direction_ms = float(perf.get('direction_ms', 0.0))

            fps_line = f"FPS: {fps:.0f}"
            total_line = (
                f"Total: {total_ms:.1f} ms ( {yolo_ms:.1f} ms + {nickname_ms:.1f} ms + {direction_ms:.1f} ms)"
            )

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

            info_lines = [
                fps_line,
                total_line,
                f"이동권한: {authority_text}",
                f"X축 범위 내 몬스터: {self.latest_monster_count}",
                f"스킬 범위 몬스터: {self.latest_primary_monster_count}",
                direction_line,
            ]

            self.info_summary_view.setPlainText('\n'.join(info_lines))
        else:
            self.info_summary_view.clear()

    def _on_summary_checkbox_changed(self, _checked: bool) -> None:
        self._update_detection_summary()
        self._save_settings()

    def _on_screen_output_toggled(self, checked: bool) -> None:
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

    def _is_nickname_overlay_active(self) -> bool:
        return bool(self._show_nickname_overlay_config)

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

    def _toggle_detection_popup(self) -> None:
        if self.is_popup_active:
            if self.detection_popup:
                self.detection_popup.close()
            return

        self.is_popup_active = True
        self.popup_btn.setText("↙")
        self.popup_btn.setToolTip("탐지 화면을 메인 창으로 복귀")

        if not self.detection_popup:
            self.detection_popup = DetectionPopup(self.last_popup_scale, self)
            self.detection_popup.closed.connect(self._handle_popup_closed)
            self.detection_popup.scale_changed.connect(self._on_popup_scale_changed)

        self.detection_popup.set_waiting_message()
        if self.detection_view:
            self.detection_view.setText("탐지 화면이 팝업으로 표시 중입니다.")
            self.detection_view.setPixmap(QPixmap())
        self.detection_popup.show()

    def _on_popup_scale_changed(self, value: int) -> None:
        self.last_popup_scale = value
        self._save_settings()

    def _handle_popup_closed(self) -> None:
        self.is_popup_active = False
        self.popup_btn.setText("↗")
        self.popup_btn.setToolTip("탐지 화면을 팝업으로 열기")
        if self.detection_view:
            if self.detect_btn.isChecked():
                self.detection_view.setText("탐지 준비 중...")
                self.detection_view.setPixmap(QPixmap())
            else:
                self.detection_view.setText("탐지 중단됨")
                self.detection_view.setPixmap(QPixmap())

        self.detection_popup = None

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
        group = QGroupBox("탐지 요약")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)

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
        self.confidence_summary_view.setMinimumHeight(140)
        self.confidence_summary_view.setStyleSheet("font-family: Consolas, monospace;")
        confidence_layout.addLayout(confidence_header)
        confidence_layout.addWidget(self.confidence_summary_view)
        content_layout.addWidget(self.summary_confidence_container, 1)

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
        box = QGroupBox("텔레포트 이동")
        form = QFormLayout()

        self.teleport_enabled_checkbox = QCheckBox("사용")
        self.teleport_enabled_checkbox.setChecked(self.teleport_settings.enabled)
        self.teleport_enabled_checkbox.toggled.connect(self._handle_setting_changed)

        self.teleport_distance_spinbox = QSpinBox()
        self.teleport_distance_spinbox.setRange(50, 600)
        self.teleport_distance_spinbox.setSingleStep(10)
        self.teleport_distance_spinbox.setValue(int(self.teleport_settings.distance_px))
        self.teleport_distance_spinbox.setSuffix(" px")
        self.teleport_distance_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.teleport_probability_spinbox = QSpinBox()
        self.teleport_probability_spinbox.setRange(0, 100)
        self.teleport_probability_spinbox.setValue(int(self.teleport_settings.probability))
        self.teleport_probability_spinbox.setSuffix(" %")
        self.teleport_probability_spinbox.valueChanged.connect(self._handle_setting_changed)

        form.addRow("사용", self.teleport_enabled_checkbox)
        form.addRow("텔레포트 이동(px)", self.teleport_distance_spinbox)
        form.addRow("사용 확률(%)", self.teleport_probability_spinbox)

        box.setLayout(form)
        return box

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
        self._emit_area_overlays()
        self._update_detection_thread_overlay_flags()
        self._save_settings()

    def _update_detection_thread_overlay_flags(self) -> None:
        if not self.detection_thread:
            return
        self.detection_thread.show_nickname_overlay = bool(self._is_nickname_overlay_active())
        self.detection_thread.show_direction_overlay = bool(self._is_direction_range_overlay_active())

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
        self._emit_area_overlays()
        self._update_detection_thread_overlay_flags()
        self._save_settings()

    def _log_control_request(self, payload: dict, reason: str | None) -> None:
        threshold = payload.get("monster_threshold")
        range_px = payload.get("range_px")
        primary_range = payload.get("primary_skill_range")
        model = payload.get("model") or "-"
        attack_count = payload.get("attack_skill_count", 0)
        buff_count = payload.get("buff_skill_count", 0)
        latest_total = payload.get("latest_monster_count")
        latest_primary = payload.get("latest_primary_monster_count")

        detail_parts = [
            f"현재 몬스터 {latest_total}마리 / 주 스킬 {latest_primary}마리",
            f"기준 {threshold}마리, 사냥범위 ±{range_px}px, 주 스킬 범위 ±{primary_range}px",
            f"모델 '{model}', 공격 스킬 {attack_count}개, 버프 스킬 {buff_count}개",
        ]
        if reason:
            detail_parts.append(f"요청 사유: {reason}")
        self.append_log("사냥 권한 요청", "info")
        if hasattr(self, 'log_view'):
            for line in detail_parts:
                self.log_view.append(f"    {line}")

    def _handle_capture_mode_toggle(self, checked: bool) -> None:
        if hasattr(self, 'set_area_btn'):
            self.set_area_btn.setEnabled(bool(checked))
        self._save_settings()

    def _handle_setting_changed(self, *args, **kwargs) -> None:
        self._save_settings()

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
        self.control_release_timeout = max(1.0, float(value))
        self._save_settings()

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
        if (
            self._get_command_delay_remaining() > 0
            and command not in ("모든 키 떼기",)
            and not normalized.startswith("방향설정(")
        ):
            return
        if not command:
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

        reason_text = reason.strip() if isinstance(reason, str) else ""
        log_message = f"{normalized} (원인: {reason_text})" if reason_text else normalized
        self._append_control_log(log_message)

    def _append_control_log(self, message: str) -> None:
        timestamp = self._format_timestamp_ms()
        if hasattr(self, 'control_log_view'):
            self.control_log_view.append(f"[{timestamp}] {message}")
        self._append_keyboard_log(message, timestamp)

    def _set_command_cooldown(self, delay_sec: float) -> None:
        delay_sec = max(0.0, float(delay_sec))
        if delay_sec <= 0.0:
            self._next_command_ready_ts = max(self._next_command_ready_ts, time.time())
            return
        ready_time = time.time() + delay_sec
        self._next_command_ready_ts = max(self._next_command_ready_ts, ready_time)

    def _get_command_delay_remaining(self) -> float:
        return max(0.0, self._next_command_ready_ts - time.time())

    def _append_keyboard_log(self, message: str, timestamp: Optional[str] = None) -> None:
        if not hasattr(self, 'keyboard_log_view'):
            return
        if timestamp is None:
            timestamp = self._format_timestamp_ms()
        self.keyboard_log_view.append(f"[{timestamp}] {message}")

    def handle_detection_payload(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return

        characters_data = payload.get('characters') or []
        monsters_data = payload.get('monsters') or []
        nickname_data = payload.get('nickname')
        perf_data = payload.get('perf') or {}

        if isinstance(perf_data, dict):
            try:
                self.latest_perf_stats['fps'] = float(perf_data.get('fps', self.latest_perf_stats['fps']))
            except (TypeError, ValueError):
                pass
            try:
                self.latest_perf_stats['total_ms'] = float(perf_data.get('total_ms', self.latest_perf_stats['total_ms']))
            except (TypeError, ValueError):
                pass
            try:
                self.latest_perf_stats['yolo_ms'] = float(perf_data.get('yolo_ms', self.latest_perf_stats['yolo_ms']))
            except (TypeError, ValueError):
                pass
            try:
                self.latest_perf_stats['nickname_ms'] = float(perf_data.get('nickname_ms', self.latest_perf_stats['nickname_ms']))
            except (TypeError, ValueError):
                pass
            try:
                self.latest_perf_stats['direction_ms'] = float(perf_data.get('direction_ms', self.latest_perf_stats['direction_ms']))
            except (TypeError, ValueError):
                pass
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
        fallback_used = False
        nickname_used = False
        nickname_record = None

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
            'direction': direction_record,
        }
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
        self.latest_detection_details = {'characters': [], 'monsters': [], 'nickname': None, 'direction': None}
        self._reset_character_cache()
        self._direction_active = False
        self._direction_last_side = None
        self._direction_last_seen_ts = 0.0
        self._last_direction_score = None
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
        using_cached_monsters = False

        if raw_monsters:
            effective_monsters = raw_monsters
            self._cached_monster_boxes = [DetectionBox(**vars(box)) for box in raw_monsters]
            self._cached_monster_boxes_ts = now
        else:
            if (
                self._cached_monster_boxes
                and now - self._cached_monster_boxes_ts <= MONSTER_LOSS_GRACE_SEC
            ):
                effective_monsters = [DetectionBox(**vars(box)) for box in self._cached_monster_boxes]
                using_cached_monsters = True
            else:
                effective_monsters = []
                self._cached_monster_boxes = []
                self._cached_monster_boxes_ts = 0.0

        if using_cached_monsters:
            self.latest_snapshot.monster_boxes = effective_monsters

        hunt_count = sum(1 for box in effective_monsters if box.intersects(hunt_area))
        primary_count = sum(
            1 for box in effective_monsters if primary_area and box.intersects(primary_area)
        )

        self.latest_monster_count = hunt_count
        self.latest_primary_monster_count = primary_count

        if primary_count > 0 or self.latest_monster_count >= max(1, self.monster_threshold_spinbox.value() if hasattr(self, 'monster_threshold_spinbox') else 1):
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
        self._update_monster_count_label()
        self._emit_area_overlays()
        self.monster_stats_updated.emit(0, 0)

    def _get_recent_monster_boxes(self) -> List[DetectionBox]:
        if self.latest_snapshot and self.latest_snapshot.monster_boxes:
            return self.latest_snapshot.monster_boxes
        now = time.time()
        if (
            self._cached_monster_boxes
            and now - self._cached_monster_boxes_ts <= MONSTER_LOSS_GRACE_SEC
        ):
            return [DetectionBox(**vars(box)) for box in self._cached_monster_boxes]
        return []

    def _apply_detected_direction(self, side: str, score: float) -> None:
        if side not in ('left', 'right'):
            return
        self._direction_active = True
        self._direction_last_seen_ts = time.time()
        self._direction_last_side = side
        self._last_direction_score = float(score)
        self._cancel_facing_reset_timer()
        self._set_current_facing(side, save=False, from_direction=True)

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

    def _handle_overlay_config_update(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        target = payload.get('target')
        show_overlay = bool(payload.get('show_overlay', True))
        if target == 'nickname':
            self._show_nickname_overlay_config = show_overlay
            if not show_overlay:
                self._latest_nickname_box = None
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
        self.refresh_model_choices()
        if hasattr(self.data_manager, 'load_settings'):
            settings = self.data_manager.load_settings()
            self.last_used_model = settings.get('last_used_model')
            if self.last_used_model:
                index = self.model_selector.findText(self.last_used_model)
                if index >= 0:
                    self.model_selector.setCurrentIndex(index)
        self.append_log("학습 데이터 연동 완료", "info")
        self._save_settings()
        self._load_nickname_configuration()
        self._load_direction_configuration()

    def set_authority_bridge_active(self, request_connected: bool, release_connected: bool) -> None:
        self._authority_request_connected = bool(request_connected)
        self._authority_release_connected = bool(release_connected)

    def _load_settings(self) -> None:
        self._suppress_settings_save = True
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
            self.monster_threshold_spinbox.setValue(int(conditions.get('monster_threshold', self.monster_threshold_spinbox.value())))
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
            auto_target = bool(display.get('auto_target', self.auto_target_radio.isChecked()))
            screen_output_enabled = bool(
                display.get(
                    'screen_output',
                    display.get('debug', self.screen_output_checkbox.isChecked()),
                )
            )
            summary_confidence = bool(display.get('summary_confidence', self.show_confidence_summary_checkbox.isChecked()))
            summary_info = bool(display.get('summary_info', self.show_info_summary_checkbox.isChecked()))

            self.show_hunt_area_checkbox.setChecked(show_hunt)
            self.show_primary_skill_checkbox.setChecked(show_primary)
            self.show_direction_checkbox.setChecked(show_direction)
            self.auto_target_radio.setChecked(auto_target)
            self.manual_target_radio.setChecked(not auto_target)
            self.screen_output_checkbox.setChecked(screen_output_enabled)
            self.show_confidence_summary_checkbox.setChecked(summary_confidence)
            self.show_info_summary_checkbox.setChecked(summary_info)

        self.manual_capture_region = data.get('manual_capture_region', self.manual_capture_region)
        self.set_area_btn.setEnabled(self.manual_target_radio.isChecked())

        self.overlay_preferences['hunt_area'] = self.show_hunt_area_checkbox.isChecked()
        self.overlay_preferences['primary_area'] = self.show_primary_skill_checkbox.isChecked()
        self.overlay_preferences['direction_area'] = self.show_direction_checkbox.isChecked()
        self._direction_area_user_pref = self.overlay_preferences['direction_area']

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

        teleport = data.get('teleport', {})
        if teleport:
            self.teleport_settings.enabled = bool(teleport.get('enabled', self.teleport_settings.enabled))
            self.teleport_settings.distance_px = float(teleport.get('distance_px', self.teleport_settings.distance_px))
            self.teleport_settings.probability = int(teleport.get('probability', self.teleport_settings.probability))
            self.teleport_command_left = teleport.get('command_left', self.teleport_command_left)
            self.teleport_command_right = teleport.get('command_right', self.teleport_command_right)
            self.teleport_command_left_v2 = teleport.get('command_left_v2', self.teleport_command_left_v2)
            self.teleport_command_right_v2 = teleport.get('command_right_v2', self.teleport_command_right_v2)
            self.teleport_enabled_checkbox.setChecked(self.teleport_settings.enabled)
            self.teleport_distance_spinbox.setValue(int(self.teleport_settings.distance_px))
            self.teleport_probability_spinbox.setValue(int(self.teleport_settings.probability))

        facing_state = data.get('last_facing')
        self._set_current_facing(facing_state if facing_state in ('left', 'right') else None, save=False)
        self.control_release_timeout = max(1.0, self.max_authority_hold_spinbox.value())

        attack_skill_data = data.get('attack_skills', [])
        if attack_skill_data:
            self.attack_skills = []
            for item in attack_skill_data:
                name = item.get('name')
                command = item.get('command')
                if not name or not command:
                    continue
                self.attack_skills.append(
                    AttackSkill(
                        name=name,
                        command=command,
                        enabled=bool(item.get('enabled', True)),
                        is_primary=bool(item.get('is_primary', False)),
                        min_monsters=int(item.get('min_monsters', 1)),
                        probability=int(item.get('probability', 100)),
                        post_delay_min=float(item.get('post_delay_min', 0.43)),
                        post_delay_max=float(item.get('post_delay_max', 0.46)),
                        completion_delay_min=float(item.get('completion_delay_min', 0.0)),
                        completion_delay_max=float(item.get('completion_delay_max', 0.0)),
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

        self._suppress_settings_save = False
        self._emit_area_overlays()
        self._save_settings()

    def _save_settings(self) -> None:
        if getattr(self, '_suppress_settings_save', False):
            return

        self.teleport_settings.enabled = bool(self.teleport_enabled_checkbox.isChecked())
        self.teleport_settings.distance_px = float(self.teleport_distance_spinbox.value())
        self.teleport_settings.probability = int(self.teleport_probability_spinbox.value())

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
                'monster_threshold': self.monster_threshold_spinbox.value(),
                'auto_request': self.auto_request_checkbox.isChecked(),
                'idle_release_sec': self.idle_release_spinbox.value(),
                'max_authority_hold_sec': self.max_authority_hold_spinbox.value(),
            },
            'display': {
                'show_hunt_area': self.show_hunt_area_checkbox.isChecked(),
                'show_primary_area': self.show_primary_skill_checkbox.isChecked(),
                'show_direction_area': self.show_direction_checkbox.isChecked(),
                'auto_target': self.auto_target_radio.isChecked(),
                'screen_output': self.screen_output_checkbox.isChecked(),
                'summary_confidence': self.show_confidence_summary_checkbox.isChecked(),
                'summary_info': self.show_info_summary_checkbox.isChecked(),
            },
            'misc': {
                'direction_delay_min': self.direction_delay_min_spinbox.value(),
                'direction_delay_max': self.direction_delay_max_spinbox.value(),
                'facing_reset_min_sec': self.facing_reset_min_spinbox.value(),
                'facing_reset_max_sec': self.facing_reset_max_spinbox.value(),
            },
            'teleport': {
                'enabled': self.teleport_settings.enabled,
                'distance_px': self.teleport_settings.distance_px,
                'probability': self.teleport_settings.probability,
                'command_left': self.teleport_command_left,
                'command_right': self.teleport_command_right,
                'command_left_v2': self.teleport_command_left_v2,
                'command_right_v2': self.teleport_command_right_v2,
            },
            'attack_skills': [
                {
                    'name': skill.name,
                    'command': skill.command,
                    'enabled': skill.enabled,
                    'is_primary': skill.is_primary,
                    'min_monsters': skill.min_monsters,
                    'probability': skill.probability,
                    'post_delay_min': skill.post_delay_min,
                    'post_delay_max': skill.post_delay_max,
                    'completion_delay_min': getattr(skill, 'completion_delay_min', 0.0),
                    'completion_delay_max': getattr(skill, 'completion_delay_max', 0.0),
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
                    'post_delay_min': skill.post_delay_min,
                    'post_delay_max': skill.post_delay_max,
                    'completion_delay_min': getattr(skill, 'completion_delay_min', 0.0),
                    'completion_delay_max': getattr(skill, 'completion_delay_max', 0.0),
                }
                for skill in self.buff_skills
            ],
            'manual_capture_region': self.manual_capture_region,
            'auto_hunt_enabled': self.auto_hunt_enabled,
            'attack_interval_sec': self.attack_interval_sec,
            'last_popup_scale': self.last_popup_scale,
            'last_facing': self.last_facing,
        }

        try:
            with open(self._settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings_data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.append_log(f"설정 저장 실패: {exc}", "warn")

    def refresh_model_choices(self) -> None:
        self.model_selector.clear()
        if not self.data_manager:
            self.model_selector.addItem("연동 필요")
            self.model_selector.setEnabled(False)
            return

        models = sorted(self.data_manager.get_saved_models()) if hasattr(self.data_manager, "get_saved_models") else []
        if not models:
            self.model_selector.addItem("사용 가능한 모델 없음")
            self.model_selector.setEnabled(False)
        else:
            self.model_selector.addItems(models)
            self.model_selector.setEnabled(True)
            if self.last_used_model and self.last_used_model in models:
                self.model_selector.setCurrentText(self.last_used_model)

    def request_control(self, reason: str | None = None) -> None:
        if self.current_authority == "hunt":
            self.append_log("이미 사냥 권한을 보유 중입니다.", "warn")
            return
        if self._request_pending:
            return

        self._request_pending = True
        if self._request_timeout_timer:
            self._request_timeout_timer.start(self.CONTROL_REQUEST_TIMEOUT_MS)

        payload = {
            "monster_threshold": self.monster_threshold_spinbox.value(),
            "range_px": self.enemy_range_spinbox.value(),
            "y_band_height": self.y_band_height_spinbox.value(),
            "y_offset": self.y_band_offset_spinbox.value(),
            "primary_skill_range": self.primary_skill_range_spinbox.value(),
            "model": self.model_selector.currentText(),
            "attack_skill_count": len(self.attack_skills),
            "buff_skill_count": len(self.buff_skills),
            "latest_monster_count": self.latest_monster_count,
            "latest_primary_monster_count": self.latest_primary_monster_count,
        }
        self.control_authority_requested.emit(payload)
        self._log_control_request(payload, reason)
        if not self._authority_request_connected:
            self.on_map_authority_changed("hunt")

    def release_control(self, reason: str | None = None) -> None:
        if self.current_authority != "hunt":
            self.append_log("현재 사냥 권한이 없습니다.", "warn")
            return
        if self._request_timeout_timer:
            self._request_timeout_timer.stop()
        self._request_pending = False

        payload = {"reason": reason or "manual"}
        self.control_authority_released.emit(payload)
        if reason:
            self.append_log(f"사냥 권한 반환 요청 ({reason})", "info")
        else:
            self.append_log("사냥 권한 반환 요청", "info")
        if not self._authority_release_connected:
            self.on_map_authority_changed("map")

    def on_map_authority_changed(self, owner: str) -> None:
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
        if owner == "hunt":
            self.append_log("사냥 탭이 조작 권한을 획득했습니다.", "success")
        elif owner == "map":
            self.append_log("맵 탭으로 권한이 반환되었습니다.", "info")
        else:
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

        threshold = self.monster_threshold_spinbox.value()

        if (
            self.latest_primary_monster_count > 0
            or self.latest_monster_count >= threshold
        ):
            self._last_monster_seen_ts = time.time()

        if self.current_authority == "hunt":
            elapsed = time.time() - self.last_control_acquired_ts if self.last_control_acquired_ts else 0.0
            idle_elapsed = (
                time.time() - self._last_monster_seen_ts
                if self._last_monster_seen_ts
                else float("inf")
            )
            should_release = False
            idle_limit = self.idle_release_spinbox.value()
            if self.latest_primary_monster_count == 0 and self.latest_monster_count < threshold:
                if idle_elapsed >= idle_limit:
                    should_release = True
            timeout = self.control_release_timeout or 0
            if timeout and elapsed >= timeout:
                should_release = True
            if should_release and (time.time() - self.last_release_attempt_ts) >= 1.0:
                self.last_release_attempt_ts = time.time()
                reason_parts = []
                if self.latest_primary_monster_count == 0:
                    reason_parts.append("주 스킬 범위 몬스터 없음")
                if self.latest_monster_count < threshold:
                    reason_parts.append(f"전체 {self.latest_monster_count}마리 < 기준 {threshold}")
                reason_parts.append(f"최근 몬스터 미탐지 {idle_elapsed:.1f}s (기준 {idle_limit:.1f}s)")
                if timeout and elapsed >= timeout:
                    reason_parts.append(f"타임아웃 {timeout}s 초과")
                reason_text = ", ".join(reason_parts)
                self.append_log(f"자동 조건 해제 → 사냥 권한 반환 ({reason_text})", "info")
                self.release_control(reason_text)
            return

        if (
            self.latest_monster_count >= threshold
            or self.latest_primary_monster_count > 0
        ):
            reason_parts = []
            if self.latest_monster_count >= threshold:
                reason_parts.append(f"전체 {self.latest_monster_count}마리 ≥ 기준 {threshold}")
            if self.latest_primary_monster_count > 0:
                reason_parts.append(f"주 스킬 범위 {self.latest_primary_monster_count}마리")
            reason_text = ", ".join(reason_parts)
            self.append_log(f"자동 조건 충족 → 사냥 권한 요청 ({reason_text})", "info")
            self.request_control(reason_text)

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
        now = time.time()
        if self._evaluate_buff_usage(now):
            return
        if not self.attack_skills:
            self._ensure_idle_keys("공격 스킬 미등록")
            return
        if self.latest_primary_monster_count == 0:
            if self._handle_monster_approach():
                return
            self._ensure_idle_keys("주 스킬 범위 몬스터 없음")
            return
        if not self.latest_snapshot or not self.latest_snapshot.character_boxes:
            self._ensure_idle_keys("탐지 데이터 없음")
            return

        if now - self.last_attack_ts < self.attack_interval_sec:
            return

        if self._movement_mode:
            self._movement_mode = None

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
                    return True

        return self._issue_walk_command(target_side, distance)

    def _issue_walk_command(self, side: str, distance: float) -> bool:
        if side not in ('left', 'right'):
            return False
        mode_key = f"walk_{side}"
        if self._movement_mode == mode_key:
            return True
        command = "걷기(좌)" if side == 'left' else "걷기(우)"
        reason = f"몬스터 접근 ({'좌' if side == 'left' else '우'}, {distance:.0f}px)"
        self._emit_control_command(command, reason=reason)
        self._movement_mode = mode_key
        self.hunting_active = True
        self._last_movement_command_ts = time.time()
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
        self._set_current_facing(side, save=False)
        self.hunting_active = True
        self._last_movement_command_ts = time.time()
        delay = random.uniform(0.12, 0.22)
        self._set_command_cooldown(delay)
        self._log_delay_message("텔레포트 이동", delay)
        return True

    def _evaluate_buff_usage(self, now: float) -> bool:
        if self._get_command_delay_remaining() > 0:
            return False
        for buff in self.buff_skills:
            if not buff.enabled or buff.cooldown_seconds <= 0:
                continue

            ready_ts = buff.next_ready_ts or 0.0
            if buff.last_triggered_ts == 0.0 or now >= ready_ts:
                self._emit_control_command(buff.command)
                self._queue_completion_delay(buff.command, buff.completion_delay_min, buff.completion_delay_max, f"버프 '{buff.name}'")
                buff.last_triggered_ts = now
                jitter_ratio = max(0, min(buff.jitter_percent, 90)) / 100.0
                jitter_window = buff.cooldown_seconds * jitter_ratio

                if jitter_window > 0:
                    mean = jitter_window / 2.0
                    std_dev = jitter_window / 6.0 if jitter_window > 0 else 0.0
                    reduction = None
                    for _ in range(5):
                        candidate = random.gauss(mean, std_dev) if std_dev > 0 else mean
                        if 0.0 <= candidate <= jitter_window:
                            reduction = candidate
                            break
                    if reduction is None:
                        candidate = random.gauss(mean, std_dev) if std_dev > 0 else mean
                        reduction = min(max(candidate, 0.0), jitter_window)
                else:
                    reduction = 0.0

                next_delay = buff.cooldown_seconds - reduction
                wait_seconds = max(0.0, next_delay)
                buff.next_ready_ts = now + wait_seconds
                self.append_log(f"버프 사용: {buff.name} - {wait_seconds:.1f}초 후 사용예정", "info")
                self.last_attack_ts = now
                self.hunting_active = True
                delay = random.uniform(buff.post_delay_min, buff.post_delay_max)
                self._set_command_cooldown(delay)
                self._log_delay_message(f"버프 '{buff.name}'", delay)
                return True

        return False

    def _execute_attack_skill(self, skill: AttackSkill) -> None:
        if not skill.enabled:
            return
        remaining = self._get_command_delay_remaining()
        if remaining > 0:
            self._schedule_skill_execution(skill, remaining)
            return
        self._emit_control_command(skill.command)
        self._queue_completion_delay(skill.command, skill.completion_delay_min, skill.completion_delay_max, f"스킬 '{skill.name}'")
        self.last_attack_ts = time.time()
        self.hunting_active = True
        delay = random.uniform(skill.post_delay_min, skill.post_delay_max)
        self._set_command_cooldown(delay)
        self._log_delay_message(f"스킬 '{skill.name}'", delay)

    def _select_attack_skill(self) -> Optional[AttackSkill]:
        enabled_skills = [s for s in self.attack_skills if s.enabled]
        if not enabled_skills:
            return None

        primary_skill = next((s for s in enabled_skills if s.is_primary), None)
        if not primary_skill:
            primary_skill = enabled_skills[0]

        chosen = primary_skill
        primary_count = self.latest_primary_monster_count
        for skill in enabled_skills:
            if skill.is_primary:
                continue
            if primary_count < max(1, skill.min_monsters):
                continue
            probability = max(0, min(skill.probability, 100))
            if random.randint(1, 100) <= probability:
                chosen = skill
                break

        return chosen

    def _select_target_monster(self, character_box: DetectionBox) -> Optional[DetectionBox]:
        if not self.latest_snapshot:
            return None
        monsters = self._get_recent_monster_boxes()
        if not monsters:
            return None
        candidates = monsters
        if self.current_primary_area:
            primary_monsters = [box for box in monsters if box.intersects(self.current_primary_area)]
            if primary_monsters:
                candidates = primary_monsters
            else:
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
        return min(candidates, key=lambda box: abs(box.center_x - char_x))

    def _ensure_direction(self, target_side: str, next_skill: Optional[AttackSkill] = None) -> bool:
        current = self.last_facing if self.last_facing in ('left', 'right') else None
        if current == target_side:
            return False
        self._schedule_direction_command(target_side, next_skill)
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
        self._emit_control_command(command)
        delay_min = min(self.direction_delay_min_spinbox.value(), self.direction_delay_max_spinbox.value())
        delay_max = max(self.direction_delay_min_spinbox.value(), self.direction_delay_max_spinbox.value())
        delay_sec = random.uniform(delay_min, delay_max)
        self._set_command_cooldown(delay_sec)
        self._log_delay_message("방향설정", delay_sec)
        if next_skill:
            self._schedule_skill_after_direction(next_skill)
        else:
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

    def set_auto_hunt_enabled(self, enabled: bool) -> None:
        self.auto_hunt_enabled = bool(enabled)
        state = "ON" if self.auto_hunt_enabled else "OFF"
        self.append_log(f"자동 사냥 모드 {state}", "info")
        if not self.auto_hunt_enabled and self.current_authority == "hunt":
            self.release_control("사용자에 의해 자동 사냥 비활성화")
        self._save_settings()

    def add_attack_skill(self) -> None:
        dialog = AttackSkillDialog(self)
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
        dialog = AttackSkillDialog(self, self.attack_skills[index])
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
        self._emit_control_command(skill.command)
        self._queue_completion_delay(skill.command, skill.completion_delay_min, skill.completion_delay_max, f"테스트 스킬 '{skill.name}'")
        self.append_log(f"테스트 실행 (공격): {skill.name}", "info")
        delay = random.uniform(skill.post_delay_min, skill.post_delay_max)
        self._set_command_cooldown(delay)
        self._log_delay_message(f"테스트 스킬 '{skill.name}'", delay)

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
        self._emit_control_command(skill.command)
        self._queue_completion_delay(skill.command, skill.completion_delay_min, skill.completion_delay_max, f"테스트 버프 '{skill.name}'")
        self.append_log(f"테스트 실행 (버프): {skill.name}", "info")
        now = time.time()
        skill.last_triggered_ts = now
        jitter_ratio = max(0, min(skill.jitter_percent, 90)) / 100.0
        jitter_window = skill.cooldown_seconds * jitter_ratio
        next_delay = skill.cooldown_seconds - random.uniform(0, jitter_window)
        skill.next_ready_ts = now + max(0.0, next_delay)
        delay = random.uniform(skill.post_delay_min, skill.post_delay_max)
        self._set_command_cooldown(delay)
        self._log_delay_message(f"테스트 버프 '{skill.name}'", delay)

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
            item.setText(4, f">= {skill.min_monsters}마리 | {skill.probability}%")
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

    def _get_selected_attack_index(self) -> Optional[int]:
        if not hasattr(self, "attack_tree"):
            return None
        item = self.attack_tree.currentItem()
        if item is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

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
        valid_levels = {"info", "warn", "success", "debug"}
        if level not in valid_levels:
            self._append_keyboard_log(message)
            return
        if level == "info" and message.lstrip().startswith("("):
            self._append_keyboard_log(message)
            return
        prefix_map = {
            "info": "[INFO]",
            "warn": "[WARN]",
            "success": "[OK]",
            "debug": "[DEBUG]",
        }
        prefix = prefix_map.get(level, "[INFO]")
        if hasattr(self, 'log_view'):
            self.log_view.append(f"{prefix} {message}")

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
        self._pending_completion_delays.clear()
        self._stop_detection_thread()
        if hasattr(self, 'detect_btn'):
            self.detect_btn.setChecked(False)
            self.detect_btn.setText("실시간 탐지 시작")
        self._authority_request_connected = False
        self._authority_release_connected = False
        self._save_settings()

    def _issue_all_keys_release(self, reason: Optional[str] = None) -> None:
        if not getattr(self, 'control_command_issued', None):
            return
        self._clear_pending_skill()
        self._clear_pending_direction()
        self._emit_control_command("모든 키 떼기", reason=reason)
        if reason:
            self.append_log(f"모든 키 떼기 명령 전송 (원인: {reason})", "debug")
        else:
            self.append_log("모든 키 떼기 명령 전송", "debug")
        self._release_pending = False
        self.hunting_active = False
        self._movement_mode = None

    def _ensure_idle_keys(self, reason: Optional[str] = None) -> None:
        self._clear_pending_skill()
        self._clear_pending_direction()
        if self.hunting_active:
            self._issue_all_keys_release(reason)
