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
import copy
import numpy as np
import cv2
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, TextIO

import pygetwindow as gw

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRect, QThread, QAbstractNativeEventFilter, QDateTime, QSignalBlocker
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QDoubleSpinBox,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QBrush, QTextCursor, QGuiApplication, QImage

from detection_runtime import DetectionPopup, DetectionThread, ScreenSnipper
from direction_detection import DirectionDetector
from nickname_detection import NicknameDetector
from status_monitor import StatusMonitorThread, StatusMonitorConfig
from authority_reason_formatter import format_authority_reason
from control_authority_manager import (
    AuthorityDecisionStatus,
    ControlAuthorityManager,
    HuntConditionSnapshot,
    DEFAULT_MAP_PROTECT_SEC,
    DEFAULT_MAX_FLOOR_HOLD_SEC,
    DEFAULT_MAX_TOTAL_HOLD_SEC,
    DEFAULT_HUNT_PROTECT_SEC,
)
from ocr_watch import ocr_korean_words, draw_word_boxes

from window_anchors import (
    ensure_relative_roi,
    get_maple_window_geometry,
    last_used_anchor_name,
    make_relative_roi,
    resolve_roi_to_absolute,
)

try:
    from map import MAPS_DIR  # type: ignore
except ImportError:
    from .map import MAPS_DIR  # type: ignore

# 텔레그램 알림(선택적): 브리지가 활성일 때만 전송
try:
    from telegram_bridge import send_telegram_text as _tg_send_text, send_telegram_photo as _tg_send_photo
except Exception:  # pragma: no cover - 환경에 따라 브리지 미설치/미활성 가능
    _tg_send_text = None
    _tg_send_photo = None

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
# 클린업 추격 밴드 오버레이 스타일
CLEANUP_CHASE_COLOR = QColor(255, 215, 0, 60)
CLEANUP_CHASE_EDGE = QPen(QColor(255, 215, 0, 220), 2, Qt.PenStyle.DashLine)
CLEANUP_CHASE_BRUSH = QBrush(CLEANUP_CHASE_COLOR)
# 군집 중심 윈도우 오버레이 스타일
CLUSTER_WINDOW_COLOR = QColor(255, 0, 255, 50)
CLUSTER_WINDOW_EDGE = QPen(QColor(255, 0, 255, 220), 2, Qt.PenStyle.DotLine)
CLUSTER_WINDOW_BRUSH = QBrush(CLUSTER_WINDOW_COLOR)
# 군집 중심 시각화 선 길이(좌우 각 px)
JUMP_CENTER_VISUAL_DISTANCE_PX = 120
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
# 클린업 상태에서 주 스킬 범위로부터 허용할 추격 밴드(전/후 각 px)
CLEANUP_CHASE_MARGIN_PX = 150
NAMEPLATE_TRACK_EDGE = QPen(QColor(255, 64, 64, 255), 3, Qt.PenStyle.SolidLine)
NAMEPLATE_TRACK_BRUSH = QBrush(QColor(255, 32, 32, 40))
NAMEPLATE_DEADZONE_EDGE = QPen(QColor(20, 20, 20, 230), 3, Qt.PenStyle.SolidLine)
NAMEPLATE_DEADZONE_SIZE = 100  # 사망 모션 무시 영역 크기(px)
LOG_LINE_LIMIT = 200

FORBIDDEN_GLYPH_MARGIN_PX = 80
FORBIDDEN_GLYPH_VISUAL_HOLD_SEC = 5.0
FORBIDDEN_GLYPH_RETRY_INTERVAL_SEC = 0.2
FORBIDDEN_GLYPH_MAX_ATTEMPTS = 3
FORBIDDEN_GLYPH_SCALES = (1.0, 0.9, 1.1)  # 간단 다중 스케일 매칭(조기종료)
FORBIDDEN_GLYPH_ROI_EDGE = QPen(QColor(255, 0, 0, 200), 2, Qt.PenStyle.DashLine)
FORBIDDEN_GLYPH_MATCH_EDGE = QPen(QColor(255, 0, 0, 255), 2, Qt.PenStyle.SolidLine)
FORBIDDEN_FRAME_STALE_SEC = 0.25
FORBIDDEN_FRAME_REQUEST_COOLDOWN = 0.2
FORBIDDEN_FRAME_FORCE_DURATION = 0.35

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
    # 방향전환 사용 여부: True면 공격 전 목표 방향으로 캐릭터를 돌린다.
    use_direction: bool = True
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
    # 점프이동 공격(주 스킬 범위 2마리 이상일 때 확률적으로 중심에 가까워지며 공격)
    jump_attack_enabled: bool = False
    jump_attack_distance_px: int = 120
    jump_attack_probability: int = 50
    jump_profile_left: str = ""
    jump_profile_right: str = ""
    # 점프공격 전용 스킬 발동 전 대기(기본 스킬 pre-delay와 분리 적용)
    jump_pre_delay_min: float = 0.0
    jump_pre_delay_max: float = 0.0
    # 점프공격 전용 스킬 발동 후 대기(기본 스킬 post-delay와 분리 적용)
    jump_post_delay_min: float = 0.0
    jump_post_delay_max: float = 0.0


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


class MapReturnManagerDialog(QDialog):
    """맵 복귀 모드에서 사용할 맵별 복구 설정을 관리하는 대화상자."""

    def __init__(self, hunt_tab: "HuntTab") -> None:
        super().__init__(hunt_tab)
        self.setWindowTitle("맵 복구 로직 설정")
        self.setModal(True)
        self._hunt_tab = hunt_tab

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        self.map_list = QListWidget()
        self.map_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.map_list.currentItemChanged.connect(self._on_map_selection_changed)
        main_layout.addWidget(self.map_list, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        self.add_button = QPushButton("추가")
        self.add_button.clicked.connect(self._add_map_entry)
        self.remove_button = QPushButton("삭제")
        self.remove_button.clicked.connect(self._remove_selected_entry)
        button_row.addWidget(self.add_button)
        button_row.addWidget(self.remove_button)
        button_row.addStretch(1)
        main_layout.addLayout(button_row)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)

        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        form.addRow("맵 프로필", self.profile_combo)

        self.waypoint_combo = QComboBox()
        self.waypoint_combo.currentIndexChanged.connect(self._on_waypoint_changed)
        form.addRow("복구 웨이포인트", self.waypoint_combo)

        self.command_combo = QComboBox()
        self.command_combo.currentIndexChanged.connect(self._on_command_changed)
        form.addRow("복구 명령프로필", self.command_combo)

        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("예: 루디스,1층")
        self.keyword_edit.textChanged.connect(self._on_keywords_changed)
        form.addRow("키워드(콤마)", self.keyword_edit)

        self.telegram_limit_spin = QSpinBox()
        self.telegram_limit_spin.setRange(1, 20)
        self.telegram_limit_spin.setValue(self._hunt_tab.map_return_telegram_limit)
        self.telegram_limit_spin.valueChanged.connect(self._on_telegram_limit_changed)
        form.addRow("텔레그램 최대 전송", self.telegram_limit_spin)

        main_layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        main_layout.addWidget(buttons)

        self.setLayout(main_layout)
        self._refresh_profile_options()
        self._refresh_command_profiles()
        self._reload_map_entries()

    # ---- 내부 유틸리티 (구현은 후속 단계에서 완성) ----
    def _reload_map_entries(self) -> None:
        self.map_list.clear()
        for name in sorted(self._hunt_tab.map_return_registered_maps.keys()):
            item = QListWidgetItem(name)
            self.map_list.addItem(item)
        if self.map_list.count() > 0:
            self.map_list.setCurrentRow(0)
        else:
            block_profile = self.profile_combo.blockSignals(True)
            try:
                self.profile_combo.setCurrentIndex(-1)
            finally:
                self.profile_combo.blockSignals(block_profile)
            block_waypoint = self.waypoint_combo.blockSignals(True)
            try:
                self.waypoint_combo.clear()
            finally:
                self.waypoint_combo.blockSignals(block_waypoint)
            block_command = self.command_combo.blockSignals(True)
            try:
                self.command_combo.setCurrentIndex(-1)
            finally:
                self.command_combo.blockSignals(block_command)
            block_keyword = self.keyword_edit.blockSignals(True)
            try:
                self.keyword_edit.setText('')
            finally:
                self.keyword_edit.blockSignals(block_keyword)

    def _refresh_profile_options(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        map_tab = getattr(self._hunt_tab, 'map_tab', None)
        profiles: list[str] = []
        if map_tab and hasattr(map_tab, 'profile_selector'):
            try:
                profiles = [map_tab.profile_selector.itemText(i) for i in range(map_tab.profile_selector.count())]
            except Exception:
                profiles = []
        for name in sorted({p for p in profiles if p}):
            self.profile_combo.addItem(name, name)
        self.profile_combo.blockSignals(False)

    def _refresh_command_profiles(self) -> None:
        self.command_combo.blockSignals(True)
        self.command_combo.clear()
        try:
            options = self._hunt_tab._get_misc_command_profiles()
        except Exception:
            options = []
        self.command_combo.addItem("선택 없음", "")
        for name in options:
            self.command_combo.addItem(name, name)
        self.command_combo.blockSignals(False)

    def _refresh_waypoint_options(self, profile_name: str) -> None:
        self.waypoint_combo.blockSignals(True)
        self.waypoint_combo.clear()
        map_tab = getattr(self._hunt_tab, 'map_tab', None)
        options: list[tuple[str, str]] = []
        if map_tab and hasattr(map_tab, 'geometry_data'):
            options = self._hunt_tab._collect_waypoint_options_for_profile(profile_name)
        for display, value in options:
            self.waypoint_combo.addItem(display, value)
        self.waypoint_combo.blockSignals(False)

    def _current_entry(self) -> Optional[dict]:
        item = self.map_list.currentItem()
        if not item:
            return None
        name = item.text()
        return self._hunt_tab.map_return_registered_maps.get(name, {})

    def _save_entry(self, map_name: str, payload: dict) -> None:
        self._hunt_tab.map_return_registered_maps[map_name] = dict(payload)
        self._hunt_tab._handle_map_return_settings_changed()

    # ---- 슬롯 ----
    def _on_map_selection_changed(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
        entry = self._current_entry() or {}
        profile = str(entry.get('profile', ''))
        command = str(entry.get('command_profile', ''))
        waypoint_name = str(entry.get('waypoint_name', ''))
        waypoint_id = str(entry.get('waypoint_id', ''))
        keywords = str(entry.get('keywords', '') or '')

        idx = self.profile_combo.findData(profile)
        if idx < 0:
            idx = 0
        self.profile_combo.blockSignals(True)
        if self.profile_combo.count() == 0:
            self.profile_combo.addItem("(미설정)", "")
        self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)

        self._refresh_waypoint_options(profile)
        wp_index = self.waypoint_combo.findData(waypoint_id) if waypoint_id else -1
        if wp_index < 0 and self.waypoint_combo.count() > 0:
            wp_index = 0
        self.waypoint_combo.blockSignals(True)
        self.waypoint_combo.setCurrentIndex(wp_index)
        self.waypoint_combo.blockSignals(False)

        cmd_index = self.command_combo.findData(command)
        if cmd_index < 0 and command:
            self.command_combo.addItem(command, command)
            cmd_index = self.command_combo.count() - 1
        if cmd_index < 0:
            cmd_index = 0
        self.command_combo.blockSignals(True)
        self.command_combo.setCurrentIndex(cmd_index)
        self.command_combo.blockSignals(False)

        self.keyword_edit.blockSignals(True)
        self.keyword_edit.setText(keywords)
        self.keyword_edit.blockSignals(False)

    def _add_map_entry(self) -> None:
        map_tab = getattr(self._hunt_tab, 'map_tab', None)
        profile_names: list[str] = []
        if map_tab and hasattr(map_tab, 'profile_selector'):
            profile_names = [map_tab.profile_selector.itemText(i) for i in range(map_tab.profile_selector.count())]
        if not profile_names:
            QMessageBox.warning(self, "프로필 없음", "맵 탭에서 사용할 프로필이 없습니다.")
            return
        name, ok = QInputDialog.getText(self, "맵 이름 추가", "복귀 대상 맵 이름:")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, "입력 오류", "맵 이름을 입력해주세요.")
            return
        if name in self._hunt_tab.map_return_registered_maps:
            QMessageBox.information(self, "중복", "이미 등록된 맵입니다.")
            return
        profile, ok = QInputDialog.getItem(
            self,
            "맵 프로필 선택",
            "복귀에 사용할 맵 프로필:",
            profile_names,
            0,
            False,
        )
        if not ok:
            return
        profile = (profile or "").strip()
        if not profile:
            QMessageBox.warning(self, "입력 오류", "맵 프로필을 선택해주세요.")
            return
        self._hunt_tab.map_return_registered_maps[name] = {
            'profile': profile,
            'waypoint_id': '',
            'waypoint_name': '',
            'command_profile': '',
            'keywords': '',
        }
        self._hunt_tab._handle_map_return_settings_changed()
        self._reload_map_entries()
        items = self.map_list.findItems(name, Qt.MatchFlag.MatchExactly)
        if items:
            self.map_list.setCurrentItem(items[0])

    def _remove_selected_entry(self) -> None:
        item = self.map_list.currentItem()
        if not item:
            return
        name = item.text()
        if name not in self._hunt_tab.map_return_registered_maps:
            return
        reply = QMessageBox.question(self, "삭제 확인", f"'{name}' 항목을 삭제할까요?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._hunt_tab.map_return_registered_maps.pop(name, None)
        self._hunt_tab._handle_map_return_settings_changed()
        self._reload_map_entries()

    def _on_profile_changed(self, index: int) -> None:
        item = self.map_list.currentItem()
        if not item:
            return
        profile = str(self.profile_combo.currentData() or '')
        self._refresh_waypoint_options(profile)
        entry = self._current_entry() or {}
        entry['profile'] = profile
        entry['waypoint_id'] = ''
        entry['waypoint_name'] = ''
        self._save_entry(item.text(), entry)

    def _on_waypoint_changed(self, index: int) -> None:
        item = self.map_list.currentItem()
        if not item:
            return
        waypoint_id = str(self.waypoint_combo.currentData() or '')
        waypoint_name = self.waypoint_combo.currentText()
        entry = self._current_entry() or {}
        entry['waypoint_id'] = waypoint_id
        entry['waypoint_name'] = waypoint_name
        self._save_entry(item.text(), entry)

    def _on_command_changed(self, index: int) -> None:
        item = self.map_list.currentItem()
        if not item:
            return
        command = str(self.command_combo.currentData() or '')
        entry = self._current_entry() or {}
        entry['command_profile'] = command
        self._save_entry(item.text(), entry)

    def _on_keywords_changed(self, text: str) -> None:
        item = self.map_list.currentItem()
        if not item:
            return
        entry = self._current_entry() or {}
        entry['keywords'] = str(text or '')
        self._save_entry(item.text(), entry)

    def _on_telegram_limit_changed(self, value: int) -> None:
        self._hunt_tab.map_return_telegram_limit = int(value)
        self._hunt_tab._handle_map_return_settings_changed()


class AttackSkillDialog(QDialog):
    """공격 스킬 정보를 입력/수정하기 위한 대화상자."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        skill: Optional[AttackSkill] = None,
        misc_commands: Optional[List[str]] = None,
        skill_commands: Optional[List[str]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("공격 스킬")

        self._misc_command_options = sorted({str(name) for name in misc_commands or [] if isinstance(name, str)})
        self._skill_command_options = sorted({str(name) for name in skill_commands or [] if isinstance(name, str)})

        self.name_input = QLineEdit()
        self.command_input = QLineEdit()
        self.enabled_checkbox = QCheckBox("사용")
        self.enabled_checkbox.setChecked(True)
        self.primary_checkbox = QCheckBox("주 공격 스킬로 설정")
        self.primary_checkbox.setChecked(False)

        # 방향전환 사용
        self.direction_checkbox = QCheckBox("방향전환 사용")
        self.direction_checkbox.setChecked(True)

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

        # 점프공격 옵션
        self.jump_enabled_checkbox = QCheckBox("점프공격")
        self.jump_enabled_checkbox.setChecked(False)

        self.jump_distance_spinbox = QSpinBox()
        self.jump_distance_spinbox.setRange(1, 2000)
        self.jump_distance_spinbox.setValue(120)
        self.jump_distance_spinbox.setSuffix(" px")

        self.jump_probability_spinbox = QSpinBox()
        self.jump_probability_spinbox.setRange(0, 100)
        self.jump_probability_spinbox.setValue(50)
        self.jump_probability_spinbox.setSuffix(" %")

        self.jump_left_combo = QComboBox()
        self.jump_left_combo.addItem("프로필 선택", "")
        for name in self._skill_command_options:
            self.jump_left_combo.addItem(name, name)

        self.jump_right_combo = QComboBox()
        self.jump_right_combo.addItem("프로필 선택", "")
        for name in self._skill_command_options:
            self.jump_right_combo.addItem(name, name)

        # 점프 전용 pre-delay
        self.jump_pre_delay_min_spinbox = QDoubleSpinBox()
        self.jump_pre_delay_min_spinbox.setRange(0.0, 5.0)
        self.jump_pre_delay_min_spinbox.setSingleStep(0.05)
        self.jump_pre_delay_min_spinbox.setDecimals(3)
        self.jump_pre_delay_min_spinbox.setValue(0.0)
        self.jump_pre_delay_min_spinbox.setSuffix(" s")

        self.jump_pre_delay_max_spinbox = QDoubleSpinBox()
        self.jump_pre_delay_max_spinbox.setRange(0.0, 5.0)
        self.jump_pre_delay_max_spinbox.setSingleStep(0.05)
        self.jump_pre_delay_max_spinbox.setDecimals(3)
        self.jump_pre_delay_max_spinbox.setValue(0.0)
        self.jump_pre_delay_max_spinbox.setSuffix(" s")

        self.jump_post_delay_min_spinbox = QDoubleSpinBox()
        self.jump_post_delay_min_spinbox.setRange(0.0, 5.0)
        self.jump_post_delay_min_spinbox.setSingleStep(0.05)
        self.jump_post_delay_min_spinbox.setDecimals(3)
        self.jump_post_delay_min_spinbox.setValue(0.0)
        self.jump_post_delay_min_spinbox.setSuffix(" s")

        self.jump_post_delay_max_spinbox = QDoubleSpinBox()
        self.jump_post_delay_max_spinbox.setRange(0.0, 5.0)
        self.jump_post_delay_max_spinbox.setSingleStep(0.05)
        self.jump_post_delay_max_spinbox.setDecimals(3)
        self.jump_post_delay_max_spinbox.setValue(0.0)
        self.jump_post_delay_max_spinbox.setSuffix(" s")

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
            try:
                self.direction_checkbox.setChecked(bool(getattr(skill, 'use_direction', True)))
            except Exception:
                self.direction_checkbox.setChecked(True)
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
            # 점프공격 로드
            try:
                self.jump_enabled_checkbox.setChecked(bool(getattr(skill, 'jump_attack_enabled', False)))
            except Exception:
                pass
            try:
                self.jump_distance_spinbox.setValue(int(getattr(skill, 'jump_attack_distance_px', 120)))
            except Exception:
                pass
            try:
                self.jump_probability_spinbox.setValue(int(getattr(skill, 'jump_attack_probability', 50)))
            except Exception:
                pass
            left_prof = str(getattr(skill, 'jump_profile_left', '') or '')
            right_prof = str(getattr(skill, 'jump_profile_right', '') or '')
            if left_prof and left_prof not in self._skill_command_options:
                self.jump_left_combo.addItem(left_prof, left_prof)
            if right_prof and right_prof not in self._skill_command_options:
                self.jump_right_combo.addItem(right_prof, right_prof)
            li = self.jump_left_combo.findData(left_prof)
            if li >= 0:
                self.jump_left_combo.setCurrentIndex(li)
            ri = self.jump_right_combo.findData(right_prof)
            if ri >= 0:
                self.jump_right_combo.setCurrentIndex(ri)
            try:
                self.jump_pre_delay_min_spinbox.setValue(float(getattr(skill, 'jump_pre_delay_min', 0.0)))
                self.jump_pre_delay_max_spinbox.setValue(float(getattr(skill, 'jump_pre_delay_max', 0.0)))
            except Exception:
                pass
            try:
                self.jump_post_delay_min_spinbox.setValue(float(getattr(skill, 'jump_post_delay_min', 0.0)))
                self.jump_post_delay_max_spinbox.setValue(float(getattr(skill, 'jump_post_delay_max', 0.0)))
            except Exception:
                pass
        
        form = QFormLayout()
        form.addRow("이름", self.name_input)
        form.addRow("명령", self.command_input)
        form.addRow("사용", self.enabled_checkbox)
        form.addRow("주 스킬", self.primary_checkbox)
        form.addRow("방향전환 사용", self.direction_checkbox)
        form.addRow(self.primary_reset_label, self.primary_reset_widget)
        form.addRow(self.primary_release_label, self.primary_release_combo)
        form.addRow("사용 최소 몬스터 수", self.min_monsters_spinbox)
        form.addRow("사용 최대 몬스터 수", self.max_monsters_spinbox)
        form.addRow("사용 확률", self.probability_spinbox)
        form.addRow("점프공격", self.jump_enabled_checkbox)
        form.addRow("점프 사용거리(px)", self.jump_distance_spinbox)
        form.addRow("점프 사용확률", self.jump_probability_spinbox)
        form.addRow("좌측 명령프로필", self.jump_left_combo)
        form.addRow("우측 명령프로필", self.jump_right_combo)
        form.addRow("점프 발동 전 대기 최소", self.jump_pre_delay_min_spinbox)
        form.addRow("점프 발동 전 대기 최대", self.jump_pre_delay_max_spinbox)
        form.addRow("점프 발동 후 대기 최소", self.jump_post_delay_min_spinbox)
        form.addRow("점프 발동 후 대기 최대", self.jump_post_delay_max_spinbox)
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
        self.jump_enabled_checkbox.toggled.connect(self._update_jump_controls)
        self._update_jump_controls(self.jump_enabled_checkbox.isChecked())

    def _update_jump_controls(self, checked: bool) -> None:
        widgets = (
            self.jump_distance_spinbox,
            self.jump_probability_spinbox,
            self.jump_left_combo,
            self.jump_right_combo,
            self.jump_pre_delay_min_spinbox,
            self.jump_pre_delay_max_spinbox,
            self.jump_post_delay_min_spinbox,
            self.jump_post_delay_max_spinbox,
        )
        state = bool(checked)
        for w in widgets:
            w.setEnabled(state)

    def accept(self) -> None:
        # 점프공격 유효성 검사: 좌/우 프로필이 모두 선택되어야 저장 가능
        try:
            if self.jump_enabled_checkbox.isChecked():
                if not (self.jump_left_combo.currentData() and self.jump_right_combo.currentData()):
                    QMessageBox.warning(self, "오류", "점프공격이 켜져 있습니다. 좌/우 명령 프로필을 모두 선택하세요.")
                    return
        except Exception:
            pass
        try:
            self._refresh_map_return_profile_options()
        except Exception:
            pass
        return super().accept()

    def get_skill(self) -> Optional[AttackSkill]:
        name = self.name_input.text().strip()
        command = self.command_input.text().strip()
        if not name or not command:
            return None
        if self.jump_enabled_checkbox.isChecked():
            if not (self.jump_left_combo.currentData() and self.jump_right_combo.currentData()):
                QMessageBox.warning(self, "오류", "점프공격이 켜져 있습니다. 좌/우 명령 프로필을 모두 선택하세요.")
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
            use_direction=bool(self.direction_checkbox.isChecked()),
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
            jump_attack_enabled=self.jump_enabled_checkbox.isChecked(),
            jump_attack_distance_px=int(self.jump_distance_spinbox.value()),
            jump_attack_probability=int(self.jump_probability_spinbox.value()),
            jump_profile_left=str(self.jump_left_combo.currentData() or ''),
            jump_profile_right=str(self.jump_right_combo.currentData() or ''),
            jump_pre_delay_min=min(self.jump_pre_delay_min_spinbox.value(), self.jump_pre_delay_max_spinbox.value()),
            jump_pre_delay_max=max(self.jump_pre_delay_min_spinbox.value(), self.jump_pre_delay_max_spinbox.value()),
            jump_post_delay_min=min(self.jump_post_delay_min_spinbox.value(), self.jump_post_delay_max_spinbox.value()),
            jump_post_delay_max=max(self.jump_post_delay_min_spinbox.value(), self.jump_post_delay_max_spinbox.value()),
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
    # 캐릭터 미검출 → ESC 효과 정지 후 재시작
    CHAR_MISSING_TIMEOUT_SEC = 10.0
    CHAR_MISSING_RESTART_DELAY_SEC = 2.0

    control_command_issued = pyqtSignal(str, object)
    control_authority_requested = pyqtSignal(dict)
    control_authority_released = pyqtSignal(dict)
    hunt_area_updated = pyqtSignal(object)
    primary_skill_area_updated = pyqtSignal(object)
    monster_stats_updated = pyqtSignal(int, int)
    detection_status_changed = pyqtSignal(bool)
    # [NEW] 외부(모니터링 탭)용 로그/프리뷰 시그널
    hunt_log_emitted = pyqtSignal(str, str)
    preview_frame_ready = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.data_manager = None
        self._auto_control_tab = None
        self.current_authority: str = "map"
        self.attack_skills: List[AttackSkill] = []
        self.buff_skills: List[BuffSkill] = []

        self.latest_snapshot: Optional[DetectionSnapshot] = None
        self.current_hunt_area: Optional[AreaRect] = None
        self.current_primary_area: Optional[AreaRect] = None
        self.current_cleanup_chase_area: Optional[AreaRect] = None
        self.current_cluster_window_area: Optional[AreaRect] = None
        # [NEW] 군집 중심 시각화용 좌표
        self.current_cluster_center_x: Optional[float] = None
        self.current_cluster_center_y: Optional[float] = None
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
        # [접근 차단 로그 쿨다운] 주 스킬 미충족으로 접근을 막을 때 로그 스팸 방지
        self._last_approach_blocked_log_ts = 0.0
        self.auto_hunt_enabled = True
        self.overlay_preferences = {
            'hunt_area': True,
            'primary_area': True,
            'cleanup_chase_area': True,
            'cluster_window_area': True,
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
        # 로그 수치 표기 형식 기본값: a(기준 b) 사용
        self._metric_format_parentheses = True
        self._suppress_downscale_prompt = False
        self._last_character_boxes: List[DetectionBox] = []
        self._last_character_details: List[dict] = []
        self._last_character_seen_ts: float = 0.0
        self._using_character_fallback: bool = False

        # ----- 맵 복귀 모드 상태 -----
        self.map_return_enabled: bool = False
        self.map_return_roi: Optional[dict] = None
        self.map_return_interval_sec: float = 3.0
        self.map_return_conf_threshold: float = 0.0
        self.map_return_min_height: int = 0
        self.map_return_max_height: int = 0
        self.map_return_min_width: int = 0
        self.map_return_max_width: int = 0
        self.map_return_base_profile: str = ""
        self.map_return_base_keywords: str = ""
        self.map_return_registered_maps: dict[str, dict] = {}
        self.map_return_telegram_limit: int = 5
        self._map_return_last_alert_ts: dict[str, float] = {}
        self._map_return_alert_count: dict[str, int] = {}
        self._map_return_active_map: Optional[str] = None
        self._map_return_recovering: bool = False
        self._map_return_geometry_cache: dict[str, dict] = {}
        self._map_return_last_detected: str = ""
        self._map_return_context: dict[str, Any] = {}
        self._map_return_detection_was_active: bool = False

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
        self._nameplate_apply_facing: bool = False
        # [NEW] 미니맵 X 보정 트래킹 상태
        self._minimap_x_primed: bool = False
        self._minimap_char_template: Optional[dict] = None  # {'y': float, 'width': float, 'height': float}
        self._minimap_char_overlay_box: Optional[dict] = None  # {'x','y','width','height'}
        self._forbidden_glyph_config: dict = {}
        self._forbidden_glyph_templates: list[dict] = []
        self._forbidden_glyph_threshold: float = 0.70
        self._forbidden_glyph_vertical_bias: float = 0.0
        self._forbidden_watch_window_until: float = 0.0
        self._forbidden_lock_until: float = 0.0
        self._forbidden_visual_overlays: list[dict] = []
        self._latest_forbidden_detection: Optional[dict] = None
        self._forbidden_notify_cache: dict[str, float] = {}
        self._forbidden_glyph_retry_state: dict[tuple, dict] = {}
        self._latest_detection_qimage: Optional[QImage] = None
        self._latest_detection_frame_ts: float = 0.0
        self._latest_detection_bgr: Optional[np.ndarray] = None
        self._latest_detection_bgr_ts: float = 0.0
        self._latest_frame_size: tuple[int, int] = (0, 0)
        self._forbidden_glyph_status: str = 'idle'
        self._forbidden_glyph_status_ts: float = 0.0
        self._forbidden_last_frame_request_ts: float = 0.0

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

        # [NEW] 겹침(2→1) 즉시 클린업 전환 판단용 상태
        self._prev_primary_count: int = 0
        self._last_primary_multi_ts: float = 0.0

        # 교전/클린업 상태
        # - engage_active: 주 스킬 범위 기준 최소 마릿수(스핀박스) 충족하여 교전 상태로 진입한 후 유지
        # - cleanup_active: 교전 중 마릿수가 기준 미만(>=1)으로 줄었을 때 잔몹 정리 상태
        self._engage_active: bool = False
        self._cleanup_active: bool = False
        self._cleanup_hold_until_ts: float = 0.0

        # 사다리복구 조건 평가용 상태(연속 상태 지속 시간 추적)
        self._ladder_escape_last_state: Optional[str] = None
        self._ladder_escape_state_since_ts: float = 0.0

        self.detection_thread: Optional[DetectionThread] = None
        self.detection_popup: Optional[DetectionPopup] = None
        self.is_popup_active = False
        self.last_popup_scale = 50
        self.last_popup_position: Optional[tuple[int, int]] = None
        self.last_popup_size: Optional[tuple[int, int]] = None
        self.manual_capture_region: Optional[dict] = None
        self.manual_capture_regions: list[dict] = []
        self.manual_area_profiles: dict[str, list[dict]] = {}
        self.active_area_profile: Optional[str] = None
        self._area_settings_dialog = None
        self.last_used_model: Optional[str] = None
        self._model_listener_registered = False
        self._authority_request_connected = False
        self._authority_release_connected = False
        self._release_pending = False
        self._settings_path = HUNT_SETTINGS_FILE
        self._suppress_settings_save = True
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
        self._preserve_exp_on_stop: bool = False
        self._resume_exp_after_pause: bool = False
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

        # HP 긴급모드/회복검사 상태
        self._hp_recovery_pending: bool = False
        self._hp_recovery_fail_streak: int = 0
        self._hp_emergency_active: bool = False
        self._hp_emergency_started_at: float = 0.0
        self._hp_emergency_telegram_sent: bool = False
        # [NEW] HP 저체력(3% 미만) 텔레그램 알림 상태
        self._low_hp_alert_active: bool = False
        # [NEW] 초긴급 명령 1회 트리거 상태
        self._low_hp_urgent_active: bool = False

        # [NEW] 금지 몬스터 플로우 상태/설정
        self.forbidden_monster_enabled: bool = False
        self.forbidden_monster_command_profile: str = ''
        self._forbidden_active: bool = False
        # [신규] 금지 명령 1회 실행 래치(도착 다중 통지 시 중복 실행 방지)
        self._forbidden_cmd_inflight: bool = False
        # [신규] 금지 명령 완료 워치독(6초, 1회 재발행)
        self._forbidden_watchdog_retry_count: int = 0
        self._FORBIDDEN_WATCHDOG_MAX_RETRY: int = 1
        self._forbidden_cooldown_until: float = 0.0
        # [NEW] 금지몬스터 감지 시 텔레그램 알림 여부(전역)
        self.forbidden_monster_telegram_alert: bool = False
        # [NEW] 금지몬스터 탐지 히스토리(탐지중지 시 초기화)
        self._forbidden_detect_history: List[str] = []
        self._forbidden_detect_last_log_ts: float = 0.0

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

        # [사냥범위 오버라이드] 맵 탭의 영역 진입 시 일시적으로 범위를 바꾸고, 이탈 시 복원하기 위한 상태
        self._zone_override_active: bool = False
        self._zone_override_id: Optional[str] = None
        self._zone_override_backup: Optional[dict] = None
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
        self.map_return_timer = QTimer(self)
        self.map_return_timer.setSingleShot(False)
        self.map_return_timer.timeout.connect(self._handle_map_return_tick)
        self.map_return_recovery_timer = QTimer(self)
        self.map_return_recovery_timer.setSingleShot(False)
        self.map_return_recovery_timer.timeout.connect(self._handle_map_return_recovery_check)
        # 화면출력(팝업) 상태 추적용 로깅 컨텍스트
        self._closing_popup_programmatically = False
        self._popup_close_reason: Optional[str] = None
        self._popup_open_reason: Optional[str] = None
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
        # 대기모드 토글 단축키(F9)
        self.wait_hotkey_manager = None
        self.wait_hotkey_event_filter = None
        self.waitmode_hotkey = 'f9'
        # [NEW] 미니맵 X 보정 최근 사용 시각
        self._minimap_x_fallback_used_ts: float = 0.0

        # 자동 대응 상태
        self.shutdown_pid_value: Optional[int] = None
        self.shutdown_pid_last_scan: Optional[float] = None
        self.shutdown_datetime_target: Optional[float] = None
        self.shutdown_reservation_enabled = False
        self.shutdown_other_player_enabled = False
        self.shutdown_other_player_detect_since: Optional[float] = None
        self.shutdown_other_player_due_ts: Optional[float] = None
        self.shutdown_other_player_last_count: int = 0
        self.shutdown_other_player_action: str = 'game_exit'
        self.shutdown_other_player_action_triggered = False
        self.shutdown_other_player_exit_delay: int = 60
        self.shutdown_other_player_wait_delay: int = 180
        self.shutdown_other_player_wait_clear_delay: int = 60
        self.shutdown_other_player_wait_waypoint_id: Optional[str] = None
        self.shutdown_other_player_wait_waypoint_name: str = ''
        # 다중 대기 웨이포인트(신규)
        # [변경] 맵 프로필별로 저장하는 구조를 도입. 기존 필드는 '현재 활성 프로필' 뷰에 매핑.
        self.shutdown_other_player_wait_waypoints_by_profile: dict[str, list[dict]] = {}
        self.shutdown_other_player_wait_waypoints: list[dict] = []  # [{'id': str, 'name': str}]
        self.shutdown_other_player_wait_active = False
        self.shutdown_other_player_wait_started_at: Optional[float] = None
        self.shutdown_other_player_wait_clear_since: Optional[float] = None
        self.shutdown_other_player_wait_restart_required = False
        # 텔레그램 무기한 대기모드 플래그
        self._manual_indefinite_wait_active: bool = False
        self._shutdown_last_reason: Optional[str] = None
        self.shutdown_sleep_enabled = False
        # 게임 종료 대기(텔레그램) 상태
        self.exit_wait_schedule_ts: Optional[float] = None
        self.exit_wait_countdown_due_ts: Optional[float] = None
        self.exit_wait_countdown_started_at: Optional[float] = None
        self.exit_wait_countdown_duration: int = 5
        self.exit_wait_in_progress: bool = False
        self.exit_wait_command_profile: str = '게임종료'
        self._exit_wait_command_sent: bool = False
        self._exit_wait_finalize_pending: bool = False
        self.exit_wait_last_request_source: str = ''
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
        self._setup_waitmode_hotkey()

        # 캐릭터 미검출 감시 타이머
        self._char_missing_restart_pending: bool = False
        self._char_missing_watchdog = QTimer(self)
        self._char_missing_watchdog.setInterval(500)
        self._char_missing_watchdog.setSingleShot(False)
        self._char_missing_watchdog.timeout.connect(self._check_character_presence_watchdog)
        self._char_missing_watchdog.start()

        # EXP 정체(최근 9회 연속 동일) 감지 후 재시작 중복 방지용 플래그
        self._exp_stagnation_restart_pending: bool = False
        # [NEW] 런타임 가시성/프리뷰 상태
        self._ui_runtime_visible: bool = True
        self._monitor_preview_enabled: bool = False
        self._monitor_preview_interval_sec: float = 0.0

        # [사다리 위협] X범위 오버라이드 상태
        self._ladder_override_active: bool = False
        self._ladder_override_backup: Optional[dict] = None
        # [사다리 정리 세션] 획득 사유가 사다리 위협일 때 활성화
        self._ladder_cleanup_session_active: bool = False
        # 초기 탐지 안정화를 위한 짧은 보호 윈도우(초)
        self._ladder_cleanup_hold_until_ts: float = 0.0
        # [신규] 사다리 준비 정리(purge) 세션 상태
        self._ladder_purge_session_active: bool = False
        # 초기 탐지 안정화를 위한 짧은 보호 윈도우(초)
        self._ladder_purge_hold_until_ts: float = 0.0

        # [NEW] 대기모드 위치 복구 임계값(px)
        # - 대기 웨이포인트에서 이 값(px) 이상 벗어나면 복귀 이동을 시작
        # - UI: '대기 모드 설정' 팝업에서 조절 (0~100, 기본 70)
        self.wait_recover_threshold_px: int = 70

    def _check_character_presence_watchdog(self) -> None:
        """캐릭터가 10초 이상 미검출 시 ESC 효과로 전체 정지 후 2초 뒤 사냥 재시작.
        - ESC 효과: 사냥/맵 모두 정지 + 모든 키 떼기
        - 재시작: 사냥탭만 api_start_detection()
        - 텔레그램 알림 발송(가능 시)
        """
        # 사냥탭 탐지가 동작 중이 아닐 때는 감시 불필요
        if not self._is_detection_active():
            self._char_missing_restart_pending = False
            return

        last_seen = float(getattr(self, '_last_character_seen_ts', 0.0) or 0.0)
        if last_seen <= 0.0:
            # 최초 탐지 이전 상태에서는 루프 폭주 방지 위해 스킵
            return

        elapsed = time.time() - last_seen
        if elapsed < self.CHAR_MISSING_TIMEOUT_SEC:
            return

        if self._char_missing_restart_pending:
            return

        # 트리거 고정: 중복 실행 방지
        self._char_missing_restart_pending = True

        # 텔레그램 알림 (가능 시)
        try:
            if _tg_send_text:
                secs = int(round(elapsed))
                _tg_send_text(f"캐릭터 미탐지 {secs}초 > 재발동 시퀀스 발동")
        except Exception:
            pass

        # 1) ESC 효과와 동일한 전체 정지
        try:
            self.append_log(f"캐릭터 미검출 {elapsed:.1f}s → ESC 효과 정지", "warn")
        except Exception:
            pass
        try:
            self.force_stop_detection(reason='esc_shortcut')
        except Exception:
            pass
        try:
            map_tab = getattr(self, 'map_tab', None)
            if map_tab and hasattr(map_tab, 'force_stop_detection'):
                map_tab.force_stop_detection(reason='esc_shortcut')
        except Exception:
            pass

        # 1.5) 약간의 지연 후 모든 키 떼기
        try:
            QTimer.singleShot(500, lambda: self._emit_control_command("모든 키 떼기", reason="esc:global_stop"))
        except Exception:
            pass

        # 2) 2초 뒤 사냥 재시작
        def _restart_hunt() -> None:
            try:
                try:
                    self.append_log("사냥 재시작(자동)", "info")
                except Exception:
                    pass
                self.api_start_detection()
            finally:
                # 재트리거 허용(다음 미검출 감지 가능)
                QTimer.singleShot(1000, lambda: setattr(self, '_char_missing_restart_pending', False))

        QTimer.singleShot(int(self.CHAR_MISSING_RESTART_DELAY_SEC * 1000), _restart_hunt)

    # -------------------- EXP 정체 대응 루틴 --------------------
    def _notify_telegram(self, text: str) -> bool:
        if not text:
            return False
        # 우선 활성 텔레그램 브리지 사용
        try:
            if _tg_send_text and _tg_send_text(text):
                return True
        except Exception:
            pass
        # 폴백: 맵탭의 직접 전송 API 사용(가능 시)
        try:
            map_tab = getattr(self, 'map_tab', None)
            if map_tab and hasattr(map_tab, 'send_emergency_telegram'):
                map_tab.send_emergency_telegram(text)
                return True
        except Exception:
            pass
        return False

    def _kill_mapleland_process_immediately(self, reason_label: str) -> bool:
        """Mapleland 프로세스를 즉시 종료하고 후속 정리 및 알림을 수행한다."""
        pid = getattr(self, 'shutdown_pid_value', None)
        if pid is None:
            try:
                self._auto_detect_mapleland_pid(auto_trigger=True)
                pid = getattr(self, 'shutdown_pid_value', None)
            except Exception:
                pid = None
        if pid is None:
            try:
                self.append_log(f"자동 종료[{reason_label}] 시도 실패: PID가 설정되어 있지 않습니다.", 'warn')
                self._log_map_shutdown(f"자동 종료[{reason_label}] 시도 실패: PID 입력 필요", 'orange')
            except Exception:
                pass
            return False

        success, detail, signal_used = self._perform_process_kill(int(pid))
        if success:
            try:
                signal_text = f" ({signal_used})" if signal_used else ''
                message = f"자동 종료[{reason_label}] - PID {pid} 프로세스를 종료했습니다{signal_text}."
                self.append_log(message, 'warn')
                self._log_map_shutdown(message, 'orange')
            except Exception:
                pass
            # 후속 처리: PID 리셋, 키 해제, 탐지 정지, 절전 모드(선택)
            try:
                self.shutdown_pid_value = None
                if hasattr(self, 'shutdown_pid_input'):
                    self.shutdown_pid_input.setText('')
            except Exception:
                pass
            try:
                self._issue_all_keys_release('shutdown')
            except Exception:
                pass
            try:
                self.force_stop_detection(reason='auto_shutdown')
            except Exception:
                pass
            try:
                map_tab = getattr(self, 'map_tab', None)
                if map_tab and hasattr(map_tab, 'force_stop_detection'):
                    map_tab.force_stop_detection(reason='auto_shutdown')
            except Exception:
                pass
            try:
                if getattr(self, 'shutdown_sleep_enabled', False):
                    self._attempt_system_sleep()
            except Exception:
                pass
            return True
        else:
            try:
                detail_text = f": {detail}" if detail else ''
                message = f"자동 종료[{reason_label}] 실패{detail_text}"
                self.append_log(message, 'warn')
                self._log_map_shutdown(message, 'red')
            except Exception:
                pass
            return False

    def _apply_esc_and_restart_for_exp(self) -> None:
        """EXP 정체 시 ESC 효과로 전체 정지 후 2초 뒤 사냥 재시작."""
        if self._exp_stagnation_restart_pending:
            return
        self._exp_stagnation_restart_pending = True

        try:
            self.append_log("[EXP] 정체 감지 → ESC 효과 정지 후 재시작", 'warn')
        except Exception:
            pass

        # ESC 효과: 사냥/맵 정지
        try:
            self.force_stop_detection(reason='esc_shortcut')
        except Exception:
            pass
        try:
            map_tab = getattr(self, 'map_tab', None)
            if map_tab and hasattr(map_tab, 'force_stop_detection'):
                map_tab.force_stop_detection(reason='esc_shortcut')
        except Exception:
            pass

        # 약간의 지연 후 모든 키 떼기
        try:
            QTimer.singleShot(500, lambda: self._emit_control_command("모든 키 떼기", reason="exp:global_stop"))
        except Exception:
            pass

        # 2초 뒤 사냥 재시작
        def _restart_hunt() -> None:
            try:
                self.append_log("[EXP] 정체 대응: 사냥 재시작(자동)", 'info')
            except Exception:
                pass
            try:
                self.api_start_detection()
            finally:
                QTimer.singleShot(1000, lambda: setattr(self, '_exp_stagnation_restart_pending', False))

        QTimer.singleShot(2000, _restart_hunt)

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

    def _setup_waitmode_hotkey(self) -> None:
        """F9: 대기모드 무기한 토글 단축키 등록."""
        if _HuntHotkeyManager is None or _HuntHotkeyEventFilter is None:
            return
        app = QApplication.instance()
        if app is None:
            return
        try:
            self.wait_hotkey_manager = _HuntHotkeyManager()
            hotkey_id = self.wait_hotkey_manager.register_hotkey(self.waitmode_hotkey)
            self.wait_hotkey_event_filter = _HuntHotkeyEventFilter(hotkey_id, self._toggle_indefinite_wait_hotkey)
            app.installNativeEventFilter(self.wait_hotkey_event_filter)
            self.append_log(f"대기모드 단축키가 '{self.waitmode_hotkey.upper()}'로 설정되었습니다.", "info")
        except Exception as exc:
            if self.wait_hotkey_manager:
                try:
                    self.wait_hotkey_manager.unregister_hotkey()
                except Exception:
                    pass
                self.wait_hotkey_manager = None
            if self.wait_hotkey_event_filter and app:
                try:
                    app.removeNativeEventFilter(self.wait_hotkey_event_filter)
                except Exception:
                    pass
                self.wait_hotkey_event_filter = None
            self.append_log(f"대기모드 단축키 등록 중 오류가 발생했습니다: {exc}", "warn")

    def _toggle_indefinite_wait_hotkey(self) -> None:
        """F9 핫키: 대기모드 무기한 토글."""
        try:
            if not bool(getattr(self, 'shutdown_other_player_wait_active', False)):
                ok, msg = self.api_enter_indefinite_wait_mode()
                self.append_log(msg, 'info' if ok else 'warn')
            else:
                ok, msg = self.api_exit_indefinite_wait_mode()
                self.append_log(msg, 'info' if ok else 'warn')
        except Exception as exc:
            self.append_log(f"대기모드 토글 중 오류: {exc}", 'warn')

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

    def force_stop_detection(self, reason: str = 'force_stop', *, preserve_forbidden: bool = False) -> bool:
        stopped = False
        if not hasattr(self, 'detect_btn'):
            return False

        try:
            is_checked = bool(self.detect_btn.isChecked())
        except Exception:
            is_checked = False

        if preserve_forbidden:
            try:
                self._preserve_forbidden_on_stop = True
            except Exception:
                self._preserve_forbidden_on_stop = True

        if is_checked:
            # 팝업 닫힘 사유 설정
            self._closing_popup_programmatically = True
            self._popup_close_reason = str(reason or 'force_stop')
            self.detect_btn.setChecked(False)
            self._toggle_detection(False)
            stopped = True
        elif self._is_detection_active():
            # 팝업 닫힘 사유 설정
            self._closing_popup_programmatically = True
            self._popup_close_reason = str(reason or 'force_stop')
            self._toggle_detection(False)
            if hasattr(self.detect_btn, 'setChecked'):
                self.detect_btn.setChecked(False)
            stopped = True

        if stopped:
            if not preserve_forbidden:
                self._reset_forbidden_status(reason=str(reason or 'force_stop'))
            if reason == 'esc_shortcut':
                self.append_log("ESC 단축키로 탐지를 강제 중단했습니다.", "warn")
            else:
                self.append_log(f"탐지를 중단합니다. (사유: {reason})", "warn")
        elif preserve_forbidden:
            try:
                self._preserve_forbidden_on_stop = False
            except Exception:
                pass
        return stopped

    # ---------------------- Telegram 브리지용 얇은 API ----------------------
    def api_get_status_summary(self) -> dict[str, str]:
        """현재 캐시된 HP/MP/EXP 요약 텍스트를 반환한다."""
        cache = getattr(self, '_status_summary_cache', {}) or {}
        if not isinstance(cache, dict):
            return {"hp": "HP: --", "mp": "MP: --", "exp": "EXP: --"}
        # 사본 반환
        result = {
            'hp': str(cache.get('hp', 'HP: --')),
            'mp': str(cache.get('mp', 'MP: --')),
            'exp': str(cache.get('exp', 'EXP: -- / --')),
        }
        return result

    def api_get_forbidden_status(self) -> dict[str, object]:
        """금지몬스터 관련 쿨타임 및 문양 감지 상태를 반환한다."""
        now = time.time()
        cooldown_until = float(getattr(self, '_forbidden_cooldown_until', 0.0) or 0.0)
        watch_until = float(getattr(self, '_forbidden_watch_window_until', 0.0) or 0.0)
        status = getattr(self, '_forbidden_glyph_status', 'idle')
        status_ts = float(getattr(self, '_forbidden_glyph_status_ts', 0.0) or 0.0)
        return {
            'cooldown_remaining': max(0.0, cooldown_until - now),
            'watch_remaining': max(0.0, watch_until - now),
            'active': bool(getattr(self, '_forbidden_active', False)),
            'glyph_status': status,
            'glyph_status_ts': status_ts,
        }

    # ---------------------- 외부 조회용 얇은 API ----------------------
    def api_get_hunt_condition_snapshot(self) -> Optional[HuntConditionSnapshot]:
        """현재 사냥 조건 스냅샷을 반환(모니터링/권한 평가용).

        - 내부 `_build_hunt_condition_snapshot()`과 동일 내용을 래핑한다.
        - 예외 발생 시 None 반환.
        """
        try:
            return self._build_hunt_condition_snapshot()
        except Exception:
            return None

    def api_is_cleanup_active(self) -> bool:
        """현재 시점 클린업 동작 중 여부를 반환.

        기준: allow_cleanup 조건과 동일(교전 중이고, 주 스킬 범위 내 ≥1 또는 클린업 유예 시간 내).
        """
        try:
            now_ts = time.time()
            return bool(
                getattr(self, '_engage_active', False)
                and (
                    int(getattr(self, 'latest_primary_monster_count', 0)) >= 1
                    or (
                        getattr(self, '_cleanup_active', False)
                        and float(getattr(self, '_cleanup_hold_until_ts', 0.0)) > 0.0
                        and now_ts <= float(getattr(self, '_cleanup_hold_until_ts', 0.0))
                    )
                )
            )
        except Exception:
            return False

    def api_is_jump_attack_possible_now(self) -> bool:
        """주 공격 스킬 기준으로 ‘점프공격’ 실행 조건 충족 여부를 평가(실행/랜덤 제외).

        - 점프공격 On
        - 주 스킬 범위 교차 몬스터 ≥ 2
        - 캐릭터와 군집 중심 X거리 ≥ 설정 px
        - 해당 방향 점프 프로필 존재
        """
        try:
            # 주 스킬 선택
            primary_skill = None
            for s in getattr(self, 'attack_skills', []) or []:
                if getattr(s, 'is_primary', False) and getattr(s, 'enabled', True):
                    primary_skill = s
                    break
            if not primary_skill or not getattr(primary_skill, 'jump_attack_enabled', False):
                return False

            primary_area = getattr(self, 'current_primary_area', None)
            if primary_area is None:
                return False

            monsters = self._get_recent_monster_boxes()
            if not monsters:
                return False
            primary_monsters = [m for m in monsters if m.intersects(primary_area)]
            if len(primary_monsters) < 2:
                return False

            # 캐릭터 기준점
            if not (self.latest_snapshot and self.latest_snapshot.character_boxes):
                return False
            character_box = self._select_reference_character_box(self.latest_snapshot.character_boxes)
            char_x = float(character_box.center_x)
            center_x = sum(float(m.center_x) for m in primary_monsters) / float(len(primary_monsters))
            side = 'left' if center_x < char_x else 'right'
            distance = abs(center_x - char_x)

            threshold = max(1, int(getattr(primary_skill, 'jump_attack_distance_px', 120)))
            if distance < threshold:
                return False

            profile = str(getattr(primary_skill, 'jump_profile_right', '') if side == 'right' else getattr(primary_skill, 'jump_profile_left', '') or '').strip()
            if not profile:
                return False
            return True
        except Exception:
            return False

    def api_get_jump_attack_metrics(self) -> dict:
        """점프공격 가능 여부와 현재/기준 거리를 함께 반환.

        반환 예: {
          'enabled': True,
          'possible': False,
          'distance_px': 72,
          'threshold_px': 70,
        }
        distance_px는 조건 계산이 불가한 경우 None.
        """
        result = {
            'enabled': False,
            'possible': False,
            'distance_px': None,
            'threshold_px': 0,
        }
        try:
            # 주 스킬 선택
            primary_skill = None
            for s in getattr(self, 'attack_skills', []) or []:
                if getattr(s, 'is_primary', False) and getattr(s, 'enabled', True):
                    primary_skill = s
                    break
            if not primary_skill:
                return result
            thr = max(1, int(getattr(primary_skill, 'jump_attack_distance_px', 120)))
            result['threshold_px'] = int(thr)
            result['enabled'] = bool(getattr(primary_skill, 'jump_attack_enabled', False))
            if not result['enabled']:
                # 활성화 안 됐어도 기준은 제공
                return result

            primary_area = getattr(self, 'current_primary_area', None)
            if primary_area is None:
                return result
            monsters = self._get_recent_monster_boxes()
            if not monsters:
                return result
            primary_monsters = [m for m in monsters if m.intersects(primary_area)]
            if not (self.latest_snapshot and self.latest_snapshot.character_boxes):
                return result
            character_box = self._select_reference_character_box(self.latest_snapshot.character_boxes)
            char_x = float(character_box.center_x)
            if primary_monsters:
                center_x = sum(float(m.center_x) for m in primary_monsters) / float(len(primary_monsters))
                distance = abs(center_x - char_x)
                result['distance_px'] = float(distance)
            else:
                result['distance_px'] = None

            # 가능 판정은 기존 로직과 동일
            if len(primary_monsters) < 2:
                return result
            if result['distance_px'] is None or float(result['distance_px']) < float(thr):
                return result
            side = 'left' if (primary_monsters and (sum(m.center_x for m in primary_monsters) / float(len(primary_monsters)) < char_x)) else 'right'
            profile = str(getattr(primary_skill, 'jump_profile_right', '') if side == 'right' else getattr(primary_skill, 'jump_profile_left', '') or '').strip()
            if not profile:
                return result
            # 확률 요소는 제외(가능 조건만)
            result['possible'] = True
            return result
        except Exception:
            return result

    def api_is_ladder_escape_condition_now(self) -> bool:
        """사다리복구 조건 충족 여부를 평가하여 반환.

        기준:
        - '사다리복구' 기능이 켜져 있어야 함
        - 포함 상태(점프/사다리/낙하) 중 하나가 현재 player_state에 해당
        - 포함 상태로 연속 유지 시간이 임계값(초) 이상
        """
        try:
            # 기능 ON 확인
            enabled = bool(getattr(self, 'ladder_escape_enabled_checkbox', None).isChecked()) if hasattr(self, 'ladder_escape_enabled_checkbox') else False
            if not enabled:
                return False
            # 포함 상태 설정
            inc_jump = bool(self.ladder_escape_include_jump_checkbox.isChecked()) if hasattr(self, 'ladder_escape_include_jump_checkbox') else True
            inc_ladder = bool(self.ladder_escape_include_ladder_checkbox.isChecked()) if hasattr(self, 'ladder_escape_include_ladder_checkbox') else True
            inc_fall = bool(self.ladder_escape_include_fall_checkbox.isChecked()) if hasattr(self, 'ladder_escape_include_fall_checkbox') else True

            included_states = set()
            if inc_jump:
                included_states.add('jumping')
            if inc_ladder:
                included_states.update({'climbing_up', 'climbing_down', 'on_ladder_idle'})
            if inc_fall:
                included_states.add('falling')

            # 현재 상태
            map_tab = getattr(self, 'map_tab', None)
            cur_state = str(getattr(map_tab, 'player_state', '') or '') if map_tab else ''
            now = time.time()
            if cur_state in included_states:
                if self._ladder_escape_last_state != cur_state:
                    self._ladder_escape_last_state = cur_state
                    self._ladder_escape_state_since_ts = now
            else:
                # 포함되지 않은 상태면 타이머 리셋
                self._ladder_escape_last_state = None
                self._ladder_escape_state_since_ts = 0.0
                return False

            # 연속 유지 시간
            elapsed = max(0.0, now - float(self._ladder_escape_state_since_ts or now))
            thr = float(self.ladder_escape_threshold_spinbox.value()) if hasattr(self, 'ladder_escape_threshold_spinbox') else 2.0
            return elapsed >= max(0.5, thr)
        except Exception:
            return False

    def api_is_ladder_threat_now(self) -> bool:
        """현재 ‘사다리 위협’ 조건이 충족되는지 평가(요청/전이 없이).

        - 맵 상태: 오르기 준비 중(prepare_to_climb)만
        - HP ≤ 임계
        - 주 스킬 범위 내 몬스터 ≥ 1
        """
        try:
            # 맵 상태 확인: prepare_to_climb만 허용
            map_tab = getattr(self, 'map_tab', None)
            nav = str(getattr(map_tab, 'navigation_action', '') or '') if map_tab else ''
            if nav != 'prepare_to_climb':
                return False

            # HP 값
            hp_val = None
            try:
                hp_val = float(self._status_display_values.get('hp'))
            except Exception:
                hp_val = None
            if not isinstance(hp_val, (int, float)):
                return False
            hp_thr = int(self.ladder_hp_threshold_spinbox.value()) if hasattr(self, 'ladder_hp_threshold_spinbox') else 90
            if not (hp_val <= float(hp_thr)):
                return False

            # 주 스킬 범위 내 마릿수 ≥ 1
            return bool(int(self.latest_primary_monster_count) >= 1)
        except Exception:
            return False

    def api_is_ladder_cleanup_active(self) -> bool:
        """사다리 위협 기반 X범위 오버라이드(사다리 정리) 활성 여부."""
        try:
            return bool(
                getattr(self, '_ladder_override_active', False)
                or getattr(self, '_ladder_cleanup_session_active', False)
                or getattr(self, '_ladder_purge_session_active', False)
            )
        except Exception:
            return False

    # ---------------------- 맵-사냥 위치 캘리브레이션 관련 API ----------------------
    def api_get_current_character_position(self) -> dict:
        """현재 기준 캐릭터 박스와 프레임 크기 요약을 반환.
        반환: {'x','y','width','height','center_x','frame_width','frame_height'}
        """
        result = {
            'x': None,
            'y': None,
            'width': None,
            'height': None,
            'center_x': None,
            'frame_width': float(self.latest_perf_stats.get('frame_width', 0.0) or 0.0),
            'frame_height': float(self.latest_perf_stats.get('frame_height', 0.0) or 0.0),
        }
        box = None
        try:
            if self.latest_snapshot and self.latest_snapshot.character_boxes:
                box = self._select_reference_character_box(self.latest_snapshot.character_boxes)
            elif self._last_character_boxes:
                box = self._select_reference_character_box(self._last_character_boxes)
        except Exception:
            box = None
        if box is not None:
            try:
                result.update({
                    'x': float(box.x),
                    'y': float(box.y),
                    'width': float(box.width),
                    'height': float(box.height),
                    'center_x': float(box.center_x),
                })
            except Exception:
                pass
        return result

    def api_get_active_capture_region(self) -> dict | None:
        """현재 사냥탭 캡처 ROI(절대좌표)를 반환."""
        try:
            return self._resolve_manual_capture_region(require_window=True)
        except Exception:
            return None

    def api_was_minimap_x_fallback_recent(self, seconds: float = 1.0) -> bool:
        try:
            if self._minimap_x_fallback_used_ts <= 0.0:
                return False
            return (time.time() - float(self._minimap_x_fallback_used_ts)) <= max(0.1, float(seconds))
        except Exception:
            return False

    def api_start_detection(self) -> bool:
        """사냥 탐지를 시작(이미 실행 중이면 그대로 유지)."""
        try:
            if self._is_detection_active():
                return True
        except Exception:
            pass
        try:
            # 비 UI 트리거에서는 창 활성화가 차단될 수 있어 1회 건너뜀
            setattr(self, '_skip_window_activation_once', True)
            self.detect_btn.setChecked(True)
            self._toggle_detection(True)
            return True
        except Exception:
            return False

    def api_stop_detection(self) -> bool:
        """사냥 탐지를 중지."""
        return bool(self.force_stop_detection(reason='telegram'))

    def api_schedule_shutdown(self, total_seconds: int) -> tuple[bool, str]:
        """n초 뒤 종료 예약을 바로 설정한다. PID 자동탐지 포함."""
        import time as _t
        try:
            sec = max(1, int(total_seconds))
        except Exception:
            sec = 10
        # PID 자동탐지
        if getattr(self, 'shutdown_pid_value', None) is None:
            try:
                self._auto_detect_mapleland_pid(auto_trigger=True)
            except Exception:
                pass
        if getattr(self, 'shutdown_pid_value', None) is None:
            return False, "PID 자동탐지 실패로 종료 예약을 설정하지 못했습니다."
        try:
            self.shutdown_reservation_enabled = True
            self.shutdown_datetime_target = float(_t.time() + sec)
            self._ensure_shutdown_timer_running()
            self._update_shutdown_labels()
            return True, f"종료 예약을 설정했습니다. {sec}초 후 종료합니다."
        except Exception as exc:
            return False, f"종료 예약 실패: {exc}"

    def api_reserve_shutdown(self, minutes: int) -> tuple[bool, str]:
        """n분 뒤 종료 예약."""
        try:
            mins = max(1, int(minutes))
        except Exception:
            mins = 1
        return self.api_schedule_shutdown(mins * 60)

    def api_cancel_shutdown_reservation(self) -> tuple[bool, str]:
        """예약된 종료가 있으면 취소한다."""
        had = bool(getattr(self, 'shutdown_datetime_target', None))
        try:
            self.shutdown_datetime_target = None
            self.shutdown_reservation_enabled = False
            self._stop_shutdown_timer_if_idle()
            self._update_shutdown_labels()
        except Exception as exc:
            return False, f"종료 예약 취소 실패: {exc}"
        return True, ("종료 예약을 취소했습니다." if had else "취소할 종료 예약이 없습니다.")

    def api_schedule_exit_wait(self, countdown_seconds: int = 5) -> tuple[bool, str]:
        """지정된 초 뒤 게임 종료 대기 모드를 시작한다."""
        return self._schedule_exit_wait(countdown_seconds=countdown_seconds, schedule_delay=0.0)

    def api_schedule_exit_wait_in(self, minutes: int, *, countdown_seconds: int = 5) -> tuple[bool, str]:
        """n분 뒤 게임 종료 대기 모드를 시작하도록 예약한다."""
        try:
            mins = max(1, int(minutes))
        except Exception:
            mins = 1
        delay = mins * 60
        return self._schedule_exit_wait(countdown_seconds=countdown_seconds, schedule_delay=delay)

    def api_cancel_exit_wait(self) -> tuple[bool, str]:
        """예약된 게임 종료 대기 플로우를 취소한다."""
        if not self._is_exit_wait_active():
            return True, "예약된 게임 종료가 없습니다."
        try:
            if self.exit_wait_in_progress and bool(getattr(self, 'shutdown_other_player_wait_active', False)):
                self._finish_other_player_wait_mode(reason="exit_wait_cancelled")
        except Exception as exc:
            return False, f"게임 종료 대기 해제 실패: {exc}"
        self._reset_exit_wait_state()
        message = "[종료] 게임 종료 예약을 취소했습니다."
        self.append_log(message, "info")
        self._log_map_shutdown(message, "green")
        return True, "게임 종료 예약을 취소했습니다."

    def _schedule_exit_wait(self, *, countdown_seconds: int, schedule_delay: float) -> tuple[bool, str]:
        if not self._has_wait_waypoint_configured():
            return False, "대기 모드를 실행하려면 먼저 웨이포인트를 설정해주세요."
        if bool(getattr(self, 'shutdown_other_player_wait_active', False)) and not self.exit_wait_in_progress:
            return False, "다른 대기 모드가 진행 중입니다."
        if self.exit_wait_in_progress:
            return False, "이미 게임 종료 대기 플로우가 진행 중입니다."
        countdown = max(0, int(countdown_seconds))
        now = time.time()

        # 상태 초기화
        self.exit_wait_last_request_source = "telegram"
        self.exit_wait_in_progress = False
        self._exit_wait_command_sent = False
        self._exit_wait_finalize_pending = False

        if schedule_delay <= 0.0:
            self.exit_wait_schedule_ts = None
            self.exit_wait_countdown_started_at = None
            self.exit_wait_countdown_due_ts = None
            # 즉시 대기 모드 진입
            self._start_exit_wait_flow()
            self._ensure_shutdown_timer_running()
            self._update_shutdown_labels()
            if not self.exit_wait_in_progress:
                return False, "[종료] 게임 종료 대기 모드 시작에 실패했습니다."
            return True, "게임 종료 대기 모드를 즉시 시작합니다."

        else:
            self.exit_wait_schedule_ts = now + schedule_delay
            self.exit_wait_countdown_started_at = None
            self.exit_wait_countdown_due_ts = None
            minutes = int(schedule_delay // 60)
            if minutes > 0 and schedule_delay % 60 == 0:
                time_text = f"{minutes}분 후"
            else:
                time_text = f"{int(schedule_delay)}초 후"
            message = f"[종료] 게임 종료를 {time_text} 대기 모드에서 실행합니다."
            self.append_log(message, "info")
            self._log_map_shutdown(message, "orange")
            self._ensure_shutdown_timer_running()
            self._update_shutdown_labels()
            return True, message

    def _is_exit_wait_active(self) -> bool:
        return any([
            self.exit_wait_schedule_ts is not None,
            self.exit_wait_countdown_due_ts is not None,
            self.exit_wait_in_progress,
            self._exit_wait_finalize_pending,
        ])

    def _reset_exit_wait_state(self) -> None:
        self.exit_wait_schedule_ts = None
        self.exit_wait_countdown_due_ts = None
        self.exit_wait_countdown_started_at = None
        self.exit_wait_countdown_duration = 5
        self.exit_wait_in_progress = False
        self._exit_wait_command_sent = False
        self._exit_wait_finalize_pending = False
        self.exit_wait_last_request_source = ""
        self._ensure_shutdown_timer_running()
        self._update_shutdown_labels()

    def _start_exit_wait_flow(self) -> None:
        if self.exit_wait_in_progress:
            return
        now = time.time()
        self.exit_wait_countdown_started_at = None
        self.exit_wait_countdown_due_ts = None
        self.append_log("[종료] 게임 종료 대기 모드를 시작합니다.", "info")
        self._log_map_shutdown("[종료] 게임 종료 대기 모드를 시작합니다.", "orange")
        ok = False
        try:
            ok = bool(self._start_other_player_wait_mode(now, flow='exit'))
        except Exception as exc:
            self.append_log(f"[종료] 대기 모드 시작 실패: {exc}", "warn")
            self._log_map_shutdown(f"[종료] 대기 모드 시작 실패: {exc}", "red")
            ok = False
        if not ok:
            self._reset_exit_wait_state()
            return
        # 게임 종료 플로우에서는 탐지를 재시작하지 않도록 강제
        self.shutdown_other_player_wait_restart_required = False
        self.exit_wait_in_progress = True
        self._exit_wait_command_sent = False
        self._exit_wait_finalize_pending = False
        self._ensure_shutdown_timer_running()
        self._update_shutdown_labels()

    def _handle_exit_wait_arrival(self, waypoint_name: str) -> None:
        if not self.exit_wait_in_progress:
            self.append_log("[종료] 대기 도착 알림이 도착했지만 종료 플로우가 활성화되어 있지 않습니다.", "debug")
            return
        if self._exit_wait_command_sent:
            return
        cmd = (getattr(self, 'exit_wait_command_profile', '') or '').strip()
        if not cmd:
            self.append_log("[종료] 실행할 '게임종료' 명령 프로필이 설정되어 있지 않아 플로우를 종료합니다.", "warn")
            self._log_map_shutdown("[종료] '게임종료' 명령 프로필이 없어 종료를 수행하지 못했습니다.", "red")
            self._finalize_exit_wait_after_command(success=False)
            return
        self._exit_wait_command_sent = True
        self._emit_control_command(cmd, reason='exit_wait')
        self.append_log(f"[종료] 대기 웨이포인트 도착 → 명령 실행: '{cmd}'", "info")
        self._log_map_shutdown(f"[종료] 대기 웨이포인트 도착 → 명령 실행: '{cmd}'", "orange")
        self._schedule_exit_wait_finalize()

    def _schedule_exit_wait_finalize(self) -> None:
        if self._exit_wait_finalize_pending:
            return
        self._exit_wait_finalize_pending = True

        def _finalize():
            self._exit_wait_finalize_pending = False
            self._finalize_exit_wait_after_command()

        try:
            QTimer.singleShot(3500, _finalize)
        except Exception:
            # 문제가 발생해도 즉시 시도
            self._finalize_exit_wait_after_command()

    def _finalize_exit_wait_after_command(self, *, success: bool = True) -> None:
        if not self.exit_wait_in_progress:
            self._reset_exit_wait_state()
            return
        if success:
            self.append_log("[종료] 게임 종료 명령 실행 이후 대기 모드를 종료합니다.", "info")
            self._log_map_shutdown("[종료] 게임 종료 명령 실행 이후 대기 모드를 종료합니다.", "orange")
        else:
            self.append_log("[종료] 게임 종료 플로우를 중단합니다.", "warn")
            self._log_map_shutdown("[종료] 게임 종료 플로우를 중단합니다.", "red")
        try:
            if bool(getattr(self, 'shutdown_other_player_wait_active', False)):
                self._finish_other_player_wait_mode(reason="exit_wait_complete")
        except Exception:
            pass
        if success and self.shutdown_sleep_enabled:
            sleep_message = "[종료] 5초 뒤 절전 모드를 시도합니다."
            try:
                self.append_log(sleep_message, "info")
                self._log_map_shutdown(sleep_message, "orange")
            except Exception:
                pass

            def _do_sleep():
                try:
                    self._attempt_system_sleep()
                except Exception:
                    pass

            try:
                QTimer.singleShot(5000, _do_sleep)
            except Exception:
                _do_sleep()
        self._reset_exit_wait_state()

    # ---------------------- 대기 모드(무기한) 제어 ----------------------
    def api_enter_indefinite_wait_mode(self) -> tuple[bool, str]:
        """즉시 대기모드로 진입하여 /대기종료 전까지 유지한다.

        사전 조건: '대기 모드' 웨이포인트가 설정되어 있어야 한다.
        """
        import time as _t
        # 대기모드가 이미 활성화되어 있다면 플래그만 전환
        if getattr(self, 'shutdown_other_player_wait_active', False):
            self._manual_indefinite_wait_active = True
            try:
                if hasattr(self, 'shutdown_other_player_elapsed'):
                    self.shutdown_other_player_elapsed.setText("대기 모드 진행 중")
            except Exception:
                pass
            return True, "이미 대기 모드입니다. 무기한 모드로 전환합니다."

        # 웨이포인트 필요(단일 또는 다중)
        if not self._has_wait_waypoint_configured():
            return False, "대기 모드를 실행하려면 먼저 웨이포인트를 설정해주세요."

        ok = bool(self._start_other_player_wait_mode(float(_t.time())))
        if not ok:
            return False, "대기 모드 시작에 실패했습니다."
        self._manual_indefinite_wait_active = True
        return True, "대기 모드를 시작했습니다(무기한). /대기종료 로 해제하세요."

    def api_exit_indefinite_wait_mode(self) -> tuple[bool, str]:
        """무기한 대기모드를 해제하고 일반 종료 동작(필요 시 탐지 재시작)을 수행한다."""
        was_active = bool(getattr(self, 'shutdown_other_player_wait_active', False))
        self._manual_indefinite_wait_active = False
        if was_active:
            try:
                self._finish_other_player_wait_mode(reason="manual_exit")
            except Exception as exc:
                return False, f"대기 모드 해제 실패: {exc}"
            return True, "대기 모드를 해제했습니다."
        return True, "대기 모드가 활성화되어 있지 않습니다."

    # ---------------------- 금지몬스터 테스트 트리거/해제 ----------------------
    def api_trigger_forbidden_monster(self) -> tuple[bool, str]:
        """금지몬스터 감지 플로우를 수동으로 트리거한다.

        - 실제 감지와 동일한 순서로 모든 키 떼기, 경고음, 대기 모드 진입을 수행
        - 이전 상태를 초기화하고 새 쿨다운(3분)을 시작
        - 웨이포인트/명령 프로필이 없으면 친절한 오류 메시지 반환
        """
        import time as _t
        # 선 조건 검사
        cmd = (getattr(self, 'forbidden_monster_command_profile', '') or '').strip()
        if not bool(getattr(self, 'auto_hunt_enabled', True)):
            return False, "[금지] 자동 사냥이 비활성화되어 있어 금지 플로우를 실행할 수 없습니다."
        if not bool(getattr(self, 'forbidden_monster_enabled', False)):
            return False, "[금지] 기능이 비활성화되어 있습니다. 사냥탭 설정에서 활성화하세요."
        if not cmd:
            return False, "[금지] 실행할 명령 프로필이 설정되어 있지 않습니다."
        if not self._has_wait_waypoint_configured():
            return False, "[금지] 대기 모드를 실행하려면 먼저 웨이포인트를 설정해주세요."

        # 이미 금지 플로우가 진행 중이면 중복 시작 방지
        if bool(getattr(self, '_forbidden_active', False)):
            return True, "[금지] 이미 금지 플로우가 진행 중입니다."

        # 초기화: 기존 쿨다운/상태 정리 후 실제 감지와 동일 플로우 실행
        try:
            self._forbidden_cooldown_until = 0.0
        except Exception:
            pass
        try:
            self._issue_all_keys_release("forbidden_monster:manual_trigger")
        except Exception:
            pass
        try:
            self._play_forbidden_alert()
        except Exception:
            pass

        # 새 쿨다운 시작(3분)
        try:
            self._forbidden_cooldown_until = float(_t.time()) + 180.0
        except Exception:
            self._forbidden_cooldown_until = 0.0

        # 대기 모드 플로우 트리거(실제 감지와 동일 경로)
        try:
            self._trigger_forbidden_wait_flow(float(_t.time()))
        except Exception as exc:
            return False, f"[금지] 대기 모드 시작 실패: {exc}"
        return True, "[금지] 금지몬스터 감지로 간주하고 대기 모드에 진입합니다."

    def api_cancel_forbidden_and_restart(self) -> tuple[bool, str]:
        """금지 플로우를 강제 해제하고 탐지를 다시 시작한다.

        - 진행 중인 대기 모드가 있으면 종료
        - 금지 상태/쿨다운 초기화(즉시 재테스트 가능)
        - 탐지가 정지 상태면 재시작
        """
        # 진행 중 플로우 종료
        if bool(getattr(self, 'shutdown_other_player_wait_active', False)):
            try:
                self._finish_other_player_wait_mode(reason='forbidden_manual_cancel')
            except Exception as exc:
                return False, f"[금지] 해제 중 오류: {exc}"
        # 상태/쿨다운 초기화
        try:
            self._forbidden_active = False
        except Exception:
            pass
        try:
            self._forbidden_cooldown_until = 0.0
        except Exception:
            pass
        self._forbidden_watch_window_until = 0.0
        self._forbidden_lock_until = 0.0
        self._forbidden_visual_overlays = []
        map_tab = getattr(self, 'map_tab', None)
        if map_tab and hasattr(map_tab, 'set_forbidden_wall_suppressed'):
            try:
                map_tab.set_forbidden_wall_suppressed(False, reason='hunt_forbidden_manual_cancel')
            except Exception:
                pass

        # 탐지 재시작 보장
        try:
            if not self._is_detection_active():
                self._restart_hunt_detection_after_wait()
        except Exception:
            # 실패해도 메시지 반환은 계속
            pass
        return True, "[금지] 해제하고 탐지를 다시 시작했습니다."

    # ---------------------- 사냥범위 오버라이드 제어(맵 탭 연동) ----------------------
    def api_get_current_ranges(self) -> dict:
        """현재 사냥탭 스핀박스 상태를 전/후 비대칭 포맷으로 반환.

        - 새 영역(사냥범위 조절칸) 생성 시 초기 기본값으로 사용.
        - 대칭 모드일 경우에도 front/back은 현재 대칭 반경 값을 그대로 채워줌.
        """
        try:
            mode_on = bool(self.facing_range_checkbox.isChecked())
        except Exception:
            mode_on = False

        # 대칭 모드에서도 front/back을 동일 값으로 채움
        if mode_on:
            enemy_front = int(self.enemy_front_spinbox.value())
            enemy_back = int(self.enemy_back_spinbox.value())
            primary_front = int(self.primary_front_spinbox.value())
            primary_back = int(self.primary_back_spinbox.value())
        else:
            radius_enemy = int(self.enemy_range_spinbox.value())
            radius_primary = int(self.primary_skill_range_spinbox.value())
            enemy_front = radius_enemy
            enemy_back = radius_enemy
            primary_front = radius_primary
            primary_back = radius_primary

        return {
            'enemy_front': enemy_front,
            'enemy_back': enemy_back,
            'primary_front': primary_front,
            'primary_back': primary_back,
            'y_band_height': int(self.y_band_height_spinbox.value()),
            'y_band_offset': int(self.y_band_offset_spinbox.value()),
        }

    def api_get_zone_override_defaults(self) -> dict:
        """사냥범위 존 생성 시 사용할 기본 오버라이드 값을 반환."""
        try:
            hunt_threshold = int(self.hunt_monster_threshold_spinbox.value())
        except Exception:
            hunt_threshold = 3
        try:
            primary_threshold = int(self.primary_monster_threshold_spinbox.value())
        except Exception:
            primary_threshold = 1
        try:
            base_teleport = float(self.teleport_probability_spinbox.value())
        except Exception:
            base_teleport = 0.0
        try:
            walk_teleport = float(self.walk_teleport_probability_spinbox.value())
        except Exception:
            walk_teleport = base_teleport
        return {
            'conditions_override': {
                'hunt_monster_threshold': hunt_threshold,
                'primary_monster_threshold': primary_threshold,
            },
            'teleport_override': {
                'probability': base_teleport,
                'walk_probability': walk_teleport,
            },
        }

    def _snapshot_current_ranges(self) -> dict:
        """현재 UI의 사냥 범위 관련 값 전체를 스냅샷으로 저장(복원용)."""
        try:
            mode_on = bool(self.facing_range_checkbox.isChecked())
        except Exception:
            mode_on = False

        snapshot = {
            'mode': 'facing' if mode_on else 'symmetric',
            'enemy_range': int(self.enemy_range_spinbox.value()),
            'primary_range': int(self.primary_skill_range_spinbox.value()),
            'enemy_front': int(self.enemy_front_spinbox.value()),
            'enemy_back': int(self.enemy_back_spinbox.value()),
            'primary_front': int(self.primary_front_spinbox.value()),
            'primary_back': int(self.primary_back_spinbox.value()),
            'y_band_height': int(self.y_band_height_spinbox.value()),
            'y_band_offset': int(self.y_band_offset_spinbox.value()),
            'hunt_monster_threshold': int(self.hunt_monster_threshold_spinbox.value()) if hasattr(self, 'hunt_monster_threshold_spinbox') else 3,
            'primary_monster_threshold': int(self.primary_monster_threshold_spinbox.value()) if hasattr(self, 'primary_monster_threshold_spinbox') else 1,
            'teleport_probability': int(self.teleport_probability_spinbox.value()) if hasattr(self, 'teleport_probability_spinbox') else 0,
            'walk_teleport_probability': float(self.walk_teleport_probability_spinbox.value()) if hasattr(self, 'walk_teleport_probability_spinbox') else 0.0,
            'teleport_enabled': bool(self.teleport_enabled_checkbox.isChecked()) if hasattr(self, 'teleport_enabled_checkbox') else False,
            'walk_teleport_enabled': bool(self.walk_teleport_checkbox.isChecked()) if hasattr(self, 'walk_teleport_checkbox') else False,
        }
        return snapshot

    def _restore_ranges_from_snapshot(self, snapshot: dict) -> None:
        """스냅샷에 저장된 값으로 사냥 범위 UI를 복원."""
        if not isinstance(snapshot, dict):
            return
        try:
            mode_on = (str(snapshot.get('mode', 'symmetric')).lower() == 'facing')
        except Exception:
            mode_on = False

        # 모드 먼저 적용(가려진 위젯 상태 정합성 유지)
        try:
            self.facing_range_checkbox.setChecked(mode_on)
            self._update_range_inputs_enabled(mode_on)
        except Exception:
            pass

        # 값 복원(보이는/숨김 여부와 무관하게 설정)
        try:
            if 'enemy_range' in snapshot:
                self.enemy_range_spinbox.setValue(int(snapshot['enemy_range']))
            if 'primary_range' in snapshot:
                self.primary_skill_range_spinbox.setValue(int(snapshot['primary_range']))
            if 'enemy_front' in snapshot:
                self.enemy_front_spinbox.setValue(int(snapshot['enemy_front']))
            if 'enemy_back' in snapshot:
                self.enemy_back_spinbox.setValue(int(snapshot['enemy_back']))
            if 'primary_front' in snapshot:
                self.primary_front_spinbox.setValue(int(snapshot['primary_front']))
            if 'primary_back' in snapshot:
                self.primary_back_spinbox.setValue(int(snapshot['primary_back']))
            if 'y_band_height' in snapshot:
                self.y_band_height_spinbox.setValue(int(snapshot['y_band_height']))
            if 'y_band_offset' in snapshot:
                self.y_band_offset_spinbox.setValue(int(snapshot['y_band_offset']))
            if 'hunt_monster_threshold' in snapshot and hasattr(self, 'hunt_monster_threshold_spinbox'):
                self.hunt_monster_threshold_spinbox.setValue(int(snapshot['hunt_monster_threshold']))
            if 'primary_monster_threshold' in snapshot and hasattr(self, 'primary_monster_threshold_spinbox'):
                self.primary_monster_threshold_spinbox.setValue(int(snapshot['primary_monster_threshold']))
            if 'teleport_probability' in snapshot and hasattr(self, 'teleport_probability_spinbox'):
                self.teleport_probability_spinbox.setValue(int(snapshot['teleport_probability']))
            if 'walk_teleport_probability' in snapshot and hasattr(self, 'walk_teleport_probability_spinbox'):
                self.walk_teleport_probability_spinbox.setValue(float(snapshot['walk_teleport_probability']))
            if 'teleport_enabled' in snapshot and hasattr(self, 'teleport_enabled_checkbox'):
                self.teleport_enabled_checkbox.setChecked(bool(snapshot['teleport_enabled']))
            if 'walk_teleport_enabled' in snapshot and hasattr(self, 'walk_teleport_checkbox'):
                self.walk_teleport_checkbox.setChecked(bool(snapshot['walk_teleport_enabled']))
        except Exception:
            pass

        # 내부 상태/표시 갱신
        try:
            self._on_area_config_changed()
            self._handle_setting_changed()
        except Exception:
            pass

    def api_apply_zone_override(self, zone_id: str, overrides: dict) -> tuple[bool, str]:
        """맵 탭에서 전달된 영역(사각형) 설정으로 사냥 범위를 일시 변경.

        - 최초 적용 시 현재 스핀박스 값을 백업
        - 같은 zone_id 재요청이면 값만 갱신
        - 다른 zone_id가 활성 중이면 먼저 복원 후 새로 적용
        - 저장 파일에는 백업값이 기록되도록 _save_settings 분기
        """
        try:
            z = str(zone_id or '').strip()
        except Exception:
            z = ''
        if not z:
            return False, '유효하지 않은 영역 ID'

        # 다른 ID가 이미 활성인 경우 우선 복원
        if self._zone_override_active and self._zone_override_id and self._zone_override_id != z:
            self.api_clear_zone_override(None)

        # 최초 진입 시 백업
        if not self._zone_override_active:
            try:
                self._zone_override_backup = self._snapshot_current_ranges()
            except Exception:
                self._zone_override_backup = None

        payload = overrides if isinstance(overrides, dict) else {}
        if any(k in payload for k in ('ranges', 'conditions_override', 'teleport_override', 'conditions', 'teleport')):
            ranges = payload.get('ranges') or {}
            conditions_override = payload.get('conditions_override') or payload.get('conditions') or {}
            teleport_override = payload.get('teleport_override') or payload.get('teleport') or {}
        else:
            ranges = payload
            conditions_override = {}
            teleport_override = {}

        range_flag = payload.get('range_enabled')
        range_enabled = bool(range_flag) if range_flag is not None else True
        if not isinstance(conditions_override, dict):
            conditions_override = {}
        if not isinstance(teleport_override, dict):
            teleport_override = {}
        conditions_enabled = bool(conditions_override.get('enabled', False))
        teleport_enabled = bool(teleport_override.get('enabled', False))
        if not (range_enabled or conditions_enabled or teleport_enabled):
            return False, '활성화된 오버라이드가 없습니다.'

        # 전/후 값만 사용(대칭은 숨김)
        def _ival(d, k, default):
            try:
                return int(d.get(k, default))
            except Exception:
                return int(default)

        if range_enabled:
            enemy_front = _ival(ranges, 'enemy_front', self.enemy_front_spinbox.value())
            enemy_back = _ival(ranges, 'enemy_back', self.enemy_back_spinbox.value())
            primary_front = _ival(ranges, 'primary_front', self.primary_front_spinbox.value())
            primary_back = _ival(ranges, 'primary_back', self.primary_back_spinbox.value())
            y_band_height = _ival(ranges, 'y_band_height', self.y_band_height_spinbox.value())
            y_band_offset = _ival(ranges, 'y_band_offset', self.y_band_offset_spinbox.value())

            # 모드 강제: 전/후 비대칭 ON
            try:
                self.facing_range_checkbox.setChecked(True)
                self._update_range_inputs_enabled(True)
            except Exception:
                pass

            # 값 적용(보이든 숨기든 상관없이 설정 가능)
            try:
                self.enemy_front_spinbox.setValue(enemy_front)
                self.enemy_back_spinbox.setValue(enemy_back)
                self.primary_front_spinbox.setValue(primary_front)
                self.primary_back_spinbox.setValue(primary_back)
                self.y_band_height_spinbox.setValue(y_band_height)
                self.y_band_offset_spinbox.setValue(y_band_offset)
            except Exception:
                pass

        # 사냥조건 임계치 오버라이드
        def _threshold_val(key, default):
            try:
                return int(conditions_override.get(key, default))
            except Exception:
                return int(default)
        if conditions_enabled:
            try:
                self.hunt_monster_threshold_spinbox.setValue(
                    _threshold_val('hunt_monster_threshold', self.hunt_monster_threshold_spinbox.value())
                )
            except Exception:
                pass
            try:
                self.primary_monster_threshold_spinbox.setValue(
                    _threshold_val('primary_monster_threshold', self.primary_monster_threshold_spinbox.value())
                )
            except Exception:
                pass

        # 텔레포트 확률 오버라이드(사냥/걷기 공통)
        if teleport_enabled:
            try:
                if hasattr(self, 'teleport_enabled_checkbox'):
                    self.teleport_enabled_checkbox.setChecked(True)
            except Exception:
                pass
            try:
                if hasattr(self, 'walk_teleport_checkbox'):
                    self.walk_teleport_checkbox.setChecked(True)
            except Exception:
                pass
            try:
                probability = float(teleport_override.get('probability', self.teleport_probability_spinbox.value()))
            except Exception:
                probability = float(self.teleport_probability_spinbox.value())
            probability = max(0.0, min(100.0, probability))
            try:
                self.teleport_probability_spinbox.setValue(int(round(probability)))
            except Exception:
                pass
            try:
                self.walk_teleport_probability_spinbox.setValue(float(probability))
            except Exception:
                pass

        # 내부 상태/표시 갱신(저장은 백업값 기준으로 수행되도록 _save_settings에서 처리)
        try:
            self._on_area_config_changed()
            self._handle_setting_changed()
        except Exception:
            pass

        self._zone_override_active = True
        self._zone_override_id = z
        return True, '사냥범위 오버라이드를 적용했습니다.'

    def api_clear_zone_override(self, zone_id: Optional[str] = None) -> tuple[bool, str]:
        """영역 이탈 등으로 오버라이드를 해제하고, 백업한 사용자 설정으로 복원."""
        if not self._zone_override_active:
            return True, '활성 오버라이드가 없습니다.'

        if zone_id is not None:
            try:
                z = str(zone_id or '').strip()
            except Exception:
                z = ''
            if z and self._zone_override_id and z != self._zone_override_id:
                return False, '다른 영역 ID가 활성화되어 있습니다.'

        try:
            if isinstance(self._zone_override_backup, dict):
                self._restore_ranges_from_snapshot(self._zone_override_backup)
        except Exception:
            pass

        self._zone_override_active = False
        self._zone_override_id = None
        self._zone_override_backup = None
        return True, '사냥범위 오버라이드를 해제했습니다.'

    def _schedule_facing_reset(self) -> None:
        if not hasattr(self, 'facing_reset_timer'):
            return
        self.facing_reset_timer.stop()
        if not self._is_detection_active():
            return
        if getattr(self, '_direction_active', False):
            return
        # [Sticky Facing] 전/후 비대칭 모드일 때는 마지막 방향을 무기한 유지한다.
        # 따라서 방향 리셋 타이머를 예약하지 않는다.
        try:
            if getattr(self, 'facing_range_checkbox', None) and self.facing_range_checkbox.isChecked():
                return
        except Exception:
            pass
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
        # [Sticky Facing] 전/후 비대칭 모드일 때는 마지막 방향을 무기한 유지한다.
        try:
            if getattr(self, 'facing_range_checkbox', None) and self.facing_range_checkbox.isChecked():
                return
        except Exception:
            pass
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
                # 탐지 비활성(ESC 등) 상태에서는 예약된 콜백을 실행하지 않음(즉시성 보장)
                if not self._is_detection_active():
                    return
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
        # [NEW] 금지몬스터 명령 완료 시 1초 뒤 대기모드 종료 + 쿨다운
        try:
            if isinstance(reason, str) and reason == 'forbidden_monster':
                self.append_log("금지 프로필 완료 콜백 수신 → 1초 뒤 대기모드 종료 예약", 'info')
                self._schedule_forbidden_finish()
        except Exception:
            pass
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
        ladder_group = self._create_ladder_settings_group()

        left_column.addWidget(detection_group)
        left_column.addStretch(1)

        right_column = QVBoxLayout()
        right_column.setSpacing(10)

        skill_group = self._create_skill_group()
        right_column.addWidget(skill_group, 1)

        config_grid = QGridLayout()
        config_grid.setContentsMargins(0, 0, 0, 0)
        config_grid.setHorizontalSpacing(12)
        config_grid.setVerticalSpacing(10)

        range_column = QVBoxLayout()
        range_column.setSpacing(10)
        for group in (range_group, condition_group):
            group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
            range_column.addWidget(group)

        direction_column = QVBoxLayout()
        direction_column.setSpacing(10)
        for group in (direction_switch_group, direction_group, ladder_group):
            group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
            direction_column.addWidget(group)

        # 자동 대응 그룹을 방향/사다리 설정 우측 열에 배치
        auto_shutdown_group = self._create_auto_shutdown_group()
        auto_column = QVBoxLayout()
        auto_column.setSpacing(10)
        auto_column.addWidget(auto_shutdown_group)
        map_return_group = self._create_map_return_group()
        auto_column.addWidget(map_return_group)
        auto_column.addStretch(1)

        config_grid.addLayout(range_column, 0, 0)
        config_grid.addLayout(direction_column, 0, 1)
        config_grid.addLayout(auto_column, 0, 2)
        # 가로 폭 비율: 범위/조건 : 방향/사다리 : 자동대응 = 2:2:1
        config_grid.setColumnStretch(0, 2)
        config_grid.setColumnStretch(1, 2)
        config_grid.setColumnStretch(2, 1)

        right_column.addLayout(config_grid)

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

    def _create_map_return_group(self) -> QGroupBox:
        group = QGroupBox("맵 복귀 모드")
        group.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        )
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setSpacing(6)
        self.map_return_enable_checkbox = QCheckBox("사용")
        self.map_return_enable_checkbox.setChecked(False)
        self.map_return_enable_checkbox.toggled.connect(self._on_map_return_enabled_toggled)
        header_row.addWidget(self.map_return_enable_checkbox)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        roi_row = QHBoxLayout()
        roi_row.setSpacing(6)
        self.map_return_roi_button = QPushButton("OCR 범위")
        self.map_return_roi_button.setMinimumWidth(90)
        self.map_return_roi_button.clicked.connect(self._handle_map_return_roi_select)
        roi_row.addWidget(self.map_return_roi_button)
        self.map_return_test_button = QPushButton("인식 테스트")
        self.map_return_test_button.setMinimumWidth(90)
        self.map_return_test_button.clicked.connect(self._handle_map_return_test)
        roi_row.addWidget(self.map_return_test_button)
        self.map_return_interval_spin = QDoubleSpinBox()
        self.map_return_interval_spin.setRange(1.0, 600.0)
        self.map_return_interval_spin.setDecimals(1)
        self.map_return_interval_spin.setSingleStep(0.5)
        self.map_return_interval_spin.setSuffix(" s")
        self.map_return_interval_spin.setToolTip("탐지 주기(초)")
        self.map_return_interval_spin.setMaximumWidth(70)
        self.map_return_interval_spin.valueChanged.connect(self._on_map_return_interval_changed)
        self.map_return_interval_spin.setValue(self.map_return_interval_sec)
        roi_row.addWidget(self.map_return_interval_spin)
        self.map_return_manage_button = QPushButton("로직 관리")
        self.map_return_manage_button.setMinimumWidth(90)
        self.map_return_manage_button.clicked.connect(self._open_map_return_config_dialog)
        roi_row.addWidget(self.map_return_manage_button)
        roi_row.addStretch(1)
        self.map_return_roi_summary = QLabel("범위 미설정")
        self.map_return_roi_summary.setStyleSheet("color: #666666;")
        self.map_return_roi_summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        roi_row.addWidget(self.map_return_roi_summary)
        layout.addLayout(roi_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)

        def _setup_spin(spin: QSpinBox | QDoubleSpinBox, width: int = 70) -> None:
            spin.setMaximumWidth(width)
            spin.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.map_return_conf_spin = QDoubleSpinBox()
        self.map_return_conf_spin.setRange(0.0, 100.0)
        self.map_return_conf_spin.setDecimals(1)
        self.map_return_conf_spin.setSingleStep(1.0)
        _setup_spin(self.map_return_conf_spin, 70)
        self.map_return_conf_spin.valueChanged.connect(self._on_map_return_conf_changed)
        self.map_return_conf_spin.setValue(self.map_return_conf_threshold)
        filter_row.addWidget(QLabel("신뢰도%"))
        filter_row.addWidget(self.map_return_conf_spin)

        self.map_return_min_height_spin = QSpinBox()
        self.map_return_min_height_spin.setRange(0, 5000)
        self.map_return_min_height_spin.setSingleStep(5)
        _setup_spin(self.map_return_min_height_spin)
        self.map_return_min_height_spin.valueChanged.connect(self._on_map_return_min_height_changed)
        self.map_return_min_height_spin.setValue(self.map_return_min_height)
        filter_row.addWidget(QLabel("H≥"))
        filter_row.addWidget(self.map_return_min_height_spin)

        self.map_return_max_height_spin = QSpinBox()
        self.map_return_max_height_spin.setRange(0, 5000)
        self.map_return_max_height_spin.setSingleStep(5)
        _setup_spin(self.map_return_max_height_spin)
        self.map_return_max_height_spin.valueChanged.connect(self._on_map_return_max_height_changed)
        self.map_return_max_height_spin.setValue(self.map_return_max_height)
        filter_row.addWidget(QLabel("H≤"))
        filter_row.addWidget(self.map_return_max_height_spin)

        self.map_return_min_width_spin = QSpinBox()
        self.map_return_min_width_spin.setRange(0, 5000)
        self.map_return_min_width_spin.setSingleStep(5)
        _setup_spin(self.map_return_min_width_spin)
        self.map_return_min_width_spin.valueChanged.connect(self._on_map_return_min_width_changed)
        self.map_return_min_width_spin.setValue(self.map_return_min_width)
        filter_row.addWidget(QLabel("W≥"))
        filter_row.addWidget(self.map_return_min_width_spin)

        self.map_return_max_width_spin = QSpinBox()
        self.map_return_max_width_spin.setRange(0, 5000)
        self.map_return_max_width_spin.setSingleStep(5)
        _setup_spin(self.map_return_max_width_spin)
        self.map_return_max_width_spin.valueChanged.connect(self._on_map_return_max_width_changed)
        self.map_return_max_width_spin.setValue(self.map_return_max_width)
        filter_row.addWidget(QLabel("W≤"))
        filter_row.addWidget(self.map_return_max_width_spin)

        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        base_row = QHBoxLayout()
        base_row.setSpacing(6)
        base_row.addWidget(QLabel("기준 맵 프로필:"))
        self.map_return_base_profile_combo = QComboBox()
        self.map_return_base_profile_combo.currentIndexChanged.connect(self._on_map_return_base_profile_changed)
        self.map_return_base_profile_combo.setMinimumWidth(140)
        self.map_return_base_profile_combo.setMaximumWidth(200)
        base_row.addWidget(self.map_return_base_profile_combo)
        base_row.addWidget(QLabel("키워드(콤마):"))
        self.map_return_base_keywords_line = QLineEdit()
        self.map_return_base_keywords_line.setPlaceholderText("예: 기호,동굴,1채")
        self.map_return_base_keywords_line.textChanged.connect(self._on_map_return_base_keywords_changed)
        self.map_return_base_keywords_line.setMaximumWidth(250)
        base_row.addWidget(self.map_return_base_keywords_line)
        layout.addLayout(base_row)

        group.setLayout(layout)
        self._refresh_map_return_profile_options()
        if hasattr(self, 'map_return_base_keywords_line'):
            blocker_kw = QSignalBlocker(self.map_return_base_keywords_line)
            try:
                self.map_return_base_keywords_line.setText(self.map_return_base_keywords)
            finally:
                del blocker_kw
        blocker = QSignalBlocker(self.map_return_enable_checkbox)
        try:
            self.map_return_enable_checkbox.setChecked(self.map_return_enabled)
        finally:
            del blocker
        self._update_map_return_controls()
        self._update_map_return_roi_summary()
        return group

    def _update_map_return_roi_summary(self) -> None:
        roi = self.map_return_roi
        if not isinstance(roi, dict):
            self.map_return_roi_summary.setText("범위 미설정")
            return
        try:
            left = int(round(float(roi.get('left', 0))))
            top = int(round(float(roi.get('top', 0))))
            width = int(round(float(roi.get('width', 0))))
            height = int(round(float(roi.get('height', 0))))
        except Exception:
            self.map_return_roi_summary.setText("범위 미설정")
            return
        self.map_return_roi_summary.setText(f"({left}, {top}) {width}x{height}")

    def _update_map_return_controls(self) -> None:
        enabled = bool(self.map_return_enable_checkbox.isChecked())
        widgets = [
            getattr(self, 'map_return_roi_button', None),
            getattr(self, 'map_return_test_button', None),
            getattr(self, 'map_return_interval_spin', None),
            getattr(self, 'map_return_conf_spin', None),
            getattr(self, 'map_return_min_height_spin', None),
            getattr(self, 'map_return_max_height_spin', None),
            getattr(self, 'map_return_min_width_spin', None),
            getattr(self, 'map_return_max_width_spin', None),
            getattr(self, 'map_return_base_profile_combo', None),
            getattr(self, 'map_return_base_keywords_line', None),
            getattr(self, 'map_return_manage_button', None),
        ]
        for widget in widgets:
            if widget is not None:
                widget.setEnabled(enabled)

    def _refresh_map_return_profile_options(self) -> None:
        combo = getattr(self, 'map_return_base_profile_combo', None)
        if combo is None:
            return
        try:
            current = str(self.map_return_base_profile or '')
        except Exception:
            current = ''
        old_profile = current
        profiles: list[str] = []
        map_tab = getattr(self, 'map_tab', None)
        if map_tab and hasattr(map_tab, 'profile_selector'):
            try:
                profiles = [map_tab.profile_selector.itemText(i) for i in range(map_tab.profile_selector.count())]
            except Exception:
                profiles = []
        unique_profiles = []
        seen = set()
        for name in profiles:
            if not name:
                continue
            if name in seen:
                continue
            seen.add(name)
            unique_profiles.append(name)
        unique_profiles.sort(key=lambda x: x.lower())
        block = combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("선택 없음", "")
            for name in unique_profiles:
                combo.addItem(name, name)
            idx = combo.findData(current)
            if idx < 0 and current:
                combo.addItem(current, current)
                idx = combo.count() - 1
            if idx < 0:
                idx = 0
            combo.setCurrentIndex(idx)
            new_profile = str(combo.currentData() or '')
            self.map_return_base_profile = new_profile
        finally:
            combo.blockSignals(block)

    def _on_map_return_enabled_toggled(self, checked: bool) -> None:
        self.map_return_enabled = bool(checked)
        if not self.map_return_enabled and self._map_return_recovering:
            self._abort_map_return("맵 복귀 모드를 해제하여 복구를 중단합니다.", frame_bgr=None, notify=False)
        self._update_map_return_controls()
        self._update_map_return_timer_state()
        self._handle_map_return_settings_changed()

    def _on_map_return_interval_changed(self, value: float) -> None:
        try:
            self.map_return_interval_sec = max(0.5, float(value))
        except (TypeError, ValueError):
            self.map_return_interval_sec = 3.0
        self._update_map_return_timer_state()
        self._handle_map_return_settings_changed()

    def _on_map_return_conf_changed(self, value: float) -> None:
        try:
            self.map_return_conf_threshold = max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            self.map_return_conf_threshold = 0.0
        self._handle_map_return_settings_changed()

    def _on_map_return_min_height_changed(self, value: int) -> None:
        try:
            self.map_return_min_height = max(0, int(value))
        except (TypeError, ValueError):
            self.map_return_min_height = 0
        self._handle_map_return_settings_changed()

    def _on_map_return_max_height_changed(self, value: int) -> None:
        try:
            self.map_return_max_height = max(0, int(value))
        except (TypeError, ValueError):
            self.map_return_max_height = 0
        self._handle_map_return_settings_changed()

    def _on_map_return_min_width_changed(self, value: int) -> None:
        try:
            self.map_return_min_width = max(0, int(value))
        except (TypeError, ValueError):
            self.map_return_min_width = 0
        self._handle_map_return_settings_changed()

    def _on_map_return_max_width_changed(self, value: int) -> None:
        try:
            self.map_return_max_width = max(0, int(value))
        except (TypeError, ValueError):
            self.map_return_max_width = 0
        self._handle_map_return_settings_changed()

    def _on_map_return_base_profile_changed(self, index: int) -> None:
        combo = getattr(self, 'map_return_base_profile_combo', None)
        if combo is None:
            return
        self.map_return_base_profile = str(combo.currentData() or '')
        self._handle_map_return_settings_changed()

    def _on_map_return_base_keywords_changed(self, text: str) -> None:
        self.map_return_base_keywords = (text or '').strip()
        self._handle_map_return_settings_changed()

    def _handle_map_return_roi_select(self) -> None:
        try:
            snipper = ScreenSnipper(self)
        except Exception as exc:
            QMessageBox.warning(self, "오류", f"화면 캡처 도구를 열 수 없습니다: {exc}")
            return
        if not snipper.exec():
            self.append_log("맵 복귀 모드 OCR 범위 지정이 취소되었습니다.", "info")
            return
        roi = snipper.get_roi()
        new_region = {
            'top': roi.top(),
            'left': roi.left(),
            'width': roi.width(),
            'height': roi.height(),
        }
        if new_region['width'] <= 0 or new_region['height'] <= 0:
            QMessageBox.warning(self, "영역 오류", "지정한 영역의 크기가 유효하지 않습니다.")
            return
        window_geometry = get_maple_window_geometry()
        relative_region = None
        if window_geometry:
            relative_region = ensure_relative_roi(new_region, window_geometry, anchor_name=last_used_anchor_name())
        if not relative_region:
            relative_region = dict(new_region)
        self.map_return_roi = copy.deepcopy(relative_region)
        self._update_map_return_roi_summary()
        self._handle_map_return_settings_changed()
        self._update_map_return_timer_state()

    def _handle_map_return_test(self) -> None:
        if not isinstance(self.map_return_roi, dict):
            QMessageBox.information(self, "맵 복귀 OCR", "탐지 범위를 먼저 지정해주세요.")
            return
        frame_bgr = self._capture_map_return_frame()
        if frame_bgr is None or frame_bgr.size == 0:
            QMessageBox.warning(self, "맵 복귀 OCR", "화면 캡처에 실패했습니다. Maple 창이 가려져 있는지 확인해주세요.")
            return

        words = self._perform_map_return_ocr(frame_bgr)
        annotated = draw_word_boxes(frame_bgr, words)
        try:
            annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        except Exception:
            annotated_rgb = annotated

        height, width = annotated_rgb.shape[:2]
        bytes_per_line = annotated_rgb.strides[0]
        qimage = QImage(annotated_rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimage)

        lines: list[str] = []
        roi_summary = self._resolve_map_return_roi_absolute()
        if roi_summary:
            lines.append(
                f"ROI: left={roi_summary['left']}, top={roi_summary['top']}, "
                f"width={roi_summary['width']}, height={roi_summary['height']}"
            )
        else:
            lines.append("ROI: (변환 실패) - 저장된 좌표를 다시 확인해주세요.")

        if self.map_return_conf_threshold > 0:
            lines.append(f"신뢰도 필터 ≥ {self.map_return_conf_threshold:.1f}%")
        if self.map_return_min_height > 0 or self.map_return_max_height > 0:
            lines.append(
                f"높이 필터 {self.map_return_min_height or 0}px ~ {self.map_return_max_height or '제한 없음'}px"
            )
        if self.map_return_min_width > 0 or self.map_return_max_width > 0:
            lines.append(
                f"너비 필터 {self.map_return_min_width or 0}px ~ {self.map_return_max_width or '제한 없음'}px"
            )

        lines.append(f"감지 단어 수: {len(words)}개")
        if words:
            for idx, word in enumerate(words[:30], start=1):
                try:
                    lines.append(
                        f"[{idx}] {word.text} (신뢰도 {int(round(word.conf))}%, "
                        f"W {int(word.width)}px / H {int(word.height)}px)"
                    )
                except Exception:
                    continue
            if len(words) > 30:
                lines.append(f"... 외 {len(words) - 30}개 생략")
        else:
            lines.append("인식된 텍스트가 없습니다.")

        dialog = QDialog(self)
        dialog.setWindowTitle("맵 복귀 OCR 인식 확인")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)

        image_label = QLabel()
        image_label.setPixmap(pixmap)
        image_label.setScaledContents(True)
        image_label.setMinimumSize(min(480, width), min(270, height))
        layout.addWidget(image_label)

        summary_edit = QTextEdit()
        summary_edit.setReadOnly(True)
        summary_edit.setText("\n".join(lines))
        summary_edit.setMinimumHeight(160)
        layout.addWidget(summary_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(dialog.reject)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)

        dialog.resize(min(width + 120, 960), min(height + 320, 760))
        dialog.exec()

    def _open_map_return_config_dialog(self) -> None:
        dlg = MapReturnManagerDialog(self)
        dlg.exec()

    def _update_map_return_timer_state(self) -> None:
        if self.map_return_timer is None:
            return
        if self.map_return_enabled and self.map_return_roi and not self._map_return_recovering:
            interval_ms = max(500, int(self.map_return_interval_sec * 1000))
            if self.map_return_timer.interval() != interval_ms:
                self.map_return_timer.setInterval(interval_ms)
            if not self.map_return_timer.isActive():
                self.map_return_timer.start()
        else:
            if self.map_return_timer.isActive():
                self.map_return_timer.stop()

    def _handle_map_return_settings_changed(self) -> None:
        # 후속 단계에서 설정 저장/상태 반영을 확장
        self._save_settings()

    def _handle_map_return_tick(self) -> None:
        """맵 복귀 모드 OCR 주기 콜백 (구현 예정)."""
        if not self.map_return_enabled or self._map_return_recovering:
            return
        roi_frame = self._capture_map_return_frame()
        if roi_frame is None:
            self._map_return_last_detected = ""
            return
        words = self._perform_map_return_ocr(roi_frame)
        if not words:
            if self._map_return_last_detected:
                self._map_return_last_detected = ""
            return
        detected_text = self._combine_map_return_words(words)
        normalized_text = self._map_return_normalize(detected_text)
        if not normalized_text:
            if self._map_return_last_detected:
                self._map_return_last_detected = ""
            return

        base_keywords = self._map_return_extract_keywords(self.map_return_base_keywords)
        if base_keywords and any(keyword in normalized_text for keyword in base_keywords):
            if self._map_return_last_detected != normalized_text:
                self.append_log(f"[맵 복귀] 기준 맵 키워드 감지: '{detected_text}'", "debug")
            self._map_return_last_detected = normalized_text
            self._reset_map_return_alerts()
            return

        matched = self._match_map_return_keyword(normalized_text)
        if matched:
            map_name, map_cfg = matched
            self._begin_map_return_recovery(map_name, map_cfg, roi_frame, detected_text, words)
            return

        self._map_return_last_detected = normalized_text
        self._map_return_maybe_notify(detected_text, roi_frame)

    def _map_return_normalize(self, text: str) -> str:
        if text is None:
            return ""
        try:
            s = str(text)
        except Exception:
            return ""
        return "".join(s.split()).lower()

    def _map_return_extract_keywords(self, raw: Optional[str]) -> list[str]:
        if not raw:
            return []
        keywords: list[str] = []
        for token in str(raw).split(','):
            normalized = self._map_return_normalize(token)
            if normalized:
                keywords.append(normalized)
        return keywords

    def _reset_map_return_alerts(self, key: Optional[str] = None) -> None:
        if key:
            self._map_return_alert_count.pop(key, None)
            self._map_return_last_alert_ts.pop(key, None)
            return
        self._map_return_alert_count.clear()
        self._map_return_last_alert_ts.clear()

    def _resolve_map_return_roi_absolute(self) -> Optional[dict]:
        if not isinstance(self.map_return_roi, dict):
            return None
        window_geometry = get_maple_window_geometry()
        resolved = resolve_roi_to_absolute(self.map_return_roi, window=window_geometry)
        if resolved is None:
            resolved = resolve_roi_to_absolute(self.map_return_roi)
        if resolved is None:
            resolved = dict(self.map_return_roi)
        try:
            left = int(round(float(resolved.get('left', 0))))
            top = int(round(float(resolved.get('top', 0))))
            width = int(round(float(resolved.get('width', 0))))
            height = int(round(float(resolved.get('height', 0))))
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        return {'left': left, 'top': top, 'width': width, 'height': height}

    def _capture_map_return_frame(self) -> Optional[np.ndarray]:
        roi = self._resolve_map_return_roi_absolute()
        if not roi:
            return None
        try:
            import mss  # type: ignore
            import numpy as _np  # type: ignore
        except Exception:
            return None
        try:
            with mss.mss() as sct:
                shot = sct.grab({'left': roi['left'], 'top': roi['top'], 'width': roi['width'], 'height': roi['height']})
            frame_bgra = _np.frombuffer(shot.raw, dtype=_np.uint8).reshape(shot.height, shot.width, 4)
            return frame_bgra[:, :, :3].copy()
        except Exception:
            return None

    def _perform_map_return_ocr(self, frame_bgr: Optional[np.ndarray]) -> list:
        if frame_bgr is None or frame_bgr.size == 0:
            return []
        conf = self.map_return_conf_threshold if self.map_return_conf_threshold > 0 else None
        min_h = self.map_return_min_height if self.map_return_min_height > 0 else None
        max_h = self.map_return_max_height if self.map_return_max_height > 0 else None
        min_w = self.map_return_min_width if self.map_return_min_width > 0 else None
        max_w = self.map_return_max_width if self.map_return_max_width > 0 else None
        try:
            words = ocr_korean_words(
                frame_bgr,
                conf_threshold=conf,
                min_height_px=min_h,
                max_height_px=max_h,
                min_width_px=min_w,
                max_width_px=max_w,
            )
        except Exception as exc:
            self.append_log(f"[맵 복귀] OCR 실패: {exc}", "warn")
            return []
        return words or []

    def _combine_map_return_words(self, words: list) -> str:
        texts: list[str] = []
        for word in words:
            text = getattr(word, 'text', '')
            if not text:
                continue
            texts.append(str(text))
        joined = " ".join(texts)
        return joined.strip()

    def _match_map_return_keyword(self, normalized_text: str) -> Optional[tuple[str, dict]]:
        if not normalized_text:
            return None
        for name, payload in self.map_return_registered_maps.items():
            if not isinstance(payload, dict):
                payload = {}
            keywords = self._map_return_extract_keywords(payload.get('keywords'))
            if keywords and any(keyword in normalized_text for keyword in keywords):
                return name, payload
            normalized_name = self._map_return_normalize(name)
            if normalized_name and normalized_name in normalized_text:
                return name, payload
        return None

    def _map_return_maybe_notify(self, detected_text: str, frame: Optional[np.ndarray]) -> None:
        key = self._map_return_normalize(detected_text) or "(empty)"
        count = int(self._map_return_alert_count.get(key, 0))
        if count >= int(self.map_return_telegram_limit):
            return
        now = time.time()
        last_ts = float(self._map_return_last_alert_ts.get(key, 0.0) or 0.0)
        if now - last_ts < max(1.0, self.map_return_interval_sec * 0.5):
            return
        message = "[맵 복귀] 기준 맵과 다른 텍스트 감지"
        if detected_text:
            message += f": {detected_text}"
        base_kw_text = str(self.map_return_base_keywords or '').strip()
        if base_kw_text:
            message += f" (기준 키워드='{base_kw_text}')"
        if self._notify_telegram(message):
            self.append_log(message, "warn")
        self._map_return_alert_count[key] = count + 1
        self._map_return_last_alert_ts[key] = now

    def _begin_map_return_recovery(
        self,
        map_name: str,
        map_cfg: dict,
        frame_bgr: Optional[np.ndarray],
        detected_text: str,
        words: list,
        existing_state: Optional[dict] = None,
    ) -> None:
        """맵 복귀 플로우를 시작한다."""
        map_tab = getattr(self, 'map_tab', None)
        if not map_tab:
            message = "[맵 복귀] 맵 탭과 연동되지 않아 복구를 실행할 수 없습니다."
            self.append_log(message, "warn")
            self._map_return_send_telegram(message, frame_bgr)
            self._map_return_recovering = False
            self._update_map_return_timer_state()
            return

        profile = str(map_cfg.get('profile', '') or '')
        waypoint_id = str(map_cfg.get('waypoint_id', '') or '')
        command_profile = str(map_cfg.get('command_profile', '') or '')
        waypoint_name = str(map_cfg.get('waypoint_name', '') or '')

        if not profile or not waypoint_id:
            message = f"[맵 복귀] '{map_name}' 설정이 부족하여 복구를 실행할 수 없습니다."
            self.append_log(message, "warn")
            self._map_return_send_telegram(message, frame_bgr)
            self._map_return_recovering = False
            self._update_map_return_timer_state()
            return

        base_state = dict(existing_state) if isinstance(existing_state, dict) else None
        if not base_state:
            base_state = {
                'hunt_detection_was_active': self._is_detection_active(),
                'previous_profile': str(getattr(map_tab, 'active_profile_name', '') or ''),
                'map_detection_was_running': bool(getattr(map_tab, 'is_detection_running', False)),
                'retry_depth': 0,
            }
        else:
            base_state['retry_depth'] = int(base_state.get('retry_depth', 0) or 0) + 1

        self._map_return_detection_was_active = bool(base_state.get('hunt_detection_was_active', False))

        # 맵 프로필 전환
        try:
            current_profile = str(getattr(map_tab, 'active_profile_name', '') or '')
        except Exception:
            current_profile = ''
        if profile != current_profile:
            selector = getattr(map_tab, 'profile_selector', None)
            if selector is None:
                message = f"[맵 복귀] 맵 탭 프로필 선택 위젯을 찾지 못했습니다. (요청 프로필: {profile})"
                self.append_log(message, "warn")
                self._map_return_send_telegram(message, frame_bgr)
                self._map_return_recovering = False
                self._update_map_return_timer_state()
                return
            idx = selector.findText(profile)
            if idx < 0:
                message = f"[맵 복귀] 맵 프로필 '{profile}'을 찾을 수 없습니다."
                self.append_log(message, "warn")
                self._map_return_send_telegram(message, frame_bgr)
                self._map_return_recovering = False
                self._update_map_return_timer_state()
                return
            blocker = QSignalBlocker(selector)
            selector.setCurrentIndex(idx)
            del blocker
            try:
                map_tab.load_profile_data(profile)
            except Exception as exc:
                self.append_log(f"[맵 복귀] 프로필 '{profile}' 로드 중 오류: {exc}", "warn")

        if not waypoint_name:
            waypoint_name = self._lookup_map_return_waypoint_name(profile, waypoint_id)

        if not bool(getattr(map_tab, 'is_detection_running', False)):
            message = "[맵 복귀] 맵 탐지가 중지되어 있어 복구를 실행할 수 없습니다."
            self.append_log(message, "warn")
            self._map_return_send_telegram(message, frame_bgr)
            self._map_return_recovering = False
            self._update_map_return_timer_state()
            return

        try:
            started = map_tab.start_other_player_wait_operation(
                waypoint_id=waypoint_id,
                waypoint_name=waypoint_name or waypoint_id,
                source='hunt.map_return',
                wait_hp_config=None,
            )
        except Exception as exc:
            message = f"[맵 복귀] 맵 탭 이동을 시작하지 못했습니다: {exc}"
            self.append_log(message, "warn")
            self._map_return_send_telegram(message, frame_bgr)
            self._map_return_recovering = False
            self._update_map_return_timer_state()
            return

        if not started:
            message = "[맵 복귀] 맵 탭이 복구 이동 요청을 거부했습니다."
            self.append_log(message, "warn")
            self._map_return_send_telegram(message, frame_bgr)
            self._map_return_recovering = False
            self._update_map_return_timer_state()
            return

        self._map_return_recovering = True
        self._map_return_active_map = map_name
        self._map_return_last_detected = self._map_return_normalize(detected_text)
        self._reset_map_return_alerts()
        self._update_map_return_timer_state()

        # 사냥 탐지 중이었다면 중지 처리
        if base_state.get('hunt_detection_was_active', False):
            previous_sync = bool(getattr(self, '_syncing_with_map', False))
            self._syncing_with_map = True
            try:
                self.force_stop_detection(reason='map_return_start', preserve_forbidden=True)
            finally:
                self._syncing_with_map = previous_sync

        try:
            if self.current_authority == 'hunt':
                self.release_control(reason='MAP_RETURN_START')
        except Exception:
            pass

        self._map_return_context = {
            'base_state': base_state,
            'target_map': map_name,
            'profile': profile,
            'waypoint_id': waypoint_id,
            'waypoint_name': waypoint_name or waypoint_id,
            'command_profile': command_profile,
            'detected_text': detected_text,
            'stage': 'travel',
            'check_attempt': 0,
            'last_detected_text': detected_text,
        }

        self.append_log(f"[맵 복귀] '{map_name}' 복구를 시작합니다. 웨이포인트: {waypoint_name}", "info")
        try:
            if hasattr(map_tab, 'update_general_log'):
                map_tab.update_general_log(f"[맵 복귀] '{map_name}' 복구를 시작합니다.", "orange")
        except Exception:
            pass

    def _handle_map_return_arrival(self, waypoint_name: str) -> None:
        if not self._map_return_recovering:
            return
        context = self._map_return_context or {}
        context['stage'] = 'arrived'
        context['arrival_waypoint'] = waypoint_name
        command = str(context.get('command_profile', '') or '')
        if command:
            self._emit_control_command(command, reason='map_return')
            try:
                map_tab = getattr(self, 'map_tab', None)
                if map_tab and hasattr(map_tab, 'on_other_player_wait_command_started'):
                    map_tab.on_other_player_wait_command_started(source='hunt.map_return')
            except Exception:
                pass
            self.append_log(f"[맵 복귀] '{context.get('target_map', '')}' 웨이포인트 도착 → 명령 '{command}' 실행", "info")
        else:
            self.append_log(f"[맵 복귀] '{context.get('target_map', '')}' 웨이포인트 도착 (명령 미지정)", "info")
        context['check_attempt'] = 0
        self._map_return_context = context
        self.map_return_recovery_timer.stop()
        self.map_return_recovery_timer.setInterval(1000)
        self.map_return_recovery_timer.start()

    def _handle_map_return_recovery_check(self) -> None:
        if not self._map_return_recovering:
            self.map_return_recovery_timer.stop()
            return

        context = self._map_return_context or {}
        attempt = int(context.get('check_attempt', 0)) + 1
        context['check_attempt'] = attempt

        frame = self._capture_map_return_frame()
        if frame is None:
            detected_text = ""
            words: list = []
            self.append_log(f"[맵 복귀] OCR 캡처 실패 ({attempt}/3)", "warn")
        else:
            words = self._perform_map_return_ocr(frame)
            detected_text = self._combine_map_return_words(words)

        normalized = self._map_return_normalize(detected_text)
        context['last_detected_text'] = detected_text
        self._map_return_context = context

        base_keywords = self._map_return_extract_keywords(self.map_return_base_keywords)
        if normalized and base_keywords and any(keyword in normalized for keyword in base_keywords):
            self.map_return_recovery_timer.stop()
            keywords_text = self.map_return_base_keywords or ','.join(base_keywords)
            target_profile = self.map_return_base_profile or '(미지정)'
            success_msg = (
                f"[맵 복귀] 기준 프로필 '{target_profile}' 복귀 확인 (시도 {attempt}회)"
                f" - 키워드: {keywords_text or '(미설정)'}"
            )
            self.append_log(success_msg, "info")
            self._map_return_send_telegram(success_msg, frame)
            self._finalize_map_return(True, detected_text=detected_text, frame_bgr=frame, reason='success')
            return

        if attempt < 3:
            self.append_log(f"[맵 복귀] 복귀 확인 중 ({attempt}/3) - 감지: '{detected_text or '(없음)'}'", "debug")
            return

        self.map_return_recovery_timer.stop()
        matched = self._match_map_return_keyword(normalized)
        if matched:
            retry_msg = f"[맵 복귀] '{matched[0]}' 감지 → 복구 재시도"
            self.append_log(retry_msg, "warn")
            self._restart_map_return_flow(matched[0], matched[1], frame, detected_text, words)
            return

        failure_msg = f"[맵 복귀] 등록되지 않은 맵 감지: {detected_text or '(없음)'} → 전체 중지"
        self._abort_map_return(failure_msg, frame_bgr=frame, notify=True)

    def _lookup_map_return_waypoint_name(self, profile: str, waypoint_id: str) -> str:
        options = self._collect_waypoint_options_for_profile(profile)
        for display, value in options:
            if str(value) == str(waypoint_id):
                return display
        return str(waypoint_id)

    def _map_return_finish_wait_operation(self, *, reason: str, resume_map_detection: bool) -> None:
        map_tab = getattr(self, 'map_tab', None)
        if not map_tab or not hasattr(map_tab, 'finish_other_player_wait_operation'):
            return
        is_active = False
        try:
            if hasattr(map_tab, '_is_other_player_wait_active'):
                is_active = bool(map_tab._is_other_player_wait_active())
            else:
                context = getattr(map_tab, 'other_player_wait_context', {})
                is_active = bool(context)
        except Exception:
            is_active = False
        if not is_active:
            return
        try:
            context = getattr(map_tab, 'other_player_wait_context', {}) or {}
            if isinstance(context, dict):
                context = dict(context)
                context['resume_map_detection'] = bool(resume_map_detection)
                map_tab.other_player_wait_context = context
        except Exception:
            pass
        try:
            map_tab.finish_other_player_wait_operation(reason=reason)
        except Exception as exc:
            self.append_log(f"[맵 복귀] 맵 탭 대기 종료 실패: {exc}", "warn")

    def _map_return_send_telegram(self, text: str, frame_bgr: Optional[np.ndarray] = None) -> None:
        if not text:
            return
        sent = False
        if frame_bgr is not None and _tg_send_photo:
            try:
                success, buffer = cv2.imencode(".png", frame_bgr)
                if success:
                    sent = bool(_tg_send_photo(buffer.tobytes(), caption=text))
            except Exception:
                sent = False
        if not sent and frame_bgr is not None:
            try:
                from ocr_watch import send_telegram_text_and_screenshot as _tg_text_and_shot  # 지연 임포트
                _tg_text_and_shot(text, image_bgr=frame_bgr)
                sent = True
            except Exception:
                sent = False
        if not sent:
            self._notify_telegram(text)

    def _restart_map_return_flow(
        self,
        map_name: str,
        map_cfg: dict,
        frame_bgr: Optional[np.ndarray],
        detected_text: str,
        words: list,
    ) -> None:
        base_state = (self._map_return_context or {}).get('base_state')
        self._map_return_finish_wait_operation(reason='retry', resume_map_detection=False)
        self._map_return_recovering = False
        self._update_map_return_timer_state()
        self._begin_map_return_recovery(
            map_name,
            map_cfg,
            frame_bgr,
            detected_text,
            words,
            existing_state=base_state if isinstance(base_state, dict) else None,
        )

    def _restore_map_profile(self, profile_name: str) -> None:
        if not profile_name:
            return
        map_tab = getattr(self, 'map_tab', None)
        if not map_tab or not hasattr(map_tab, 'profile_selector'):
            return
        try:
            current_profile = str(getattr(map_tab, 'active_profile_name', '') or '')
        except Exception:
            current_profile = ''
        if profile_name == current_profile:
            return
        selector = map_tab.profile_selector
        idx = selector.findText(profile_name)
        if idx < 0:
            return
        blocker = QSignalBlocker(selector)
        selector.setCurrentIndex(idx)
        del blocker
        try:
            map_tab.load_profile_data(profile_name)
        except Exception as exc:
            self.append_log(f"[맵 복귀] 프로필 '{profile_name}' 복원 실패: {exc}", "warn")

    def _finalize_map_return(
        self,
        success: bool,
        *,
        detected_text: str,
        frame_bgr: Optional[np.ndarray],
        reason: str,
    ) -> None:
        context = self._map_return_context or {}
        base_state = context.get('base_state', {}) or {}
        self.map_return_recovery_timer.stop()
        resume_map_detection = bool(base_state.get('map_detection_was_running', False))
        finish_reason = 'success' if success else (reason or 'abort')
        self._map_return_finish_wait_operation(reason=finish_reason, resume_map_detection=resume_map_detection)
        previous_profile = str(base_state.get('previous_profile', '') or '')
        if success:
            target_profile = self.map_return_base_profile or previous_profile
        else:
            target_profile = previous_profile
        self._restore_map_profile(target_profile)
        self._map_return_context = {}
        self._map_return_active_map = None
        self._map_return_recovering = False
        self._reset_map_return_alerts()
        self._update_map_return_timer_state()
        if success:
            profile_label = target_profile or '(미지정)'
            self.append_log(f"[맵 복귀] '{profile_label}' 프로필 기준 복구 완료. 사냥을 재개합니다.", "info")
            if bool(base_state.get('hunt_detection_was_active', False)):
                self._restart_hunt_detection_after_map_return()
        else:
            self.append_log(reason or "[맵 복귀] 복구 실패", "warn")
        self._map_return_detection_was_active = False

    def _abort_map_return(self, message: str, *, frame_bgr: Optional[np.ndarray], notify: bool) -> None:
        if notify and message:
            self._map_return_send_telegram(message, frame_bgr)
        base_state = (self._map_return_context or {}).get('base_state', {}) or {}
        self.map_return_recovery_timer.stop()
        self._map_return_finish_wait_operation(reason='abort', resume_map_detection=False)
        previous_profile = str(base_state.get('previous_profile', '') or '')
        self._restore_map_profile(previous_profile)
        self._map_return_context = {}
        self._map_return_active_map = None
        self._map_return_recovering = False
        self._map_return_detection_was_active = False
        self._reset_map_return_alerts()
        self._update_map_return_timer_state()
        try:
            self.force_stop_detection(reason='map_return_abort', preserve_forbidden=True)
        except Exception:
            pass
        try:
            self._emit_control_command("모든 키 떼기", "map_return_abort")
            self._emit_control_command("ESC", "map_return_abort")
        except Exception:
            pass
        self.append_log(message, "warn")

    def _restart_hunt_detection_after_map_return(self) -> None:
        try:
            if self._is_detection_active():
                return
        except Exception:
            return
        try:
            setattr(self, '_auto_restart_after_wait', True)
        except Exception:
            pass
        try:
            if hasattr(self, 'detect_btn'):
                self.detect_btn.setChecked(True)
            self._toggle_detection(True)
        except Exception as exc:
            self.append_log(f"[맵 복귀] 사냥 탐지 재시작 실패: {exc}", "warn")
        finally:
            try:
                delattr(self, '_auto_restart_after_wait')
            except Exception:
                pass

    def _create_range_group(self) -> QGroupBox:
        group = QGroupBox("사냥 범위 설정")
        group.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        )
        group.setMinimumWidth(0)
        area_form = QFormLayout()

        # 전/후 비대칭 범위 모드 스위치
        self.facing_range_checkbox = QCheckBox("전/후 비대칭")
        self.facing_range_checkbox.setChecked(False)
        area_form.addRow(self.facing_range_checkbox)

        self.enemy_range_spinbox = QSpinBox()
        self.enemy_range_spinbox.setRange(20, 2000)
        self.enemy_range_spinbox.setSingleStep(10)
        self.enemy_range_spinbox.setValue(400)
        self._label_enemy_range = QLabel("X 범위(±px)")
        area_form.addRow(self._label_enemy_range, self.enemy_range_spinbox)

        # 전/후(비대칭)용 사냥 범위
        self.enemy_front_spinbox = QSpinBox()
        self.enemy_front_spinbox.setRange(0, 2000)
        self.enemy_front_spinbox.setSingleStep(10)
        self.enemy_front_spinbox.setValue(self.enemy_range_spinbox.value())
        self.enemy_back_spinbox = QSpinBox()
        self.enemy_back_spinbox.setRange(0, 2000)
        self.enemy_back_spinbox.setSingleStep(10)
        self.enemy_back_spinbox.setValue(self.enemy_range_spinbox.value())
        self._label_enemy_front = QLabel("사냥 전방 X(px)")
        self._label_enemy_back = QLabel("사냥 후방 X(px)")
        area_form.addRow(self._label_enemy_front, self.enemy_front_spinbox)
        area_form.addRow(self._label_enemy_back, self.enemy_back_spinbox)

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
        self._label_primary_range = QLabel("주 스킬 X 범위(±px)")
        area_form.addRow(self._label_primary_range, self.primary_skill_range_spinbox)

        # 전/후(비대칭)용 주 스킬 범위
        self.primary_front_spinbox = QSpinBox()
        self.primary_front_spinbox.setRange(0, 1200)
        self.primary_front_spinbox.setSingleStep(10)
        self.primary_front_spinbox.setValue(self.primary_skill_range_spinbox.value())
        self.primary_back_spinbox = QSpinBox()
        self.primary_back_spinbox.setRange(0, 1200)
        self.primary_back_spinbox.setSingleStep(10)
        self.primary_back_spinbox.setValue(self.primary_skill_range_spinbox.value())
        self._label_primary_front = QLabel("주 스킬 전방 X(px)")
        self._label_primary_back = QLabel("주 스킬 후방 X(px)")
        area_form.addRow(self._label_primary_front, self.primary_front_spinbox)
        area_form.addRow(self._label_primary_back, self.primary_back_spinbox)

        area_layout = QVBoxLayout()
        area_layout.addLayout(area_form)
        group.setLayout(area_layout)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))

        # [개선] 전/후 비대칭 토글 시 높이 변화로 인한 UI 흔들림 방지
        # - 대칭/비대칭 두 상태의 sizeHint 높이를 미리 계산해 더 큰 값으로 고정
        # - 초기에는 대략값으로 고정하고, 레이아웃 적용 직후 한 번 더 정밀 재계산
        try:
            initial_checked = bool(self.facing_range_checkbox.isChecked())
            # 대칭 상태 높이(대략)
            self._update_range_inputs_enabled(False)
            sym_h = group.sizeHint().height()
            # 비대칭 상태 높이(대략)
            self._update_range_inputs_enabled(True)
            asym_h = group.sizeHint().height()
            # 초기 표시 상태 복원
            self._update_range_inputs_enabled(initial_checked)
            reserve_h = max(sym_h, asym_h)
            if reserve_h > 0:
                group.setFixedHeight(reserve_h)
        except Exception:
            pass

        # 레이아웃이 실제 배치된 뒤(폭 확정 후) 다시 한 번 고정 높이 재계산
        try:
            QTimer.singleShot(0, lambda: self._apply_range_group_fixed_height(group))
        except Exception:
            pass

        for spin in (
            self.enemy_range_spinbox,
            self.y_band_height_spinbox,
            self.y_band_offset_spinbox,
            self.primary_skill_range_spinbox,
            self.enemy_front_spinbox,
            self.enemy_back_spinbox,
            self.primary_front_spinbox,
            self.primary_back_spinbox,
        ):
            spin.valueChanged.connect(self._on_area_config_changed)
            spin.valueChanged.connect(self._handle_setting_changed)

        # 모드 토글 시 UI 상태/영역 재계산/저장
        self.facing_range_checkbox.toggled.connect(self._update_range_inputs_enabled)
        self.facing_range_checkbox.toggled.connect(self._on_area_config_changed)
        self.facing_range_checkbox.toggled.connect(self._handle_setting_changed)
        # 토글 시에도(필요 시) 고정 높이를 상향 재계산하여 흔들림/클리핑 방지
        try:
            self.facing_range_checkbox.toggled.connect(lambda _checked: self._apply_range_group_fixed_height(group))
        except Exception:
            pass

        # 초기 표시 상태 정리(위의 높이 선확보 로직이 상태를 복원하지만, 안전 차원에서 재호출)
        self._update_range_inputs_enabled(self.facing_range_checkbox.isChecked())

        return group

    def _apply_range_group_fixed_height(self, group: QGroupBox) -> None:
        """사냥 범위 그룹의 고정 높이를 대칭/비대칭 중 더 큰 값으로 설정.
        - 현재 폭에서의 sizeHint/레이아웃을 반영하기 위해 토글해가며 측정
        - 이미 설정된 fixedHeight보다 작아지는 경우는 방지(흔들림 방지)
        """
        try:
            initial_checked = bool(self.facing_range_checkbox.isChecked())
            # 대칭 상태 측정
            self._update_range_inputs_enabled(False)
            if group.layout() is not None:
                group.layout().activate()
            sym_h = group.sizeHint().height()
            # 비대칭 상태 측정
            self._update_range_inputs_enabled(True)
            if group.layout() is not None:
                group.layout().activate()
            asym_h = group.sizeHint().height()
            # 표시 상태 복원
            self._update_range_inputs_enabled(initial_checked)

            reserve_h = max(sym_h, asym_h)
            if reserve_h > 0:
                current_fixed = group.height() if group.height() > 0 else 0
                group.setFixedHeight(max(current_fixed, reserve_h))
                group.updateGeometry()
        except Exception:
            pass

    def _create_condition_group(self) -> QGroupBox:
        group = QGroupBox("사냥 조건")
        group.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        )
        group.setMinimumWidth(0)
        condition_form = QFormLayout()

        # [NEW] 확장사냥 모드: 사냥조건 첫 줄 체크박스
        self.expanded_hunt_checkbox = QCheckBox("확장사냥 모드")
        self.expanded_hunt_checkbox.setChecked(False)
        self.expanded_hunt_checkbox.toggled.connect(self._handle_setting_changed)
        condition_form.addRow(self.expanded_hunt_checkbox)

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

        # 클린업 유예(ms): 잔몹이 0마리로 잠깐 튈 때 즉시 교전을 종료하지 않도록 유예
        self.cleanup_grace_spinbox = QSpinBox()
        self.cleanup_grace_spinbox.setRange(0, 5000)
        self.cleanup_grace_spinbox.setSingleStep(100)
        self.cleanup_grace_spinbox.setValue(1000)
        self.cleanup_grace_spinbox.setSuffix(" ms")
        condition_form.addRow("클린업 유예(ms)", self.cleanup_grace_spinbox)
        self.cleanup_grace_spinbox.valueChanged.connect(self._handle_setting_changed)

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

    def _create_ladder_settings_group(self) -> QGroupBox:
        group = QGroupBox("사다리 설정")
        group.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        )
        group.setMinimumWidth(0)

        form = QFormLayout()

        # 기능 ON/OFF
        self.ladder_threat_enable_checkbox = QCheckBox("사다리 위협 시 자동 클린업 전환")
        self.ladder_threat_enable_checkbox.setChecked(True)
        form.addRow(self.ladder_threat_enable_checkbox)
        self.ladder_threat_enable_checkbox.toggled.connect(self._handle_setting_changed)

        # 사다리 근접(px, 맵 기준): 맵탭 좌표계에서 사다리 축과의 가로거리 허용치
        self.ladder_near_px_spinbox = QSpinBox()
        self.ladder_near_px_spinbox.setRange(1, 200)
        self.ladder_near_px_spinbox.setSingleStep(1)
        self.ladder_near_px_spinbox.setValue(15)
        self.ladder_near_px_spinbox.setSuffix(" px")
        form.addRow("사다리 근접(맵 기준)", self.ladder_near_px_spinbox)
        self.ladder_near_px_spinbox.valueChanged.connect(self._handle_setting_changed)

        # 체력 조건(%): 이 값 미만일 때 사다리 위협 조건 유효
        self.ladder_hp_threshold_spinbox = QSpinBox()
        self.ladder_hp_threshold_spinbox.setRange(1, 100)
        self.ladder_hp_threshold_spinbox.setSingleStep(1)
        self.ladder_hp_threshold_spinbox.setValue(90)
        self.ladder_hp_threshold_spinbox.setSuffix(" %")
        form.addRow("체력 조건(%)", self.ladder_hp_threshold_spinbox)
        self.ladder_hp_threshold_spinbox.valueChanged.connect(self._handle_setting_changed)

        # [신규] 사다리/점프/낙하 지속 시 탈출 설정
        # 마스터 스위치
        self.ladder_escape_enabled_checkbox = QCheckBox("사다리복구")
        self.ladder_escape_enabled_checkbox.setChecked(False)
        form.addRow(self.ladder_escape_enabled_checkbox)
        self.ladder_escape_enabled_checkbox.toggled.connect(self._handle_setting_changed)
        self.ladder_escape_enabled_checkbox.toggled.connect(self._update_ladder_escape_controls)

        # 탈출 명령프로필
        self.ladder_escape_profile_combo = QComboBox()
        self.ladder_escape_profile_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.ladder_escape_profile_combo.addItem("프로필 선택", "")
        form.addRow("탈출 명령프로필", self.ladder_escape_profile_combo)
        self.ladder_escape_profile_combo.currentIndexChanged.connect(self._handle_setting_changed)

        # 지속 임계값/쿨다운(초)
        self.ladder_escape_threshold_spinbox = QDoubleSpinBox()
        self.ladder_escape_threshold_spinbox.setRange(0.5, 10.0)
        self.ladder_escape_threshold_spinbox.setSingleStep(0.1)
        self.ladder_escape_threshold_spinbox.setDecimals(2)
        self.ladder_escape_threshold_spinbox.setValue(2.0)
        self.ladder_escape_threshold_spinbox.setSuffix(" s")
        form.addRow("지속 임계값(초)", self.ladder_escape_threshold_spinbox)
        self.ladder_escape_threshold_spinbox.valueChanged.connect(self._handle_setting_changed)

        self.ladder_escape_cooldown_spinbox = QDoubleSpinBox()
        self.ladder_escape_cooldown_spinbox.setRange(0.5, 30.0)
        self.ladder_escape_cooldown_spinbox.setSingleStep(0.5)
        self.ladder_escape_cooldown_spinbox.setDecimals(2)
        self.ladder_escape_cooldown_spinbox.setValue(3.0)
        self.ladder_escape_cooldown_spinbox.setSuffix(" s")
        form.addRow("쿨다운(초)", self.ladder_escape_cooldown_spinbox)
        self.ladder_escape_cooldown_spinbox.valueChanged.connect(self._handle_setting_changed)

        # 감지 상태(점프/사다리/낙하)
        self._ladder_escape_states_widget = QWidget()
        _states_layout = QHBoxLayout(self._ladder_escape_states_widget)
        _states_layout.setContentsMargins(0, 0, 0, 0)
        _states_layout.setSpacing(8)
        self.ladder_escape_include_jump_checkbox = QCheckBox("점프 포함")
        self.ladder_escape_include_jump_checkbox.setChecked(True)
        self.ladder_escape_include_ladder_checkbox = QCheckBox("사다리 포함")
        self.ladder_escape_include_ladder_checkbox.setChecked(True)
        self.ladder_escape_include_fall_checkbox = QCheckBox("낙하 포함")
        self.ladder_escape_include_fall_checkbox.setChecked(True)
        for cb in (
            self.ladder_escape_include_jump_checkbox,
            self.ladder_escape_include_ladder_checkbox,
            self.ladder_escape_include_fall_checkbox,
        ):
            cb.toggled.connect(self._handle_setting_changed)
            _states_layout.addWidget(cb)
        form.addRow("감지 상태", self._ladder_escape_states_widget)

        # 초기 enable 상태
        self._update_ladder_escape_controls(self.ladder_escape_enabled_checkbox.isChecked())

        group.setLayout(form)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        return group

    def _update_ladder_escape_controls(self, checked: bool) -> None:
        """사다리복구 토글에 따라 하위 컨트롤 활성화 제어."""
        widgets = [
            getattr(self, 'ladder_escape_profile_combo', None),
            getattr(self, 'ladder_escape_threshold_spinbox', None),
            getattr(self, 'ladder_escape_cooldown_spinbox', None),
            getattr(self, '_ladder_escape_states_widget', None),
        ]
        for w in widgets:
            try:
                if w is not None:
                    w.setEnabled(bool(checked))
            except Exception:
                pass

    def _refresh_ladder_escape_profile_options(self, keep_selection: bool = True) -> None:
        """'탈출 명령프로필' 콤보를 '기타' 카테고리 목록으로 갱신.
        기본값으로 '사다리 멈춤복구'를 우선 선택.
        """
        combo = getattr(self, 'ladder_escape_profile_combo', None)
        if combo is None:
            return
        try:
            previous_data = combo.currentData() if keep_selection else None
        except Exception:
            previous_data = None
        names = []
        try:
            names = self._get_misc_command_profiles()
        except Exception:
            names = []
        default_name = "사다리 멈춤복구"
        # 중복 제거 + 정렬
        seen = set()
        ordered = []
        for n in names:
            if isinstance(n, str) and n not in seen:
                seen.add(n)
                ordered.append(n)
        if default_name not in seen:
            ordered.insert(0, default_name)

        # 재구성
        current_block = combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("프로필 선택", "")
            for n in ordered:
                combo.addItem(n, n)
            # 이전 선택 복원 또는 기본값 선택
            target = previous_data or default_name
            idx = combo.findData(target)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setCurrentIndex(0)
        finally:
            combo.blockSignals(current_block)

    def _create_auto_shutdown_group(self) -> QGroupBox:
        group = QGroupBox("자동 대응")
        group.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )

        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(10)

        # PID 설정 및 자동 검색
        pid_row = QHBoxLayout()
        pid_row.setSpacing(6)
        pid_row.addWidget(QLabel("PID:"))
        self.shutdown_pid_input = QLineEdit()
        self.shutdown_pid_input.setPlaceholderText("예: 12345")
        self.shutdown_pid_input.setMaximumWidth(120)
        pid_row.addWidget(self.shutdown_pid_input)

        self.shutdown_pid_find_btn = QPushButton("PID 찾기")
        pid_row.addWidget(self.shutdown_pid_find_btn)
        pid_row.addStretch(1)
        outer_layout.addLayout(pid_row)

        # 종료 예약 섹션
        reservation_group = QGroupBox("종료 예약")
        reservation_layout = QVBoxLayout()
        reservation_layout.setContentsMargins(8, 6, 8, 6)
        reservation_layout.setSpacing(6)

        reservation_row = QHBoxLayout()
        reservation_row.setSpacing(6)
        self.shutdown_reservation_checkbox = QCheckBox("종료 예약")
        reservation_row.addWidget(self.shutdown_reservation_checkbox)

        self.shutdown_datetime_edit = QDateTimeEdit()
        self.shutdown_datetime_edit.setCalendarPopup(True)
        self.shutdown_datetime_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.shutdown_datetime_edit.setMinimumDateTime(QDateTime.currentDateTime())
        self.shutdown_datetime_edit.setEnabled(False)
        reservation_row.addWidget(self.shutdown_datetime_edit, 1)

        self.shutdown_reservation_apply_btn = QPushButton("예약")
        self.shutdown_reservation_apply_btn.setEnabled(False)
        reservation_row.addWidget(self.shutdown_reservation_apply_btn)

        self.shutdown_reservation_cancel_btn = QPushButton("취소")
        self.shutdown_reservation_cancel_btn.setEnabled(False)
        reservation_row.addWidget(self.shutdown_reservation_cancel_btn)

        self.shutdown_reservation_status = QLabel("--")
        self.shutdown_reservation_status.setMinimumWidth(120)
        reservation_row.addWidget(self.shutdown_reservation_status)

        reservation_layout.addLayout(reservation_row)

        sleep_row = QHBoxLayout()
        sleep_row.setSpacing(6)
        self.shutdown_sleep_checkbox = QCheckBox("종료 성공 시 절전 모드")
        self.shutdown_sleep_checkbox.setToolTip("PID 종료 후 Windows 절전 모드를 시도합니다.")
        sleep_row.addWidget(self.shutdown_sleep_checkbox)
        sleep_row.addStretch(1)
        reservation_layout.addLayout(sleep_row)

        reservation_group.setLayout(reservation_layout)
        outer_layout.addWidget(reservation_group)

        # 다른 캐릭터 감지 섹션
        other_group = QGroupBox("다른 캐릭터 감지")
        other_layout = QVBoxLayout()
        other_layout.setContentsMargins(8, 6, 8, 6)
        other_layout.setSpacing(6)

        other_header = QHBoxLayout()
        other_header.setContentsMargins(0, 0, 0, 0)
        other_header.setSpacing(8)
        self.shutdown_other_player_checkbox = QCheckBox("사용")
        other_header.addWidget(self.shutdown_other_player_checkbox)
        self.shutdown_other_player_elapsed = QLabel("--")
        self.shutdown_other_player_elapsed.setMinimumWidth(0)
        self.shutdown_other_player_elapsed.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        other_header.addSpacing(6)
        other_header.addWidget(self.shutdown_other_player_elapsed)
        other_header.addStretch(1)
        other_layout.addLayout(other_header)

        self.shutdown_other_player_action_group = QButtonGroup(self)
        actions_layout = QVBoxLayout()
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)

        # 게임 종료 액션
        self.shutdown_other_player_radio_shutdown = QRadioButton()
        self.shutdown_other_player_action_group.addButton(self.shutdown_other_player_radio_shutdown, 0)

        self.shutdown_other_player_shutdown_btn = QPushButton("게임 종료")
        self.shutdown_other_player_shutdown_summary = QLabel("감지시간 60초")
        self.shutdown_other_player_shutdown_summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        shutdown_row = QHBoxLayout()
        shutdown_row.setContentsMargins(0, 0, 0, 0)
        shutdown_row.setSpacing(6)
        shutdown_row.addWidget(self.shutdown_other_player_radio_shutdown)
        shutdown_row.addWidget(self.shutdown_other_player_shutdown_btn)
        shutdown_row.addWidget(self.shutdown_other_player_shutdown_summary, 1)
        actions_layout.addLayout(shutdown_row)

        # 대기 모드 액션
        self.shutdown_other_player_radio_wait = QRadioButton()
        self.shutdown_other_player_action_group.addButton(self.shutdown_other_player_radio_wait, 1)

        self.shutdown_other_player_wait_btn = QPushButton("대기 모드")
        self.shutdown_other_player_wait_summary = QLabel("감지시간 180초 / 대기종료 60초 / 웨이포인트 미설정")
        self.shutdown_other_player_wait_summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        wait_row = QHBoxLayout()
        wait_row.setContentsMargins(0, 0, 0, 0)
        wait_row.setSpacing(6)
        wait_row.addWidget(self.shutdown_other_player_radio_wait)
        wait_row.addWidget(self.shutdown_other_player_wait_btn)
        wait_row.addWidget(self.shutdown_other_player_wait_summary, 1)
        actions_layout.addLayout(wait_row)

        

        # 마을 귀환 액션 (미구현)
        self.shutdown_other_player_radio_town = QRadioButton()
        self.shutdown_other_player_action_group.addButton(self.shutdown_other_player_radio_town, 2)

        self.shutdown_other_player_town_btn = QPushButton("마을 귀환 (미구현)")
        self.shutdown_other_player_town_summary = QLabel("준비 중")
        self.shutdown_other_player_town_summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        town_row = QHBoxLayout()
        town_row.setContentsMargins(0, 0, 0, 0)
        town_row.setSpacing(6)
        town_row.addWidget(self.shutdown_other_player_radio_town)
        town_row.addWidget(self.shutdown_other_player_town_btn)
        town_row.addWidget(self.shutdown_other_player_town_summary, 1)
        actions_layout.addLayout(town_row)

        other_layout.addLayout(actions_layout)
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
        if not hasattr(self, 'shutdown_reservation_checkbox'):
            return

        try:
            default_dt = QDateTime.currentDateTime().addSecs(600)
            self.shutdown_datetime_edit.setDateTime(default_dt)
        except Exception:
            pass

        self.shutdown_reservation_checkbox.toggled.connect(self._on_shutdown_reservation_toggled)
        self.shutdown_reservation_apply_btn.clicked.connect(self._apply_shutdown_reservation)
        self.shutdown_reservation_cancel_btn.clicked.connect(self._cancel_shutdown_reservation)

        self.shutdown_pid_input.editingFinished.connect(self._sync_shutdown_pid_from_input)
        self.shutdown_pid_find_btn.clicked.connect(lambda: self._auto_detect_mapleland_pid(manual=True))

        self.shutdown_sleep_checkbox.toggled.connect(self._on_shutdown_sleep_toggled)

        self.shutdown_other_player_checkbox.toggled.connect(self._toggle_other_player_mode)
        self.shutdown_other_player_action_group.idClicked.connect(self._on_other_player_action_changed)
        self.shutdown_other_player_shutdown_btn.clicked.connect(self._configure_other_player_game_exit)
        self.shutdown_other_player_wait_btn.clicked.connect(self._configure_other_player_wait_mode)
        self.shutdown_other_player_town_btn.clicked.connect(self._configure_other_player_town_mode)
        self.shutdown_other_player_radio_shutdown.setChecked(True)

        self._update_other_player_action_summary()
        self._update_shutdown_labels()

    def _on_shutdown_reservation_toggled(self, checked: bool) -> None:
        checked = bool(checked)
        self.shutdown_reservation_enabled = checked
        for widget in (
            self.shutdown_datetime_edit,
            self.shutdown_reservation_apply_btn,
            self.shutdown_reservation_cancel_btn,
        ):
            widget.setEnabled(checked)

        if checked and self.shutdown_pid_value is None:
            self._auto_detect_mapleland_pid(auto_trigger=True)

        if not checked:
            self.shutdown_datetime_target = None
            self.shutdown_reservation_status.setText("--")

        self._ensure_shutdown_timer_running()
        self._update_shutdown_labels()

    def _apply_shutdown_reservation(self) -> None:
        if not self.shutdown_reservation_checkbox.isChecked():
            QMessageBox.warning(self, "예약 필요", "종료 예약을 먼저 활성화해주세요.")
            return

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
        self.shutdown_reservation_checkbox.setChecked(True)
        self.shutdown_reservation_status.setText(self._format_remaining_text(target_ts - now))
        self._ensure_shutdown_timer_running()
        self._update_shutdown_labels()
        self.append_log("종료 예약이 설정되었습니다.", "info")

    def _cancel_shutdown_reservation(self) -> None:
        if self.shutdown_datetime_target is None:
            self.shutdown_reservation_status.setText("--")
            return

        self.shutdown_datetime_target = None
        self.shutdown_reservation_status.setText("--")
        self._stop_shutdown_timer_if_idle()
        self._update_shutdown_labels()
        self.append_log("종료 예약을 취소했습니다.", "info")

    def _auto_detect_mapleland_pid(self, *, manual: bool = False, auto_trigger: bool = False) -> Optional[int]:
        candidate_pid: Optional[int] = None
        detect_errors: list[str] = []

        target_image = 'msw.exe'
        target_lower = target_image.lower()

        # 1. psutil 우선 사용
        try:
            import psutil  # type: ignore

            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                name = (proc.info.get('name') or '').lower()
                cmdline = ' '.join(proc.info.get('cmdline') or []).lower()
                if name == target_lower or target_lower in cmdline:
                    candidate_pid = int(proc.info['pid'])
                    break
        except ImportError:
            detect_errors.append('psutil 미설치')
        except Exception as exc:  # pragma: no cover - 진단 로그
            detect_errors.append(f'psutil 오류: {exc}')

        # 2. Windows tasklist fallback
        if candidate_pid is None and os.name == 'nt':
            import subprocess
            import locale

            try:
                encoding = locale.getpreferredencoding(False) or 'cp949'
                output = subprocess.check_output(
                    ['tasklist', '/FI', f'IMAGENAME eq {target_image}'],
                    stderr=subprocess.STDOUT,
                )
                text = output.decode(encoding, errors='ignore')
                for line in text.splitlines():
                    if target_lower not in line.lower():
                        continue
                    parts = [p for p in line.split() if p.isdigit()]
                    if parts:
                        candidate_pid = int(parts[0])
                        break
            except FileNotFoundError:
                detect_errors.append('tasklist 미지원 환경')
            except Exception as exc:  # pragma: no cover - 진단 로그
                detect_errors.append(f'tasklist 오류: {exc}')

        if candidate_pid is None:
            if manual:
                detail = '\n'.join(detect_errors) if detect_errors else f'{target_image} 프로세스를 찾지 못했습니다.'
                QMessageBox.warning(self, "PID 검색 실패", detail)
            elif not auto_trigger:
                self.append_log(f"{target_image} PID 자동 검색에 실패했습니다.", "warn")
            return None

        self.shutdown_pid_value = candidate_pid
        self.shutdown_pid_last_scan = time.time()
        if hasattr(self, 'shutdown_pid_input'):
            blocker = QSignalBlocker(self.shutdown_pid_input)
            self.shutdown_pid_input.setText(str(candidate_pid))
            del blocker

        if manual:
            self.append_log(f"{target_image} PID 자동 검색 성공: {candidate_pid}", "info")
        elif not auto_trigger:
            self.append_log(f"PID {candidate_pid} 자동 감지", "info")

        return candidate_pid

    def _on_other_player_action_changed(self, action_id: int) -> None:
        mapping = {
            0: 'game_exit',
            1: 'wait_mode',
            2: 'town_return',
        }
        self.shutdown_other_player_action = mapping.get(action_id, 'game_exit')
        if self.shutdown_other_player_action == 'town_return':
            self.append_log("마을 귀환 기능은 아직 구현되지 않았습니다.", "warn")
        self._update_other_player_action_summary()

    def _configure_other_player_game_exit(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("게임 종료 대기 시간")
        layout = QFormLayout(dialog)

        minutes_spin = QSpinBox(dialog)
        minutes_spin.setRange(0, 180)
        minutes_spin.setValue(self.shutdown_other_player_exit_delay // 60)
        minutes_spin.setSuffix(" 분")

        seconds_spin = QSpinBox(dialog)
        seconds_spin.setRange(0, 59)
        seconds_spin.setValue(self.shutdown_other_player_exit_delay % 60)
        seconds_spin.setSuffix(" 초")

        time_row_widget = QWidget(dialog)
        time_row_layout = QHBoxLayout(time_row_widget)
        time_row_layout.setContentsMargins(0, 0, 0, 0)
        time_row_layout.setSpacing(8)
        time_row_layout.addWidget(minutes_spin)
        time_row_layout.addWidget(seconds_spin)

        layout.addRow("감지 시간", time_row_widget)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        total_seconds = minutes_spin.value() * 60 + seconds_spin.value()
        if total_seconds <= 0:
            QMessageBox.warning(self, "시간 오류", "1초 이상으로 설정해주세요.")
            return

        self.shutdown_other_player_exit_delay = total_seconds
        self.shutdown_other_player_radio_shutdown.setChecked(True)
        self.shutdown_other_player_action = 'game_exit'
        self._update_other_player_action_summary()

    def _configure_other_player_wait_mode(self) -> None:
        waypoint_options = self._collect_waypoint_options()
        if not waypoint_options:
            QMessageBox.warning(self, "웨이포인트 없음", "맵 탭에서 웨이포인트 정보를 불러오지 못했습니다.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("대기 모드 설정")
        layout = QFormLayout(dialog)

        minutes_spin = QSpinBox(dialog)
        minutes_spin.setRange(0, 180)
        minutes_spin.setValue(self.shutdown_other_player_wait_delay // 60)
        minutes_spin.setSuffix(" 분")

        seconds_spin = QSpinBox(dialog)
        seconds_spin.setRange(0, 59)
        seconds_spin.setValue(self.shutdown_other_player_wait_delay % 60)
        seconds_spin.setSuffix(" 초")

        detect_row_widget = QWidget(dialog)
        detect_row_layout = QHBoxLayout(detect_row_widget)
        detect_row_layout.setContentsMargins(0, 0, 0, 0)
        detect_row_layout.setSpacing(8)
        detect_row_layout.addWidget(minutes_spin)
        detect_row_layout.addWidget(seconds_spin)

        clear_minutes_spin = QSpinBox(dialog)
        clear_minutes_spin.setRange(0, 180)
        clear_minutes_spin.setValue(self.shutdown_other_player_wait_clear_delay // 60)
        clear_minutes_spin.setSuffix(" 분")

        clear_seconds_spin = QSpinBox(dialog)
        clear_seconds_spin.setRange(0, 59)
        clear_seconds_spin.setValue(self.shutdown_other_player_wait_clear_delay % 60)
        clear_seconds_spin.setSuffix(" 초")

        clear_row_widget = QWidget(dialog)
        clear_row_layout = QHBoxLayout(clear_row_widget)
        clear_row_layout.setContentsMargins(0, 0, 0, 0)
        clear_row_layout.setSpacing(8)
        clear_row_layout.addWidget(clear_minutes_spin)
        clear_row_layout.addWidget(clear_seconds_spin)

        waypoint_combo = QComboBox(dialog)
        for name, wp_id in waypoint_options:
            waypoint_combo.addItem(name, wp_id)
        if self.shutdown_other_player_wait_waypoint_name:
            index = waypoint_combo.findText(self.shutdown_other_player_wait_waypoint_name)
            if index >= 0:
                waypoint_combo.setCurrentIndex(index)

        # 다중 웨이포인트 편집: 추가/삭제 버튼 + 목록
        wp_edit_row = QWidget(dialog)
        wp_edit_layout = QHBoxLayout(wp_edit_row)
        wp_edit_layout.setContentsMargins(0, 0, 0, 0)
        wp_edit_layout.setSpacing(8)
        add_btn = QPushButton("추가", dialog)
        del_btn = QPushButton("삭제", dialog)
        wp_edit_layout.addWidget(waypoint_combo, 1)
        wp_edit_layout.addWidget(add_btn)
        wp_edit_layout.addWidget(del_btn)

        waypoint_list = QListWidget(dialog)
        # 초기 목록: 기존 다중 목록 우선, 없으면 단일값
        initial_items: list[tuple[str, str]] = []
        # [변경] 현재 활성 맵 프로필 기준으로 초기 목록 구성
        current_items = self._get_wait_waypoints_for_current_profile()
        if current_items:
            for item in current_items:
                wp_id = str(item.get('id') or '').strip()
                if not wp_id:
                    continue
                name = str(item.get('name') or wp_id)
                initial_items.append((name, wp_id))
        elif self.shutdown_other_player_wait_waypoint_id:
            initial_items.append((self.shutdown_other_player_wait_waypoint_name or str(self.shutdown_other_player_wait_waypoint_id), str(self.shutdown_other_player_wait_waypoint_id)))
        for name, wp_id in initial_items:
            from PyQt6.QtWidgets import QListWidgetItem as _QLI
            item = _QLI(name)
            item.setData(Qt.ItemDataRole.UserRole, wp_id)
            waypoint_list.addItem(item)

        def _add_current_wp():
            idx = waypoint_combo.currentIndex()
            if idx < 0:
                return
            wp_id = str(waypoint_combo.currentData())
            name = waypoint_combo.currentText()
            if not wp_id:
                return
            # 중복 방지
            for i in range(waypoint_list.count()):
                it = waypoint_list.item(i)
                if str(it.data(Qt.ItemDataRole.UserRole)) == wp_id:
                    return
            from PyQt6.QtWidgets import QListWidgetItem as _QLI
            new_item = _QLI(name)
            new_item.setData(Qt.ItemDataRole.UserRole, wp_id)
            waypoint_list.addItem(new_item)

        def _remove_selected_wp():
            selected = waypoint_list.selectedItems()
            if not selected:
                return
            for it in selected:
                row = waypoint_list.row(it)
                waypoint_list.takeItem(row)

        add_btn.clicked.connect(_add_current_wp)
        del_btn.clicked.connect(_remove_selected_wp)

        layout.addRow("감지 시간", detect_row_widget)
        layout.addRow("대기 종료", clear_row_widget)
        layout.addRow("웨이포인트", wp_edit_row)
        layout.addRow("선택 목록", waypoint_list)

        # [추가] 대기모드 전용 체력회복 설정(이 다이얼로그에 배치)
        wait_hp_row_widget = QWidget(dialog)
        wait_hp_row_layout = QHBoxLayout(wait_hp_row_widget)
        wait_hp_row_layout.setContentsMargins(0, 0, 0, 0)
        wait_hp_row_layout.setSpacing(8)

        wait_hp_enable_chk = QCheckBox("사용", dialog)
        # 현재 저장된 전역 값으로 초기화
        try:
            wait_hp_enable_chk.setChecked(bool(getattr(self, 'wait_hp_enabled', False)))
        except Exception:
            wait_hp_enable_chk.setChecked(False)

        wait_hp_threshold_spin = QSpinBox(dialog)
        wait_hp_threshold_spin.setRange(1, 99)
        try:
            wait_hp_threshold_spin.setValue(int(getattr(self, 'wait_hp_threshold', 50) or 50))
        except Exception:
            wait_hp_threshold_spin.setValue(50)
        wait_hp_threshold_spin.setSuffix(" %")

        wait_hp_command_combo = QComboBox(dialog)
        wait_hp_command_combo.addItem("프로필 선택", "")
        try:
            misc_profiles = self._get_misc_command_profiles()
            for name in misc_profiles:
                wait_hp_command_combo.addItem(name, name)
            current_cmd = str(getattr(self, 'wait_hp_command_profile', '') or '')
            if current_cmd:
                idx = wait_hp_command_combo.findData(current_cmd)
                if idx >= 0:
                    wait_hp_command_combo.setCurrentIndex(idx)
        except Exception:
            pass

        wait_hp_row_layout.addWidget(wait_hp_enable_chk)
        wait_hp_row_layout.addWidget(QLabel("HP 임계값", dialog))
        wait_hp_row_layout.addWidget(wait_hp_threshold_spin)
        wait_hp_row_layout.addSpacing(8)
        wait_hp_row_layout.addWidget(QLabel("명령 프로필", dialog))
        wait_hp_row_layout.addWidget(wait_hp_command_combo, 1)

        layout.addRow("대기모드 체력회복", wait_hp_row_widget)

        # [NEW] 대기모드 위치 복구(px): 웨이포인트 X에서 이만큼 벗어나면 복귀 시작
        wait_recover_spin = QSpinBox(dialog)
        wait_recover_spin.setRange(0, 100)
        try:
            wait_recover_spin.setValue(int(getattr(self, 'wait_recover_threshold_px', 70) or 70))
        except Exception:
            wait_recover_spin.setValue(70)
        wait_recover_spin.setSuffix(" px")
        layout.addRow("대기모드 위치 복구(px)", wait_recover_spin)

        # [NEW] 금지몬스터 감지 설정 (자동제어 '기타' 프로필 실행)
        forbid_row = QWidget(dialog)
        forbid_layout = QHBoxLayout(forbid_row)
        forbid_layout.setContentsMargins(0, 0, 0, 0)
        forbid_layout.setSpacing(8)
        forbid_enable_chk = QCheckBox("사용", dialog)
        try:
            forbid_enable_chk.setChecked(bool(getattr(self, 'forbidden_monster_enabled', False)))
        except Exception:
            forbid_enable_chk.setChecked(False)
        forbid_layout.addWidget(forbid_enable_chk)
        forbid_layout.addWidget(QLabel("명령 프로필", dialog))
        forbid_cmd_combo = QComboBox(dialog)
        forbid_cmd_combo.addItem("프로필 선택", "")
        try:
            misc_profiles = self._get_misc_command_profiles()
            for name in misc_profiles:
                forbid_cmd_combo.addItem(name, name)
            current_forbid_cmd = str(getattr(self, 'forbidden_monster_command_profile', '') or '')
            if current_forbid_cmd:
                idx = forbid_cmd_combo.findData(current_forbid_cmd)
                if idx >= 0:
                    forbid_cmd_combo.setCurrentIndex(idx)
        except Exception:
            pass
        forbid_layout.addWidget(forbid_cmd_combo, 1)
        # [NEW] 금지몬스터 텔레그램 알림 전역 옵션
        forbid_tg_chk = QCheckBox("텔레그램 알림", dialog)
        try:
            forbid_tg_chk.setChecked(bool(getattr(self, 'forbidden_monster_telegram_alert', False)))
        except Exception:
            forbid_tg_chk.setChecked(False)
        forbid_layout.addWidget(forbid_tg_chk)
        layout.addRow("금지몬스터 감지", forbid_row)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        total_seconds = minutes_spin.value() * 60 + seconds_spin.value()
        if total_seconds <= 0:
            QMessageBox.warning(self, "시간 오류", "1초 이상으로 설정해주세요.")
            return

        clear_total_seconds = clear_minutes_spin.value() * 60 + clear_seconds_spin.value()
        if clear_total_seconds <= 0:
            QMessageBox.warning(self, "시간 오류", "대기 종료 시간은 1초 이상으로 설정해주세요.")
            return

        self.shutdown_other_player_wait_delay = total_seconds
        self.shutdown_other_player_wait_clear_delay = clear_total_seconds
        # 목록 수집 및 검증
        collected: list[dict] = []
        for i in range(waypoint_list.count()):
            it = waypoint_list.item(i)
            wp_id = str(it.data(Qt.ItemDataRole.UserRole) or '').strip()
            name = it.text().strip() or wp_id
            if wp_id:
                collected.append({'id': wp_id, 'name': name})
        if not collected:
            QMessageBox.warning(self, "웨이포인트 없음", "대기할 웨이포인트를 최소 1개 이상 추가해주세요.")
            return
        # [변경] 현재 활성 프로필에 저장. 구버전 단일 필드도 첫 항목으로 동기화
        self._set_wait_waypoints_for_current_profile(collected)
        self.shutdown_other_player_wait_waypoint_id = collected[0]['id']
        self.shutdown_other_player_wait_waypoint_name = collected[0]['name']
        self.shutdown_other_player_radio_wait.setChecked(True)
        self.shutdown_other_player_action = 'wait_mode'
        # [추가] 대기모드 체력회복 설정 저장(전역 속성)
        try:
            setattr(self, 'wait_hp_enabled', bool(wait_hp_enable_chk.isChecked()))
            setattr(self, 'wait_hp_threshold', int(wait_hp_threshold_spin.value()))
            setattr(self, 'wait_hp_command_profile', str(wait_hp_command_combo.currentData() or ''))
        except Exception:
            setattr(self, 'wait_hp_enabled', False)
            setattr(self, 'wait_hp_threshold', 50)
            setattr(self, 'wait_hp_command_profile', '')

        # [NEW] 대기모드 위치 복구(px) 저장
        try:
            setattr(self, 'wait_recover_threshold_px', int(wait_recover_spin.value()))
        except Exception:
            setattr(self, 'wait_recover_threshold_px', 70)
        # [NEW] 금지몬스터 감지 설정 저장
        try:
            self.forbidden_monster_enabled = bool(forbid_enable_chk.isChecked())
            self.forbidden_monster_command_profile = str(forbid_cmd_combo.currentData() or '')
            self.forbidden_monster_telegram_alert = bool(forbid_tg_chk.isChecked())
        except Exception:
            self.forbidden_monster_enabled = False
            self.forbidden_monster_command_profile = ''
            self.forbidden_monster_telegram_alert = False

        self._update_other_player_action_summary()
        self._save_settings()

    # ----- [NEW] 금지몬스터 경고음 재생 -----
    def _play_forbidden_alert(self) -> None:
        """금지몬스터 감지 시 색다른 경고음(짧은 멜로디)을 비동기 재생.

        - Windows: winsound.Beep 시퀀스
        - 기타: QGuiApplication.beep() 3회
        """
        import threading

        def _worker():
            try:
                import os
                if os.name == 'nt':
                    try:
                        import winsound, time as _t
                        pattern = [
                            (880, 120),  # A5
                            (660, 100),  # E5
                            (1460, 160), # F#6-ish
                            (0, 60),
                            (1460, 160),
                        ]
                        for freq, dur in pattern:
                            if freq > 0:
                                winsound.Beep(int(freq), int(dur))
                            else:
                                _t.sleep(dur / 1000.0)
                        return
                    except Exception:
                        pass
                # Fallback: Qt 기본 비프 3회
                try:
                    from PyQt6.QtGui import QGuiApplication
                    import time as _t
                    for _ in range(3):
                        QGuiApplication.beep()
                        _t.sleep(0.12)
                except Exception:
                    pass
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _configure_other_player_town_mode(self) -> None:
        QMessageBox.information(self, "마을 귀환", "마을 귀환 기능은 아직 구현되지 않았습니다.")
        self.shutdown_other_player_radio_town.setChecked(True)
        self.shutdown_other_player_action = 'town_return'
        self._update_other_player_action_summary()

    def _collect_waypoint_options(self) -> list[tuple[str, str]]:
        map_tab = getattr(self, 'map_tab', None)
        geometry = getattr(map_tab, 'geometry_data', None)
        waypoints = []
        if isinstance(geometry, dict):
            for item in geometry.get('waypoints', []) or []:
                name = item.get('name') or ''
                wp_id = item.get('id')
                if not name or wp_id is None:
                    continue
                waypoints.append((str(name), str(wp_id)))
        waypoints.sort(key=lambda x: x[0].lower())
        return waypoints

    def _collect_waypoint_options_for_profile(self, profile_name: str) -> list[tuple[str, str]]:
        if not profile_name:
            return []
        map_tab = getattr(self, 'map_tab', None)
        active_profile = getattr(map_tab, 'active_profile_name', None)
        if map_tab and profile_name == active_profile:
            return self._collect_waypoint_options()
        geometry = self._load_map_geometry_for_profile(profile_name)
        if not isinstance(geometry, dict):
            return []
        waypoints = []
        for item in geometry.get('waypoints', []) or []:
            try:
                name = str(item.get('name') or '')
                wp_id = item.get('id')
            except Exception:
                continue
            if not name or wp_id in (None, ''):
                continue
            waypoints.append((name, str(wp_id)))
        waypoints.sort(key=lambda x: x[0].lower())
        return waypoints

    def _load_map_geometry_for_profile(self, profile_name: str) -> dict:
        if not profile_name:
            return {}
        cached = self._map_return_geometry_cache.get(profile_name)
        if isinstance(cached, dict) and cached:
            return cached
        map_tab = getattr(self, 'map_tab', None)
        if map_tab and getattr(map_tab, 'active_profile_name', None) == profile_name:
            geometry = getattr(map_tab, 'geometry_data', None)
            if isinstance(geometry, dict):
                self._map_return_geometry_cache[profile_name] = geometry
                return geometry
        path = os.path.join(MAPS_DIR, profile_name, "map_geometry.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                geometry = json.load(f)
        except FileNotFoundError:
            geometry = {}
        except Exception as exc:
            geometry = {}
            self.append_log(f"맵 프로필 '{profile_name}' 지형 데이터를 불러오지 못했습니다: {exc}", "warn")
        if isinstance(geometry, dict):
            self._map_return_geometry_cache[profile_name] = geometry
        return geometry

    # ---------------------- 대기 모드(무기한) 보조 유틸 ----------------------
    def _current_map_profile_name(self) -> str:
        map_tab = getattr(self, 'map_tab', None)
        name = getattr(map_tab, 'active_profile_name', None)
        return str(name) if isinstance(name, str) else ''

    def _get_wait_waypoints_for_current_profile(self) -> list[dict]:
        profile = self._current_map_profile_name()
        if not profile:
            return list(self.shutdown_other_player_wait_waypoints or [])
        return list(self.shutdown_other_player_wait_waypoints_by_profile.get(profile, []))

    def _set_wait_waypoints_for_current_profile(self, items: list[dict]) -> None:
        profile = self._current_map_profile_name()
        if profile:
            self.shutdown_other_player_wait_waypoints_by_profile[profile] = list(items or [])
        # UI/요약에서 사용할 현재 뷰 동기화
        self.shutdown_other_player_wait_waypoints = list(items or [])

    def _filter_waypoints_by_geometry(self, items: list[dict]) -> list[dict]:
        map_tab = getattr(self, 'map_tab', None)
        geometry = getattr(map_tab, 'geometry_data', None)
        if not isinstance(geometry, dict):
            return []
        valid_ids = {str(wp.get('id')) for wp in (geometry.get('waypoints') or []) if wp.get('id') is not None}
        result: list[dict] = []
        for entry in (items or []):
            wp_id = str(entry.get('id') or '').strip()
            if wp_id and wp_id in valid_ids:
                name = str(entry.get('name') or wp_id)
                result.append({'id': wp_id, 'name': name})
        return result

    def map_active_profile_changed(self, profile_name: str) -> None:
        """맵 탭에서 활성 맵 프로필이 변경될 때 호출.
        - 현재 프로필에 저장된 대기 웨이포인트를 현 기하(geometry) 기준으로 정합성 검증/정리
        - UI 요약 레이블 갱신
        - 설정 저장
        """
        try:
            current_items = self._get_wait_waypoints_for_current_profile()
            filtered = self._filter_waypoints_by_geometry(current_items)
            self._set_wait_waypoints_for_current_profile(filtered)
            # 활성 대기 모드 중에 유효 웨이포인트가 사라졌다면 즉시 종료
            if self.shutdown_other_player_wait_active and not filtered:
                try:
                    self._finish_other_player_wait_mode(reason="waypoint_removed", from_map=True)
                except Exception:
                    pass
            # 구버전 단일 필드 동기화
            if filtered:
                self.shutdown_other_player_wait_waypoint_id = filtered[0]['id']
                self.shutdown_other_player_wait_waypoint_name = filtered[0]['name']
            else:
                self.shutdown_other_player_wait_waypoint_id = None
                self.shutdown_other_player_wait_waypoint_name = ''
            # 요약 반영 및 저장
            self._update_other_player_action_summary()
            self._save_settings()
        except Exception:
            pass

    def _has_wait_waypoint_configured(self) -> bool:
        try:
            items = self._get_wait_waypoints_for_current_profile()
            return bool(isinstance(items, list) and len(items) > 0)
        except Exception:
            return False

    def _select_random_wait_waypoint(self) -> Optional[tuple[str, str]]:
        """현재 활성 맵 프로필의 유효한 웨이포인트 중 하나를 무작위 선택."""
        try:
            items = self._get_wait_waypoints_for_current_profile()
            # 현 기하 기준으로 유효성 필터
            valid_items = self._filter_waypoints_by_geometry(items)
            if not valid_items:
                # 저장된 목록을 정리하여 이후 시도에서 반복 로그가 발생하지 않도록 함
                self._set_wait_waypoints_for_current_profile([])
                return None
            choice = random.choice(valid_items)
            wp_id = str(choice.get('id') or '').strip()
            if not wp_id:
                return None
            name = str(choice.get('name') or wp_id)
            return wp_id, name
        except Exception:
            return None

    def _update_other_player_action_summary(self) -> None:
        exit_delay_text = self._format_duration_text(self.shutdown_other_player_exit_delay)
        self.shutdown_other_player_shutdown_summary.setText(f"감지시간 {exit_delay_text}")

        wait_delay_text = self._format_duration_text(self.shutdown_other_player_wait_delay)
        clear_delay_text = self._format_duration_text(self.shutdown_other_player_wait_clear_delay)
        # [변경] 현재 활성 프로필의 목록 기준으로 요약 표시
        waypoint_count = len(self._get_wait_waypoints_for_current_profile())
        if waypoint_count == 0:
            waypoint_text = "웨이포인트 미설정"
        elif waypoint_count == 1:
            items = self._get_wait_waypoints_for_current_profile()
            waypoint_text = (items[0].get('name') or str(items[0].get('id'))) if items else "웨이포인트 1개"
        else:
            waypoint_text = f"웨이포인트 {waypoint_count}개"
        self.shutdown_other_player_wait_summary.setText(
            f"감지시간 {wait_delay_text} / 대기종료 {clear_delay_text} / {waypoint_text}"
        )

        if self.shutdown_other_player_action == 'town_return':
            self.shutdown_other_player_town_summary.setText("준비 중")
        else:
            self.shutdown_other_player_town_summary.setText("준비 중")

    def _format_duration_text(self, total_seconds: int) -> str:
        total_seconds = max(0, int(total_seconds))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}시간 {minutes}분 {seconds}초"
        if minutes:
            return f"{minutes}분 {seconds}초"
        return f"{seconds}초"

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

    def _toggle_other_player_mode(self, checked: bool) -> None:
        checked = bool(checked)
        self.shutdown_other_player_enabled = checked

        if checked:
            if self.shutdown_other_player_action == 'game_exit' and self.shutdown_pid_value is None:
                self._auto_detect_mapleland_pid(auto_trigger=True)
            self._reset_other_player_progress(reset_state_only=True)
            self.shutdown_other_player_elapsed.setText("감지 대기")
            self._ensure_shutdown_timer_running()
        else:
            self._reset_other_player_progress()
        self._update_shutdown_labels()

    def _reset_other_player_progress(self, *, reset_state_only: bool = False) -> None:
        """다른 캐릭터 감지 진행상태 초기화.

        주의: 금지몬스터 플로우(hunt.forbidden)로 인해 진입한 대기모드는
        '다른 캐릭터 감지 사용' 토글과 무관하게 유지되어야 한다.
        따라서 해당 경우에는 종료/리셋을 건너뛴다.
        """
        # 금지몬스터 유도 대기모드인 경우: 강제 리셋/종료를 스킵
        try:
            if not reset_state_only and self.shutdown_other_player_wait_active:
                map_tab = getattr(self, 'map_tab', None)
                ctx = getattr(map_tab, 'other_player_wait_context', {}) if map_tab else {}
                source = str(ctx.get('source', '') or '') if isinstance(ctx, dict) else ''
                if source == 'hunt.forbidden':
                    # 금지 플로우는 자체 스케줄에 따라 종료되므로 건드리지 않음
                    return
        except Exception:
            pass

        if not reset_state_only and self.shutdown_other_player_wait_active:
            self._finish_other_player_wait_mode(reason="reset")

        self.shutdown_other_player_detect_since = None
        self.shutdown_other_player_due_ts = None
        self.shutdown_other_player_last_count = 0
        self.shutdown_other_player_action_triggered = False
        if not reset_state_only:
            self.shutdown_other_player_wait_active = False
            self.shutdown_other_player_wait_started_at = None
            self.shutdown_other_player_wait_clear_since = None
            self.shutdown_other_player_wait_restart_required = False
            self.shutdown_other_player_elapsed.setText("--")
            self._stop_shutdown_timer_if_idle()

    def _on_shutdown_sleep_toggled(self, checked: bool) -> None:
        self.shutdown_sleep_enabled = bool(checked)
        self._update_shutdown_labels()
        self._handle_setting_changed()

    def _ensure_shutdown_timer_running(self) -> None:
        needs_timer = (
            (self.shutdown_reservation_enabled and self.shutdown_datetime_target is not None)
            or self.shutdown_other_player_enabled
            or self._is_exit_wait_active()
        )
        if needs_timer and not self.shutdown_timer.isActive():
            self.shutdown_timer.start()
        elif not needs_timer and self.shutdown_timer.isActive():
            self.shutdown_timer.stop()

    def _stop_shutdown_timer_if_idle(self) -> None:
        if not (
            (self.shutdown_reservation_enabled and self.shutdown_datetime_target is not None)
            or self.shutdown_other_player_enabled
            or self._is_exit_wait_active()
        ):
            self.shutdown_timer.stop()

    def _handle_shutdown_timer_tick(self) -> None:
        now = time.time()
        triggered = False

        exit_status_text: Optional[str] = None

        if self.exit_wait_schedule_ts is not None:
            remaining_to_schedule = self.exit_wait_schedule_ts - now
            if remaining_to_schedule <= 0:
                self.exit_wait_schedule_ts = None
                self._start_exit_wait_flow()
                if self.exit_wait_in_progress:
                    exit_status_text = "게임 종료 대기 진행 중"
            else:
                exit_status_text = f"게임 종료 예약: {self._format_remaining_text(remaining_to_schedule)}"
        elif self.exit_wait_in_progress:
            exit_status_text = "게임 종료 대기 진행 중"

        if exit_status_text:
            self.shutdown_reservation_status.setText(exit_status_text)

        if self.shutdown_reservation_enabled and self.shutdown_datetime_target is not None:
            remaining = self.shutdown_datetime_target - now
            if remaining <= 0:
                self._trigger_shutdown('reservation')
                triggered = True
            else:
                self.shutdown_reservation_status.setText(self._format_remaining_text(remaining))

        if self.shutdown_other_player_enabled and self.shutdown_other_player_detect_since is not None:
            elapsed = now - self.shutdown_other_player_detect_since
            self.shutdown_other_player_elapsed.setText(f"감지 {self._format_remaining_text(elapsed)}")

        if not triggered:
            self._update_shutdown_labels()
            self._stop_shutdown_timer_if_idle()

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
        reservation_text = "--"
        exit_wait_active = self._is_exit_wait_active()

        if self.shutdown_reservation_enabled:
            parts.append("종료 예약")
            if self.shutdown_datetime_target is not None:
                remaining = self.shutdown_datetime_target - now
                if remaining > 0:
                    reservation_text = self._format_remaining_text(remaining)
                else:
                    reservation_text = "--"
            else:
                reservation_text = "--"

        if self.exit_wait_schedule_ts is not None:
            remaining = self.exit_wait_schedule_ts - now
            parts.append("게임 종료 예약")
            reservation_text = f"게임 종료 예약: {self._format_remaining_text(remaining)}" if remaining > 0 else "게임 종료 예약 준비 중"
        elif self.exit_wait_in_progress:
            parts.append("게임 종료 대기 중")
            reservation_text = "대기 모드 진행 중"

        if reservation_text == "--" and not self.shutdown_reservation_enabled:
            self.shutdown_reservation_status.setText("--")
        else:
            self.shutdown_reservation_status.setText(reservation_text)

        if self.shutdown_other_player_enabled:
            parts.append("다른 캐릭터 감시")
            if self.shutdown_other_player_detect_since is None:
                self.shutdown_other_player_elapsed.setText("감지 대기")
        else:
            self.shutdown_other_player_elapsed.setText("--")

        if self.shutdown_sleep_enabled and (
            (self.shutdown_reservation_enabled and self.shutdown_datetime_target is not None)
            or self.shutdown_other_player_enabled
            or exit_wait_active
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
        if mode_key == 'reservation':
            self.shutdown_datetime_target = None
        elif mode_key == 'other':
            self.shutdown_other_player_detect_since = None
            self.shutdown_other_player_due_ts = None
        self._stop_shutdown_timer_if_idle()
        self._update_shutdown_labels()

        pid = self.shutdown_pid_value
        reason_map = {
            'reservation': '종료 예약',
            'other': '다른 캐릭터 감지',
        }
        reason_label = reason_map.get(mode_key, '자동 대응')
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
            self.force_stop_detection(reason='auto_shutdown')
            if getattr(self, 'map_tab', None) and hasattr(self.map_tab, 'force_stop_detection'):
                try:
                    self.map_tab.force_stop_detection(reason='auto_shutdown')
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
        self.shutdown_reservation_enabled = False
        self.shutdown_datetime_target = None
        self.shutdown_other_player_enabled = False
        self.shutdown_other_player_detect_since = None
        self.shutdown_other_player_due_ts = None
        self.shutdown_other_player_last_count = 0
        self.shutdown_other_player_action_triggered = False
        self.shutdown_other_player_wait_active = False
        self.shutdown_other_player_wait_started_at = None
        self.shutdown_other_player_wait_clear_since = None

        if hasattr(self, 'shutdown_reservation_checkbox') and self.shutdown_reservation_checkbox.isChecked():
            blocker = QSignalBlocker(self.shutdown_reservation_checkbox)
            self.shutdown_reservation_checkbox.setChecked(False)
            del blocker
        if hasattr(self, 'shutdown_other_player_checkbox') and self.shutdown_other_player_checkbox.isChecked():
            blocker = QSignalBlocker(self.shutdown_other_player_checkbox)
            self.shutdown_other_player_checkbox.setChecked(False)
            del blocker

        if hasattr(self, 'shutdown_reservation_status'):
            self.shutdown_reservation_status.setText("--")
        if hasattr(self, 'shutdown_other_player_elapsed'):
            self.shutdown_other_player_elapsed.setText("--")

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
                self.shutdown_other_player_action_triggered = False
                self.shutdown_other_player_elapsed.setText("감지 00:00")
                if self.shutdown_other_player_action == 'game_exit' and self.shutdown_pid_value is None:
                    self._auto_detect_mapleland_pid(auto_trigger=True)

            self.shutdown_other_player_last_count = count
            self.shutdown_other_player_wait_clear_since = None
            self._ensure_shutdown_timer_running()

            if self.shutdown_other_player_action == 'game_exit':
                due_ts = self.shutdown_other_player_detect_since + self.shutdown_other_player_exit_delay
                self.shutdown_other_player_due_ts = due_ts
                if not self.shutdown_other_player_action_triggered and now >= due_ts:
                    self.shutdown_other_player_action_triggered = True
                    self._trigger_shutdown('other')
            elif self.shutdown_other_player_action == 'wait_mode':
                due_ts = self.shutdown_other_player_detect_since + self.shutdown_other_player_wait_delay
                self.shutdown_other_player_due_ts = due_ts
                if (
                    not self.shutdown_other_player_action_triggered
                    and now >= due_ts
                    and self._has_wait_waypoint_configured()
                ):
                    if self._start_other_player_wait_mode(now):
                        self.shutdown_other_player_action_triggered = True
                elif not self._has_wait_waypoint_configured():
                    self.shutdown_other_player_elapsed.setText("웨이포인트 미설정")
            else:
                # 미구현 상태에서는 경과만 표시
                self.shutdown_other_player_elapsed.setText(f"감지 {self._format_remaining_text(now - self.shutdown_other_player_detect_since)}")
        else:
            self.shutdown_other_player_last_count = 0
            if self.shutdown_other_player_action == 'wait_mode' and self.shutdown_other_player_wait_active:
                # 무기한 대기모드일 경우 자동 해제를 하지 않는다.
                if getattr(self, '_manual_indefinite_wait_active', False):
                    try:
                        self.shutdown_other_player_elapsed.setText("대기 모드 진행 중")
                    except Exception:
                        pass
                else:
                    if self.shutdown_other_player_wait_clear_since is None:
                        self.shutdown_other_player_wait_clear_since = now
                    clear_elapsed = now - self.shutdown_other_player_wait_clear_since
                    if clear_elapsed >= max(1, float(self.shutdown_other_player_wait_clear_delay)):
                        self._finish_other_player_wait_mode(reason="other_absent")
                        self.shutdown_other_player_detect_since = None
                        self.shutdown_other_player_action_triggered = False
                        self.shutdown_other_player_elapsed.setText("감지 대기")
            else:
                self._reset_other_player_progress()

        self._update_shutdown_labels()

    def _start_other_player_wait_mode(self, started_at: float, *, flow: str = 'other_player') -> bool:
        selected = self._select_random_wait_waypoint()
        if not selected:
            self.append_log("대기 모드를 실행하려면 웨이포인트를 먼저 설정해주세요.", "warn")
            return False
        waypoint_id, waypoint_name = selected

        map_tab = getattr(self, 'map_tab', None)
        if not map_tab or not hasattr(map_tab, 'start_other_player_wait_operation'):
            self.append_log("맵 탭이 대기 모드를 지원하지 않습니다.", "warn")
            return False

        waypoint_id_str = str(waypoint_id)

        try:
            # 대기모드 체력회복 설정 전달
            wait_hp_cfg = {
                'enabled': bool(getattr(self, 'wait_hp_enabled', False)),
                'threshold': int(getattr(self, 'wait_hp_threshold', 50) or 50),
                'command_profile': str(getattr(self, 'wait_hp_command_profile', '') or ''),
                # [NEW] 대기모드 위치 복구 임계값(px)
                'recover_threshold_px': int(getattr(self, 'wait_recover_threshold_px', 70) or 70),
            }
            success = map_tab.start_other_player_wait_operation(
                waypoint_id=waypoint_id_str,
                waypoint_name=waypoint_name,
                source=f'hunt.{flow}',
                wait_hp_config=wait_hp_cfg,
            )
        except Exception as exc:
            self.append_log(f"대기 모드 시작 실패: {exc}", "warn")
            return False

        if not success:
            self.append_log("대기 모드 요청이 거부되었습니다.", "warn")
            return False

        self.shutdown_other_player_wait_restart_required = self._is_detection_active()
        if map_tab and hasattr(map_tab, 'suppress_hunt_sync_once'):
            try:
                map_tab.suppress_hunt_sync_once('other_player_wait_start')
            except Exception:
                pass
        self._preserve_exp_on_stop = True
        stopped = False
        previous_sync = bool(getattr(self, '_syncing_with_map', False))
        self._syncing_with_map = True
        try:
            stopped = self.force_stop_detection(reason='other_player_wait_start', preserve_forbidden=True)
        finally:
            self._syncing_with_map = previous_sync
        if not stopped:
            self._preserve_exp_on_stop = False
        # [추가] 대기 모드에서는 맵이 권한을 갖도록 즉시 반납
        try:
            if self.current_authority == 'hunt':
                self.release_control(reason='OTHER_PLAYER_WAIT_START')
        except Exception:
            pass
        self.shutdown_other_player_wait_active = True
        self.shutdown_other_player_wait_started_at = started_at
        self.shutdown_other_player_elapsed.setText("대기 모드 진행 중")
        self.append_log(f"대기 모드를 시작합니다. 대상 웨이포인트: {waypoint_name}", "info")
        return True

    def _finish_other_player_wait_mode(self, reason: str = "finished", *, from_map: bool = False) -> None:
        if not self.shutdown_other_player_wait_active:
            return

        map_tab = getattr(self, 'map_tab', None)
        restart_required = self.shutdown_other_player_wait_restart_required
        if from_map:
            restart_required = False
            self.shutdown_other_player_wait_restart_required = False

        if (
            not from_map
            and map_tab
            and hasattr(map_tab, 'finish_other_player_wait_operation')
        ):
            try:
                map_tab.finish_other_player_wait_operation(reason=reason)
            except Exception as exc:
                self.append_log(f"대기 모드 종료 중 오류: {exc}", "warn")

        self.shutdown_other_player_wait_active = False
        self.shutdown_other_player_wait_started_at = None
        self.shutdown_other_player_wait_clear_since = None
        self.shutdown_other_player_elapsed.setText("감지 대기")
        reason_text = reason or "finished"
        self.append_log(f"대기 모드를 종료합니다. (사유: {reason_text})", "info")

        if getattr(self, 'exit_wait_in_progress', False):
            if reason != 'exit_wait_complete':
                self._reset_exit_wait_state()
            else:
                self.exit_wait_in_progress = False

        if restart_required:
            QTimer.singleShot(500, self._restart_hunt_detection_after_wait)
        self.shutdown_other_player_wait_restart_required = False
        self._manual_indefinite_wait_active = False

    def _restart_hunt_detection_after_wait(self) -> None:
        if self._is_detection_active():
            return

        try:
            # [NEW] 자동 재시작 플래그: 수동 시작과 구분하여 쿨다운 초기화 방지
            setattr(self, '_auto_restart_after_wait', True)
            self.detect_btn.setChecked(True)
            self._toggle_detection(True)
        except Exception as exc:
            self.append_log(f"대기 모드 후 탐지 재시작 실패: {exc}", "warn")
        else:
            self.append_log("대기 모드 종료 후 사냥 탐지를 재시작합니다.", "info")
        finally:
            try:
                delattr(self, '_auto_restart_after_wait')
            except Exception:
                pass

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

        control_row = QHBoxLayout()
        control_row.setSpacing(12)

        self.detect_btn = QPushButton("사냥시작")
        self.detect_btn.setCheckable(True)
        self.detect_btn.setToolTip("단축키: F10")
        self.detect_btn.clicked.connect(self._toggle_detection)
        control_row.addWidget(self.detect_btn)

        self.area_settings_btn = QPushButton("영역 설정")
        self.area_settings_btn.clicked.connect(self._open_area_settings_dialog)
        control_row.addWidget(self.area_settings_btn)

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
        # [연결 강화] 자동사냥 체크박스로 루프 ON/OFF도 함께 제어
        try:
            self.auto_request_checkbox.toggled.connect(self.set_auto_hunt_enabled)
        except Exception:
            pass
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

        # [NEW] 오버레이 추가 체크박스 (아랫줄)
        self.show_cleanup_chase_checkbox = QCheckBox("클린업 추격밴드")
        self.show_cleanup_chase_checkbox.setChecked(True)
        self.show_cleanup_chase_checkbox.toggled.connect(self._on_overlay_toggle_changed)
        self.show_cluster_window_checkbox = QCheckBox("군집 중심 범위")
        self.show_cluster_window_checkbox.setChecked(True)
        self.show_cluster_window_checkbox.toggled.connect(self._on_overlay_toggle_changed)

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
        # 로그 수치 표기 토글: a(기준 b) 표기 사용
        self.metric_parentheses_checkbox = QCheckBox("수치 표기 a(기준 b)")
        self.metric_parentheses_checkbox.setChecked(True)
        self.metric_parentheses_checkbox.toggled.connect(self._on_metric_parentheses_toggled)

        for checkbox in (
            self.show_hunt_area_checkbox,
            self.show_primary_skill_checkbox,
            self.show_cleanup_chase_checkbox,
            self.show_cluster_window_checkbox,
            self.show_direction_checkbox,
            self.show_nickname_range_checkbox,
            self.show_nameplate_checkbox,
            self.show_nameplate_tracking_checkbox,
            self.show_monster_confidence_checkbox,
            self.metric_parentheses_checkbox,
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
        button_row.addWidget(self.metric_parentheses_checkbox)

        button_row.addStretch(1)
        control_layout.addLayout(button_row)

        # [NEW] 오버레이 2열 배치(요청: 아랫줄)
        button_row2 = QHBoxLayout()
        button_row2.setSpacing(12)
        button_row2.addWidget(self.show_cleanup_chase_checkbox)
        button_row2.addWidget(self.show_cluster_window_checkbox)
        # [NEW] 미니맵 보정 캐릭터 오버레이 토글
        self.show_minimap_char_checkbox = QCheckBox("미니맵 보정 캐릭터")
        self.show_minimap_char_checkbox.setChecked(False)
        button_row2.addWidget(self.show_minimap_char_checkbox)
        button_row2.addStretch(1)
        control_layout.addLayout(button_row2)

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
            window_geometry = get_maple_window_geometry()
            if window_geometry:
                relative_region = make_relative_roi(new_region, window_geometry, anchor_name=last_used_anchor_name())
            else:
                relative_region = dict(new_region)
                self.append_log('경고: Mapleland 창 좌표를 찾지 못해 절대 좌표로 저장했습니다. 창 좌표를 먼저 저장하면 이동해도 안전합니다.', 'warn')

            self.manual_capture_region = copy.deepcopy(relative_region)
            self.manual_capture_regions = [copy.deepcopy(relative_region)]
            self.active_area_profile = None
            display_region = resolve_roi_to_absolute(relative_region, window=window_geometry) or new_region
            self.append_log(f"수동 탐지 영역 초기화: {display_region}")
            self._update_manual_area_summary()
            self._notify_area_settings_changed()
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
            window_geometry = get_maple_window_geometry()
            if window_geometry:
                relative_region = make_relative_roi(new_region, window_geometry, anchor_name=last_used_anchor_name())
            else:
                relative_region = dict(new_region)
                self.append_log('경고: Mapleland 창 좌표를 찾지 못해 새 영역을 절대 좌표로 저장했습니다.', 'warn')

            self.manual_capture_regions.append(copy.deepcopy(relative_region))
            self.manual_capture_region = self._merge_manual_capture_regions()
            self.active_area_profile = None
            display_region = resolve_roi_to_absolute(self.manual_capture_region, window=window_geometry) or new_region
            self.append_log(f"영역 추가 완료. 합성 영역: {display_region}")
            self._update_manual_area_summary()
            self._notify_area_settings_changed()
            self._save_settings()
        else:
            self.append_log('영역 추가가 취소되었습니다.', 'info')

    def _merge_manual_capture_regions(self) -> Optional[dict]:
        if not self.manual_capture_regions:
            return self.manual_capture_region
        window_geometry = get_maple_window_geometry()
        resolved_regions: list[dict] = []
        for payload in self.manual_capture_regions:
            absolute = resolve_roi_to_absolute(payload, window=window_geometry)
            if absolute is None:
                absolute = resolve_roi_to_absolute(payload)
            if not absolute:
                continue
            resolved_regions.append(absolute)

        if not resolved_regions:
            return self.manual_capture_region

        top_values = [region['top'] for region in resolved_regions]
        left_values = [region['left'] for region in resolved_regions]
        bottoms = [region['top'] + region['height'] for region in resolved_regions]
        rights = [region['left'] + region['width'] for region in resolved_regions]
        merged_absolute = {
            'top': min(top_values),
            'left': min(left_values),
            'width': max(rights) - min(left_values),
            'height': max(bottoms) - min(top_values),
        }

        return ensure_relative_roi(
            merged_absolute,
            window_geometry,
            anchor_name=last_used_anchor_name(),
        ) or merged_absolute

    def _resolve_manual_capture_region(self, *, require_window: bool = False) -> Optional[dict]:
        if not self.manual_capture_region:
            return None
        window_geometry = get_maple_window_geometry()
        resolved = resolve_roi_to_absolute(self.manual_capture_region, window=window_geometry)
        if resolved is None and require_window:
            if window_geometry is None:
                self.append_log("Mapleland 창을 찾을 수 없어 수동 탐지 영역을 복원하지 못했습니다.", "warn")
            else:
                self.append_log("수동 탐지 영역을 복원할 수 없습니다. 영역을 다시 지정해주세요.", "warn")
        return resolved

    def _resolve_manual_subregions(self, capture_region: dict) -> Optional[list[dict]]:
        if not isinstance(capture_region, dict):
            return None
        if not self.manual_capture_regions or len(self.manual_capture_regions) <= 1:
            return None

        window_geometry = get_maple_window_geometry()

        base_absolute = resolve_roi_to_absolute(capture_region, window=window_geometry)
        if base_absolute is None:
            base_absolute = resolve_roi_to_absolute(capture_region)
        if base_absolute is None:
            return None

        try:
            base_top = int(base_absolute['top'])
            base_left = int(base_absolute['left'])
            base_width = int(base_absolute['width'])
            base_height = int(base_absolute['height'])
        except (KeyError, TypeError, ValueError):
            return None
        if base_width <= 0 or base_height <= 0:
            return None

        subregions: list[dict] = []
        for payload in self.manual_capture_regions:
            absolute = resolve_roi_to_absolute(payload, window=window_geometry)
            if absolute is None:
                absolute = resolve_roi_to_absolute(payload)
            if absolute is None:
                continue
            try:
                top = int(absolute['top']) - base_top
                left = int(absolute['left']) - base_left
                width = int(absolute['width'])
                height = int(absolute['height'])
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
        display_region = self._resolve_manual_capture_region()
        self.append_log(
            f"추가된 영역 수: {count}, 합성 캡처 범위: {display_region or self.manual_capture_region}."
            " 합성 범위 내부에서도 지정된 영역만 탐지에 사용됩니다."
        )

    def _notify_area_settings_changed(self) -> None:
        dialog = getattr(self, '_area_settings_dialog', None)
        if dialog:
            dialog.update_state()
        button = getattr(self, 'area_settings_btn', None)
        if button:
            if self.manual_capture_region:
                profile_line = (
                    f"현재 프로필: {self.active_area_profile}"
                    if self.active_area_profile
                    else "현재 프로필: (저장되지 않음)"
                )
                button.setToolTip(
                    profile_line
                    + "\n"
                    + f"합성 영역: {self.manual_capture_region}"
                )
            else:
                button.setToolTip("설정된 탐지 영역이 없습니다.")

    def _open_area_settings_dialog(self) -> None:
        if self._area_settings_dialog is None:
            self._area_settings_dialog = _AreaSettingsDialog(self)
        self._area_settings_dialog.update_state()
        self._area_settings_dialog.show()
        self._area_settings_dialog.raise_()
        self._area_settings_dialog.activateWindow()

    def _save_area_profile(self, name: str) -> bool:
        normalized = name.strip()
        if not normalized:
            return False
        if not self.manual_capture_regions:
            return False
        stored_regions = [copy.deepcopy(region) for region in self.manual_capture_regions]
        replaced = normalized in self.manual_area_profiles
        self.manual_area_profiles[normalized] = stored_regions
        self.manual_capture_region = self._merge_manual_capture_regions()
        self.active_area_profile = normalized
        action = "갱신" if replaced else "저장"
        self.append_log(f"사냥 영역 프로필 {action}: '{normalized}'", "info")
        self._notify_area_settings_changed()
        self._save_settings()
        return True

    def _apply_area_profile(
        self,
        name: str,
        *,
        emit_log: bool = True,
        auto_save: bool = True,
    ) -> bool:
        normalized = name.strip()
        if not normalized:
            return False
        regions = self.manual_area_profiles.get(normalized)
        if not regions:
            if emit_log:
                self.append_log(f"사냥 영역 프로필을 찾을 수 없습니다: '{normalized}'", "warn")
            return False

        self.manual_capture_regions = [copy.deepcopy(region) for region in regions]
        self.manual_capture_region = self._merge_manual_capture_regions()
        if not self.manual_capture_region:
            if emit_log:
                self.append_log(
                    f"사냥 영역 프로필 '{normalized}'의 데이터가 유효하지 않습니다.",
                    "warn",
                )
            return False

        self.active_area_profile = normalized

        if emit_log:
            resolved = self._resolve_manual_capture_region()
            display_region = resolved or self.manual_capture_region
            self.append_log(
                f"사냥 영역 프로필 불러오기: '{normalized}' → {display_region}",
                "info",
            )
            self._update_manual_area_summary()

        self._notify_area_settings_changed()

        if auto_save:
            self._save_settings()

        return True

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
            # [NEW] 수동 시작 시 금지몬스터 쿨다운 초기화
            try:
                if not bool(getattr(self, '_auto_restart_after_wait', False)):
                    self._forbidden_cooldown_until = 0.0
                    self._forbidden_active = False
            except Exception:
                pass
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

            # 텔레그램 등 비 UI 트리거에서 포커싱이 막힐 수 있으므로, 1회에 한해 활성화 건너뛰기 지원
            skip_activation = bool(getattr(self, '_skip_window_activation_once', False))
            if skip_activation:
                try:
                    delattr(self, '_skip_window_activation_once')
                except Exception:
                    pass
                try:
                    maple_windows = gw.getWindowsWithTitle('Mapleland')
                except Exception:
                    maple_windows = []
                maple_window = maple_windows[0] if maple_windows else None
            else:
                maple_window = self._activate_maple_window()
            if not maple_window:
                QMessageBox.warning(self, '오류', '메이플스토리 창을 찾을 수 없습니다.')
                self.detect_btn.setChecked(False)
                return

            if not self.manual_capture_region:
                QMessageBox.warning(self, '오류', "'영역 지정'으로 탐지 영역을 설정해주세요.")
                self.detect_btn.setChecked(False)
                return
            capture_region = self._resolve_manual_capture_region(require_window=True)
            if not capture_region:
                QMessageBox.warning(self, '오류', '탐지 영역을 복원할 수 없습니다. 창 위치를 확인하고 다시 지정해주세요.')
                self.detect_btn.setChecked(False)
                return

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
            resume_exp = bool(getattr(self, '_resume_exp_after_pause', False))
            if resume_exp:
                self._resume_exp_after_pause = False
            if self.status_monitor:
                try:
                    self.status_monitor.set_tab_active(hunt=True, preserve_exp=resume_exp)
                except TypeError:
                    self.status_monitor.set_tab_active(hunt=True)
            if not resume_exp or not self._status_detection_start_ts:
                self._status_detection_start_ts = time.time()
            if not resume_exp:
                self._status_exp_records = []
                self._status_exp_start_snapshot = None
                self._status_ocr_warned = False
                self._status_display_values = {'hp': None, 'mp': None}
                self._update_status_summary_cache()
            self._hp_guard_active = False
            self._hp_guard_timer.stop()
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
                self._popup_open_reason = 'detect_start'
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
            preserve_forbidden = bool(getattr(self, '_preserve_forbidden_on_stop', False))
            # 탐지 중단을 누른 즉시 모든 키를 해제해 캐릭터가 바로 멈추도록 함
            try:
                self._issue_all_keys_release("사냥중지")
                self._release_pending = False
            except Exception:
                pass
            # [NEW] 탐지 중지 시 금지몬스터 히스토리 초기화(보존 모드에서는 유지)
            if not preserve_forbidden:
                try:
                    self._forbidden_detect_history = []
                    self._forbidden_detect_last_log_ts = 0.0
                except Exception:
                    pass
            self._stop_perf_logging()
            if not preserve_forbidden:
                self._reset_forbidden_status(reason='toggle_off')
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

            if preserve_forbidden:
                try:
                    self._preserve_forbidden_on_stop = False
                except Exception:
                    pass

            if self.map_link_enabled and self.map_tab and not self._syncing_with_map:
                self._syncing_with_map = True
                try:
                    if hasattr(self.map_tab, 'detect_anchor_btn') and self.map_tab.detect_anchor_btn.isChecked():
                        self.map_tab.detect_anchor_btn.setChecked(False)
                        if hasattr(self.map_tab, 'set_detection_stop_reason'):
                            self.map_tab.set_detection_stop_reason('hunt_link_sync')
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
        preserve_exp = bool(getattr(self, '_preserve_exp_on_stop', False))
        self._preserve_exp_on_stop = False
        if self.status_monitor:
            try:
                self.status_monitor.set_tab_active(hunt=False, preserve_exp=preserve_exp)
            except TypeError:
                # 구버전 호환: preserve_exp 미지원
                self.status_monitor.set_tab_active(hunt=False)
        if preserve_exp:
            self._resume_exp_after_pause = True
        else:
            self._finalize_exp_tracking()
            self._status_exp_records = []
            self._status_exp_start_snapshot = None
            self._status_detection_start_ts = None
            self._resume_exp_after_pause = False
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
            # 프로그램적 닫힘 사유 기록(상위에서 지정된 사유가 없으면 기본값)
            if not self._popup_close_reason:
                self._popup_close_reason = 'stop_detection_thread'
            self._closing_popup_programmatically = True
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
        # 프리뷰 재동기화(스레드 종료 시 초기화)
        self._sync_detection_thread_status()

    def _handle_detection_log(self, messages: List[str]) -> None:
        for msg in messages:
            self.append_log(msg, "debug")

    def _handle_detection_frame(self, q_image) -> None:
        try:
            self._cache_latest_detection_frame(q_image)
        except Exception:
            pass
        if not self._is_screen_output_enabled():
            return
        # 탭이 보이지 않고 팝업도 없으면 UI 업데이트 생략(모니터링이 직접 오버레이를 그릴 수 있도록 원본 전달)
        if not getattr(self, '_ui_runtime_visible', True) and not bool(getattr(self, 'is_popup_active', False)):
            try:
                self.preview_frame_ready.emit(q_image)
            except Exception:
                pass
            return
        image = q_image.copy()
        self._paint_overlays(image)
        if self.is_popup_active and self.detection_popup:
            self.detection_popup.update_frame(image)
        elif self.detection_view:
            self._update_detection_frame(image)
        # [NEW] 모니터링 프리뷰로도 전달
        try:
            self.preview_frame_ready.emit(image)
        except Exception:
            pass

    def _cache_latest_detection_frame(self, q_image) -> None:
        if not getattr(self, 'forbidden_monster_enabled', False) and not self._forbidden_active:
            if time.time() > float(self._forbidden_watch_window_until or 0.0):
                return
        if not isinstance(q_image, QImage) or q_image.isNull():
            return
        image = q_image
        if image.format() != QImage.Format.Format_RGB888:
            try:
                image = image.convertToFormat(QImage.Format.Format_RGB888)
            except Exception:
                return
        self._latest_detection_qimage = image.copy()
        self._latest_detection_frame_ts = time.time()
        self._latest_detection_bgr = None
        self._latest_detection_bgr_ts = 0.0

    def _get_latest_detection_bgr(self) -> Optional[np.ndarray]:
        qimg = self._latest_detection_qimage
        if qimg is None or qimg.isNull():
            return None
        if self._latest_detection_bgr is not None:
            if abs(self._latest_detection_bgr_ts - self._latest_detection_frame_ts) < 1e-6:
                return self._latest_detection_bgr
        width = qimg.width()
        height = qimg.height()
        bytes_per_line = qimg.bytesPerLine()
        ptr = qimg.bits()
        try:
            ptr.setsize(qimg.sizeInBytes())
        except Exception:
            return None
        arr = np.frombuffer(ptr, np.uint8).reshape(height, bytes_per_line)
        arr = arr[:, : width * 3].reshape(height, width, 3)
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        self._latest_detection_bgr = bgr
        self._latest_detection_bgr_ts = self._latest_detection_frame_ts
        return bgr

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
            # [NEW] 클린업 추격밴드 오버레이(클린업 중에만)
            if (
                getattr(self, 'current_cleanup_chase_area', None)
                and self.overlay_preferences.get('cleanup_chase_area', True)
                and hasattr(self, 'show_cleanup_chase_checkbox')
                and self.show_cleanup_chase_checkbox.isChecked()
            ):
                rect = self._area_to_rect(self.current_cleanup_chase_area, image.width(), image.height())
                if not rect.isNull():
                    painter.setPen(CLEANUP_CHASE_EDGE)
                    painter.setBrush(CLEANUP_CHASE_BRUSH)
                    painter.drawRect(rect)
            if self._forbidden_visual_overlays:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for entry in self._forbidden_visual_overlays:
                    rect_info = entry.get('rect')
                    if rect_info and len(rect_info) == 4:
                        rx, ry, rw, rh = rect_info
                        roi_rect = QRect(int(round(rx)), int(round(ry)), int(round(rw)), int(round(rh)))
                        if not roi_rect.isNull():
                            painter.setPen(FORBIDDEN_GLYPH_ROI_EDGE)
                            painter.drawRect(roi_rect)
                    match_info = entry.get('match_rect')
                    if match_info and len(match_info) == 4:
                        mx, my, mw, mh = match_info
                        match_rect = QRect(int(round(mx)), int(round(my)), int(round(mw)), int(round(mh)))
                        if not match_rect.isNull():
                            painter.setPen(FORBIDDEN_GLYPH_MATCH_EDGE)
                            painter.drawRect(match_rect)
            # [NEW] 군집 중심 윈도우 오버레이
            if (
                self.overlay_preferences.get('cluster_window_area', True)
                and hasattr(self, 'show_cluster_window_checkbox')
                and self.show_cluster_window_checkbox.isChecked()
            ):
                # [NEW] 군집 중심 점 + 좌우 120px 선 시각화
                cx = getattr(self, 'current_cluster_center_x', None)
                cy = getattr(self, 'current_cluster_center_y', None)
                pa = getattr(self, 'current_primary_area', None)
                if cx is not None and cy is not None and pa is not None:
                    h = image.height()
                    w = image.width()
                    # 수평선은 중심 Y를 기준(주 스킬 밴드 중앙)
                    y = int(max(0, min(h - 1, round(cy))))
                    half = int(JUMP_CENTER_VISUAL_DISTANCE_PX)
                    x1 = int(max(0, min(w - 1, round(cx - half))))
                    x2 = int(max(0, min(w - 1, round(cx + half))))
                    painter.setPen(CLUSTER_WINDOW_EDGE)
                    painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    painter.drawLine(x1, y, x2, y)
                    # 중심 점(작은 원)
                    radius = 4
                    center_x = int(max(0, min(w - 1, round(cx))))
                    center_y = y
                    painter.setPen(CLUSTER_WINDOW_EDGE)
                    painter.setBrush(CLUSTER_WINDOW_BRUSH)
                    painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
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
                # fallthrough
            # [NEW] 미니맵 보정 캐릭터 박스 오버레이(체크된 경우에만)
            if getattr(self, 'show_minimap_char_checkbox', None) and self.show_minimap_char_checkbox.isChecked():
                box = getattr(self, '_minimap_char_overlay_box', None)
                if isinstance(box, dict):
                    try:
                        x = float(box.get('x', 0.0))
                        y = float(box.get('y', 0.0))
                        w = float(box.get('width', 0.0))
                        h = float(box.get('height', 0.0))
                        if w > 0 and h > 0:
                            painter.setPen(QPen(QColor(255, 215, 0), 2))
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                            painter.drawRect(int(x), int(y), int(w), int(h))
                    except Exception:
                        pass
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

            # [NEW] 금지몬스터 감지 히스토리 표시
            try:
                hist = list(getattr(self, '_forbidden_detect_history', []) or [])
            except Exception:
                hist = []
            if hist:
                lines.append("사냥금지 몬스터: " + " , ".join(hist))

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

    def _log_screen_output_event(self, action: str, level: str = 'info', **kwargs) -> None:
        """화면출력 팝업 관련 이벤트 로깅(원인 추적용)."""
        try:
            parts = [f"action={action}"]
            for k, v in kwargs.items():
                try:
                    parts.append(f"{k}={v}")
                except Exception:
                    continue
            msg = "[화면출력] " + ", ".join(parts)
            self.append_log(msg, level)
        except Exception:
            pass

    def _on_screen_output_toggled(self, checked: bool) -> None:
        # 상태 스냅샷(로깅용)
        try:
            detect_active = bool(self._is_detection_active())
        except Exception:
            detect_active = False
        try:
            thread_running = bool(self.detection_thread is not None and self.detection_thread.isRunning())
        except Exception:
            thread_running = False
        try:
            is_popup_active = bool(self.is_popup_active)
        except Exception:
            is_popup_active = False

        self._log_screen_output_event(
            "checkbox_toggled",
            level='info',
            checked=bool(checked),
            active=detect_active,
            thread=thread_running,
            popup=is_popup_active,
        )

        if self.detection_thread and hasattr(self.detection_thread, 'set_screen_output_enabled'):
            try:
                self.detection_thread.set_screen_output_enabled(bool(checked))
            except Exception:
                pass
        if not checked and self.is_popup_active:
            # 프로그램에 의한 팝업 닫힘 사유 기록
            self._closing_popup_programmatically = True
            self._popup_close_reason = 'screen_output_unchecked'
            self._toggle_detection_popup()
        if not checked and self.detection_view:
            self.detection_view.setText("화면출력이 비활성화되었습니다.")
            self.detection_view.setPixmap(QPixmap())
        if checked and self.detect_btn.isChecked() and not self.is_popup_active:
            # 프로그램에 의한 팝업 열림 사유 기록
            self._popup_open_reason = 'screen_output_checked_on'
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
        # 모니터링 프리뷰가 활성화되면 강제로 화면출력을 허용
        if bool(getattr(self, '_monitor_preview_enabled', False)):
            return True
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
                # 프로그램적 닫힘 사유가 없다면 기본값 지정
                if not self._popup_close_reason:
                    self._popup_close_reason = 'toggle_detection_popup'
                self._closing_popup_programmatically = True
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

        # 열림 로깅
        try:
            reason = self._popup_open_reason or 'toggle_detection_popup'
            self._popup_open_reason = None
            # 실행 시점 상태 스냅샷
            detect_active = bool(self._is_detection_active())
            thread_running = bool(self.detection_thread is not None and self.detection_thread.isRunning())
            size_w = int(self.detection_popup.width()) if self.detection_popup else 0
            size_h = int(self.detection_popup.height()) if self.detection_popup else 0
            checked = bool(self.screen_output_checkbox.isChecked()) if hasattr(self, 'screen_output_checkbox') else True
            sender_obj = None
            try:
                sender_obj = self.sender()
            except Exception:
                sender_obj = None
            self._log_screen_output_event(
                'popup_open',
                level='info',
                reason=reason,
                checked=checked,
                active=detect_active,
                thread=thread_running,
                size=f"{size_w}x{size_h}",
                scale=int(self.last_popup_scale),
                programmatic=bool(sender_obj is None),
            )
        except Exception:
            pass

    def _on_popup_scale_changed(self, value: int) -> None:
        self.last_popup_scale = value
        self._save_settings()
        try:
            self._log_screen_output_event('popup_scale', level='debug', scale=int(value))
        except Exception:
            pass

    def _on_popup_size_changed(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        self.last_popup_size = (int(width), int(height))
        self._save_settings()
        try:
            self._log_screen_output_event('popup_size', level='debug', size=f"{int(width)}x{int(height)}")
        except Exception:
            pass

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

        # 닫힘 로깅
        try:
            size_w = 0
            size_h = 0
            if isinstance(self.last_popup_size, tuple) and len(self.last_popup_size) == 2:
                try:
                    size_w = int(self.last_popup_size[0])
                    size_h = int(self.last_popup_size[1])
                except Exception:
                    size_w = size_w or 0
                    size_h = size_h or 0
            reason = self._popup_close_reason or 'unknown'
            self._log_screen_output_event(
                'popup_close',
                level='info',
                reason=reason,
                programmatic=bool(self._closing_popup_programmatically),
                size=f"{size_w}x{size_h}",
                scale=int(self.last_popup_scale),
            )
        except Exception:
            pass
        finally:
            # 컨텍스트 초기화
            self._closing_popup_programmatically = False
            self._popup_close_reason = None

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

    def _update_range_inputs_enabled(self, checked: bool | None = None) -> None:
        try:
            mode_on = bool(self.facing_range_checkbox.isChecked() if checked is None else checked)
        except Exception:
            mode_on = False
        # 대칭 컨트롤
        for w in (self._label_enemy_range, self.enemy_range_spinbox, self._label_primary_range, self.primary_skill_range_spinbox):
            if hasattr(w, 'setVisible'):
                w.setVisible(not mode_on)
            if hasattr(w, 'setEnabled'):
                w.setEnabled(not mode_on)
        # 전/후 컨트롤
        for w in (
            self._label_enemy_front,
            self.enemy_front_spinbox,
            self._label_enemy_back,
            self.enemy_back_spinbox,
            self._label_primary_front,
            self.primary_front_spinbox,
            self._label_primary_back,
            self.primary_back_spinbox,
        ):
            if hasattr(w, 'setVisible'):
                w.setVisible(mode_on)
            if hasattr(w, 'setEnabled'):
                w.setEnabled(mode_on)

    def _emit_area_overlays(self) -> None:
        if not hasattr(self, "show_hunt_area_checkbox"):
            return
        show_hunt = self.overlay_preferences.get('hunt_area', True)
        show_primary = self.overlay_preferences.get('primary_area', True)
        # 신규 오버레이 토글은 같은 함수에서 detection 스레드로 보낼 필요 없음(현지 렌더링)
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
        if hasattr(self, 'show_cleanup_chase_checkbox'):
            self.overlay_preferences['cleanup_chase_area'] = self.show_cleanup_chase_checkbox.isChecked()
        if hasattr(self, 'show_cluster_window_checkbox'):
            self.overlay_preferences['cluster_window_area'] = self.show_cluster_window_checkbox.isChecked()
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

    def _on_metric_parentheses_toggled(self, checked: bool) -> None:
        """로그 수치 표기 형식 토글 핸들러."""
        self._metric_format_parentheses = bool(checked)
        try:
            self._save_settings()
        except Exception:
            pass
        # 즉시 반영: 이후 로그부터 새로운 형식 적용
        try:
            self._handle_setting_changed()
        except Exception:
            pass

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
        # [NEW] 모니터링 프리뷰 설정을 런타임에 반영
        try:
            if hasattr(self.detection_thread, 'set_frame_emit_min_interval'):
                if self._monitor_preview_enabled:
                    # 프리뷰 ON: 화면출력 강제 활성 + 저주기 배출
                    self.detection_thread.set_screen_output_enabled(True)
                    try:
                        interval_sec = float(self._monitor_preview_interval_sec)
                    except (TypeError, ValueError):
                        interval_sec = 0.0
                    if interval_sec <= 0.0:
                        self.detection_thread.set_frame_emit_min_interval(0.0)
                    else:
                        self.detection_thread.set_frame_emit_min_interval(max(0.01, interval_sec))
                else:
                    # 프리뷰 OFF: 체크박스 상태로 복원 + 제한 해제
                    checkbox = getattr(self, 'screen_output_checkbox', None)
                    base_enabled = bool(checkbox.isChecked()) if checkbox is not None else True
                    self.detection_thread.set_screen_output_enabled(base_enabled)
                    self.detection_thread.set_frame_emit_min_interval(0.0)
        except Exception:
            pass

    # [NEW] 외부에서 모니터링 프리뷰를 요청/해제
    def api_set_preview_enabled(self, enabled: bool, min_interval_sec: float = 1.0) -> None:
        self._monitor_preview_enabled = bool(enabled)
        try:
            self._monitor_preview_interval_sec = float(min_interval_sec)
        except (TypeError, ValueError):
            self._monitor_preview_interval_sec = 1.0
        self._sync_detection_thread_status()

    # [NEW] 탭 가시성 전파(비가시 시 팝업 자동 닫기)
    def set_tab_visible(self, visible: bool) -> None:
        self._ui_runtime_visible = bool(visible)
        if not self._ui_runtime_visible and bool(getattr(self, 'is_popup_active', False)):
            try:
                self._closing_popup_programmatically = True
                self._popup_close_reason = 'auto_hide'
                self._toggle_detection_popup()
            except Exception:
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
        # [NEW] 클린업/군집 중심 범위도 외부에서 제어 가능하도록 반영
        if 'cleanup_chase_area' in options:
            cleanup_state = bool(options['cleanup_chase_area'])
            self.overlay_preferences['cleanup_chase_area'] = cleanup_state
            if hasattr(self, 'show_cleanup_chase_checkbox') and self.show_cleanup_chase_checkbox.isChecked() != cleanup_state:
                self.show_cleanup_chase_checkbox.blockSignals(True)
                self.show_cleanup_chase_checkbox.setChecked(cleanup_state)
                self.show_cleanup_chase_checkbox.blockSignals(False)
        if 'cluster_window_area' in options:
            cluster_state = bool(options['cluster_window_area'])
            self.overlay_preferences['cluster_window_area'] = cluster_state
            if hasattr(self, 'show_cluster_window_checkbox') and self.show_cluster_window_checkbox.isChecked() != cluster_state:
                self.show_cluster_window_checkbox.blockSignals(True)
                self.show_cluster_window_checkbox.setChecked(cluster_state)
                self.show_cluster_window_checkbox.blockSignals(False)
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
        range_mode = payload.get("range_mode")
        range_front = payload.get("range_front_px")
        range_back = payload.get("range_back_px")
        primary_front = payload.get("primary_front_px")
        primary_back = payload.get("primary_back_px")
        model = payload.get("model") or "-"
        attack_count = payload.get("attack_skill_count", 0)
        buff_count = payload.get("buff_skill_count", 0)
        latest_total = payload.get("latest_monster_count")
        latest_primary = payload.get("latest_primary_monster_count")

        detail_parts = [
            f"현재 몬스터 {latest_total}마리 / 주 스킬 {latest_primary}마리",
            f"사냥범위 기준 {hunt_threshold}마리, 주 스킬 기준 {primary_threshold}마리",
            (
                f"사냥범위 전 {range_front}px / 후 {range_back}px, 주 스킬 전 {primary_front}px / 후 {primary_back}px"
                if str(range_mode).lower() == 'facing'
                else f"사냥범위 ±{range_px}px, 주 스킬 범위 ±{primary_range}px"
            ),
            f"모델 '{model}', 공격 스킬 {attack_count}개, 버프 스킬 {buff_count}개",
        ]
        if reason:
            friendly_reason = format_authority_reason(reason, payload)
            detail_parts.append(f"요청 사유: {friendly_reason}")
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
                    "맵 탭이 최신 상태 스냅샷을 전달하지 않아 캐릭터 상태를 파악할 수 없습니다. (맵 탐지 실행 여부 확인 필요)"
                )
                continue

            if code == "MAP_NOT_WALKING":
                state = map_snapshot.get("player_state") or "알 수 없음"
                descriptions.append(
                    f"캐릭터가 지상(on_terrain), 대기(idle), 점프(jumping) 상태 중 하나가 아닙니다. 현재 상태={state}."
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
                    f"맵 탭 캐릭터가 아직 안정 상태가 아닙니다. 현재 상태={state}{extra_text}."
                )
                continue

            if code == "MAP_PROTECT_ACTIVE":
                if map_protect_seconds is not None:
                    descriptions.append(
                        f"맵 탭 권한 보호 시간 {map_protect_seconds:.1f}초가 아직 끝나지 않아 대기합니다."
                    )
                else:
                    descriptions.append(
                        "맵 탭이 권한을 되찾은 직후 보호 시간이 아직 끝나지 않아 대기합니다."
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
                    f"맵 탭이 우선 처리 작업을 진행하고 있어 권한을 유지해야 합니다{extra_text}."
                )
                continue

            if code == "MAP_NOT_NEAR_FLOOR":
                base_floor = map_meta.get("baseline_floor_int")
                h = map_meta.get("height_from_last_floor_px")
                thr = map_meta.get("near_floor_threshold_px")
                try:
                    base_floor_text = f"{int(base_floor)}층" if isinstance(base_floor, (int, float)) else "알 수 없음"
                except Exception:
                    base_floor_text = "알 수 없음"
                if isinstance(h, (int, float)) and isinstance(thr, (int, float)):
                    descriptions.append(
                        f"착지 전이라 권한 위임을 보류합니다. (마지막 지면층 {base_floor_text}, ΔY={float(h):.1f}px, 임계값={float(thr):.1f}px)"
                    )
                else:
                    descriptions.append(
                        f"착지 전이라 권한 위임을 보류합니다. (마지막 지면층 {base_floor_text})"
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
                    "강제 반납 이후 캐릭터가 다른 층으로 이동하기 전까지 맵 탭 권한을 유지합니다." + reason_text + floor_text + elapsed_text
                )
                continue

            if code == "HUNT_PROTECT_ACTIVE":
                if hunt_protect_seconds is not None:
                    descriptions.append(
                        f"사냥 탭 권한 보호 시간 {hunt_protect_seconds:.1f}초가 지나지 않아 권한을 유지합니다."
                    )
                else:
                    descriptions.append(
                        "사냥 탭이 권한을 획득한 직후 보호 시간 내에 있어 맵 탭 요청을 대기합니다."
                    )
                continue

            if code == "HUNT_SNAPSHOT_OUTDATED":
                timestamp = hunt_snapshot.get("timestamp")
                if isinstance(timestamp, (int, float)):
                    elapsed = now - timestamp
                    descriptions.append(
                        f"사냥 스냅샷이 {elapsed:.1f}초 동안 갱신되지 않아 안전을 위해 대기합니다."
                    )
                else:
                    descriptions.append(
                        "사냥 스냅샷이 최신이 아니어서 대기합니다."
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
                    "사냥 조건을 충족하지 못했습니다. " + ", ".join(shortage_bits) + "."
                )
                continue

            if code == "HUNT_SNAPSHOT_MISSING":
                descriptions.append(
                    "사냥 탭이 최신 몬스터 정보를 전달하지 않아 요청을 보류합니다. (사냥 탐지 실행 여부 확인)"
                )
                continue

            if code == "MAP_ALREADY_OWNER":
                descriptions.append(
                    "이미 맵 탭이 조작 권한을 보유 중입니다."
                )
                continue

            if code == "HOLD_LIMIT_NOT_REACHED":
                descriptions.append(
                    "HOLD_LIMIT_NOT_REACHED: 설정된 권한 유지 시간에 아직 도달하지 않아 사냥 탭으로 넘길 수 없습니다."
                )
                continue

            descriptions.append("추가 정보 없이 대기 중입니다.")

        return descriptions

    def _summarize_authority_pending(
        self,
        failed_codes: Iterable[str],
        detail_payload: dict,
    ) -> str:
        """PENDING 사유를 한 줄 요약용 한국어 태그로 변환한다.

        - 일부 항목은 괄호로 간단한 현재값(상태/초/수치)을 함께 표시한다.
        - 반환 문자열은 ", "로 연결된 요약 항목들이다.
        """
        items: list[str] = []
        map_snapshot = detail_payload.get("map_snapshot") or {}
        hunt_snapshot = detail_payload.get("hunt_snapshot") or {}
        request_meta = detail_payload.get("meta") or {}
        map_state = map_snapshot.get("player_state") or None
        map_meta = map_snapshot.get("metadata") if isinstance(map_snapshot.get("metadata"), dict) else {}
        map_protect_seconds = request_meta.get("map_protect_sec")
        hunt_protect_seconds = request_meta.get("hunt_protect_sec")

        now = time.time()
        for code in failed_codes:
            tag = None
            if code == "MAP_SNAPSHOT_MISSING":
                tag = "맵 스냅샷 없음"
            elif code == "MAP_NOT_WALKING":
                tag = "캐릭터 상태 비정상"
                if isinstance(map_state, str):
                    tag += f" (현재: {map_state})"
            elif code == "MAP_STATE_ACTIVE":
                tag = "맵 탭 동작 중"
                if isinstance(map_state, str):
                    tag += f" (현재: {map_state})"
            elif code == "MAP_PROTECT_ACTIVE":
                tag = "맵 보호 시간"
                try:
                    sec = float(map_protect_seconds)
                    if sec > 0:
                        tag += f" (~{sec:.1f}s)"
                except Exception:
                    pass
            elif code == "MAP_PRIORITY_LOCK":
                tag = "맵 우선 처리"
            elif code == "MAP_NOT_NEAR_FLOOR":
                tag = "착지 전"
                h = map_meta.get("height_from_last_floor_px")
                thr = map_meta.get("near_floor_threshold_px")
                if isinstance(h, (int, float)) and isinstance(thr, (int, float)):
                    try:
                        tag += f" (ΔY={float(h):.0f}/임계 {float(thr):.0f}px)"
                    except Exception:
                        pass
            elif code == "FLOOR_CHANGE_PENDING":
                tag = "층 이동 대기"
                lock_set_at = request_meta.get("floor_lock_set_at")
                if isinstance(lock_set_at, (int, float)):
                    try:
                        elapsed = now - float(lock_set_at)
                        if elapsed >= 0:
                            tag += f" (~{elapsed:.1f}s)"
                    except Exception:
                        pass
            elif code == "HUNT_PROTECT_ACTIVE":
                tag = "사냥 보호 시간"
                try:
                    sec = float(hunt_protect_seconds)
                    if sec > 0:
                        tag += f" (~{sec:.1f}s)"
                except Exception:
                    pass
            elif code == "HUNT_SNAPSHOT_OUTDATED":
                tag = "사냥 스냅샷 오래됨"
                ts = hunt_snapshot.get("timestamp")
                if isinstance(ts, (int, float)):
                    try:
                        elapsed = now - float(ts)
                        if elapsed >= 0:
                            tag += f" (~{elapsed:.1f}s)"
                    except Exception:
                        pass
            elif code == "HUNT_MONSTER_SHORTAGE":
                tag = "몬스터 부족"
                total = hunt_snapshot.get("monster_count")
                total_thr = hunt_snapshot.get("hunt_monster_threshold")
                prim = hunt_snapshot.get("primary_monster_count")
                prim_thr = hunt_snapshot.get("primary_monster_threshold")
                bits: list[str] = []
                if isinstance(total, (int, float)) and isinstance(total_thr, (int, float)) and total < total_thr:
                    bits.append(f"{int(total) if float(total).is_integer() else total}<{int(total_thr) if float(total_thr).is_integer() else total_thr}")
                if isinstance(prim, (int, float)) and isinstance(prim_thr, (int, float)) and prim < prim_thr:
                    bits.append(f"주 {int(prim) if float(prim).is_integer() else prim}<{int(prim_thr) if float(prim_thr).is_integer() else prim_thr}")
                if bits:
                    tag += " (" + ", ".join(bits) + ")"
            elif code == "HUNT_SNAPSHOT_MISSING":
                tag = "사냥 스냅샷 없음"
            elif code == "MAP_ALREADY_OWNER":
                tag = "맵 탭 보유 중"
            elif code == "HOLD_LIMIT_NOT_REACHED":
                tag = "보유 시간 미달"

            if tag:
                items.append(tag)

        return ", ".join(items)

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
        # 탐지 비활성 시 조건 폴링을 수행하지 않음
        if not self._is_detection_active():
            return
        self._poll_hunt_conditions()

    def _handle_request_timeout(self) -> None:
        self._request_pending = False
        # 탐지 비활성 또는 사냥 권한 아님: 재평가 생략(불필요한 재요청/명령 방지)
        if not self._is_detection_active() or self.current_authority != "hunt":
            return
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
                summary_text = self._summarize_authority_pending(failed, details)
                self.append_log(
                    f"사냥 권한 요청 대기: {summary_text}",
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
        mode_on = bool(getattr(self, 'facing_range_checkbox', None) and self.facing_range_checkbox.isChecked())
        enemy_front = int(self.enemy_front_spinbox.value()) if hasattr(self, 'enemy_front_spinbox') else int(self.enemy_range_spinbox.value())
        enemy_back = int(self.enemy_back_spinbox.value()) if hasattr(self, 'enemy_back_spinbox') else int(self.enemy_range_spinbox.value())
        primary_front = int(self.primary_front_spinbox.value()) if hasattr(self, 'primary_front_spinbox') else int(self.primary_skill_range_spinbox.value())
        primary_back = int(self.primary_back_spinbox.value()) if hasattr(self, 'primary_back_spinbox') else int(self.primary_skill_range_spinbox.value())
        effective_enemy_range = self.enemy_range_spinbox.value()
        effective_primary_range = self.primary_skill_range_spinbox.value()
        if mode_on:
            try:
                effective_enemy_range = max(enemy_front, enemy_back)
                effective_primary_range = max(primary_front, primary_back)
            except Exception:
                pass
        # HP(%)를 메타에 포함해 사유 포맷팅에 활용
        hp_val = None
        try:
            hp_val = float(self._status_display_values.get('hp'))
        except Exception:
            hp_val = None
        return {
            "hunt_monster_threshold": hunt_threshold,
            "primary_monster_threshold": primary_threshold,
            "monster_threshold": hunt_threshold,
            "range_px": effective_enemy_range,
            "y_band_height": self.y_band_height_spinbox.value(),
            "y_offset": self.y_band_offset_spinbox.value(),
            "primary_skill_range": effective_primary_range,
            "range_mode": "facing" if mode_on else "symmetric",
            "range_front_px": enemy_front,
            "range_back_px": enemy_back,
            "primary_front_px": primary_front,
            "primary_back_px": primary_back,
            "model": self._get_active_model_name() or "-",
            "attack_skill_count": len(self.attack_skills),
            "buff_skill_count": len(self.buff_skills),
            "latest_monster_count": self.latest_monster_count,
            "latest_primary_monster_count": self.latest_primary_monster_count,
            "map_protect_sec": float(self.map_protect_spinbox.value()) if hasattr(self, 'map_protect_spinbox') else float(self.map_protect_seconds),
            "hunt_protect_sec": float(self.hunt_protect_spinbox.value()) if hasattr(self, 'hunt_protect_spinbox') else float(self.hunt_protect_seconds),
            "hp_percent": hp_val,
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

        # [긴급 경로] 모든 키 떼기는 즉시 라즈베리 측까지 반영되도록 전용 API를 우선 사용
        try:
            if normalized == '모든 키 떼기' and getattr(self, '_auto_control_tab', None):
                act = getattr(self._auto_control_tab, 'api_emergency_stop_all', None)
                if callable(act):
                    reason_text = str(reason) if isinstance(reason, str) else 'hunt:release_all'
                    act(reason=reason_text)
                    # 중복 전송 방지를 위해 일반 경로(control_command_issued.emit)는 생략
                    try:
                        if reason_text:
                            self._append_control_log(f"모든 키 떼기 -원인: {reason_text}")
                        else:
                            self._append_control_log("모든 키 떼기")
                    except Exception:
                        pass
                    return
        except Exception:
            # 실패 시 기존 경로로 폴백
            pass

        # [NEW] 금지 플로우 활성 중에는 '모든 키 떼기'와 금지 플로우 전용 명령만 허용
        try:
            if getattr(self, '_forbidden_active', False):
                reason_str = str(reason) if isinstance(reason, str) else ''
                if normalized != '모든 키 떼기' and reason_str != 'forbidden_monster':
                    return
        except Exception:
            pass

        reason_str = str(reason) if isinstance(reason, str) else ""
        is_status_command = reason_str.startswith('status:')
        is_urgent_command = reason_str.startswith('urgent:')
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
        # [추가] 금지몬 프로필은 쿨다운 우회 허용
        if reason_str == 'forbidden_monster':
            allow_during_cooldown = True

        # HP 긴급모드 보호: 아래 항목들은 허용
        # - HP 상태 명령(status:hp)
        # - 초긴급(urgent:*)
        # - '모든 키 떼기', '사다리 멈춤복구'
        # - 금지몬스터 전용 명령(reason='forbidden_monster')
        if getattr(self, '_hp_emergency_active', False):
            # 허용 조건 중 하나라도 만족하지 않으면 차단
            if not (
                (is_status_command and status_resource == 'hp')
                or is_urgent_command
                or normalized in ('모든 키 떼기', '사다리 멈춤복구')
                or reason_str == 'forbidden_monster'
            ):
                return

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
        # HP 회복 시도 후 다음 탐지 주기에서 회복여부 판단
        if is_status_command and status_resource == 'hp':
            self._hp_recovery_pending = True
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

    def attach_auto_control_tab(self, auto_control_tab) -> None:
        """자동 제어 탭 참조를 보관해 긴급 정지 경로에 사용한다."""
        self._auto_control_tab = auto_control_tab

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
        # 설정에서 HP 긴급모드를 비활성화하면 즉시 긴급 보호를 해제하여 차단 상태를 풀어준다.
        try:
            hp_cfg = getattr(config, 'hp', None)
            if hp_cfg is not None and not getattr(hp_cfg, 'emergency_enabled', False):
                if getattr(self, '_hp_emergency_active', False):
                    self._hp_emergency_active = False
                    self._hp_emergency_started_at = 0.0
                    self._hp_emergency_telegram_sent = False
                    self.append_log("[HP] 긴급 회복 보호 해제 [설정 해제]", 'info')
        except Exception:
            pass
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
                    # HP 회복여부 판단 및 긴급모드 제어
                    try:
                        threshold = getattr(hp_cfg, 'recovery_threshold', None)
                        if isinstance(threshold, int):
                            current = float(hp_value)
                            # 임계값을 퍼센트로 환산(100 초과 → 절대 HP 입력)
                            thr_percent: float | None
                            if threshold > 100:
                                maximum = getattr(hp_cfg, 'maximum_value', None)
                                try:
                                    max_val = float(maximum) if maximum is not None else 0.0
                                except (TypeError, ValueError):
                                    max_val = 0.0
                                if max_val <= 0.0:
                                    thr_percent = None
                                    if not hasattr(self, '_hp_abs_thr_warned') or not getattr(self, '_hp_abs_thr_warned'):
                                        try:
                                            self.append_log('[HP] 최대체력이 설정되지 않아 절대 HP 임계값 회복검사를 건너뜁니다.', 'warn')
                                        except Exception:
                                            pass
                                        try:
                                            setattr(self, '_hp_abs_thr_warned', True)
                                        except Exception:
                                            pass
                                else:
                                    thr_percent = float(threshold) * 100.0 / max_val
                            else:
                                thr_percent = float(threshold)

                            # 회복여부 판단은 HP 명령 직후 다음 주기 한 번만
                            if self._hp_recovery_pending:
                                self._hp_recovery_pending = False
                                if thr_percent is not None and current >= float(thr_percent):
                                    # 성공
                                    self._hp_recovery_fail_streak = 0
                                    if self._hp_emergency_active:
                                        self._hp_emergency_active = False
                                        self._hp_emergency_started_at = 0.0
                                        self._hp_emergency_telegram_sent = False
                                        self.append_log(f"[HP] 긴급 회복 보호 해제 [{int(round(current))}%]", 'info')
                                elif thr_percent is not None:
                                    # 실패
                                    self._hp_recovery_fail_streak = int(self._hp_recovery_fail_streak) + 1
                                    if self._hp_emergency_active:
                                        self.append_log(
                                            f"HP회복검사 통과 실패 : 기준치 [{int(round(thr_percent))}%] > 현재수치 [{int(round(current))}%]",
                                            'warn',
                                        )
                                        # 긴급 모드에서는 즉시 HP 회복 명령 재발행
                                        cmd = getattr(hp_cfg, 'command_profile', None)
                                        if isinstance(cmd, str) and cmd.strip():
                                            self._issue_status_command('hp', cmd.strip(), current)
                                    if (
                                        thr_percent is not None
                                        and getattr(hp_cfg, 'emergency_enabled', False)
                                        and not self._hp_emergency_active
                                        and self._hp_recovery_fail_streak >= int(getattr(hp_cfg, 'emergency_trigger_failures', 3) or 3)
                                    ):
                                        # [변경] 사다리 등반 중에는 긴급모드 진입 금지
                                        if not self._is_on_ladder():
                                            self._enter_hp_emergency_mode()
                        # [NEW] 긴급모드 HP 임계값(%)에 의한 즉시 진입 (OR 조건)
                        try:
                            em_thr = getattr(hp_cfg, 'emergency_trigger_hp_percent', None)
                            if (
                                getattr(hp_cfg, 'emergency_enabled', False)
                                and not self._hp_emergency_active
                                and isinstance(em_thr, int)
                            ):
                                current2 = float(hp_value)
                                if current2 <= float(em_thr):
                                    # [변경] 사다리 등반 중에는 긴급모드 진입 금지
                                    if not self._is_on_ladder():
                                        self.append_log(
                                            f"[HP] 긴급모드 진입: HP 임계값({int(em_thr)}%) 이하 감지 (현재 {int(round(current2))}%)",
                                            'warn',
                                        )
                                        self._enter_hp_emergency_mode()
                                    else:
                                        self.append_log(
                                            f"[HP] 긴급모드 조건 충족(HP {int(round(current2))}%)이나 사다리 상태로 진입 보류",
                                            'info',
                                        )
                        except Exception:
                            pass
                        # 긴급모드 시간 초과 검사
                        if self._hp_emergency_active:
                            max_dur = float(getattr(hp_cfg, 'emergency_max_duration_sec', 10.0) or 10.0)
                            if max_dur >= 1.0 and (time.time() - self._hp_emergency_started_at) >= max_dur and not self._hp_emergency_telegram_sent:
                                if bool(getattr(hp_cfg, 'emergency_timeout_telegram', False)):
                                    # 맵탭을 통해 텔레그램 전송 시도
                                    map_tab = getattr(self, 'map_tab', None)
                                    message = "[HP] 긴급 회복 모드 시간이 초과되었습니다. (자동 전송)"
                                    sent = False
                                    if map_tab and hasattr(map_tab, 'send_emergency_telegram'):
                                        try:
                                            map_tab.send_emergency_telegram(message)
                                            sent = True
                                        except Exception:
                                            sent = False
                                    if not sent:
                                        self.append_log("텔레그램 전송 실패 또는 비활성화 상태입니다.", 'warn')
                                else:
                                    self.append_log("[HP] 긴급 회복 모드 시간이 초과되었습니다.", 'warn')
                                self._hp_emergency_telegram_sent = True
                                # 시간 초과 시 긴급 보호 해제
                                self._hp_emergency_active = False
                                self._hp_emergency_started_at = 0.0
                                self.append_log("[HP] 긴급 회복 보호 해제 [시간 초과]", 'info')
                        # [NEW] HP 저체력 텔레그램/초긴급 명령 처리
                        try:
                            low_hp_enabled = bool(getattr(hp_cfg, 'low_hp_telegram_alert', False))
                            current = float(hp_value)
                            # 임계값: 설정값 없으면 3%
                            try:
                                threshold = float(getattr(hp_cfg, 'urgent_threshold', None) or 3.0)
                            except Exception:
                                threshold = 3.0
                            if low_hp_enabled:
                                if current < threshold and not self._low_hp_alert_active:
                                    msg = f"[HP] 경고: HP {int(threshold)}% 미만 감지 (현재 {int(round(current))}%)"
                                    sent = False
                                    map_tab = getattr(self, 'map_tab', None)
                                    if map_tab and hasattr(map_tab, 'send_emergency_telegram'):
                                        try:
                                            map_tab.send_emergency_telegram(msg)
                                            sent = True
                                        except Exception:
                                            sent = False
                                    if not sent:
                                        self.append_log("텔레그램 전송 실패 또는 비활성화 상태입니다.", 'warn')
                                    self._low_hp_alert_active = True
                                elif current >= threshold and self._low_hp_alert_active:
                                    msg = f"[HP] 회복: HP {int(threshold)}% 이상으로 회복됨 (현재 {int(round(current))}%)"
                                    sent = False
                                    map_tab = getattr(self, 'map_tab', None)
                                    if map_tab and hasattr(map_tab, 'send_emergency_telegram'):
                                        try:
                                            map_tab.send_emergency_telegram(msg)
                                            sent = True
                                        except Exception:
                                            sent = False
                                    if not sent:
                                        self.append_log("텔레그램 전송 실패 또는 비활성화 상태입니다.", 'warn')
                                    self._low_hp_alert_active = False
                            # 초긴급 명령프로필 실행 (선택된 경우: 매 HP 판단 주기마다 재트리거)
                            urgent_cmd = getattr(hp_cfg, 'urgent_command_profile', None)
                            if isinstance(urgent_cmd, str) and urgent_cmd.strip():
                                interval = 1.0
                                try:
                                    interval = float(getattr(hp_cfg, 'interval_sec', 1.0) or 1.0)
                                except Exception:
                                    interval = 1.0
                                last_ts = float(getattr(self, '_last_hp_urgent_ts', 0.0) or 0.0)
                                if current < threshold:
                                    if (timestamp - last_ts) >= max(0.1, interval * 0.9):
                                        self._emit_control_command(urgent_cmd.strip(), reason=f"urgent:hp:{int(round(current))}")
                                        self.append_log(f"[HP] 초긴급 명령 실행: '{urgent_cmd.strip()}'", 'warn')
                                        try:
                                            setattr(self, '_last_hp_urgent_ts', timestamp)
                                        except Exception:
                                            pass
                                else:
                                    try:
                                        setattr(self, '_last_hp_urgent_ts', 0.0)
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                    except Exception:
                        pass
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
                # [EXP 정체 감지] 최근 9회 연속 완전 동일하면 문제로 간주
                try:
                    records = getattr(self, '_status_exp_records', []) or []
                    if len(records) >= 9:
                        window = records[-9:]
                        try:
                            amount_set = {int(r.get('amount')) for r in window}
                            percent_set = {float(r.get('percent')) for r in window}
                        except Exception:
                            amount_set = set()
                            percent_set = set()
                        same_amount = (len(amount_set) == 1)
                        same_percent = (len(percent_set) == 1)
                        if same_amount and same_percent:
                            # HP 확인: 10% 미만이면(또는 읽기 실패) 사망 판단 → 프로세스 종료
                            hp_percent: Optional[float] = None
                            hp_info = payload.get('hp') if isinstance(payload, dict) else None
                            if isinstance(hp_info, dict) and isinstance(hp_info.get('percentage'), (int, float)):
                                hp_percent = float(hp_info.get('percentage'))
                            if hp_percent is None:
                                hp_last = self._status_display_values.get('hp') if hasattr(self, '_status_display_values') else None
                                if isinstance(hp_last, (int, float)):
                                    hp_percent = float(hp_last)

                            if hp_percent is None or hp_percent < 10.0:
                                # 사망으로 판단 → 즉시 종료 + 텔레그램 알림 + (선택) 절전
                                reason = "EXP 정체 + HP 읽기 실패" if hp_percent is None else f"EXP 정체 + HP {int(round(hp_percent))}%"
                                killed = self._kill_mapleland_process_immediately(reason)
                                if killed:
                                    try:
                                        self._notify_telegram(f"[자동조치] {reason} → 게임 프로세스 종료 처리")
                                    except Exception:
                                        pass
                            else:
                                # 로직 문제로 간주 → ESC 효과로 정지 후 2초 뒤 재시작
                                self._apply_esc_and_restart_for_exp()
                except Exception:
                    pass
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
        # [정책 변경] 대기모드에서는 일반 HP 회복을 절대 실행하지 않음
        # - 대기모드 전용 HP 회복만 허용(맵 탭에서 처리)
        # - 긴급/초긴급 로직은 아래 별도 경로에서 계속 판단
        if resource == 'hp' and bool(getattr(self, 'shutdown_other_player_wait_active', False)):
            return
        threshold = getattr(cfg, 'recovery_threshold', None)
        if threshold is None:
            return
        command_name = getattr(cfg, 'command_profile', None) or ''
        command_name = command_name.strip()
        if not command_name:
            return
        # [변경] HP 임계값이 100 초과면 절대 HP로 간주 → 퍼센트 환산
        thr_percent: float
        if resource == 'hp' and isinstance(threshold, int) and threshold > 100:
            maximum = getattr(cfg, 'maximum_value', None)
            try:
                max_val = float(maximum) if maximum is not None else 0.0
            except (TypeError, ValueError):
                max_val = 0.0
            if max_val <= 0.0:
                # A안: 최대체력 미설정 시 무시 + 1회 경고
                if not hasattr(self, '_hp_abs_thr_warned') or not getattr(self, '_hp_abs_thr_warned'):
                    try:
                        self.append_log('[HP] 최대체력이 설정되지 않아 절대 HP 임계값을 적용할 수 없습니다. (회복 트리거 건너뜀)', 'warn')
                    except Exception:
                        pass
                    try:
                        setattr(self, '_hp_abs_thr_warned', True)
                    except Exception:
                        pass
                return
            thr_percent = float(threshold) * 100.0 / max_val
        else:
            try:
                thr_percent = float(threshold)
            except (TypeError, ValueError):
                return

        if percentage > thr_percent:
            return
        last_ts = self._status_last_command_ts.get(resource, 0.0)
        interval = max(0.1, getattr(cfg, 'interval_sec', 1.0))
        if (timestamp - last_ts) < interval:
            return

        if resource == 'hp':
            if self._hp_guard_active:
                return
            if percentage < 20.0:
                self._ensure_mapleland_foreground()
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

    def _ensure_mapleland_foreground(self) -> None:
        """Mapleland 창을 전면으로 가져옵니다."""
        try:
            candidate_windows = gw.getWindowsWithTitle('Mapleland')
        except Exception:
            return

    def _is_on_ladder(self) -> bool:
        """맵 탭의 player_state를 확인하여 사다리 관련 상태(climbing_up/down, on_ladder_idle)인지 판별.

        맵탭이 없거나 상태를 알 수 없으면 False로 간주한다.
        """
        try:
            map_tab = getattr(self, 'map_tab', None)
            if not map_tab:
                return False
            state = getattr(map_tab, 'player_state', None)
            return str(state) in {'climbing_up', 'climbing_down', 'on_ladder_idle'}
        except Exception:
            return False

        target_window = None
        for window in candidate_windows:
            if not window:
                continue
            try:
                title = (getattr(window, 'title', '') or '').strip()
            except Exception:
                continue
            if 'mapleland' in title.lower():
                target_window = window
                break

        if target_window is None:
            return

        try:
            if getattr(target_window, 'isMinimized', False):
                target_window.restore()
            if not getattr(target_window, 'isActive', False):
                target_window.activate()
            if not getattr(target_window, 'isActive', False):
                target_window.minimize()
                target_window.restore()
        except Exception:
            return

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

    def _enter_hp_emergency_mode(self) -> None:
        if self._hp_emergency_active:
            return
        self._hp_emergency_active = True
        self._hp_emergency_started_at = time.time()
        self._hp_emergency_telegram_sent = False
        # 즉시 모든 키 해제 (원인 로그 포함)
        self._issue_all_keys_release(reason="HP회복 긴급모드 진입")
        # 최초 진입 로그
        self.append_log("[WARN] [HP] 긴급 회복 모드에 진입했습니다. 다른 명령을 차단합니다.", 'warn')
        # 즉시 HP 회복 명령 1회 발행하여 다음 주기에 회복판단
        try:
            hp_cfg = getattr(self, '_status_config', None).hp if hasattr(self, '_status_config') else None
            cmd = getattr(hp_cfg, 'command_profile', None) if hp_cfg else None
            if isinstance(cmd, str) and cmd.strip():
                self._issue_status_command('hp', cmd.strip(), None)
        except Exception:
            pass

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
        exp_extra = ''
        if self._status_exp_records:
            latest = self._status_exp_records[-1]
            amount = latest.get('amount')
            percent = latest.get('percent')
            if amount is not None and percent is not None:
                exp_text = f"{amount} / {percent:.2f}%"
                # 실시간 EXP 통계 추가
                stats = self._compute_exp_live_stats() if exp_enabled else None
                if isinstance(stats, dict):
                    def _fmt_percent(val: float) -> str:
                        try:
                            text = f"{float(val):.2f}"
                            if '.' in text:
                                text = text.rstrip('0').rstrip('.')
                            return text
                        except Exception:
                            return '--'

                    per_min_amt = stats.get('per_minute_amount')
                    per_min_pct = stats.get('per_minute_percent')
                    total_pct = stats.get('total_percent_gain')
                    eta_sec = stats.get('eta_seconds')

                    per_min_text = (
                        f"{int(per_min_amt)} / {_fmt_percent(float(per_min_pct))}%"
                        if per_min_amt is not None and per_min_pct is not None
                        else "-- / --"
                    )
                    total_pct_text = _fmt_percent(float(total_pct)) if total_pct is not None else '--'
                    eta_text = self._format_duration_text(float(eta_sec)) if isinstance(eta_sec, (int, float)) else '--'
                    exp_extra = f" | 분당: {per_min_text} | 누적: +{total_pct_text}% | 레벨업: {eta_text}"
        elif exp_enabled:
            exp_text = '-- / --'
        else:
            exp_text = '비활성'
        self._status_summary_cache = {
            'hp': f"HP: {hp_text}",
            'mp': f"MP: {mp_text}",
            'exp': f"EXP: {exp_text}{exp_extra}",
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

    def _compute_exp_live_stats(self) -> Optional[dict]:
        """현재까지 수집된 EXP 스냅샷으로 실시간 통계를 계산합니다.

        반환값 예시:
            {
                'total_amount_gain': int,
                'total_percent_gain': float,
                'per_minute_amount': int,
                'per_minute_percent': float,
                'eta_seconds': Optional[float],
                'latest_percent': float,
            }

        데이터 부족 시 None을 반환합니다.
        """
        try:
            records = [
                {
                    'timestamp': float(e.get('timestamp', time.time())),
                    'amount': int(str(e.get('amount'))),
                    'percent': float(e.get('percent')),
                }
                for e in (self._status_exp_records or [])
                if isinstance(e, dict) and e.get('amount') is not None and e.get('percent') is not None
            ]
        except (TypeError, ValueError):
            records = []

        if not records:
            return None

        records.sort(key=lambda item: item.get('timestamp', 0.0))

        start_snapshot = self._status_exp_start_snapshot
        start_amount: Optional[int] = None
        start_percent: Optional[float] = None
        start_timestamp: float = records[0].get('timestamp', time.time())
        if isinstance(start_snapshot, dict):
            try:
                start_amount = max(0, int(str(start_snapshot.get('amount'))))
                start_percent = max(0.0, float(start_snapshot.get('percent')))
                start_timestamp = float(start_snapshot.get('timestamp', start_timestamp))
            except (TypeError, ValueError):
                start_amount = None
                start_percent = None

        if start_amount is None or start_percent is None:
            start_amount = records[0]['amount']
            start_percent = records[0]['percent']
        else:
            first = records[0]
            if (
                start_amount != first['amount']
                or abs(start_percent - first['percent']) > 1e-6
            ):
                records.insert(0, {
                    'timestamp': start_timestamp,
                    'amount': start_amount,
                    'percent': start_percent,
                })
            else:
                first['timestamp'] = min(first.get('timestamp', start_timestamp), start_timestamp)

        # 누적 증가량 계산 (레벨업 감지 포함)
        LEVELUP_AMOUNT_DROP_MIN = 10
        LEVELUP_PERCENT_DROP_MIN = 0.2
        LEVELUP_PERCENT_RESET_THRESHOLD = 5.0
        LEVELUP_AMOUNT_RATIO_THRESHOLD = 0.2
        LEVELUP_PERCENT_RATIO_THRESHOLD = 0.5
        POSITIVE_PERCENT_EPS = 0.001

        total_amount_gain = 0
        total_percent_gain = 0.0
        prev_amount = records[0]['amount']
        prev_percent = records[0]['percent']

        for entry in records[1:]:
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
        total_percent_gain = max(0.0, float(total_percent_gain))

        # 분당 계산
        now_ts = time.time()
        duration_start_ts = self._status_detection_start_ts or records[0].get('timestamp', now_ts)
        duration = max(0.0, float(now_ts) - float(duration_start_ts))
        minutes = max(1.0 / 60.0, duration / 60.0)
        per_minute_amount = int(total_amount_gain / minutes) if minutes > 0 else total_amount_gain
        per_minute_percent = total_percent_gain / minutes if minutes > 0 else total_percent_gain

        # ETA 계산 (현재 레벨에서 100%까지)
        latest_percent = float(records[-1]['percent'])
        if per_minute_percent > POSITIVE_PERCENT_EPS and latest_percent < 100.0:
            left_percent = max(0.0, 100.0 - latest_percent)
            eta_minutes = left_percent / per_minute_percent
            eta_seconds: Optional[float] = max(0.0, eta_minutes * 60.0)
        else:
            eta_seconds = None

        return {
            'total_amount_gain': total_amount_gain,
            'total_percent_gain': total_percent_gain,
            'per_minute_amount': per_minute_amount,
            'per_minute_percent': per_minute_percent,
            'eta_seconds': eta_seconds,
            'latest_percent': latest_percent,
        }

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
        frame_width = 0
        frame_height = 0
        if isinstance(perf_data, dict):
            try:
                frame_width = int(float(perf_data.get('frame_width', 0.0) or 0.0))
                frame_height = int(float(perf_data.get('frame_height', 0.0) or 0.0))
            except (TypeError, ValueError):
                frame_width = frame_height = 0
        if frame_width > 0 and frame_height > 0:
            self._latest_frame_size = (frame_width, frame_height)

        self._expire_nameplate_dead_zones(received_ts)
        self._expire_forbidden_visuals(received_ts)
        # [NEW] 금지몬스터 감지 → 대기모드 트리거(쿨다운 및 플래그 검사 포함)
        try:
            self._maybe_trigger_forbidden_flow(monsters_data, received_ts)
        except Exception:
            pass
        # [NEW] 금지몬스터 감지 히스토리 기록(탐지신뢰도 영역에 표시)
        try:
            self._append_forbidden_detection_log(monsters_data, received_ts)
        except Exception:
            pass
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
                    # [NEW] 미니맵 보정 준비: 최초 닉네임 박스 검출 시 템플릿 고정
                    try:
                        self._minimap_x_primed = True
                        self._minimap_char_template = {
                            'y': float(nickname_box.y),
                            'width': float(nickname_box.width),
                            'height': float(nickname_box.height),
                        }
                        self._minimap_char_overlay_box = None
                    except Exception:
                        pass
                    # [NEW] 온라인 캘리브레이션 샘플 업데이트(닉네임 검출 시만)
                    try:
                        # 기능 토글/연동 상태 확인
                        try:
                            from map_hunt_calibration import is_enabled as _calib_enabled
                            if not bool(_calib_enabled()):
                                raise RuntimeError('calibration disabled')
                        except Exception:
                            raise RuntimeError('calibration disabled')

                        if not bool(getattr(self, 'map_link_enabled', False)):
                            raise RuntimeError('map link disabled')

                        # 맵 전역 X
                        map_tab = getattr(self, 'map_tab', None)
                        if not map_tab or not hasattr(map_tab, 'api_export_minimap_view_state'):
                            raise RuntimeError('no map tab')
                        state = map_tab.api_export_minimap_view_state()
                        pos = state.get('final_player_pos') if isinstance(state, dict) else None
                        if pos is None:
                            raise RuntimeError('no minimap pos')
                        if hasattr(pos, 'x'):
                            map_x = float(pos.x())
                        elif isinstance(pos, dict) and 'x' in pos:
                            map_x = float(pos['x'])
                        else:
                            raise RuntimeError('no minimap x')

                        # ROI/프레임폭/관측 중심X
                        roi = None
                        try:
                            roi = self.api_get_active_capture_region()
                        except Exception:
                            roi = None
                        frame_w = None
                        try:
                            info = self.api_get_current_character_position()
                            if isinstance(info, dict):
                                frame_w = info.get('frame_width')
                        except Exception:
                            frame_w = None
                        x_obs = float(nickname_box.x) + float(nickname_box.width) / 2.0

                        # 업데이트 호출
                        try:
                            from minimap_online_calibrator import update as _calib_update
                            saved_now = _calib_update(getattr(map_tab, 'active_profile_name', None) or '', roi, map_x, x_obs, frame_w)
                            if saved_now:
                                try:
                                    from map_hunt_calibration import find_calibration as _find_calib
                                    profile_name = getattr(map_tab, 'active_profile_name', None)
                                    calib = _find_calib(profile_name or '', roi)
                                    if calib:
                                        a_logged, b_logged = calib
                                        self.append_log(f"[캘리브레이션] 자동 저장 완료: a={a_logged:.5f}, b={b_logged:.2f}", 'info')
                                    else:
                                        self.append_log("[캘리브레이션] 자동 저장 완료", 'info')
                                except Exception:
                                    self.append_log("[캘리브레이션] 자동 저장 완료", 'info')
                        except Exception:
                            pass
                    except Exception:
                        # 조건 미충족/실패 시 조용히 무시
                        pass
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
                    dir_center_x: Optional[float] = None
                    if getattr(self, "_direction_active", False) and self._latest_direction_match:
                        last_seen = float(getattr(self, "_direction_last_seen_ts", 0.0))
                        if now - last_seen <= self.DIRECTION_TIMEOUT_SEC:
                            try:
                                mx = float(self._latest_direction_match.get("x", 0.0))
                                mw = float(self._latest_direction_match.get("width", 0.0))
                                dir_center_x = mx + mw / 2.0
                            except Exception:
                                dir_center_x = None
                    if dir_center_x is not None and characters:
                        fw = 0.0
                        try:
                            perf_data = payload.get("perf") or {}
                            fw = float(perf_data.get("frame_width", 0.0))
                        except Exception:
                            fw = 0.0
                        for idx, box in enumerate(characters):
                            width = float(box.width)
                            new_x = dir_center_x - width / 2.0
                            if fw > 1.0 and width > 0.0:
                                new_x = max(0.0, min(new_x, fw - width))
                            box.x = float(new_x)
                            if idx < len(characters_data) and isinstance(characters_data[idx], dict):
                                characters_data[idx]['x'] = float(new_x)
                    # [NEW] 닉네임 미검/캐시 사용 시, 미니맵 X 보정이 가능하면 추가 적용
                    try:
                        perf = payload.get("perf") or {}
                    except Exception:
                        perf = {}
                    self._maybe_apply_minimap_x_correction(characters, characters_data, perf)
                    fallback_used = True
                else:
                    # [NEW] 캐시 만료 이후에도 미니맵 보정으로 synthetic 캐릭터 박스를 생성 시도
                    try:
                        perf = payload.get("perf") or {}
                    except Exception:
                        perf = {}
                    # synthetic 박스를 생성하고 characters에 반영
                    if self._maybe_create_minimap_character(perf, characters_data):
                        try:
                            box = self._last_character_boxes[0]
                            characters = [DetectionBox(**vars(box))]
                        except Exception:
                            pass
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
                apply_facing = bool(getattr(self, '_nameplate_apply_facing', False))
                passes_direction = True
                if apply_facing and facing and char_center_x is not None:
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

    def _maybe_apply_minimap_x_correction(self, characters: List[DetectionBox], characters_data: Optional[list], perf_data: dict) -> None:
        """학습탭에서 활성화한 미니맵 X 보정이 가능하면 캐릭터 X를 보정.
        - 전제: 현재 프레임이 닉네임 미검/캐시 사용 상황(강제는 아님)
        - 조건: 기능 enabled + 연동 On + 맵탭/ROI/프로필/보정값 존재
        """
        if not characters:
            return
        if not getattr(self, 'map_link_enabled', False):
            return
        map_tab = getattr(self, 'map_tab', None)
        if not map_tab:
            return
        try:
            from map_hunt_calibration import is_enabled, find_calibration
        except Exception:
            return
        try:
            if not is_enabled():
                return
        except Exception:
            return
        # 맵 전역 X
        try:
            state = map_tab.api_export_minimap_view_state() if hasattr(map_tab, 'api_export_minimap_view_state') else None
            pos = state.get('final_player_pos') if isinstance(state, dict) else None
            if pos is None:
                return
            if hasattr(pos, 'x'):
                map_x = float(pos.x())
            elif isinstance(pos, dict) and 'x' in pos:
                map_x = float(pos['x'])
            else:
                return
        except Exception:
            return
        # ROI/프로필/보정값
        try:
            profile = getattr(map_tab, 'active_profile_name', None)
        except Exception:
            profile = None
        if not profile:
            return
        try:
            roi = self.api_get_active_capture_region()
        except Exception:
            roi = None
        calib = None
        # [NEW] 온라인 추정 우선 사용, 없으면 저장값 사용
        try:
            from minimap_online_calibrator import get as _calib_get
            online = _calib_get(profile, roi)
        except Exception:
            online = None
        if online is not None:
            a, b = online
        else:
            try:
                calib = find_calibration(profile, roi)
            except Exception:
                calib = None
            if not calib:
                return
            a, b = calib
        try:
            fw = float(perf_data.get('frame_width', 0.0)) if isinstance(perf_data, dict) else 0.0
        except Exception:
            fw = 0.0
        center_x = float(a) * float(map_x) + float(b)
        for idx, box in enumerate(characters):
            try:
                width = float(box.width)
                new_x = center_x - width / 2.0
                if fw > 1.0 and width > 0.0:
                    new_x = max(0.0, min(new_x, fw - width))
                box.x = float(new_x)
                if characters_data and idx < len(characters_data) and isinstance(characters_data[idx], dict):
                    characters_data[idx]['x'] = float(new_x)
            except Exception:
                continue
        self._minimap_x_fallback_used_ts = time.time()
        # 오버레이 박스도 최신 교정 값으로 갱신(그리기는 체크박스가 제어)
        try:
            if characters:
                b0 = characters[0]
                self._minimap_char_overlay_box = {
                    'x': float(b0.x), 'y': float(b0.y), 'width': float(b0.width), 'height': float(b0.height)
                }
        except Exception:
            pass

    def _maybe_create_minimap_character(self, perf_data: dict, characters_data: Optional[list]) -> bool:
        """닉네임 미검/캐시 만료 이후에도 미니맵 보정으로 synthetic 캐릭터 박스를 생성.
        - 최초 1회 닉네임 박스 검출로 템플릿(y,width,height) 확보 후에만 동작.
        - 성공 시 characters_data에도 항목을 추가할 수 있다.
        """
        try:
            from map_hunt_calibration import is_enabled, find_calibration
        except Exception:
            return False
        if not getattr(self, '_minimap_x_primed', False):
            return False
        if not getattr(self, 'map_link_enabled', False):
            return False
        template = getattr(self, '_minimap_char_template', None)
        if not isinstance(template, dict):
            return False
        map_tab = getattr(self, 'map_tab', None)
        if not map_tab or not hasattr(map_tab, 'api_export_minimap_view_state'):
            return False
        try:
            if not is_enabled():
                return False
        except Exception:
            return False
        # 맵 전역 X
        try:
            state = map_tab.api_export_minimap_view_state()
            pos = state.get('final_player_pos') if isinstance(state, dict) else None
            if pos is None:
                return False
            if hasattr(pos, 'x'):
                map_x = float(pos.x())
            elif isinstance(pos, dict) and 'x' in pos:
                map_x = float(pos['x'])
            else:
                return False
        except Exception:
            return False
        # 보정 파라미터
        try:
            profile = getattr(map_tab, 'active_profile_name', None)
        except Exception:
            profile = None
        try:
            roi = self.api_get_active_capture_region()
        except Exception:
            roi = None
        calib = None
        # [NEW] 온라인 추정 우선 사용, 없으면 저장값 사용
        try:
            from minimap_online_calibrator import get as _calib_get
            online = _calib_get(profile, roi)
        except Exception:
            online = None
        if online is not None:
            a, b = online
        else:
            try:
                calib = find_calibration(profile, roi)
            except Exception:
                calib = None
            if not calib:
                return False
            a, b = calib
        try:
            fw = float(perf_data.get('frame_width', 0.0)) if isinstance(perf_data, dict) else 0.0
        except Exception:
            fw = 0.0
        # 템플릿으로 높이/폭/Y 고정, X만 미니맵 보정
        width = float(template.get('width', 0.0) or 0.0)
        height = float(template.get('height', 0.0) or 0.0)
        y = float(template.get('y', 0.0) or 0.0)
        if width <= 0.0 or height <= 0.0:
            return False
        center_x = float(a) * float(map_x) + float(b)
        new_x = center_x - width / 2.0
        if fw > 1.0:
            new_x = max(0.0, min(new_x, fw - width))
        # synthetic 박스 생성
        try:
            box = DetectionBox(x=float(new_x), y=float(y), width=float(width), height=float(height), score=0.0, label='minimap')
        except Exception:
            return False
        # characters_data에도 표시용 항목 추가
        if isinstance(characters_data, list):
            try:
                characters_data.append({'x': box.x, 'y': box.y, 'width': box.width, 'height': box.height, 'score': 0.0, 'class_name': '미니맵'})
            except Exception:
                pass
        # 오버레이 박스 저장(체크박스가 꺼져 있으면 그리지는 않음)
        self._minimap_char_overlay_box = {'x': box.x, 'y': box.y, 'width': box.width, 'height': box.height}
        # 캐시 갱신: synthetic도 최근 본 것으로 처리(지속 추적 목적)
        try:
            self._last_character_boxes = [DetectionBox(**vars(box))]
            self._last_character_details = [{'x': box.x, 'y': box.y, 'width': box.width, 'height': box.height, 'score': 0.0, 'class_name': '미니맵'}]
            self._last_character_seen_ts = time.time()
            self._using_character_fallback = True
        except Exception:
            pass
        self._minimap_x_fallback_used_ts = time.time()
        return True

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
        self._forbidden_visual_overlays = []
        self._latest_detection_qimage = None
        self._latest_detection_bgr = None
        self._latest_detection_frame_ts = 0.0
        self._latest_detection_bgr_ts = 0.0
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
        # 초기화: 프레임별로 갱신
        self.current_cleanup_chase_area = None
        self.current_cluster_window_area = None
        self.current_cluster_center_x = None
        self.current_cluster_center_y = None

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

        # [NEW] 겹침 판단을 위해 이전 프레임 주 스킬 마릿수를 보존
        try:
            prev_primary = int(getattr(self, 'latest_primary_monster_count', 0) or 0)
        except Exception:
            prev_primary = 0
        self._prev_primary_count = prev_primary

        self.latest_monster_count = hunt_count
        self.latest_primary_monster_count = primary_count

        # [NEW] 최근 다중(≥2) 관측 시각 저장
        if primary_count >= 2:
            self._last_primary_multi_ts = now

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

        # [NEW] 오버레이 계산: 클린업 추격밴드 & 군집 중심 윈도우
        try:
            # 클린업 추격밴드: 클린업 상태일 때만 표시
            if primary_area is not None and getattr(self, '_cleanup_active', False):
                margin = float(CLEANUP_CHASE_MARGIN_PX)
                self.current_cleanup_chase_area = AreaRect(
                    x=primary_area.x - margin,
                    y=primary_area.y,
                    width=primary_area.width + (margin * 2.0),
                    height=primary_area.height,
                )
            # 군집 중심 점: 주 스킬 범위와 교차하는 몬스터의 중심 X를 산술평균
            self.current_cluster_center_x = None
            self.current_cluster_center_y = None
            if primary_area is not None and effective_monsters:
                primary_monsters = [m for m in effective_monsters if m.intersects(primary_area)]
                if len(primary_monsters) >= 2:
                    center_x = sum(m.center_x for m in primary_monsters) / float(len(primary_monsters))
                    center_y = primary_area.y + (primary_area.height / 2.0)
                    self.current_cluster_center_x = float(center_x)
                    self.current_cluster_center_y = float(center_y)
        except Exception:
            # 계산 실패 시 조용히 무시
            pass

    def _should_enter_cleanup_due_to_overlap(self, now_ts: float) -> bool:
        """겹침(이전 프레임 ≥2 → 현재 1) 상황에서 즉시 클린업으로 전환할지 판단.

        - 거리 조건은 사용하지 않음(현재 1마리는 이미 주 스킬 범위 내를 의미)
        - 접근 윈도우: 최근 2.0초 내 이동 명령이 있었는지 검사
        - 다중관측 윈도우: 최근 1.0초 내 주 스킬 범위에서 2마리 이상을 관측했는지 검사
        """
        try:
            if int(getattr(self, '_prev_primary_count', 0)) < 2:
                return False
            if int(self.latest_primary_monster_count) != 1:
                return False

            # 접근 윈도우(2초)
            last_move_ts = float(getattr(self, '_last_movement_command_ts', 0.0) or 0.0)
            if last_move_ts <= 0.0 or (now_ts - last_move_ts) > 2.0:
                return False

            # 다중관측 윈도우(1초)
            last_multi_ts = float(getattr(self, '_last_primary_multi_ts', 0.0) or 0.0)
            if last_multi_ts <= 0.0 or (now_ts - last_multi_ts) > 1.0:
                return False

            # 조건 충족 → 즉시 클린업 진입
            self._engage_active = True
            self._cleanup_active = True
            self._cleanup_hold_until_ts = 0.0
            self._last_monster_seen_ts = now_ts
            try:
                self.append_log("겹침 감지 → 클린업 진입 (접근≤2s, 다중관측≤1s)", "info")
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _clear_detection_metrics(self) -> None:
        self.current_hunt_area = None
        self.current_primary_area = None
        self.current_cleanup_chase_area = None
        self.current_cluster_window_area = None
        self.current_cluster_center_x = None
        self.current_cluster_center_y = None
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

    # ----- [NEW] 금지몬스터 감지 플로우 -----
    def _request_forbidden_detection_frame(self, now: float, *, force: bool = False) -> None:
        if self._is_screen_output_enabled():
            return
        thread = getattr(self, 'detection_thread', None)
        if thread is None or not hasattr(thread, 'request_forced_frame_emit'):
            return
        try:
            is_running = thread.isRunning()
        except Exception:
            is_running = True
        if not is_running:
            return
        if not force:
            last_req = float(getattr(self, '_forbidden_last_frame_request_ts', 0.0) or 0.0)
            if (now - last_req) < FORBIDDEN_FRAME_REQUEST_COOLDOWN:
                return
        duration = FORBIDDEN_FRAME_FORCE_DURATION
        try:
            thread.request_forced_frame_emit(duration)
            self._forbidden_last_frame_request_ts = now
        except Exception:
            pass

    def _maybe_trigger_forbidden_flow(self, monsters: List[dict], now: float) -> None:
        if not bool(getattr(self, 'auto_hunt_enabled', True)):
            return
        if not bool(getattr(self, 'forbidden_monster_enabled', False)):
            return
        cmd = (getattr(self, 'forbidden_monster_command_profile', '') or '').strip()
        if not cmd:
            return
        if not self._has_wait_waypoint_configured():
            return
        self._expire_forbidden_visuals(now)
        lock_until = float(getattr(self, '_forbidden_lock_until', 0.0) or 0.0)
        if now < lock_until:
            return
        candidate = self._extract_forbidden_candidate(monsters)
        if candidate is None:
            return

        watch_until = float(getattr(self, '_forbidden_watch_window_until', 0.0) or 0.0)
        cooldown_until = float(getattr(self, '_forbidden_cooldown_until', 0.0) or 0.0)
        perform_match = False
        if now <= watch_until or now < cooldown_until or bool(getattr(self, '_forbidden_active', False)):
            perform_match = True
        if perform_match and not self._is_screen_output_enabled():
            stale = True
            qimg = self._latest_detection_qimage
            last_ts = float(getattr(self, '_latest_detection_frame_ts', 0.0) or 0.0)
            if qimg is not None and not qimg.isNull() and last_ts > 0.0 and (now - last_ts) <= FORBIDDEN_FRAME_STALE_SEC:
                stale = False
            if stale:
                self._request_forbidden_detection_frame(now, force=True)
        evaluation = self._evaluate_forbidden_glyph(candidate, now, perform_match=perform_match)
        if perform_match and evaluation.get('roi_rect'):
            highlight_rect = evaluation.get('match_rect') or evaluation.get('best_rect')
            self._append_forbidden_visual(evaluation['roi_rect'], highlight_rect, now)

        if evaluation.get('retry_pending'):
            attempts = int(evaluation.get('retry_attempts', 0) or 0)
            try:
                if attempts > 0:
                    self.append_log(
                        f"[금지] 문양 판정 대기 중... ({min(attempts, FORBIDDEN_GLYPH_MAX_ATTEMPTS)}/{FORBIDDEN_GLYPH_MAX_ATTEMPTS})",
                        'debug',
                    )
                    # [조정] 대기(reason='retry_wait') 상태는 텔레그램 전송 생략
                    if str(evaluation.get('reason') or '').lower() != 'retry_wait':
                        try:
                            self._emit_forbidden_retry_attempt(
                                candidate,
                                evaluation,
                                min(attempts, FORBIDDEN_GLYPH_MAX_ATTEMPTS),
                            )
                        except Exception:
                            pass
            except Exception:
                pass
            return

        if bool(getattr(self, '_forbidden_active', False)):
            match_flag = evaluation.get('matched')
            if match_flag is True:
                self._apply_forbidden_lock(candidate, evaluation, now)
                self._notify_forbidden_result_event(candidate, evaluation, now, triggered=False, locked=True)
            elif match_flag is not None:
                self._notify_forbidden_result_event(candidate, evaluation, now, triggered=False, locked=False)
            return

        matched_flag = evaluation.get('matched')
        if now < cooldown_until:
            if matched_flag is True:
                self._apply_forbidden_lock(candidate, evaluation, now)
                return
            if matched_flag is False:
                self._start_forbidden_sequence(candidate, now, reason='cooldown_override', evaluation=evaluation)
                return
            return

        self._start_forbidden_sequence(candidate, now, reason='normal', evaluation=evaluation)

    def _get_forbidden_class_set(self) -> set[str]:
        forbidden_set: set[str] = set()
        if self.data_manager and hasattr(self.data_manager, 'get_monster_attack_forbidden_map'):
            try:
                fmap = self.data_manager.get_monster_attack_forbidden_map() or {}
                forbidden_set = {name for name, enabled in fmap.items() if enabled}
            except Exception:
                forbidden_set = set()
        return forbidden_set

    def _resolve_monster_threshold(self, class_id: int) -> float:
        try:
            overrides = getattr(self, '_active_monster_confidence_overrides', {}) or {}
            if class_id in overrides:
                threshold = float(overrides.get(class_id, 0.0))
            else:
                threshold = float(self.conf_monster_spinbox.value()) if hasattr(self, 'conf_monster_spinbox') else 0.85
        except Exception:
            threshold = 0.85
        return max(0.05, min(0.95, threshold))

    def _extract_forbidden_candidate(self, monsters: List[dict]) -> Optional[dict]:
        forbidden_set = self._get_forbidden_class_set()
        if not forbidden_set:
            return None
        best_entry: Optional[dict] = None
        for item in monsters or []:
            if not isinstance(item, dict):
                continue
            if str(item.get('source') or 'yolo') != 'yolo':
                continue
            cname = str(item.get('class_name') or '')
            if not cname or cname not in forbidden_set:
                continue
            try:
                score = float(item.get('score', 0.0))
            except (TypeError, ValueError):
                continue
            try:
                class_id = int(item.get('class_id', -1))
            except (TypeError, ValueError):
                class_id = -1
            threshold = self._resolve_monster_threshold(class_id)
            if score < threshold:
                continue
            try:
                box = {
                    'x': float(item.get('x', 0.0)),
                    'y': float(item.get('y', 0.0)),
                    'width': float(item.get('width', 0.0)),
                    'height': float(item.get('height', 0.0)),
                }
            except (TypeError, ValueError):
                continue
            if box['width'] <= 0.0 or box['height'] <= 0.0:
                continue
            if best_entry is None or score > best_entry['score']:
                best_entry = {
                    'class_name': cname,
                    'score': score,
                    'class_id': class_id,
                    'box': box,
                    'raw': item,
                }
        return best_entry

    def _evaluate_forbidden_glyph(self, detection: dict, now: float, *, perform_match: bool) -> dict:
        result = {
            'timestamp': now,
            'matched': None,
            'score': 0.0,
            'template_id': None,
            'match_rect': None,
            'roi_rect': None,
            'reason': None,
        }
        box = detection.get('box') if isinstance(detection, dict) else None
        if not isinstance(box, dict):
            result['reason'] = 'no_box'
            return result
        frame_width, frame_height = self._latest_frame_size
        if frame_width <= 0 or frame_height <= 0:
            qimg = self._latest_detection_qimage
            if qimg is not None and not qimg.isNull():
                frame_width = qimg.width()
                frame_height = qimg.height()
        if frame_width <= 0 or frame_height <= 0:
            self._request_forbidden_detection_frame(now, force=False)
            result['reason'] = 'no_frame_size'
            return result
        margin = FORBIDDEN_GLYPH_MARGIN_PX
        try:
            x = float(box.get('x', 0.0))
            y = float(box.get('y', 0.0))
            width = float(box.get('width', 0.0))
            height = float(box.get('height', 0.0))
        except (TypeError, ValueError):
            result['reason'] = 'invalid_box'
            return result
        cx = x + width * 0.5
        cy = y + height * 0.5
        bias_ratio = float(getattr(self, '_forbidden_glyph_vertical_bias', 0.0) or 0.0)
        target_cy = cy + height * bias_ratio
        half_w = (width * 0.5) + margin
        half_h = (height * 0.5) + margin
        desired_width = max(1, int(math.ceil(half_w * 2.0)))
        desired_height = max(1, int(math.ceil(half_h * 2.0)))

        left_f = cx - half_w
        right_f = cx + half_w
        top_f = target_cy - half_h
        bottom_f = target_cy + half_h

        roi_left = int(math.floor(left_f))
        roi_right = int(math.ceil(right_f))
        roi_top = int(math.floor(top_f))
        roi_bottom = int(math.ceil(bottom_f))

        roi_left = max(0, roi_left)
        roi_top = max(0, roi_top)
        roi_right = min(frame_width, roi_right)
        roi_bottom = min(frame_height, roi_bottom)

        # 부족한 폭/높이 보정(가능한 범위 내에서 원래 크기 유지)
        if roi_right - roi_left < desired_width:
            deficit = desired_width - (roi_right - roi_left)
            add_right = min(deficit // 2 + deficit % 2, frame_width - roi_right)
            roi_right += add_right
            deficit -= add_right
            add_left = min(deficit // 2 + deficit % 2, roi_left)
            roi_left -= add_left
        if roi_bottom - roi_top < desired_height:
            deficit_h = desired_height - (roi_bottom - roi_top)
            add_bottom = min(deficit_h // 2 + deficit_h % 2, frame_height - roi_bottom)
            roi_bottom += add_bottom
            deficit_h -= add_bottom
            add_top = min(deficit_h // 2 + deficit_h % 2, roi_top)
            roi_top -= add_top

        roi_width = max(0, roi_right - roi_left)
        roi_height = max(0, roi_bottom - roi_top)
        if roi_width <= 0 or roi_height <= 0:
            result['reason'] = 'empty_roi'
            return result
        result['roi_rect'] = (roi_left, roi_top, roi_width, roi_height)
        result['roi_bias_ratio'] = bias_ratio
        result['roi_center'] = (cx, target_cy)
        if not perform_match:
            return result

        retry_key: Optional[tuple] = None
        retry_state: Optional[dict] = None
        try:
            class_label = str(detection.get('class_name') or '')
            if class_label:
                retry_key = (class_label,)
        except Exception:
            retry_key = None

        if retry_key is not None:
            retry_state = self._forbidden_glyph_retry_state.get(retry_key)
            max_window = FORBIDDEN_GLYPH_RETRY_INTERVAL_SEC * (FORBIDDEN_GLYPH_MAX_ATTEMPTS + 1)
            if retry_state is None:
                retry_state = {
                    'attempts': 0,
                    'first_ts': now,
                    'next_ts': now,
                }
                self._forbidden_glyph_retry_state[retry_key] = retry_state
            else:
                first_ts = float(retry_state.get('first_ts', now) or now)
                if now - first_ts > max_window:
                    retry_state = {
                        'attempts': 0,
                        'first_ts': now,
                        'next_ts': now,
                    }
                    self._forbidden_glyph_retry_state[retry_key] = retry_state

            def schedule_retry(reason: str) -> dict:
                nonlocal retry_state
                if retry_state is None:
                    retry_state = {
                        'attempts': 0,
                        'first_ts': now,
                        'next_ts': now,
                    }
                    self._forbidden_glyph_retry_state[retry_key] = retry_state
                attempts = int(retry_state.get('attempts', 0) or 0)
                next_ts = float(retry_state.get('next_ts', now) or now)
                if attempts > 0 and now < next_ts:
                    result['reason'] = 'retry_wait'
                    result['retry_pending'] = True
                    result['matched'] = None
                    result['retry_attempts'] = attempts
                    return result
                attempts += 1
                retry_state['attempts'] = attempts
                retry_state['next_ts'] = now + FORBIDDEN_GLYPH_RETRY_INTERVAL_SEC
                result['reason'] = reason
                if attempts < FORBIDDEN_GLYPH_MAX_ATTEMPTS:
                    result['matched'] = None
                    result['retry_pending'] = True
                    result['retry_attempts'] = attempts
                else:
                    self._forbidden_glyph_retry_state.pop(retry_key, None)
                    result['matched'] = False
                return result
        else:
            def schedule_retry(reason: str) -> dict:
                result['reason'] = reason
                result['matched'] = False
                return result

        if retry_state and retry_state.get('attempts', 0) > 0:
            next_ts = float(retry_state.get('next_ts', now) or now)
            if now < next_ts:
                result['reason'] = 'retry_wait'
                result['retry_pending'] = True
                result['matched'] = None
                result['retry_attempts'] = int(retry_state.get('attempts', 0) or 0)
                return result

        if not self._forbidden_glyph_templates:
            return schedule_retry('no_templates')
        roi_image_bgr = self._get_latest_detection_bgr()
        if roi_image_bgr is None:
            self._request_forbidden_detection_frame(now, force=False)
            return schedule_retry('no_frame')
        if roi_bottom > roi_image_bgr.shape[0] or roi_right > roi_image_bgr.shape[1]:
            return schedule_retry('roi_out_of_bounds')
        roi_view = roi_image_bgr[roi_top:roi_bottom, roi_left:roi_right]
        if roi_view.size == 0:
            return schedule_retry('empty_roi')
        roi_gray = cv2.cvtColor(roi_view, cv2.COLOR_BGR2GRAY)
        best_val: float = 0.0
        best_loc: Optional[tuple[int, int]] = None
        best_wh: Optional[tuple[int, int]] = None
        for template in self._forbidden_glyph_templates:
            tpl_img = template.get('image')
            if tpl_img is None:
                continue
            th, tw = tpl_img.shape[:2]
            # 다중 스케일 시도(조기 종료)
            for scale in FORBIDDEN_GLYPH_SCALES:
                if abs(scale - 1.0) < 1e-9:
                    scaled = tpl_img
                    h, w = th, tw
                else:
                    h = max(1, int(round(th * scale)))
                    w = max(1, int(round(tw * scale)))
                    # 너무 작아지면 매칭 품질 저하, 10x10 미만은 스킵
                    if h < 10 or w < 10:
                        continue
                    scaled = cv2.resize(tpl_img, (w, h), interpolation=cv2.INTER_LINEAR)
                if roi_gray.shape[0] < h or roi_gray.shape[1] < w:
                    continue
                res = cv2.matchTemplate(roi_gray, scaled, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                # 최고값 추적(디버그/보고용)
                if max_val > best_val:
                    best_val = float(max_val)
                    best_loc = (int(max_loc[0]), int(max_loc[1]))
                    best_wh = (w, h)
                if max_val >= self._forbidden_glyph_threshold:
                    match_left = roi_left + max_loc[0]
                    match_top = roi_top + max_loc[1]
                    result['matched'] = True
                    result['score'] = float(max_val)
                    result['template_id'] = template.get('id')
                    result['match_rect'] = (match_left, match_top, w, h)
                    if retry_key is not None:
                        self._forbidden_glyph_retry_state.pop(retry_key, None)
                    return result
        if best_val > 0.0:
            result['best_score'] = float(best_val)
            if best_loc is not None and best_wh is not None:
                bx, by = best_loc
                bw, bh = best_wh
                result['best_rect'] = (roi_left + bx, roi_top + by, bw, bh)
        return schedule_retry('no_match')

    def _set_forbidden_glyph_status(self, status: str) -> None:
        self._forbidden_glyph_status = status
        try:
            self._forbidden_glyph_status_ts = float(time.time())
        except Exception:
            self._forbidden_glyph_status_ts = 0.0

    def _prepare_forbidden_detection(self) -> None:
        try:
            self._issue_all_keys_release("forbidden_monster:detect")
        except Exception:
            pass
        try:
            self._play_forbidden_alert()
        except Exception:
            pass

    def _start_forbidden_sequence(self, candidate: dict, now: float, *, reason: str, evaluation: Optional[dict]) -> None:
        self._set_forbidden_glyph_status('pending')
        self._prepare_forbidden_detection()
        cooldown_until = now + 180.0
        self._forbidden_cooldown_until = cooldown_until
        self._forbidden_watch_window_until = cooldown_until
        self._latest_forbidden_detection = {
            'class_name': candidate.get('class_name'),
            'score': float(candidate.get('score', 0.0)),
            'timestamp': now,
        }
        self._notify_forbidden_detection_event(candidate, reason, evaluation)
        if evaluation and evaluation.get('matched') is not None:
            self._notify_forbidden_result_event(candidate, evaluation, now, triggered=True, locked=False)
        self._trigger_forbidden_wait_flow(now)

    def _apply_forbidden_lock(self, candidate: dict, evaluation: Optional[dict], now: float) -> None:
        lock_until = now + 180.0
        self._forbidden_lock_until = max(self._forbidden_lock_until, lock_until)
        self._forbidden_cooldown_until = max(self._forbidden_cooldown_until, lock_until)
        self._forbidden_watch_window_until = max(self._forbidden_watch_window_until, lock_until)
        if evaluation:
            self._notify_forbidden_result_event(candidate, evaluation, now, triggered=False, locked=True)

    def _notify_forbidden_detection_event(self, candidate: dict, reason: str, evaluation: Optional[dict]) -> None:
        name = candidate.get('class_name', '금지몬스터')
        score_pct = float(candidate.get('score', 0.0)) * 100.0
        message = f"금지몬스터 감지: '{name}(신뢰도:{score_pct:.1f}%)' → 대기 모드 진입"
        if reason == 'cooldown_override':
            message += " (문양 無 재실행)"
        try:
            self.append_log(message, 'info')
        except Exception:
            pass
        image_bgr = self._build_forbidden_detection_image(candidate, evaluation)
        label = f"detect:{name}:{reason}"
        self._emit_forbidden_notification(label, message, image_bgr)

    def _notify_forbidden_result_event(self, candidate: dict, evaluation: dict, now: float, *, triggered: bool, locked: bool) -> None:
        matched = evaluation.get('matched')
        if matched is None:
            return
        name = candidate.get('class_name', '금지몬스터')
        match_pct = float(evaluation.get('score', 0.0)) * 100.0
        image_bgr: Optional[np.ndarray]
        image_bgr = self._build_forbidden_result_image(evaluation)
        if matched:
            if locked:
                message = f"금지몬스터 문양 판정: '{name}' 문양 有 (매칭 {match_pct:.1f}%) → 3분 잠금 재적용"
            else:
                message = f"금지몬스터 문양 판정: '{name}' 문양 有 (매칭 {match_pct:.1f}%)"
        else:
            if triggered:
                message = f"금지몬스터 문양 판정: '{name}' 문양 無 → 재실행 및 쿨다운 리셋"
            else:
                message = f"금지몬스터 문양 판정: '{name}' 문양 無"
        try:
            self.append_log(message, 'info')
        except Exception:
            pass
        label = f"result:{name}:{int(bool(matched))}:{int(locked)}"
        self._emit_forbidden_notification(label, message, image_bgr)
        if matched:
            self._set_forbidden_glyph_status('success')
        else:
            self._set_forbidden_glyph_status('failure')

    def _emit_forbidden_notification(self, label: str, text: str, image_bgr: Optional[np.ndarray]) -> None:
        if not bool(getattr(self, 'forbidden_monster_telegram_alert', False)):
            return
        now_ts = time.time()
        last_ts = self._forbidden_notify_cache.get(label)
        # 재시도 라벨은 스로틀을 완화하여(거의 즉시) 0.1초 간격 3회 로그 전송 허용
        min_interval = 0.0 if isinstance(label, str) and label.startswith('retry:') else 2.0
        if last_ts and (now_ts - last_ts) < min_interval:
            return
        self._forbidden_notify_cache[label] = now_ts
        self._send_forbidden_telegram(text, image_bgr=image_bgr)

    def _send_forbidden_telegram(self, text: str, *, image_bgr: Optional[np.ndarray] = None) -> None:
        if not text:
            return
        sent = False
        if image_bgr is not None and _tg_send_photo:
            try:
                success, buffer = cv2.imencode(".png", image_bgr)
                if success:
                    image_bytes = buffer.tobytes()
                    sent = bool(_tg_send_photo(image_bytes, caption=text))
            except Exception:
                sent = False
        if sent:
            return
        # [폴백] 브리지가 없거나 실패 시, OCR 경로의 간단 전송 함수를 사용(사진 포함)
        if image_bgr is not None:
            try:
                from ocr_watch import send_telegram_text_and_screenshot as _tg_text_and_shot  # 지연 임포트
                _tg_text_and_shot(text, image_bgr=image_bgr)
                return
            except Exception:
                pass
        try:
            self._notify_telegram(text)
        except Exception:
            pass

    def _emit_forbidden_retry_attempt(self, candidate: dict, evaluation: dict, attempts: int) -> None:
        """문양 재시도 로그를 텔레그램으로 전송(사진 포함).

        - 라벨: retry:{name}:{attempt}
        - 스로틀 완화: 재시도 라벨은 즉시 전송(상단 스로틀 로직 참고)
        """
        try:
            name = str((candidate or {}).get('class_name') or '금지몬스터')
        except Exception:
            name = '금지몬스터'
        total = int(FORBIDDEN_GLYPH_MAX_ATTEMPTS)
        reason_key = str(evaluation.get('reason') or '')
        reason_map = {
            'retry_wait': '대기',
            'no_templates': '템플릿 없음',
            'no_frame': '프레임 없음',
            'roi_out_of_bounds': 'ROI 범위 오류',
            'empty_roi': 'ROI 비어있음',
            'no_match': '매칭 미달',
        }
        reason_text = reason_map.get(reason_key, reason_key or '-')
        # 부가정보: best_score 존재 시 표시(디버그)
        best_info = ''
        try:
            best_val = float(evaluation.get('best_score', 0.0) or 0.0)
            if best_val > 0.0:
                best_info = f", 최고매칭 {best_val*100.0:.1f}%"
        except Exception:
            best_info = ''
        msg = f"[금지] 문양 판정 재시도 {attempts}/{total} (사유: {reason_text}{best_info})"
        image_bgr = self._build_forbidden_result_image(evaluation)
        label = f"retry:{name}:{attempts}"
        self._emit_forbidden_notification(label, msg, image_bgr)

    def _build_forbidden_result_image(self, evaluation: dict) -> Optional[np.ndarray]:
        base = self._get_latest_detection_bgr()
        offset = (0, 0)
        if base is None:
            # [폴백] 화면 캡처로 대체
            base = self._capture_maple_window_bgr()
            if base is None:
                return None
            offset = self._resolve_forbidden_overlay_offset()
        ox, oy = offset
        annotated = base.copy()
        self._overlay_forbidden_regions(annotated, evaluation, include_match=True, offset=(ox, oy))
        return annotated

    def _build_forbidden_detection_image(self, candidate: dict, evaluation: Optional[dict]) -> Optional[np.ndarray]:
        base = self._get_latest_detection_bgr()
        offset = (0, 0)
        if base is None:
            # [폴백] 화면 캡처로 대체
            base = self._capture_maple_window_bgr()
            if base is None:
                return None
            offset = self._resolve_forbidden_overlay_offset()
        ox, oy = offset
        annotated = base.copy()
        box = candidate.get('box') if isinstance(candidate, dict) else None
        if isinstance(box, dict):
            try:
                x = float(box.get('x', 0.0))
                y = float(box.get('y', 0.0))
                w = float(box.get('width', 0.0))
                h = float(box.get('height', 0.0))
                x1 = max(0, int(round(x + ox)))
                y1 = max(0, int(round(y + oy)))
                x2 = max(x1 + 1, int(round(x + w + ox)))
                y2 = max(y1 + 1, int(round(y + h + oy)))
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
            except Exception:
                pass
        if evaluation and evaluation.get('roi_rect'):
            self._overlay_forbidden_regions(annotated, evaluation, include_match=True, offset=(ox, oy))
        return annotated

    def _overlay_forbidden_regions(
        self,
        image: np.ndarray,
        evaluation: dict,
        *,
        include_match: bool,
        offset: Optional[tuple[int, int]] = None,
    ) -> None:
        if image is None or evaluation is None:
            return
        dx = dy = 0
        if offset is not None:
            try:
                dx = int(round(offset[0]))
                dy = int(round(offset[1]))
            except Exception:
                dx = dy = 0
        roi_rect = evaluation.get('roi_rect')
        if roi_rect and len(roi_rect) == 4:
            rx, ry, rw, rh = roi_rect
            rx1 = max(0, int(round(rx + dx)))
            ry1 = max(0, int(round(ry + dy)))
            rx2 = max(rx1 + 1, int(round(rx + rw + dx)))
            ry2 = max(ry1 + 1, int(round(ry + rh + dy)))
            try:
                cv2.rectangle(image, (rx1, ry1), (rx2, ry2), (0, 255, 255), 2)
            except Exception:
                pass
        if include_match and evaluation.get('matched') and evaluation.get('match_rect') and len(evaluation['match_rect']) == 4:
            x, y, w, h = evaluation['match_rect']
            x1 = max(0, int(round(x + dx)))
            y1 = max(0, int(round(y + dy)))
            x2 = max(x1 + 1, int(round(x + w + dx)))
            y2 = max(y1 + 1, int(round(y + h + dy)))
            try:
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
            except Exception:
                pass
        elif include_match and evaluation.get('best_rect') and len(evaluation.get('best_rect')) == 4:
            bx, by, bw, bh = evaluation['best_rect']
            bx1 = max(0, int(round(bx + dx)))
            by1 = max(0, int(round(by + dy)))
            bx2 = max(bx1 + 1, int(round(bx + bw + dx)))
            by2 = max(by1 + 1, int(round(by + bh + dy)))
            try:
                cv2.rectangle(image, (bx1, by1), (bx2, by2), (0, 165, 255), 1)
            except Exception:
                pass

    def _capture_maple_window_bgr(self) -> Optional[np.ndarray]:
        """Mapleland 창을 스크린샷하여 BGR 프레임으로 반환(실패 시 None)."""
        try:
            import mss  # type: ignore
            import numpy as _np  # type: ignore
            from window_anchors import get_maple_window_geometry as _get_geo
        except Exception:
            return None
        try:
            geo = _get_geo()
            if geo is None:
                return None
            region = {"left": int(geo.left), "top": int(geo.top), "width": int(geo.width), "height": int(geo.height)}
            if region["width"] <= 0 or region["height"] <= 0:
                return None
            with mss.mss() as sct:
                shot = sct.grab(region)
            frame_bgra = _np.frombuffer(shot.raw, dtype=_np.uint8).reshape(shot.height, shot.width, 4)
            return frame_bgra[:, :, :3].copy()
        except Exception:
            return None

    def _resolve_forbidden_overlay_offset(self) -> tuple[int, int]:
        """금지몬스터 오버레이를 전체 창 캡처에 맞춰 그릴 때 필요한 ROI 오프셋."""
        try:
            capture_region = self._resolve_manual_capture_region()
        except Exception:
            capture_region = None
        if not isinstance(capture_region, dict):
            return (0, 0)
        try:
            capture_left = float(capture_region.get('left', 0.0))
            capture_top = float(capture_region.get('top', 0.0))
        except Exception:
            return (0, 0)
        window_geometry = get_maple_window_geometry()
        if window_geometry is None:
            return (0, 0)
        try:
            offset_x = int(round(capture_left - float(window_geometry.left)))
            offset_y = int(round(capture_top - float(window_geometry.top)))
        except Exception:
            return (0, 0)
        return offset_x, offset_y

    def _trigger_forbidden_wait_flow(self, now: float) -> None:
        if self._forbidden_active:
            return
        self._forbidden_active = True
        map_tab = getattr(self, 'map_tab', None)
        ok = False
        try:
            ok = bool(self._start_other_player_wait_mode(now, flow='forbidden'))
        except Exception as exc:
            self.append_log(f"금지몬스터 대기모드 시작 실패: {exc}", 'warn')
            ok = False
        if not ok:
            if map_tab and hasattr(map_tab, 'set_forbidden_wall_suppressed'):
                try:
                    map_tab.set_forbidden_wall_suppressed(False, reason='hunt_forbidden_abort')
                except Exception:
                    pass
            self._forbidden_active = False
            return
        if map_tab and hasattr(map_tab, 'set_forbidden_wall_suppressed'):
            try:
                map_tab.set_forbidden_wall_suppressed(True, reason='hunt_forbidden')
            except Exception:
                pass
        try:
            self.append_log("금지몬스터 감지 → 대기 모드 진입", 'info')
            # 맵 탭 일반 로그에도 표시(가능 시)
            if getattr(self, 'map_tab', None) and hasattr(self.map_tab, 'update_general_log'):
                try:
                    self.map_tab.update_general_log("[금지] 몬스터 감지 → 대기 모드 진입", "red")
                except Exception:
                    pass
        except Exception:
            pass

    def on_other_player_wait_arrived(self, source: str = '', waypoint_name: str = '') -> None:
        """맵탭이 대기 웨이포인트 도착을 알릴 때 호출."""
        normalized_source = str(source or '').strip().lower()
        if normalized_source == 'hunt.exit':
            self._handle_exit_wait_arrival(waypoint_name)
            return
        if normalized_source == 'hunt.map_return':
            self._handle_map_return_arrival(waypoint_name)
            return
        try:
            # [완화] 소스 문자열이 일치하지 않더라도 금지 플로우 활성 상태이면 처리
            if not self._forbidden_active:
                return
            if normalized_source != 'hunt.forbidden':
                # 디버그 로깅만 수행(과도한 스팸 방지 위해 info 이하)
                try:
                    self.append_log(f"[금지] 도착 알림 source='{source}'(예상 'hunt.forbidden')이지만 금지 플로우 활성 상태이므로 실행 처리.", 'debug')
                except Exception:
                    pass
            # [신규] 이미 명령 실행 중이면 중복 실행 방지
            if bool(getattr(self, '_forbidden_cmd_inflight', False)):
                return
            cmd = (getattr(self, 'forbidden_monster_command_profile', '') or '').strip()
            if not cmd:
                # 명령 미지정: 즉시 종료 및 쿨다운 시작
                self._schedule_forbidden_finish()
                return
            # 실행 래치 세팅(완료 시 해제)
            self._forbidden_cmd_inflight = True
            self._emit_control_command(cmd, reason='forbidden_monster')
            # [ACK] 맵탭에 명령 시작 알림(핸드셰이크)
            try:
                map_tab = getattr(self, 'map_tab', None)
                if map_tab and hasattr(map_tab, 'on_other_player_wait_command_started'):
                    map_tab.on_other_player_wait_command_started(source='hunt.forbidden')
            except Exception:
                pass
            # [워치독] 완료 감시 시작(6초)
            try:
                self._forbidden_watchdog_retry_count = 0
                self._forbidden_command_name = cmd
                QTimer.singleShot(6000, self._forbidden_watchdog_check)
            except Exception:
                pass
            self.append_log(f"금지몬스터 도착 → 명령 실행: '{cmd}'", 'info')
        except Exception:
            # 에러 시에도 종료 예약
            self._schedule_forbidden_finish()

    def _forbidden_watchdog_check(self) -> None:
        """금지 명령 완료 감시(6초). 미완료 시 1회 재발행, 재차 실패 시 종료."""
        try:
            # 탐지/대기모드 상태 점검: 비활성/종료면 무시
            if not bool(getattr(self, '_forbidden_active', False)):
                return
            if not bool(getattr(self, '_forbidden_cmd_inflight', False)):
                return
            # 아직 완료 콜백이 오지 않음
            if int(getattr(self, '_forbidden_watchdog_retry_count', 0) or 0) < int(getattr(self, '_FORBIDDEN_WATCHDOG_MAX_RETRY', 1) or 1):
                # 1회 재발행
                cmd = (getattr(self, '_forbidden_command_name', '') or '').strip()
                if cmd:
                    self.append_log("[금지] 완료 지연: 금지 프로필 재발행(1/1)", 'warn')
                    self._emit_control_command(cmd, reason='forbidden_monster')
                    try:
                        map_tab = getattr(self, 'map_tab', None)
                        if map_tab and hasattr(map_tab, 'on_other_player_wait_command_started'):
                            map_tab.on_other_player_wait_command_started(source='hunt.forbidden')
                    except Exception:
                        pass
                    self._forbidden_watchdog_retry_count = int(getattr(self, '_forbidden_watchdog_retry_count', 0) or 0) + 1
                    QTimer.singleShot(6000, self._forbidden_watchdog_check)
                else:
                    # 프로필명이 없다면 안전 종료
                    self.append_log("[금지] 완료 지연: 프로필 미상 → 대기모드 종료", 'warn')
                    self._schedule_forbidden_finish()
            else:
                # 재시도 초과: 안전 종료
                self.append_log("[금지] 완료 지연: 재시도 초과 → 대기모드 종료", 'warn')
                self._schedule_forbidden_finish()
        except Exception:
            try:
                self._schedule_forbidden_finish()
            except Exception:
                pass

    def _schedule_forbidden_finish(self) -> None:
        """금지 플로우 종료(1초 후 대기모드 종료 + 3분 쿨다운)."""
        try:
            QTimer.singleShot(1000, lambda: self._finish_other_player_wait_mode(reason='forbidden_done'))
        except Exception:
            try:
                self._finish_other_player_wait_mode(reason='forbidden_done')
            except Exception:
                pass
        self._forbidden_active = False
        map_tab = getattr(self, 'map_tab', None)
        if map_tab and hasattr(map_tab, 'set_forbidden_wall_suppressed'):
            try:
                map_tab.set_forbidden_wall_suppressed(False, reason='hunt_forbidden_finish')
            except Exception:
                pass
        # [신규] 명령 완료 처리: 래치/워치독 초기화
        self._forbidden_cmd_inflight = False
        self._forbidden_watchdog_retry_count = 0
        try:
            import time as _t
            # [변경] 이미 감지 시점에 쿨다운이 설정되었다면 덮어쓰지 않음
            now_ts = float(_t.time())
            if float(getattr(self, '_forbidden_cooldown_until', 0.0) or 0.0) <= now_ts:
                self._forbidden_cooldown_until = now_ts + 180.0
        except Exception:
            self._forbidden_cooldown_until = 0.0
        if getattr(self, '_forbidden_glyph_status', 'idle') == 'pending':
            self._set_forbidden_glyph_status('idle')

    def _reset_forbidden_status(self, reason: str = '') -> None:
        """금지 몬스터 관련 상태를 완전히 초기화한다."""
        try:
            self._forbidden_active = False
        except Exception:
            pass
        if hasattr(self, '_forbidden_cmd_inflight'):
            self._forbidden_cmd_inflight = False
        if hasattr(self, '_forbidden_watchdog_retry_count'):
            self._forbidden_watchdog_retry_count = 0
        if hasattr(self, '_forbidden_command_name'):
            self._forbidden_command_name = ''
        self._forbidden_watch_window_until = 0.0
        self._forbidden_lock_until = 0.0
        self._forbidden_cooldown_until = 0.0
        self._latest_forbidden_detection = None
        self._forbidden_visual_overlays = []
        if hasattr(self, '_forbidden_glyph_retry_state'):
            try:
                self._forbidden_glyph_retry_state.clear()
            except Exception:
                self._forbidden_glyph_retry_state = {}
        self._set_forbidden_glyph_status('idle')
        map_tab = getattr(self, 'map_tab', None)
        if map_tab and hasattr(map_tab, 'set_forbidden_wall_suppressed'):
            try:
                map_tab.set_forbidden_wall_suppressed(False, reason='hunt_forbidden_reset')
            except Exception:
                pass

    def _expire_nameplate_dead_zones(self, now: float) -> None:
        if not self._nameplate_dead_zones:
            return
        self._nameplate_dead_zones = [
            zone for zone in self._nameplate_dead_zones if float(zone.get('expires_at', 0.0)) > now
        ]

    def _expire_forbidden_visuals(self, now: float) -> None:
        if not self._forbidden_visual_overlays:
            return
        remaining: list[dict] = []
        for entry in self._forbidden_visual_overlays:
            expires_at = float(entry.get('expires_at', 0.0) or 0.0)
            if expires_at > now:
                remaining.append(entry)
        self._forbidden_visual_overlays = remaining

    def _append_forbidden_visual(self, rect: tuple[float, float, float, float], match_rect: Optional[tuple[float, float, float, float]], now: float) -> None:
        entry = {
            'rect': rect,
            'match_rect': match_rect,
            'expires_at': now + FORBIDDEN_GLYPH_VISUAL_HOLD_SEC,
        }
        self._forbidden_visual_overlays.append(entry)
        if len(self._forbidden_visual_overlays) > 6:
            self._forbidden_visual_overlays = self._forbidden_visual_overlays[-6:]

    # [NEW] 금지몬스터 감지 히스토리 기록 함수
    def _append_forbidden_detection_log(self, monsters: List[dict], ts: float) -> None:
        # 데이터 관리자에서 공격 금지 맵을 가져옴
        fmap: dict[str, bool] = {}
        if self.data_manager and hasattr(self.data_manager, 'get_monster_attack_forbidden_map'):
            try:
                fmap = self.data_manager.get_monster_attack_forbidden_map() or {}
            except Exception:
                fmap = {}
        forbidden_set = {name for name, enabled in fmap.items() if enabled}
        if not forbidden_set:
            return

        # 각 탐지 항목 중 금지 대상 + 신뢰도 임계 통과하는 최고 항목만 1건 기록(스팸 방지)
        best_entry: Optional[tuple[str, float]] = None
        for item in (monsters or []):
            if not isinstance(item, dict):
                continue
            if str(item.get('source') or 'yolo') != 'yolo':
                continue
            cname = str(item.get('class_name') or '')
            if not cname or cname not in forbidden_set:
                continue
            try:
                score = float(item.get('score', 0.0))
            except (TypeError, ValueError):
                continue
            # 임계치: 개별 오버라이드 우선, 없으면 전역 몬스터 신뢰도
            try:
                class_id = int(item.get('class_id', -1))
            except (TypeError, ValueError):
                class_id = -1
            try:
                overrides = getattr(self, '_active_monster_confidence_overrides', {}) or {}
                if class_id in overrides:
                    threshold = float(overrides.get(class_id, 0.0))
                else:
                    threshold = float(self.conf_monster_spinbox.value()) if hasattr(self, 'conf_monster_spinbox') else 0.85
            except Exception:
                threshold = 0.85
            thr = max(0.05, min(0.95, float(threshold)))
            if score < thr:
                continue
            if best_entry is None or score > best_entry[1]:
                best_entry = (cname, score)

        if best_entry is None:
            return

        # 너무 잦은 기록 방지(최소 1초 간격)
        try:
            last_ts = float(getattr(self, '_forbidden_detect_last_log_ts', 0.0) or 0.0)
        except Exception:
            last_ts = 0.0
        if ts - last_ts < 1.0:
            return
        self._forbidden_detect_last_log_ts = float(ts)

        # "리치 (0.94) 13:33:23" 형식으로 저장
        name, score = best_entry
        try:
            import time as _t
            timetext = _t.strftime("%H:%M:%S", _t.localtime(ts))
        except Exception:
            timetext = "--:--:--"
        entry_text = f"{name} ({score:.2f}) {timetext}"

        try:
            hist = getattr(self, '_forbidden_detect_history', None)
            if not isinstance(hist, list):
                hist = []
            hist.append(entry_text)
            # 길이 제한(최근 50개)
            if len(hist) > 50:
                del hist[: len(hist) - 50]
            self._forbidden_detect_history = hist
        except Exception:
            pass

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
            # [Sticky Facing] 전/후 비대칭 모드에서는 마지막 방향을 유지한다.
            # 따라서 리셋 타이머를 예약하지 않는다.
            do_schedule = self._is_detection_active()
            try:
                if getattr(self, 'facing_range_checkbox', None) and self.facing_range_checkbox.isChecked():
                    do_schedule = False
            except Exception:
                pass
            if do_schedule:
                self._schedule_facing_reset()

    def _select_reference_character_box(self, boxes: List[DetectionBox]) -> DetectionBox:
        return max(boxes, key=lambda box: box.score)

    def _compute_hunt_area_rect(self, character_box: DetectionBox) -> AreaRect:
        height = max(1.0, float(self.y_band_height_spinbox.value()))
        offset = float(self.y_band_offset_spinbox.value())
        base_y = character_box.bottom
        top = base_y - height + offset

        mode_on = bool(getattr(self, 'facing_range_checkbox', None) and self.facing_range_checkbox.isChecked())
        facing = getattr(self, 'last_facing', None)

        if mode_on and facing in ('left', 'right'):
            front = max(0.0, float(self.enemy_front_spinbox.value()))
            back = max(0.0, float(self.enemy_back_spinbox.value()))
            width = max(1.0, front + back)
            if facing == 'left':
                x = character_box.center_x - front
            else:  # 'right'
                x = character_box.center_x - back
            return AreaRect(x=x, y=top, width=width, height=height)

        # 폴백: 대칭 처리 (전/후 중 큰 값을 반경으로 사용)
        radius_x = float(self.enemy_range_spinbox.value())
        if mode_on:
            try:
                fb_max = max(
                    max(0.0, float(self.enemy_front_spinbox.value())),
                    max(0.0, float(self.enemy_back_spinbox.value())),
                )
                radius_x = max(radius_x, fb_max)
            except Exception:
                pass
        width = max(1.0, radius_x * 2.0)
        return AreaRect(x=character_box.center_x - radius_x, y=top, width=width, height=height)

    def _compute_primary_skill_rect(self, character_box: DetectionBox, hunt_area: AreaRect) -> Optional[AreaRect]:
        mode_on = bool(getattr(self, 'facing_range_checkbox', None) and self.facing_range_checkbox.isChecked())
        facing = getattr(self, 'last_facing', None)

        if mode_on and facing in ('left', 'right'):
            front = max(0.0, float(self.primary_front_spinbox.value()))
            back = max(0.0, float(self.primary_back_spinbox.value()))
            width = max(1.0, front + back)
            if width <= 1.0:
                # 최소 폭 보장(후방 0 허용)
                width = 1.0
            if facing == 'left':
                x = character_box.center_x - front
            else:
                x = character_box.center_x - back
            return AreaRect(x=x, y=hunt_area.y, width=width, height=hunt_area.height)

        # 폴백: 대칭 처리 (전/후 중 큰 값을 반경으로 사용)
        radius = float(self.primary_skill_range_spinbox.value())
        if mode_on:
            try:
                fb_max = max(
                    max(0.0, float(self.primary_front_spinbox.value())),
                    max(0.0, float(self.primary_back_spinbox.value())),
                )
                radius = max(radius, fb_max)
            except Exception:
                pass
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
            # [Sticky Facing] 전/후 비대칭 모드에서는 방향 리셋을 예약하지 않는다.
            try:
                if not (getattr(self, 'facing_range_checkbox', None) and self.facing_range_checkbox.isChecked()):
                    self._schedule_facing_reset()
            except Exception:
                self._schedule_facing_reset()
        self._sync_detection_thread_status()
        if save and not from_direction:
            self._save_settings()

    # ----------------------- 로그 포맷 유틸 -----------------------
    def _is_metric_parentheses_enabled(self) -> bool:
        cb = getattr(self, 'metric_parentheses_checkbox', None)
        if cb is not None:
            return bool(cb.isChecked())
        return bool(getattr(self, '_metric_format_parentheses', True))

    def _format_metric(self, label: str, value: int, threshold: int, *, ready: bool | None = None) -> str:
        try:
            v = int(value)
            t = int(threshold)
        except Exception:
            v = value
            t = threshold
        if t <= 0:
            # 기준 미사용 시 단순 표기
            return f"{label} {v}마리"
        if ready is None:
            ready = v >= t
        if self._is_metric_parentheses_enabled():
            suffix = "충족" if ready else "부족"
            return f"{label} {v}(기준 {t}) {suffix}"
        else:
            comp = "≥" if ready else "<"
            return f"{label} {v}마리 {comp} 기준 {t}"

    def _format_current_ranges_lr(self) -> str:
        """사냥범위/주 스킬 범위의 좌/우 값을 한 줄 문자열로 반환한다.
        - 전/후(방향 기반) 모드에서는 캐릭터 방향에 따라 좌=back/우=front 또는 좌=front/우=back 매핑
        - 대칭 모드에서는 좌=우=반경
        """
        try:
            mode_on = bool(getattr(self, 'facing_range_checkbox', None) and self.facing_range_checkbox.isChecked())
            facing = getattr(self, 'last_facing', None)
            # 사냥범위 좌/우
            if mode_on and facing in ('left', 'right'):
                e_front = int(self.enemy_front_spinbox.value()) if hasattr(self, 'enemy_front_spinbox') else int(self.enemy_range_spinbox.value())
                e_back = int(self.enemy_back_spinbox.value()) if hasattr(self, 'enemy_back_spinbox') else int(self.enemy_range_spinbox.value())
                if facing == 'left':
                    e_left, e_right = e_front, e_back
                else:
                    e_left, e_right = e_back, e_front
            else:
                r = int(self.enemy_range_spinbox.value())
                e_left = e_right = r

            # 주 스킬 좌/우
            if mode_on and facing in ('left', 'right'):
                p_front = int(self.primary_front_spinbox.value()) if hasattr(self, 'primary_front_spinbox') else int(self.primary_skill_range_spinbox.value())
                p_back = int(self.primary_back_spinbox.value()) if hasattr(self, 'primary_back_spinbox') else int(self.primary_skill_range_spinbox.value())
                if facing == 'left':
                    p_left, p_right = p_front, p_back
                else:
                    p_left, p_right = p_back, p_front
            else:
                pr = int(self.primary_skill_range_spinbox.value())
                p_left = p_right = pr

            return f"사냥범위(좌 {e_left}, 우 {e_right}) · 주 스킬(좌 {p_left}, 우 {p_right})"
        except Exception:
            return ""

    # -------------------- 사다리 위협 전용 보조 --------------------
    def _apply_ladder_threat_range_override(self) -> None:
        """사다리 위협 사유로 권한 획득 시, 사냥 X범위를 일시적으로 (주변범위+20)으로 설정한다.

        - 비대칭 모드일 경우 전/후 모두 동일 값으로 덮어써 효과를 일관되게 한다.
        - 설정 파일에는 백업값을 저장하여 일시 변경이 영구 저장되지 않도록 한다.
        """
        try:
            if self._ladder_override_active:
                return
            near_px = int(self.ladder_near_px_spinbox.value()) if hasattr(self, 'ladder_near_px_spinbox') else 250
            override_val = max(1, int(near_px) + 20)

            # 백업 스냅샷
            mode = 'facing' if (hasattr(self, 'facing_range_checkbox') and self.facing_range_checkbox.isChecked()) else 'symmetric'
            backup = {
                'mode': mode,
                'enemy_range': int(self.enemy_range_spinbox.value()) if hasattr(self, 'enemy_range_spinbox') else 0,
                'enemy_front': int(self.enemy_front_spinbox.value()) if hasattr(self, 'enemy_front_spinbox') else 0,
                'enemy_back': int(self.enemy_back_spinbox.value()) if hasattr(self, 'enemy_back_spinbox') else 0,
                'primary_range': int(self.primary_skill_range_spinbox.value()) if hasattr(self, 'primary_skill_range_spinbox') else 0,
                'primary_front': int(self.primary_front_spinbox.value()) if hasattr(self, 'primary_front_spinbox') else 0,
                'primary_back': int(self.primary_back_spinbox.value()) if hasattr(self, 'primary_back_spinbox') else 0,
            }
            self._ladder_override_backup = backup

            # 적용: 현재 모드 유지한 채 사냥 X범위만 덮어쓰기
            if hasattr(self, 'facing_range_checkbox') and self.facing_range_checkbox.isChecked():
                if hasattr(self, 'enemy_front_spinbox'):
                    self.enemy_front_spinbox.setValue(override_val)
                if hasattr(self, 'enemy_back_spinbox'):
                    self.enemy_back_spinbox.setValue(override_val)
            else:
                if hasattr(self, 'enemy_range_spinbox'):
                    self.enemy_range_spinbox.setValue(override_val)

            self._ladder_override_active = True
            # 즉시 오버레이 반영
            try:
                self._emit_area_overlays()
            except Exception:
                pass
            self.append_log(f"[사다리] 주변범위+20 적용: X범위={override_val}px", 'info')
        except Exception:
            pass

    def _revert_ladder_threat_range_override(self) -> None:
        """사다리 위협 오버라이드를 원래 값으로 복원한다."""
        try:
            if not self._ladder_override_active:
                return
            snap = self._ladder_override_backup or {}
            # 복원
            if 'enemy_range' in snap and hasattr(self, 'enemy_range_spinbox'):
                self.enemy_range_spinbox.setValue(int(snap.get('enemy_range', self.enemy_range_spinbox.value())))
            if 'enemy_front' in snap and hasattr(self, 'enemy_front_spinbox'):
                self.enemy_front_spinbox.setValue(int(snap.get('enemy_front', self.enemy_front_spinbox.value())))
            if 'enemy_back' in snap and hasattr(self, 'enemy_back_spinbox'):
                self.enemy_back_spinbox.setValue(int(snap.get('enemy_back', self.enemy_back_spinbox.value())))
            # 모드는 변경하지 않는다(사용자 의도 유지)
            self._ladder_override_active = False
            self._ladder_override_backup = None
            try:
                self._emit_area_overlays()
            except Exception:
                pass
            self.append_log("[사다리] X범위 오버라이드 해제", 'info')
        except Exception:
            pass

    def _is_monster_near_character(self, radius_px: int) -> bool:
        """사냥탭의 X 반경(radius_px)과 Y 밴드 높이(y_band_height_spinbox)를 사용해 근접 위협을 판정.

        - X축: 캐릭터 중심 기준 abs(mx - cx) <= radius_px
        - Y축: 사냥 Y 밴드(top ~ top+height) 내부인지 확인
        """
        try:
            if not self.latest_snapshot or not self.latest_snapshot.character_boxes or not self.latest_snapshot.monster_boxes:
                return False
            character_box = self._select_reference_character_box(self.latest_snapshot.character_boxes)
            if not character_box:
                return False
            cx = float(character_box.center_x)
            # 사냥 밴드 Y 범위 계산(사냥 범위 계산과 동일 방식)
            height = max(1.0, float(self.y_band_height_spinbox.value())) if hasattr(self, 'y_band_height_spinbox') else 40.0
            offset = float(self.y_band_offset_spinbox.value()) if hasattr(self, 'y_band_offset_spinbox') else 0.0
            base_y = float(character_box.bottom)
            top = base_y - height + offset
            bottom = top + height
            rx = float(max(1, int(radius_px)))
            for m in self.latest_snapshot.monster_boxes:
                mx = float(m.x + m.width / 2.0)
                my = float(m.y + m.height / 2.0)
                if abs(mx - cx) <= rx and top <= my <= bottom:
                    return True
            return False
        except Exception:
            return False

    def _maybe_request_ladder_threat_cleanup(self) -> bool:
        """사다리 접근 중(맵 상태) + HP<임계 + 근접 위협(≥1) 시 사냥 권한 요청.
        반환값: 요청을 발행했으면 True, 아니면 False
        """
        try:
            # 기능 비활성화 시 동작 안 함
            if hasattr(self, 'ladder_threat_enable_checkbox') and not self.ladder_threat_enable_checkbox.isChecked():
                return False
            if self.current_authority == 'hunt':
                return False
            if not getattr(self, 'map_link_enabled', False):
                return False
            if self._request_pending:
                return False
            # 맵 상태: 사다리 접근/등반 맥락에서만
            map_tab = getattr(self, 'map_tab', None)
            nav = str(getattr(map_tab, 'navigation_action', '') or '') if map_tab else ''
            on_ladder = str(getattr(map_tab, 'player_state', '') or '')
            allowed_nav = {'align_for_climb', 'prepare_to_climb', 'climb_in_progress'}
            if not (nav in allowed_nav or on_ladder in {'climbing_up', 'climbing_down', 'on_ladder_idle'}):
                return False
            # HP 조건
            hp_val = None
            try:
                hp_val = float(self._status_display_values.get('hp'))
            except Exception:
                hp_val = None
            if not isinstance(hp_val, (int, float)):
                return False
            hp_thr = int(self.ladder_hp_threshold_spinbox.value()) if hasattr(self, 'ladder_hp_threshold_spinbox') else 90
            if not (hp_val < float(hp_thr)):
                return False
            # [추가] 맵 기준 사다리 근접(px) 판정
            try:
                tol_px = int(self.ladder_near_px_spinbox.value()) if hasattr(self, 'ladder_near_px_spinbox') else 15
            except Exception:
                tol_px = 15
            try:
                pos = getattr(map_tab, 'smoothed_player_pos', None) or getattr(map_tab, 'last_player_pos', None)
                transition_objects = (getattr(map_tab, 'geometry_data', {}) or {}).get('transition_objects', [])
                current_floor = getattr(map_tab, 'current_player_floor', None)
                is_near_ladder = False
                if pos is not None and hasattr(map_tab, '_check_near_ladder') and transition_objects:
                    result = map_tab._check_near_ladder(
                        pos,
                        transition_objects,
                        float(tol_px),
                        return_dist=True,
                        current_floor=current_floor,
                    )
                    is_near_ladder = bool(result[0]) if isinstance(result, tuple) and len(result) >= 1 else False
                if not is_near_ladder:
                    return False
            except Exception:
                return False

            # [변경] 근접 위협 대신 '주 스킬 범위 내' 마릿수 ≥ 1을 조건으로 사용
            if int(self.latest_primary_monster_count) < 1:
                return False
            # 권한 요청(사유 코드는 유지, 표시 문구는 포맷터에서 한글화)
            self.request_control("LADDER_THREAT_CLEANUP")
            return True
        except Exception:
            return False
        except Exception:
            return ""

    def _maybe_request_ladder_prepare_purge(self) -> bool:
        """맵이 사다리 오르기 준비 중이고(prepare_to_climb), HP≤임계, 주 스킬 범위 내 ≥1일 때 purge 권한 요청.
        반환값: 요청을 발행했으면 True, 아니면 False
        """
        try:
            # 기능 토글 사용(기존 토글 재활용)
            if hasattr(self, 'ladder_threat_enable_checkbox') and not self.ladder_threat_enable_checkbox.isChecked():
                return False
            if self.current_authority == 'hunt':
                return False
            if not getattr(self, 'map_link_enabled', False):
                return False
            if self._request_pending:
                return False
            # 맵 상태: 오르기 "준비" 상태로 한정
            map_tab = getattr(self, 'map_tab', None)
            nav = str(getattr(map_tab, 'navigation_action', '') or '') if map_tab else ''
            if nav != 'prepare_to_climb':
                return False
            # HP 조건: 설정값 이하(≤)
            hp_val = None
            try:
                hp_val = float(self._status_display_values.get('hp'))
            except Exception:
                hp_val = None
            if not isinstance(hp_val, (int, float)):
                return False
            hp_thr = int(self.ladder_hp_threshold_spinbox.value()) if hasattr(self, 'ladder_hp_threshold_spinbox') else 90
            if not (hp_val <= float(hp_thr)):
                return False
            # 주 스킬 범위 내 마릿수 ≥ 1
            if int(self.latest_primary_monster_count) < 1:
                return False
            # 권한 요청(새 사유 코드)
            self.request_control("LADDER_PREPARE_PURGE")
            return True
        except Exception:
            return False

    def _get_latest_map_snapshot_payload(self) -> Optional[dict]:
        """권한 매니저의 최신 맵 스냅샷을 payload(dict) 형태로 가져온다.
        사용가능 시 as_payload()를 반환, 없으면 None.
        """
        try:
            manager = self._authority_manager
            # 내부 헬퍼 접근(가용 시)
            if hasattr(manager, '_get_map_snapshot'):
                snap = manager._get_map_snapshot()
                if snap:
                    return snap.as_payload()
        except Exception:
            pass
        return None

    def _format_character_state_for_log(self, map_snapshot: Optional[dict]) -> str:
        """캐릭터 상태 요약을 한 줄로 구성한다(문장 없이).
        포함 후보: 층, 상태, 이동, 방향
        """
        parts: list[str] = []
        # 층
        try:
            if map_snapshot and map_snapshot.get('floor') is not None:
                parts.append(f"층 {int(map_snapshot['floor'])}")
        except Exception:
            pass
        # 상태
        state_ko = None
        if map_snapshot and isinstance(map_snapshot.get('player_state'), str):
            ps = map_snapshot.get('player_state')
            mapping = {
                'idle': '대기',
                'on_terrain': '지면',
                'jumping': '점프',
                'falling': '낙하',
                'climbing_up': '오르기',
                'climbing_down': '내리기',
                'on_ladder_idle': '사다리 대기',
            }
            state_ko = mapping.get(ps, None)
            if state_ko:
                parts.append(f"상태 {state_ko}")
        # 이동
        if map_snapshot and isinstance(map_snapshot.get('navigation_action'), str):
            na = map_snapshot.get('navigation_action')
            mapping = {
                'move_to_target': '이동',
                'prepare_to_down_jump': '하강 준비',
                'prepare_to_climb': '오르기 준비',
                'align_for_climb': '정렬',
                'climb_in_progress': '오르기 중',
                'idle': '대기',
            }
            nav_ko = mapping.get(na, None)
            if nav_ko:
                parts.append(f"행동 {nav_ko}")
        # 방향
        facing = None
        if self.last_facing in ('left', 'right'):
            facing = self.last_facing
        elif getattr(self, '_direction_last_side', None) in ('left', 'right'):
            facing = getattr(self, '_direction_last_side')
        if facing:
            parts.append(f"방향 {'좌' if facing == 'left' else '우'}")

        return ("캐릭터(" + ", ".join(parts) + ")") if parts else "캐릭터(정보 없음)"

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

    def _load_forbidden_glyph_resources(self) -> None:
        self._forbidden_glyph_config = {}
        self._forbidden_glyph_templates = []
        self._forbidden_glyph_threshold = 0.70
        if not self.data_manager or not hasattr(self.data_manager, 'get_forbidden_glyph_config'):
            return
        try:
            cfg = self.data_manager.get_forbidden_glyph_config()
            templates = self.data_manager.list_forbidden_glyph_templates()
        except Exception as exc:
            self.append_log(f"금지 문양 템플릿을 불러오지 못했습니다: {exc}", 'warn')
            return
        if isinstance(cfg, dict):
            self._forbidden_glyph_config = cfg
            try:
                thr = float(cfg.get('match_threshold', 0.70))
            except (TypeError, ValueError):
                thr = 0.70
            self._forbidden_glyph_threshold = max(0.50, min(0.95, thr))
            try:
                bias = float(cfg.get('vertical_bias_ratio', 0.0))
            except (TypeError, ValueError):
                bias = 0.0
            self._forbidden_glyph_vertical_bias = max(-1.0, min(1.0, bias))
        else:
            self._forbidden_glyph_vertical_bias = 0.0
        loaded_templates: list[dict] = []
        for entry in templates if isinstance(templates, list) else []:
            if not isinstance(entry, dict):
                continue
            path = entry.get('path')
            if not path or not os.path.exists(path):
                continue
            image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if image is None or image.size == 0:
                continue
            tpl = dict(entry)
            tpl['image'] = image
            tpl['height'], tpl['width'] = image.shape[:2]
            loaded_templates.append(tpl)
        self._forbidden_glyph_templates = loaded_templates

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
            self._nameplate_apply_facing = bool(self._nameplate_config.get('apply_facing', False))
        except Exception:
            self._nameplate_apply_facing = False
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
            # 캐릭터 방향 적용 상태 반영(없으면 기존 유지)
            try:
                self._nameplate_apply_facing = bool(payload.get('apply_facing', self._nameplate_apply_facing))
            except Exception:
                pass
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

    def _handle_nickname_config_updated(self, config: dict) -> None:
        if not isinstance(config, dict):
            return
        self._nickname_config = config
        templates: list[dict] = []
        try:
            templates = self.data_manager.list_nickname_templates() if self.data_manager else []
        except Exception:
            templates = self._nickname_templates
        else:
            self._nickname_templates = templates if isinstance(templates, list) else []

        if self.detection_thread and self.detection_thread.isRunning():
            try:
                if hasattr(self.detection_thread, 'update_nickname_config'):
                    self.detection_thread.update_nickname_config(self._nickname_config or {})
            except Exception:
                pass
            try:
                if hasattr(self.detection_thread, 'reload_nickname_templates'):
                    payload = self._nickname_templates if isinstance(self._nickname_templates, list) else []
                    self.detection_thread.reload_nickname_templates(payload)
            except Exception:
                pass

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
        if hasattr(self.data_manager, 'register_nickname_config_listener'):
            try:
                self.data_manager.register_nickname_config_listener(self._handle_nickname_config_updated)
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
        self._load_forbidden_glyph_resources()
        self._load_nameplate_configuration()
        # [신규] 탈출 명령프로필 콤보 갱신
        try:
            self._refresh_ladder_escape_profile_options(keep_selection=True)
        except Exception:
            pass
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
        # [신규] 현재 활성 맵 프로필 동기화(최초 1회)
        try:
            profile = getattr(map_tab, 'active_profile_name', None)
            if isinstance(profile, str) and profile:
                self.map_active_profile_changed(profile)
        except Exception:
            pass
        try:
            self._refresh_map_return_profile_options()
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
            # 전/후 비대칭 모드 및 값 로드
            try:
                mode = str(ranges.get('mode', 'symmetric')).strip().lower()
            except Exception:
                mode = 'symmetric'
            if hasattr(self, 'facing_range_checkbox'):
                self.facing_range_checkbox.setChecked(mode == 'facing')
                # 새 필드가 없으면 기존 대칭 값으로 초기화
                enemy_default = int(ranges.get('enemy_range', self.enemy_range_spinbox.value()))
                primary_default = int(ranges.get('primary_range', self.primary_skill_range_spinbox.value()))
                if hasattr(self, 'enemy_front_spinbox'):
                    self.enemy_front_spinbox.setValue(int(ranges.get('enemy_front', enemy_default)))
                if hasattr(self, 'enemy_back_spinbox'):
                    self.enemy_back_spinbox.setValue(int(ranges.get('enemy_back', enemy_default)))
                if hasattr(self, 'primary_front_spinbox'):
                    self.primary_front_spinbox.setValue(int(ranges.get('primary_front', primary_default)))
                if hasattr(self, 'primary_back_spinbox'):
                    self.primary_back_spinbox.setValue(int(ranges.get('primary_back', primary_default)))
                # UI 상태 즉시 반영
                self._update_range_inputs_enabled(self.facing_range_checkbox.isChecked())

        confidence = data.get('confidence', {})
        if confidence:
            self.conf_char_spinbox.setValue(float(confidence.get('char', self.conf_char_spinbox.value())))
            self.conf_monster_spinbox.setValue(float(confidence.get('monster', self.conf_monster_spinbox.value())))

        conditions = data.get('conditions', {})
        if conditions:
            hunt_threshold_val = conditions.get('hunt_monster_threshold')
            primary_threshold_val = conditions.get('primary_monster_threshold')
            legacy_threshold_val = conditions.get('monster_threshold')
            cleanup_grace_ms = conditions.get('cleanup_grace_ms')

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

            try:
                if cleanup_grace_ms is not None and hasattr(self, 'cleanup_grace_spinbox'):
                    self.cleanup_grace_spinbox.setValue(int(cleanup_grace_ms))
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

            # [NEW] 확장사냥 모드 로드
            try:
                if hasattr(self, 'expanded_hunt_checkbox'):
                    self.expanded_hunt_checkbox.setChecked(bool(conditions.get('expanded_hunt', False)))
            except Exception:
                pass

        # 사다리 위협 설정 로드
        ladder_cfg = data.get('ladder_threat', {})
        if isinstance(ladder_cfg, dict):
            try:
                near_px = ladder_cfg.get('near_px')
                if near_px is not None and hasattr(self, 'ladder_near_px_spinbox'):
                    val = int(near_px)
                    # 마이그레이션: 기존(사냥탭 기준) 큰 값(예: 220, 250 등)을 맵 기준 15px로 변환
                    if val > 200:
                        val = 15
                    self.ladder_near_px_spinbox.setValue(val)
            except Exception:
                pass
            try:
                hp_percent = ladder_cfg.get('hp_percent')
                if hp_percent is not None and hasattr(self, 'ladder_hp_threshold_spinbox'):
                    self.ladder_hp_threshold_spinbox.setValue(int(hp_percent))
            except Exception:
                pass
            try:
                enabled = ladder_cfg.get('enabled')
                if enabled is not None and hasattr(self, 'ladder_threat_enable_checkbox'):
                    self.ladder_threat_enable_checkbox.setChecked(bool(enabled))
            except Exception:
                pass

        # [신규] 사다리/점프/낙하 지속 시 탈출 설정 로드
        ladder_escape_cfg = data.get('ladder_escape', {})
        if isinstance(ladder_escape_cfg, dict):
            try:
                enabled = bool(ladder_escape_cfg.get('enabled', False))
                if hasattr(self, 'ladder_escape_enabled_checkbox'):
                    self.ladder_escape_enabled_checkbox.setChecked(enabled)
            except Exception:
                pass
            # 콤보 목록 갱신 후 선택
            try:
                self._refresh_ladder_escape_profile_options(keep_selection=False)
                cmd = str(ladder_escape_cfg.get('command_profile') or '').strip()
                if cmd:
                    idx = self.ladder_escape_profile_combo.findData(cmd)
                    if idx >= 0:
                        self.ladder_escape_profile_combo.setCurrentIndex(idx)
                    else:
                        # 목록에 없으면 임시 추가
                        self.ladder_escape_profile_combo.addItem(cmd, cmd)
                        self.ladder_escape_profile_combo.setCurrentIndex(self.ladder_escape_profile_combo.findData(cmd))
                else:
                    # 기본값: 사다리 멈춤복구
                    idx = self.ladder_escape_profile_combo.findData("사다리 멈춤복구")
                    if idx >= 0:
                        self.ladder_escape_profile_combo.setCurrentIndex(idx)
            except Exception:
                pass
            try:
                thr = float(ladder_escape_cfg.get('threshold_sec', 2.0) or 2.0)
                if hasattr(self, 'ladder_escape_threshold_spinbox'):
                    self.ladder_escape_threshold_spinbox.setValue(max(0.5, min(10.0, thr)))
            except Exception:
                pass
            try:
                cd = float(ladder_escape_cfg.get('cooldown_sec', 3.0) or 3.0)
                if hasattr(self, 'ladder_escape_cooldown_spinbox'):
                    self.ladder_escape_cooldown_spinbox.setValue(max(0.5, min(30.0, cd)))
            except Exception:
                pass
            try:
                states = ladder_escape_cfg.get('states') or {}
                if hasattr(self, 'ladder_escape_include_jump_checkbox'):
                    self.ladder_escape_include_jump_checkbox.setChecked(bool(states.get('include_jump', True)))
                if hasattr(self, 'ladder_escape_include_ladder_checkbox'):
                    self.ladder_escape_include_ladder_checkbox.setChecked(bool(states.get('include_ladder', True)))
                if hasattr(self, 'ladder_escape_include_fall_checkbox'):
                    self.ladder_escape_include_fall_checkbox.setChecked(bool(states.get('include_fall', True)))
            except Exception:
                pass
            try:
                self._update_ladder_escape_controls(self.ladder_escape_enabled_checkbox.isChecked())
            except Exception:
                pass

        display = data.get('display', {})
        if display:
            show_hunt = bool(display.get('show_hunt_area', self.show_hunt_area_checkbox.isChecked()))
            show_primary = bool(display.get('show_primary_area', self.show_primary_skill_checkbox.isChecked()))
            show_cleanup_chase = bool(display.get('show_cleanup_chase_area', getattr(self, 'show_cleanup_chase_checkbox').isChecked() if hasattr(self, 'show_cleanup_chase_checkbox') else True))
            show_cluster_window = bool(display.get('show_cluster_window_area', getattr(self, 'show_cluster_window_checkbox').isChecked() if hasattr(self, 'show_cluster_window_checkbox') else True))
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
            metric_parentheses = bool(display.get('metric_parentheses', True))
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
            if hasattr(self, 'show_cleanup_chase_checkbox'):
                self.show_cleanup_chase_checkbox.setChecked(show_cleanup_chase)
            if hasattr(self, 'show_cluster_window_checkbox'):
                self.show_cluster_window_checkbox.setChecked(show_cluster_window)
            self.show_direction_checkbox.setChecked(show_direction)
            self.show_nickname_range_checkbox.setChecked(show_nickname_range)
            self.show_nameplate_checkbox.setChecked(show_nameplate)
            if hasattr(self, 'show_nameplate_tracking_checkbox'):
                self.show_nameplate_tracking_checkbox.setChecked(show_nameplate_tracking)
            if hasattr(self, 'show_monster_confidence_checkbox'):
                self.show_monster_confidence_checkbox.setChecked(show_monster_confidence)
            if hasattr(self, 'metric_parentheses_checkbox'):
                self.metric_parentheses_checkbox.setChecked(metric_parentheses)
            self._metric_format_parentheses = metric_parentheses
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

        map_return_cfg = data.get('map_return', {})
        if isinstance(map_return_cfg, dict):
            self.map_return_enabled = bool(map_return_cfg.get('enabled', False))
            try:
                self.map_return_interval_sec = max(0.5, float(map_return_cfg.get('interval_sec', self.map_return_interval_sec)))
            except (TypeError, ValueError):
                self.map_return_interval_sec = 3.0
            try:
                self.map_return_conf_threshold = float(map_return_cfg.get('conf_threshold', self.map_return_conf_threshold))
            except (TypeError, ValueError):
                self.map_return_conf_threshold = 0.0
            try:
                self.map_return_min_height = max(0, int(map_return_cfg.get('min_height', self.map_return_min_height)))
            except (TypeError, ValueError):
                self.map_return_min_height = 0
            try:
                self.map_return_max_height = max(0, int(map_return_cfg.get('max_height', self.map_return_max_height)))
            except (TypeError, ValueError):
                self.map_return_max_height = 0
            try:
                self.map_return_min_width = max(0, int(map_return_cfg.get('min_width', self.map_return_min_width)))
            except (TypeError, ValueError):
                self.map_return_min_width = 0
            try:
                self.map_return_max_width = max(0, int(map_return_cfg.get('max_width', self.map_return_max_width)))
            except (TypeError, ValueError):
                self.map_return_max_width = 0
            base_profile_val = map_return_cfg.get('base_profile', self.map_return_base_profile)
            base_keywords_val = map_return_cfg.get('base_keywords', self.map_return_base_keywords)
            if base_keywords_val in (None, ''):
                base_keywords_val = map_return_cfg.get('base_keyword', '')
            if base_profile_val in (None, ''):
                legacy_profile = map_return_cfg.get('base_keyword', '')
                if legacy_profile:
                    base_profile_val = legacy_profile
            self.map_return_base_profile = str(base_profile_val or '')
            self.map_return_base_keywords = str(base_keywords_val or '')
            try:
                self.map_return_telegram_limit = max(1, int(map_return_cfg.get('telegram_limit', self.map_return_telegram_limit)))
            except (TypeError, ValueError):
                self.map_return_telegram_limit = 5
            roi_payload = map_return_cfg.get('roi')
            self.map_return_roi = copy.deepcopy(roi_payload) if isinstance(roi_payload, dict) else None
            maps_cfg = map_return_cfg.get('maps', {})
            if isinstance(maps_cfg, dict):
                resolved: dict[str, dict] = {}
                for key, val in maps_cfg.items():
                    if not isinstance(key, str) or not key:
                        continue
                    if not isinstance(val, dict):
                        continue
                    resolved[key] = {
                        'profile': str(val.get('profile', '') or ''),
                        'waypoint_id': str(val.get('waypoint_id', '') or ''),
                        'waypoint_name': str(val.get('waypoint_name', '') or ''),
                        'command_profile': str(val.get('command_profile', '') or ''),
                        'keywords': str(val.get('keywords', '') or ''),
                    }
                self.map_return_registered_maps = resolved
            else:
                self.map_return_registered_maps = {}
        else:
            self.map_return_enabled = False
            self.map_return_registered_maps = {}
            self.map_return_roi = None
            self.map_return_interval_sec = 3.0
            self.map_return_conf_threshold = 0.0
            self.map_return_min_height = 0
            self.map_return_max_height = 0
            self.map_return_min_width = 0
            self.map_return_max_width = 0
            self.map_return_base_profile = ''
            self.map_return_base_keywords = ''
            self.map_return_telegram_limit = 5

        if hasattr(self, 'map_return_enable_checkbox'):
            blocker = QSignalBlocker(self.map_return_enable_checkbox)
            self.map_return_enable_checkbox.setChecked(self.map_return_enabled)
            del blocker
        if hasattr(self, 'map_return_interval_spin'):
            blocker = QSignalBlocker(self.map_return_interval_spin)
            self.map_return_interval_spin.setValue(self.map_return_interval_sec)
            del blocker
        if hasattr(self, 'map_return_conf_spin'):
            blocker = QSignalBlocker(self.map_return_conf_spin)
            self.map_return_conf_spin.setValue(self.map_return_conf_threshold)
            del blocker
        if hasattr(self, 'map_return_min_height_spin'):
            blocker = QSignalBlocker(self.map_return_min_height_spin)
            self.map_return_min_height_spin.setValue(self.map_return_min_height)
            del blocker
        if hasattr(self, 'map_return_max_height_spin'):
            blocker = QSignalBlocker(self.map_return_max_height_spin)
            self.map_return_max_height_spin.setValue(self.map_return_max_height)
            del blocker
        if hasattr(self, 'map_return_min_width_spin'):
            blocker = QSignalBlocker(self.map_return_min_width_spin)
            self.map_return_min_width_spin.setValue(self.map_return_min_width)
            del blocker
        if hasattr(self, 'map_return_max_width_spin'):
            blocker = QSignalBlocker(self.map_return_max_width_spin)
            self.map_return_max_width_spin.setValue(self.map_return_max_width)
            del blocker
        self._refresh_map_return_profile_options()
        if hasattr(self, 'map_return_base_keywords_line'):
            blocker = QSignalBlocker(self.map_return_base_keywords_line)
            self.map_return_base_keywords_line.setText(self.map_return_base_keywords)
            del blocker
        self._update_map_return_roi_summary()
        self._update_map_return_controls()
        self._map_return_geometry_cache.clear()
        self._update_map_return_timer_state()

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

            reservation_enabled = bool(auto_shutdown_cfg.get('reservation_enabled', False))
            if hasattr(self, 'shutdown_reservation_checkbox'):
                blocker = QSignalBlocker(self.shutdown_reservation_checkbox)
                self.shutdown_reservation_checkbox.setChecked(reservation_enabled)
                del blocker
            self.shutdown_reservation_enabled = reservation_enabled

            dt_epoch = auto_shutdown_cfg.get('reservation_epoch') or auto_shutdown_cfg.get('datetime_epoch')
            if dt_epoch is not None:
                try:
                    epoch_int = int(dt_epoch)
                    dt_value = QDateTime.fromSecsSinceEpoch(epoch_int)
                    blocker = QSignalBlocker(self.shutdown_datetime_edit)
                    self.shutdown_datetime_edit.setDateTime(dt_value)
                    del blocker
                except Exception:
                    pass

            now_ts = time.time()
            reservation_target = auto_shutdown_cfg.get('reservation_target')
            if reservation_target is None:
                reservation_target = auto_shutdown_cfg.get('datetime_target')
            if isinstance(reservation_target, (int, float)) and float(reservation_target) > now_ts:
                self.shutdown_datetime_target = float(reservation_target)

            action_key = str(auto_shutdown_cfg.get('other_action', 'game_exit') or 'game_exit').lower()
            if action_key not in {'game_exit', 'wait_mode', 'town_return'}:
                action_key = 'game_exit'
            self.shutdown_other_player_action = action_key

            exit_delay = auto_shutdown_cfg.get('other_exit_delay')
            if isinstance(exit_delay, (int, float)) and exit_delay > 0:
                self.shutdown_other_player_exit_delay = int(exit_delay)

            wait_delay = auto_shutdown_cfg.get('other_wait_delay')
            if isinstance(wait_delay, (int, float)) and wait_delay > 0:
                self.shutdown_other_player_wait_delay = int(wait_delay)
            else:
                legacy_minutes = auto_shutdown_cfg.get('other_minutes')
                if isinstance(legacy_minutes, (int, float)) and legacy_minutes > 0:
                    self.shutdown_other_player_wait_delay = int(legacy_minutes) * 60

            wait_clear_delay = auto_shutdown_cfg.get('other_wait_clear_delay')
            if isinstance(wait_clear_delay, (int, float)) and wait_clear_delay > 0:
                self.shutdown_other_player_wait_clear_delay = int(wait_clear_delay)

            # v2 스키마: 이전 저장값 무시(초기화) 후 새 구조 사용
            version = 0
            try:
                version = int(auto_shutdown_cfg.get('wait_waypoints_schema_version') or 0)
            except Exception:
                version = 0

            # 공통 초기값(분기 밖에서 참조하므로 미리 정의)
            loaded_waypoints: list[dict] = []

            if version < 2:
                # 기존에 저장된 대기 웨이포인트는 모두 폐기(새로 시작)
                self.shutdown_other_player_wait_waypoints_by_profile = {}
                self.shutdown_other_player_wait_waypoint_id = None
                self.shutdown_other_player_wait_waypoint_name = ''
                self.shutdown_other_player_wait_waypoints = []
            else:
                # 다중 웨이포인트 우선 로드
                waypoints_payload = auto_shutdown_cfg.get('other_wait_waypoints')
                if isinstance(waypoints_payload, list):
                    for entry in waypoints_payload:
                        if isinstance(entry, dict):
                            wp_id = str(entry.get('id') or '').strip()
                            if not wp_id:
                                continue
                            name = str(entry.get('name') or wp_id)
                            loaded_waypoints.append({'id': wp_id, 'name': name})
                        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                            wp_id = str(entry[1]).strip()
                            name = str(entry[0])
                            if wp_id:
                                loaded_waypoints.append({'id': wp_id, 'name': name})
                # 단일 필드(구버전)도 병합
                wait_wp_id = auto_shutdown_cfg.get('other_wait_waypoint_id')
                wait_wp_name = auto_shutdown_cfg.get('other_wait_waypoint_name')
                if wait_wp_id is not None and not loaded_waypoints:
                    wait_wp_id_str = str(wait_wp_id).strip()
                    if wait_wp_id_str:
                        loaded_waypoints = [{'id': wait_wp_id_str, 'name': str(wait_wp_name or wait_wp_id_str)}]
                # 프로필별 목록 로드(있으면 우선)
                by_profile_payload = auto_shutdown_cfg.get('other_wait_waypoints_by_profile')
                self.shutdown_other_player_wait_waypoints_by_profile = {}
                if isinstance(by_profile_payload, dict):
                    for k, v in by_profile_payload.items():
                        try:
                            profile_key = str(k)
                            items: list[dict] = []
                            if isinstance(v, list):
                                for entry in v:
                                    if isinstance(entry, dict):
                                        wp_id = str(entry.get('id') or '').strip()
                                        if not wp_id:
                                            continue
                                        name = str(entry.get('name') or wp_id)
                                        items.append({'id': wp_id, 'name': name})
                            if items:
                                self.shutdown_other_player_wait_waypoints_by_profile[profile_key] = items
                        except Exception:
                            continue

                # 상태에 반영(현재 활성 프로필 기준으로 뷰 선택)
                current_items = self._get_wait_waypoints_for_current_profile()
                if not current_items and loaded_waypoints:
                    # 프로필별 정보가 없으면 구버전 목록으로 초기화하되, 현재 프로필 키로 옮겨담는다.
                    self._set_wait_waypoints_for_current_profile(loaded_waypoints)
                    current_items = list(loaded_waypoints)
            # 구버전 단일 필드도 동기화
            if loaded_waypoints:
                self.shutdown_other_player_wait_waypoint_id = loaded_waypoints[0]['id']
                self.shutdown_other_player_wait_waypoint_name = loaded_waypoints[0]['name']
            else:
                self.shutdown_other_player_wait_waypoint_id = None
                self.shutdown_other_player_wait_waypoint_name = ''

            other_enabled = bool(auto_shutdown_cfg.get('other_enabled', False))
            if hasattr(self, 'shutdown_other_player_checkbox'):
                blocker = QSignalBlocker(self.shutdown_other_player_checkbox)
                self.shutdown_other_player_checkbox.setChecked(other_enabled)
                del blocker
            self.shutdown_other_player_enabled = other_enabled
            self.shutdown_other_player_detect_since = None
            self.shutdown_other_player_last_count = 0
            self.shutdown_other_player_due_ts = None

            # 동기화된 라디오 업데이트
            if hasattr(self, 'shutdown_other_player_action_group'):
                button_map = {
                    'game_exit': getattr(self, 'shutdown_other_player_radio_shutdown', None),
                    'wait_mode': getattr(self, 'shutdown_other_player_radio_wait', None),
                    'town_return': getattr(self, 'shutdown_other_player_radio_town', None),
                }
                button = button_map.get(self.shutdown_other_player_action)
                if button is not None:
                    blocker = QSignalBlocker(button)
                    button.setChecked(True)
                    del blocker

            self._update_other_player_action_summary()
            self._on_shutdown_reservation_toggled(self.shutdown_reservation_enabled)
            self._ensure_shutdown_timer_running()
            self._update_shutdown_labels()
            self._update_shutdown_labels()
            self._stop_shutdown_timer_if_idle()

            # [추가] 대기모드 체력회복 설정 로드(전역 속성)
            try:
                using = bool(auto_shutdown_cfg.get('wait_hp_enabled', False))
                thr_raw = auto_shutdown_cfg.get('wait_hp_threshold', 50)
                try:
                    thr_val = int(thr_raw)
                except Exception:
                    thr_val = 50
                thr_val = max(1, min(99, thr_val))
                cmd = str(auto_shutdown_cfg.get('wait_hp_command_profile', '') or '')

                setattr(self, 'wait_hp_enabled', using)
                setattr(self, 'wait_hp_threshold', thr_val)
                setattr(self, 'wait_hp_command_profile', cmd)
            except Exception:
                setattr(self, 'wait_hp_enabled', False)
                setattr(self, 'wait_hp_threshold', 50)
                setattr(self, 'wait_hp_command_profile', '')

            # [NEW] 대기모드 위치 복구(px) 로드
            try:
                rec_raw = auto_shutdown_cfg.get('wait_recover_threshold_px', 70)
                try:
                    rec_val = int(rec_raw)
                except Exception:
                    rec_val = 70
                rec_val = max(0, min(100, rec_val))
                setattr(self, 'wait_recover_threshold_px', rec_val)
            except Exception:
                setattr(self, 'wait_recover_threshold_px', 70)

        regions_data = data.get('manual_capture_regions', [])
        manual_regions: list[dict] = []
        window_geometry = get_maple_window_geometry()
        if isinstance(regions_data, list):
            for payload in regions_data:
                if not isinstance(payload, dict):
                    continue
                converted = ensure_relative_roi(payload, window_geometry, anchor_name=last_used_anchor_name())
                if converted is None:
                    continue
                manual_regions.append(copy.deepcopy(converted))

        legacy_region = data.get('manual_capture_region')
        if not manual_regions and isinstance(legacy_region, dict):
            converted_legacy = ensure_relative_roi(legacy_region, window_geometry, anchor_name=last_used_anchor_name())
            if converted_legacy:
                manual_regions = [copy.deepcopy(converted_legacy)]

        self.manual_capture_regions = manual_regions
        if self.manual_capture_regions:
            self.manual_capture_region = self._merge_manual_capture_regions()
        else:
            self.manual_capture_region = None

        profiles_payload = data.get('manual_area_profiles')
        parsed_profiles: dict[str, list[dict]] = {}
        active_profile_name: Optional[str] = None

        if isinstance(profiles_payload, dict):
            raw_profiles = profiles_payload.get('profiles')
            if isinstance(raw_profiles, dict):
                for raw_name, payload in raw_profiles.items():
                    if not isinstance(raw_name, str):
                        continue
                    normalized_name = raw_name.strip()
                    if not normalized_name or not isinstance(payload, list):
                        continue
                    converted_regions: list[dict] = []
                    for region_payload in payload:
                        if not isinstance(region_payload, dict):
                            continue
                        converted_region = ensure_relative_roi(
                            region_payload,
                            window_geometry,
                            anchor_name=last_used_anchor_name(),
                        )
                        if converted_region is None:
                            continue
                        converted_regions.append(copy.deepcopy(converted_region))
                    if converted_regions:
                        parsed_profiles[normalized_name] = converted_regions
            profile_candidate = profiles_payload.get('active')
            if isinstance(profile_candidate, str) and profile_candidate.strip():
                active_profile_name = profile_candidate.strip()

        self.manual_area_profiles = parsed_profiles
        self.active_area_profile = None

        if active_profile_name and active_profile_name in self.manual_area_profiles:
            applied = self._apply_area_profile(
                active_profile_name,
                emit_log=False,
                auto_save=False,
            )
            if applied:
                self.active_area_profile = active_profile_name

        self._update_manual_area_summary()
        self._notify_area_settings_changed()

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
                        use_direction=bool(item.get('use_direction', True)),
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
                        jump_attack_enabled=bool(item.get('jump_attack_enabled', False)),
                        jump_attack_distance_px=int(item.get('jump_attack_distance_px', 120)),
                        jump_attack_probability=int(item.get('jump_attack_probability', 50)),
                        jump_profile_left=str(item.get('jump_profile_left', '') or ''),
                        jump_profile_right=str(item.get('jump_profile_right', '') or ''),
                        jump_pre_delay_min=float(item.get('jump_pre_delay_min', 0.0)),
                        jump_pre_delay_max=float(item.get('jump_pre_delay_max', 0.0)),
                        jump_post_delay_min=float(item.get('jump_post_delay_min', 0.0)),
                        jump_post_delay_max=float(item.get('jump_post_delay_max', 0.0)),
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
        # [초기 동기화] 자동사냥 체크 상태로 루프 ON/OFF를 일치시킴
        try:
            self.set_auto_hunt_enabled(bool(self.auto_request_checkbox.isChecked()))
        except Exception:
            pass
        # [NEW] 금지몬스터 감지 설정 로드
        try:
            self._load_forbidden_monster_settings(data)
        except Exception:
            pass
        self._save_settings()

    def _load_forbidden_monster_settings(self, data: dict) -> None:
        """금지몬스터 감지 저장값 로드."""
        try:
            cfg = data.get('forbidden_monster', {}) if isinstance(data, dict) else {}
            enabled = bool(cfg.get('enabled', False))
            cmd = str(cfg.get('command_profile', '') or '')
            tg = bool(cfg.get('telegram_alert', False))
            self.forbidden_monster_enabled = enabled
            self.forbidden_monster_command_profile = cmd
            self.forbidden_monster_telegram_alert = tg
        except Exception:
            self.forbidden_monster_enabled = False
            self.forbidden_monster_command_profile = ''
            self.forbidden_monster_telegram_alert = False

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

        # [오버라이드 저장 정책]
        # - 오버라이드 중에는 백업(사용자 원래 설정) 값을 저장하여
        #   일시 변경값이 설정 파일에 남지 않도록 한다.
        snap = None
        if getattr(self, '_zone_override_active', False) and isinstance(getattr(self, '_zone_override_backup', None), dict):
            snap = self._zone_override_backup or {}
        elif getattr(self, '_ladder_override_active', False) and isinstance(getattr(self, '_ladder_override_backup', None), dict):
            snap = self._ladder_override_backup or {}

        if isinstance(snap, dict):
            try:
                mode_value = str(snap.get('mode', 'symmetric')).strip().lower()
            except Exception:
                mode_value = 'symmetric'
            ranges_data = {
                'enemy_range': int(snap.get('enemy_range', self.enemy_range_spinbox.value())),
                'y_band_height': int(snap.get('y_band_height', self.y_band_height_spinbox.value())) if 'y_band_height' in snap else int(self.y_band_height_spinbox.value()),
                'y_band_offset': int(snap.get('y_band_offset', self.y_band_offset_spinbox.value())) if 'y_band_offset' in snap else int(self.y_band_offset_spinbox.value()),
                'primary_range': int(snap.get('primary_range', self.primary_skill_range_spinbox.value())),
                'mode': mode_value,
                'enemy_front': int(snap.get('enemy_front', self.enemy_front_spinbox.value())) if hasattr(self, 'enemy_front_spinbox') else int(self.enemy_range_spinbox.value()),
                'enemy_back': int(snap.get('enemy_back', self.enemy_back_spinbox.value())) if hasattr(self, 'enemy_back_spinbox') else int(self.enemy_range_spinbox.value()),
                'primary_front': int(snap.get('primary_front', self.primary_front_spinbox.value())) if hasattr(self, 'primary_front_spinbox') else int(self.primary_skill_range_spinbox.value()),
                'primary_back': int(snap.get('primary_back', self.primary_back_spinbox.value())) if hasattr(self, 'primary_back_spinbox') else int(self.primary_skill_range_spinbox.value()),
            }
        else:
            ranges_data = {
                'enemy_range': self.enemy_range_spinbox.value(),
                'y_band_height': self.y_band_height_spinbox.value(),
                'y_band_offset': self.y_band_offset_spinbox.value(),
                'primary_range': self.primary_skill_range_spinbox.value(),
                'mode': 'facing' if (hasattr(self, 'facing_range_checkbox') and self.facing_range_checkbox.isChecked()) else 'symmetric',
                'enemy_front': int(self.enemy_front_spinbox.value()) if hasattr(self, 'enemy_front_spinbox') else int(self.enemy_range_spinbox.value()),
                'enemy_back': int(self.enemy_back_spinbox.value()) if hasattr(self, 'enemy_back_spinbox') else int(self.enemy_range_spinbox.value()),
                'primary_front': int(self.primary_front_spinbox.value()) if hasattr(self, 'primary_front_spinbox') else int(self.primary_skill_range_spinbox.value()),
                'primary_back': int(self.primary_back_spinbox.value()) if hasattr(self, 'primary_back_spinbox') else int(self.primary_skill_range_spinbox.value()),
            }

        if isinstance(snap, dict):
            hunt_threshold_save = int(snap.get('hunt_monster_threshold', self.hunt_monster_threshold_spinbox.value()))
            primary_threshold_save = int(snap.get('primary_monster_threshold', self.primary_monster_threshold_spinbox.value()))
            teleport_prob_save = int(snap.get('teleport_probability', self.teleport_settings.probability))
            walk_teleport_prob_save = float(snap.get('walk_teleport_probability', self.teleport_settings.walk_probability))
            teleport_enabled_save = bool(snap.get('teleport_enabled', self.teleport_enabled_checkbox.isChecked()))
            walk_teleport_enabled_save = bool(snap.get('walk_teleport_enabled', self.walk_teleport_checkbox.isChecked()))
        else:
            hunt_threshold_save = int(self.hunt_monster_threshold_spinbox.value())
            primary_threshold_save = int(self.primary_monster_threshold_spinbox.value())
            teleport_prob_save = int(self.teleport_settings.probability)
            walk_teleport_prob_save = float(self.teleport_settings.walk_probability)
            teleport_enabled_save = bool(self.teleport_enabled_checkbox.isChecked())
            walk_teleport_enabled_save = bool(self.walk_teleport_checkbox.isChecked())
        teleport_prob_save = max(0, min(100, int(teleport_prob_save)))
        walk_teleport_prob_save = max(0.0, min(100.0, float(walk_teleport_prob_save)))

        settings_data = {
            'ranges': ranges_data,
            'confidence': {
                'char': self.conf_char_spinbox.value(),
                'monster': self.conf_monster_spinbox.value(),
            },
            'conditions': {
                'hunt_monster_threshold': hunt_threshold_save,
                'primary_monster_threshold': primary_threshold_save,
                'monster_threshold': hunt_threshold_save,
                'cleanup_grace_ms': int(self.cleanup_grace_spinbox.value()) if hasattr(self, 'cleanup_grace_spinbox') else 0,
                'auto_request': self.auto_request_checkbox.isChecked(),
                'idle_release_sec': self.idle_release_spinbox.value(),
                'max_authority_hold_sec': self.max_authority_hold_spinbox.value(),
                'map_link_enabled': self.map_link_checkbox.isChecked(),
                'map_protect_sec': self.map_protect_spinbox.value(),
                'floor_hold_sec': self.floor_hold_spinbox.value(),
                'hunt_protect_sec': self.hunt_protect_spinbox.value(),
                'expanded_hunt': bool(self.expanded_hunt_checkbox.isChecked()) if hasattr(self, 'expanded_hunt_checkbox') else False,
            },
            'display': {
                'show_hunt_area': self.show_hunt_area_checkbox.isChecked(),
                'show_primary_area': self.show_primary_skill_checkbox.isChecked(),
                'show_cleanup_chase_area': bool(self.show_cleanup_chase_checkbox.isChecked()) if hasattr(self, 'show_cleanup_chase_checkbox') else True,
                'show_cluster_window_area': bool(self.show_cluster_window_checkbox.isChecked()) if hasattr(self, 'show_cluster_window_checkbox') else True,
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
                'metric_parentheses': bool(
                    self.metric_parentheses_checkbox.isChecked()
                ) if hasattr(self, 'metric_parentheses_checkbox') else bool(
                    getattr(self, '_metric_format_parentheses', True)
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
            'ladder_threat': {
                'enabled': bool(self.ladder_threat_enable_checkbox.isChecked()) if hasattr(self, 'ladder_threat_enable_checkbox') else True,
                'near_px': int(self.ladder_near_px_spinbox.value()) if hasattr(self, 'ladder_near_px_spinbox') else 250,
                'hp_percent': int(self.ladder_hp_threshold_spinbox.value()) if hasattr(self, 'ladder_hp_threshold_spinbox') else 90,
            },
            'ladder_escape': {
                'enabled': bool(getattr(self, 'ladder_escape_enabled_checkbox', None).isChecked()) if hasattr(self, 'ladder_escape_enabled_checkbox') else False,
                'command_profile': (self.ladder_escape_profile_combo.currentData() or '') if hasattr(self, 'ladder_escape_profile_combo') else '',
                'threshold_sec': float(self.ladder_escape_threshold_spinbox.value()) if hasattr(self, 'ladder_escape_threshold_spinbox') else 2.0,
                'cooldown_sec': float(self.ladder_escape_cooldown_spinbox.value()) if hasattr(self, 'ladder_escape_cooldown_spinbox') else 3.0,
                'states': {
                    'include_jump': bool(self.ladder_escape_include_jump_checkbox.isChecked()) if hasattr(self, 'ladder_escape_include_jump_checkbox') else True,
                    'include_ladder': bool(self.ladder_escape_include_ladder_checkbox.isChecked()) if hasattr(self, 'ladder_escape_include_ladder_checkbox') else True,
                    'include_fall': bool(self.ladder_escape_include_fall_checkbox.isChecked()) if hasattr(self, 'ladder_escape_include_fall_checkbox') else True,
                },
            },
            'map_return': {
                'enabled': bool(self.map_return_enabled),
                'interval_sec': float(self.map_return_interval_sec),
                'conf_threshold': float(self.map_return_conf_threshold),
                'min_height': int(self.map_return_min_height),
                'max_height': int(self.map_return_max_height),
                'min_width': int(self.map_return_min_width),
                'max_width': int(self.map_return_max_width),
                'base_profile': self.map_return_base_profile,
                'base_keywords': self.map_return_base_keywords,
                'roi': copy.deepcopy(self.map_return_roi) if isinstance(self.map_return_roi, dict) else None,
                'telegram_limit': int(self.map_return_telegram_limit),
                'maps': {
                    str(name): {
                        'profile': str(cfg.get('profile', '') or ''),
                        'waypoint_id': str(cfg.get('waypoint_id', '') or ''),
                        'waypoint_name': str(cfg.get('waypoint_name', '') or ''),
                        'command_profile': str(cfg.get('command_profile', '') or ''),
                        'keywords': str(cfg.get('keywords', '') or ''),
                    }
                    for name, cfg in self.map_return_registered_maps.items()
                    if isinstance(name, str) and name
                },
            },
            'teleport': {
                'enabled': teleport_enabled_save,
                'distance_px': self.teleport_settings.distance_px,
                'probability': teleport_prob_save,
                'walk_enabled': walk_teleport_enabled_save,
                'walk_probability': walk_teleport_prob_save,
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
                    'use_direction': bool(getattr(skill, 'use_direction', True)),
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
                    'jump_attack_enabled': bool(getattr(skill, 'jump_attack_enabled', False)),
                    'jump_attack_distance_px': int(getattr(skill, 'jump_attack_distance_px', 120)),
                    'jump_attack_probability': int(getattr(skill, 'jump_attack_probability', 50)),
                    'jump_profile_left': str(getattr(skill, 'jump_profile_left', '') or ''),
                    'jump_profile_right': str(getattr(skill, 'jump_profile_right', '') or ''),
                    'jump_pre_delay_min': float(getattr(skill, 'jump_pre_delay_min', 0.0)),
                    'jump_pre_delay_max': float(getattr(skill, 'jump_pre_delay_max', 0.0)),
                    'jump_post_delay_min': float(getattr(skill, 'jump_post_delay_min', 0.0)),
                    'jump_post_delay_max': float(getattr(skill, 'jump_post_delay_max', 0.0)),
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
            'manual_area_profiles': {
                'active': self.active_area_profile,
                'profiles': {
                    name: [copy.deepcopy(region) for region in regions]
                    for name, regions in self.manual_area_profiles.items()
                },
            },
            'manual_capture_region': self.manual_capture_region,
            'manual_capture_regions': self.manual_capture_regions,
            'auto_hunt_enabled': self.auto_hunt_enabled,
            'attack_interval_sec': self.attack_interval_sec,
            'last_popup_scale': self.last_popup_scale,
            'last_facing': self.last_facing,
            'last_popup_position': list(self.last_popup_position) if self.last_popup_position else None,
            'last_popup_size': list(self.last_popup_size) if self.last_popup_size else None,
            'auto_shutdown': self._build_auto_shutdown_settings(),
            # [NEW] 금지몬스터 감지 설정 저장
            'forbidden_monster': {
                'enabled': bool(getattr(self, 'forbidden_monster_enabled', False)),
                'command_profile': str(getattr(self, 'forbidden_monster_command_profile', '') or ''),
                'cooldown_sec': 180,
                'telegram_alert': bool(getattr(self, 'forbidden_monster_telegram_alert', False)),
            },
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
        # 현재 활성 프로필 기준으로 저장되는 목록(호환 유지)
        current_profile_items = self._get_wait_waypoints_for_current_profile()

        data: dict[str, object] = {
            'pid': pid_text,
            'reservation_target': float(self.shutdown_datetime_target) if self.shutdown_datetime_target else None,
            'reservation_enabled': bool(self.shutdown_reservation_enabled),
            'other_enabled': bool(self.shutdown_other_player_enabled),
            'other_action': self.shutdown_other_player_action,
            'other_exit_delay': int(self.shutdown_other_player_exit_delay),
            'other_wait_delay': int(self.shutdown_other_player_wait_delay),
            'other_wait_clear_delay': int(self.shutdown_other_player_wait_clear_delay),
            'other_wait_waypoint_id': self.shutdown_other_player_wait_waypoint_id,
            'other_wait_waypoint_name': self.shutdown_other_player_wait_waypoint_name,
            'other_wait_waypoints': [
                {'id': str(item.get('id', '')), 'name': str(item.get('name', ''))}
                for item in (current_profile_items or [])
                if str(item.get('id', '')).strip()
            ],
            # [신규] 맵 프로필별 대기 웨이포인트 저장
            'other_wait_waypoints_by_profile': {
                str(profile): [
                    {'id': str(it.get('id', '')), 'name': str(it.get('name', ''))}
                    for it in (items or []) if str(it.get('id', '')).strip()
                ]
                for profile, items in (self.shutdown_other_player_wait_waypoints_by_profile or {}).items()
            },
            'sleep_enabled': bool(self.shutdown_sleep_enabled),
            # v2 스키마 마커(기존 저장값 무시 후 새 구조 사용)
            'wait_waypoints_schema_version': 2,
        }

        if hasattr(self, 'shutdown_datetime_edit') and self.shutdown_datetime_edit:
            try:
                dt_value = self.shutdown_datetime_edit.dateTime()
                data['reservation_epoch'] = int(dt_value.toSecsSinceEpoch())
            except Exception:
                data['reservation_epoch'] = None

        # [추가] 대기모드 체력회복 설정 저장(전역 속성 기반)
        try:
            data['wait_hp_enabled'] = bool(getattr(self, 'wait_hp_enabled', False))
            data['wait_hp_threshold'] = int(getattr(self, 'wait_hp_threshold', 50) or 50)
            data['wait_hp_command_profile'] = str(getattr(self, 'wait_hp_command_profile', '') or '')
        except Exception:
            data['wait_hp_enabled'] = False
            data['wait_hp_threshold'] = 50
            data['wait_hp_command_profile'] = ''

        # [NEW] 대기모드 위치 복구(px) 저장
        try:
            data['wait_recover_threshold_px'] = int(getattr(self, 'wait_recover_threshold_px', 70) or 70)
        except Exception:
            data['wait_recover_threshold_px'] = 70

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

    def release_control(self, reason: str | None = None, *, meta: Optional[Dict[str, Any]] = None) -> None:
        if self.current_authority != "hunt":
            self.append_log("현재 사냥 권한이 없습니다.", "warn")
            return
        if self._request_timeout_timer:
            self._request_timeout_timer.stop()
        self._request_pending = False

        reason_text = str(reason) if reason else "manual"
        meta_payload: Dict[str, Any] = dict(meta) if isinstance(meta, dict) else {}
        if reason:
            meta_payload.setdefault("reason", reason_text)

        payload = {"reason": reason_text}
        if meta_payload:
            payload["meta"] = meta_payload

        self.control_authority_released.emit(payload)
        if reason:
            friendly_reason = format_authority_reason(reason_text, meta_payload)
            self.append_log(f"사냥 권한 반환 요청 ({friendly_reason})", "info")
        else:
            self.append_log("사냥 권한 반환 요청", "info")

        if not self.map_link_enabled:
            local_payload = {"reason": reason_text, "source": "local"}
            if meta_payload:
                local_payload["meta"] = meta_payload
            self.on_map_authority_changed("map", local_payload)
            return

        decision = self._authority_manager.release_control(
            "hunt",
            reason=reason_text,
            meta=meta_payload,
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
            # 권한 획득 즉시 키 상태를 안전하게 초기화하여 잔여 입력으로 인한 충돌 방지
            try:
                self._emit_control_command("모든 키 떼기", reason="authority:reset")
            except Exception:
                pass
        else:
            self.last_control_acquired_ts = 0.0
            self.last_release_attempt_ts = 0.0
            self._last_monster_seen_ts = time.time()
            # 맵으로 반환 시 사다리 오버라이드 해제
            try:
                self._revert_ladder_threat_range_override()
            except Exception:
                pass
            # 사다리 정리 세션 종료
            self._ladder_cleanup_session_active = False
            self._ladder_cleanup_hold_until_ts = 0.0
        self._update_authority_ui()
        self._sync_detection_thread_status()
        reason_text = payload.get('reason')
        raw_meta = payload.get('meta')
        meta_payload = raw_meta if isinstance(raw_meta, dict) else {}
        display_reason = format_authority_reason(reason_text, meta_payload)
        if not display_reason and reason_text:
            display_reason = str(reason_text)
        silent = bool(payload.get('silent'))
        if owner == "hunt":
            if not silent:
                message = "권한 획득"
                if display_reason:
                    message += f" | 사유 {display_reason}"
                # 현재 범위/캐릭터 상태(좌/우, 층/상태/이동/방향) 함께 표기
                range_text = self._format_current_ranges_lr()
                if range_text:
                    message += f" | {range_text}"
                map_snapshot = payload.get('map_snapshot') if isinstance(payload, dict) else None
                char_text = self._format_character_state_for_log(map_snapshot)
                if char_text:
                    message += f" | {char_text}"
                self.append_log(message, "success")
            # 사유에 따라 사다리 관련 세션 적용/해제
            try:
                if str(reason_text) == 'LADDER_THREAT_CLEANUP':
                    # 사다리 정리 세션 시작 + 초기 보호 윈도우(0.3초)
                    try:
                        self._ladder_cleanup_session_active = True
                        self._ladder_cleanup_hold_until_ts = time.time() + 0.3
                    except Exception:
                        pass
                    self._apply_ladder_threat_range_override()
                elif str(reason_text) == 'LADDER_PREPARE_PURGE':
                    # [신규] 사다리 준비 정리(purge) 세션 시작 + 초기 보호 윈도우(0.3초)
                    try:
                        self._ladder_purge_session_active = True
                        self._ladder_purge_hold_until_ts = time.time() + 0.3
                    except Exception:
                        pass
                    # purge는 X범위 오버라이드 미사용
                else:
                    self._ladder_cleanup_session_active = False
                    self._ladder_cleanup_hold_until_ts = 0.0
                    self._ladder_purge_session_active = False
                    self._ladder_purge_hold_until_ts = 0.0
                    self._revert_ladder_threat_range_override()
            except Exception:
                pass
        elif owner == "map":
            if not silent:
                message = "권한 반납"
                if display_reason:
                    message += f" | 사유 {display_reason}"
                range_text = self._format_current_ranges_lr()
                if range_text:
                    message += f" | {range_text}"
                map_snapshot = payload.get('map_snapshot') if isinstance(payload, dict) else None
                char_text = self._format_character_state_for_log(map_snapshot)
                if char_text:
                    message += f" | {char_text}"
                self.append_log(message, "info")
        else:
            if not silent:
                self.append_log(f"권한 소유자 변경: {owner}", "info")
        if owner != "hunt":
            # 세션 종료 정리
            self._ladder_cleanup_session_active = False
            self._ladder_cleanup_hold_until_ts = 0.0
            self._ladder_purge_session_active = False
            self._ladder_purge_hold_until_ts = 0.0
            self._schedule_condition_poll()

    def _update_authority_ui(self) -> None:
        self._update_detection_summary()
        self._update_attack_buttons()
        self._update_buff_buttons()

    def _poll_hunt_conditions(self, *, force: bool = False) -> None:
        now = time.time()
        # 탐지 비활성(ESC 등) 시 조건 평가 중단: 즉시성 보장
        if not self._is_detection_active():
            return
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

        # [사다리 준비 purge] prepare_to_climb + HP≤임계 + 주스킬≥1이면 우선 권한 요청
        try:
            if self._maybe_request_ladder_prepare_purge():
                return
        except Exception:
            pass

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

                release_meta: Dict[str, Any] = {}
                if not primary_ready and not hunt_ready:
                    release_meta.update(
                        {
                            "latest_monster_count": self.latest_monster_count,
                            "hunt_monster_threshold": hunt_threshold,
                            "latest_primary_monster_count": self.latest_primary_monster_count,
                            "primary_monster_threshold": primary_threshold,
                            "idle_limit": idle_limit,
                        }
                    )
                    if math.isfinite(idle_elapsed):
                        release_meta["idle_elapsed"] = idle_elapsed

                if timeout and elapsed >= timeout:
                    release_meta.update(
                        {
                            "hold_elapsed": elapsed,
                            "hold_limit": timeout,
                        }
                    )

                if release_reason_code:
                    release_meta.setdefault("reason", release_reason_code)

                reason_parts = []
                if primary_threshold > 0:
                    reason_parts.append(
                        self._format_metric("주 스킬", self.latest_primary_monster_count, primary_threshold, ready=False)
                    )
                if hunt_threshold > 0:
                    reason_parts.append(
                        self._format_metric("사냥범위", self.latest_monster_count, hunt_threshold, ready=False)
                    )
                reason_parts.append(f"최근 미탐지 {idle_elapsed:.1f}초 (기준 {idle_limit:.1f}초)")
                if timeout and elapsed >= timeout:
                    reason_parts.append(f"타임아웃 {timeout}초 초과")
                reason_text = ", ".join(reason_parts)
                range_text = self._format_current_ranges_lr()
                if range_text:
                    reason_text = f"{reason_text} | {range_text}"
                self.append_log(f"권한 반납 | {reason_text}", "info")
                release_reason = release_reason_code if (self.map_link_enabled and release_reason_code) else reason_text
                self.release_control(release_reason, meta=release_meta or None)
            return

        # [정책 변경] 권한 요청 조건
        # - 주 스킬 기준 충족 시 즉시 요청
        # - 사냥범위 기준만 충족 시에는, "사냥범위 내 몬스터들이 이동 시 주 스킬 범위 기준을 만족하도록 배치 가능"할 때만 요청
        reachable = False
        if not primary_ready and hunt_ready:
            try:
                reachable = self._is_primary_reachable_from_hunt()
            except Exception:
                reachable = False
        if primary_ready or (hunt_ready and reachable):
            reason_parts = []
            if hunt_threshold > 0 and hunt_ready:
                reason_parts.append(
                    self._format_metric("사냥범위", self.latest_monster_count, hunt_threshold, ready=True)
                )
            if primary_threshold > 0 and primary_ready:
                reason_parts.append(
                    self._format_metric("주 스킬", self.latest_primary_monster_count, primary_threshold, ready=True)
                )
            if not primary_ready and reachable:
                reason_parts.append("주 스킬 기준 도달 가능(이동)")
            if not reason_parts:
                reason_parts.append("몬스터 조건 충족")
            reason_text = ", ".join(reason_parts)
            range_text = self._format_current_ranges_lr()
            char_text = self._format_character_state_for_log(self._get_latest_map_snapshot_payload())
            if range_text:
                reason_text = f"{reason_text} | {range_text}"
            if char_text:
                reason_text = f"{reason_text} | {char_text}"
            self.append_log(f"권한 요청 | {reason_text}", "info")
            request_reason = "MONSTER_READY" if self.map_link_enabled else reason_text
            self.request_control(request_reason)

    def _run_hunt_loop(self) -> None:
        # 탐지 비활성 상태에서는 즉시 반환(잔여 명령 방지)
        if not self._is_detection_active():
            return
        # 대기 모드(active)에서는 어떤 공격/버프도 수행하지 않고 즉시 유휴 상태를 유지한다.
        try:
            if bool(getattr(self, 'shutdown_other_player_wait_active', False)):
                self._engage_active = False
                self._cleanup_active = False
                self._cleanup_hold_until_ts = 0.0
                self._ensure_idle_keys("대기 모드 진행 중")
                return
        except Exception:
            pass
        if not self.auto_hunt_enabled:
            # 교전/클린업 상태 초기화
            self._engage_active = False
            self._cleanup_active = False
            self._cleanup_hold_until_ts = 0.0
            self._ensure_idle_keys("자동 사냥 비활성화")
            return
        if self.current_authority != "hunt":
            # 교전/클린업 상태 초기화
            self._engage_active = False
            self._cleanup_active = False
            self._cleanup_hold_until_ts = 0.0
            self._ensure_idle_keys("사냥 권한 없음")
            return
        if self._pending_skill_timer or self._pending_direction_timer:
            return
        remaining_delay = self._get_command_delay_remaining()
        if remaining_delay > 0:
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
        # [사다리 정리 세션] 주 스킬 범위 0마리면 즉시 맵으로 반납(초기 보호 시간 경과 후)
        if getattr(self, '_ladder_cleanup_session_active', False):
            try:
                if time.time() >= float(getattr(self, '_ladder_cleanup_hold_until_ts', 0.0) or 0.0):
                    if int(self.latest_primary_monster_count) <= 0:
                        # 간단한 한글 사유 + 수치 괄호
                        hp_val = None
                        try:
                            hp_val = float(self._status_display_values.get('hp'))
                        except Exception:
                            hp_val = None
                        total = int(self.latest_monster_count)
                        reason_text = f"사다리 정리 완료 (P 0 / H {total}" + (f", HP {int(hp_val)}%" if isinstance(hp_val, (int, float)) else "") + ")"
                        self.release_control(reason_text)
                        return
            except Exception:
                pass
        # [사다리 준비 purge 세션] 주 스킬 범위 0마리면 즉시 맵으로 반납(초기 보호 시간 경과 후)
        if getattr(self, '_ladder_purge_session_active', False):
            try:
                if time.time() >= float(getattr(self, '_ladder_purge_hold_until_ts', 0.0) or 0.0):
                    if int(self.latest_primary_monster_count) <= 0:
                        hp_val = None
                        try:
                            hp_val = float(self._status_display_values.get('hp'))
                        except Exception:
                            hp_val = None
                        total = int(self.latest_monster_count)
                        reason_text = f"사다리 정리 완료 (P 0 / H {total}" + (f", HP {int(hp_val)}%" if isinstance(hp_val, (int, float)) else "") + ")"
                        self.release_control(reason_text)
                        return
            except Exception:
                pass
        if self.latest_monster_count == 0:
            self._ensure_idle_keys("감지 범위 몬스터 없음")
            return
        primary_threshold_widget = getattr(self, 'primary_monster_threshold_spinbox', None)
        primary_threshold = max(1, primary_threshold_widget.value()) if primary_threshold_widget else 1

        # 교전/클린업 상태 갱신
        primary_ready = self.latest_primary_monster_count >= primary_threshold
        prev_engage = self._engage_active
        prev_cleanup = self._cleanup_active
        prev_hold_until = self._cleanup_hold_until_ts
        now_ts = time.time()

        if not self._engage_active:
            # 기준 충족으로 교전 시작
            if primary_ready:
                self._engage_active = True
                self._cleanup_active = False
                self._cleanup_hold_until_ts = 0.0
                try:
                    # 교전 시작 시 수치 표기를 토글 형식에 맞춰 출력
                    msg_metric = self._format_metric("주 스킬", self.latest_primary_monster_count, primary_threshold, ready=True)
                    self.append_log(f"교전 시작 | {msg_metric}", "info")
                except Exception:
                    pass
        else:
            # 교전 중 상태 유지/전환
            if primary_ready:
                # 다시 2마리 이상 확보되면 일반 교전
                self._cleanup_active = False
                self._cleanup_hold_until_ts = 0.0
                if prev_cleanup:
                    try:
                        # 원인: 주 스킬 기준 충족
                        msg_metric = self._format_metric("주 스킬", self.latest_primary_monster_count, primary_threshold, ready=True)
                        reason_text = msg_metric
                        range_text = self._format_current_ranges_lr()
                        if range_text:
                            reason_text = f"{reason_text} | {range_text}"
                        self.append_log(f"클린업 종료 | {reason_text}", "info")
                    except Exception:
                        # 포맷 실패 시 기본 로그 유지
                        self.append_log("클린업 종료", "info")
            elif self.latest_primary_monster_count >= 1:
                # 잔몹 1마리 남은 상태 → 클린업 유지
                self._cleanup_active = True
                self._cleanup_hold_until_ts = 0.0
                if not prev_cleanup:
                    try:
                        # 원인: 주 스킬 미충족(잔몹 정리)
                        msg_metric = self._format_metric("주 스킬", self.latest_primary_monster_count, primary_threshold, ready=False)
                        reason_text = msg_metric
                        range_text = self._format_current_ranges_lr()
                        if range_text:
                            reason_text = f"{reason_text} | {range_text}"
                        self.append_log(f"클린업 진입 | {reason_text}", "info")
                    except Exception:
                        self.append_log("클린업 진입", "info")
            else:
                # 주 스킬 범위 내 0마리 → 클린업 유예 적용 후 종료 판단
                if self._cleanup_active and self._cleanup_hold_until_ts <= 0.0:
                    grace_ms = 0
                    try:
                        grace_ms = int(getattr(self, 'cleanup_grace_spinbox', None).value()) if hasattr(self, 'cleanup_grace_spinbox') else 0
                    except Exception:
                        grace_ms = 0
                    if grace_ms > 0:
                        self._cleanup_hold_until_ts = now_ts + (grace_ms / 1000.0)
                        try:
                            self.append_log(f"클린업 유예 시작 | {grace_ms}밀리초", "info")
                        except Exception:
                            pass
                if self._cleanup_hold_until_ts > 0.0 and now_ts <= self._cleanup_hold_until_ts:
                    # 유예 중에는 교전 유지(allow_cleanup에서 반영)
                    pass
                else:
                    # 유예 종료 → 교전 종료
                    if self._cleanup_hold_until_ts > 0.0 and now_ts > self._cleanup_hold_until_ts:
                        try:
                            self.append_log("클린업 유예 종료", "info")
                        except Exception:
                            pass
                    self._engage_active = False
                    self._cleanup_active = False
                    self._cleanup_hold_until_ts = 0.0
                    if prev_engage:
                        try:
                            self.append_log("교전 종료", "info")
                        except Exception:
                            pass

        # 클린업 허용 여부
        allow_cleanup = (
            (
                self._engage_active
                and (
                    self.latest_primary_monster_count >= 1
                    or (
                        self._cleanup_active
                        and self._cleanup_hold_until_ts > 0.0
                        and now_ts <= self._cleanup_hold_until_ts
                    )
                )
            )
            or getattr(self, '_ladder_cleanup_session_active', False)
        )

        # 클린업 중에도 최근 몬스터 관측 시간 갱신(권한 자동 반환 방지)
        if allow_cleanup:
            self._last_monster_seen_ts = time.time()

        if (
            self.latest_primary_monster_count < primary_threshold
            and not allow_cleanup
            and not getattr(self, '_ladder_purge_session_active', False)
        ):
            # [겹침 예외] 이전 프레임≥2 → 현재 1, 최근 2s 이동 + 최근 1s 다중관측이면 즉시 클린업 전환
            if not self._should_enter_cleanup_due_to_overlap(now_ts):
                # 주 스킬 기준이 아직 미충족인 경우: 사냥범위 내 몬스터들로 주 스킬 기준 도달이 가능한지 평가
                reachable = False
                try:
                    reachable = self._is_primary_reachable_from_hunt()
                except Exception:
                    reachable = False

                if reachable:
                    # 도달 가능하면 기존 접근 로직으로 몬스터 쪽으로 이동 시도
                    if self._handle_monster_approach():
                        return
                # 도달 불가하거나 접근 시도가 실패하면 이동 중단 및 권한 반환 시도
                if self.latest_monster_count == 0:
                    self._ensure_idle_keys("감지 범위 몬스터 없음")
                else:
                    self._ensure_idle_keys("이동 보류: 주 스킬 범위 미충족 → 맵 탭 권한 반환 대기")

                now_try = time.time()
                if (now_try - self.last_release_attempt_ts) >= 1.0:
                    self.last_release_attempt_ts = now_try
                    try:
                        hunt_threshold_widget = getattr(self, 'hunt_monster_threshold_spinbox', None)
                        hunt_threshold = int(hunt_threshold_widget.value()) if hunt_threshold_widget else 0
                    except Exception:
                        hunt_threshold = 0
                    release_meta = {
                        "latest_monster_count": int(self.latest_monster_count),
                        "hunt_monster_threshold": int(hunt_threshold),
                        "latest_primary_monster_count": int(self.latest_primary_monster_count),
                        "primary_monster_threshold": int(primary_threshold),
                    }
                    self.release_control("PRIMARY_NOT_READY", meta=release_meta)
                return

        # [클린업 추격] 교전 유지 중(allow_cleanup)이며 주 스킬 범위 내 마릿수가 0일 때,
        # 주 스킬 범위로부터 전/후 각 CLEANUP_CHASE_MARGIN_PX(px) 확장한 밴드 내의 몬스터를 향해 이동 시도
        if allow_cleanup and self.latest_primary_monster_count == 0:
            try:
                primary_area = getattr(self, 'current_primary_area', None)
                if primary_area is not None and isinstance(primary_area, AreaRect):
                    margin = float(CLEANUP_CHASE_MARGIN_PX)
                    chase_area = AreaRect(
                        x=primary_area.x - margin,
                        y=primary_area.y,
                        width=primary_area.width + (margin * 2.0),
                        height=primary_area.height,
                    )
                    if self._handle_monster_approach(restrict_area=chase_area):
                        return
            except Exception:
                pass
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
        # 점프공격(주 스킬 범위 중심 기준) 시도: 성공 시 방향전환 무시하고 종료
        # - 주 스킬에 점프공격이 켜져 있으면 주 스킬 기준으로 우선 시도
        # - 아니면 선택된 스킬이 점프공격을 지원하면 그 스킬로 시도(기존 동작 유지)
        try:
            primary_skill = next((s for s in getattr(self, 'attack_skills', []) if getattr(s, 'is_primary', False) and getattr(s, 'enabled', True)), None)
        except Exception:
            primary_skill = None
        jump_skill = None
        if primary_skill and getattr(primary_skill, 'jump_attack_enabled', False):
            jump_skill = primary_skill
        elif getattr(skill, 'jump_attack_enabled', False):
            jump_skill = skill
        if jump_skill and self._try_jump_attack(jump_skill, character_box):
            return
        target_box = self._select_target_monster(character_box)
        if not target_box:
            self._ensure_idle_keys("목표 몬스터 탐지 실패")
            return

        target_side = 'left' if target_box.center_x < character_box.center_x else 'right'
        # 방향전환 사용 설정에 따라 방향 보정 여부 결정
        if getattr(skill, 'use_direction', True):
            direction_changed = self._ensure_direction(target_side, skill)
            if direction_changed:
                return

        self._execute_attack_skill(skill)

    def _handle_monster_approach(self, restrict_area: Optional[AreaRect] = None) -> bool:
        if not self.latest_snapshot or not self.latest_snapshot.character_boxes:
            return False
        # 접근 대상 영역: 기본은 사냥범위, 전달되면 지정 영역 사용(예: 클린업 추격 밴드)
        target_area = restrict_area if restrict_area is not None else self.current_hunt_area
        if not target_area:
            return False
        monsters = self._get_recent_monster_boxes()
        if not monsters:
            return False

        candidates = [box for box in monsters if box.intersects(target_area)]
        if not candidates:
            return False

        character_box = self._select_reference_character_box(self.latest_snapshot.character_boxes)

        # 공통 헬퍼로 주 스킬 폭/임계 계산 후 군집 탐지 시도
        width, primary_threshold = self._compute_primary_window_width_threshold()
        cluster_center_x: Optional[float] = None
        cluster_count: int = 0

        if width > 0.0 and primary_threshold >= 1:
            best_cluster = self._find_best_primary_cluster(
                candidates,
                width,
                primary_threshold,
                character_box.center_x,
            )
            if best_cluster is not None:
                cluster_center_x, cluster_count = best_cluster

        if cluster_center_x is not None:
            # 군집 중심 기준으로 접근 방향/거리 산정
            target_side = 'left' if cluster_center_x < character_box.center_x else 'right'
            distance = abs(cluster_center_x - character_box.center_x)
            # 추후 로그에 반영될 수 있도록 마지막 목표 정보 갱신
            self._last_target_side = target_side
            self._last_target_distance = distance
            self._last_target_update_ts = time.time()
            try:
                self.append_log(
                    f"군집 선택: 중심X={int(round(cluster_center_x))}, 마릿수={cluster_count}, 폭={int(round(width))}",
                    'debug',
                )
            except Exception:
                pass
        else:
            # 군집이 없으면 기존 로직: 가장 가까운 1마리로 접근
            target = min(candidates, key=lambda box: abs(box.center_x - character_box.center_x))
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

    def _try_jump_attack(self, skill: AttackSkill, character_box: DetectionBox) -> bool:
        """점프공격 시도: 기본(주 스킬 범위 내 ≥2) + [확장사냥] x범위 내 군집(주 스킬 폭) 기반.

        - 기본: 주 스킬 범위 교차 몬스터 ≥ 2일 때 중심으로 점프공격
        - 확장사냥 모드 On: 사냥범위 내 몬스터들로 주 스킬 폭 내 임계치(최소 2) 충족 군집이 있으면 그 군집 중심으로 점프공격
        - 방향전환은 무시(점프 프로필 자체가 방향 포함 가정)
        - 지연: jump_pre_delay_*, jump_post_delay_*, completion 지연은 스킬 기본값
        """
        try:
            if not getattr(skill, 'jump_attack_enabled', False):
                return False

            monsters = self._get_recent_monster_boxes()
            if not monsters:
                return False

            char_x = character_box.center_x
            center_x: Optional[float] = None
            used_mode = '기본'

            # 1) 기본: 주 스킬 범위 내 2마리 이상이면 중심X 사용
            if self.current_primary_area:
                try:
                    primary_monsters = [m for m in monsters if m.intersects(self.current_primary_area)]
                except Exception:
                    primary_monsters = []
                if len(primary_monsters) >= 2:
                    center_x = sum(m.center_x for m in primary_monsters) / float(len(primary_monsters))
                    used_mode = '기본'

            # 2) [확장사냥] 주 스킬 범위가 2 미만일 때, x범위 내 군집(주 스킬 폭/임계 적용) 탐색
            if center_x is None:
                expanded_on = bool(getattr(self, 'expanded_hunt_checkbox', None) and self.expanded_hunt_checkbox.isChecked())
                if expanded_on and self.current_hunt_area:
                    width, primary_threshold = self._compute_primary_window_width_threshold()
                    # 최소 2마리 조건 보장 + 사용자가 더 높게 설정한 경우 존중
                    required = max(2, int(primary_threshold))
                    if width > 0.0 and required >= 2:
                        try:
                            hunt_monsters = [b for b in monsters if b.intersects(self.current_hunt_area)]
                        except Exception:
                            hunt_monsters = []
                        cluster = self._find_best_primary_cluster(hunt_monsters, width, required, char_x)
                        if cluster is not None:
                            center_x, _ = cluster
                            used_mode = '확장'

            if center_x is None:
                return False

            side = 'left' if center_x < char_x else 'right'
            distance = abs(center_x - char_x)
            threshold = max(1, int(getattr(skill, 'jump_attack_distance_px', 120)))
            if distance < threshold:
                return False
            prob = max(0, min(100, int(getattr(skill, 'jump_attack_probability', 50))))
            roll = random.randint(1, 100)
            if roll > prob:
                return False

            profile = str(getattr(skill, 'jump_profile_right', '') if side == 'right' else getattr(skill, 'jump_profile_left', '') or '').strip()
            if not profile:
                return False

            # 사유 문자열
            base_reason = self._build_attack_usage_reason(
                skill,
                monster_count=self.latest_primary_monster_count,
                total_monster_count=self.latest_monster_count,
            )
            direction_text = '우' if side == 'right' else '좌'
            tag = '확장' if used_mode == '확장' else '점프공격'
            usage_reason = f"{base_reason} | {tag}({direction_text}, 중심거리 {int(round(distance))}픽셀)"

            # 점프 전에는 점프 전용 pre-delay를 적용(기본값 0.0)
            pre_delay = self._sample_delay(
                getattr(skill, 'jump_pre_delay_min', 0.0),
                getattr(skill, 'jump_pre_delay_max', 0.0),
            )

            def emit() -> None:
                exec_time = time.time()
                self._next_command_ready_ts = max(self._next_command_ready_ts, exec_time)
                self._emit_control_command(profile, reason=usage_reason)
                # 완료 지연/카운팅은 스킬의 completion 지연을 그대로 사용
                self._queue_completion_delay(
                    profile,
                    getattr(skill, 'completion_delay_min', 0.0),
                    getattr(skill, 'completion_delay_max', 0.0),
                    f"스킬 '{skill.name}'",
                    payload={'type': 'attack', 'skill': skill},
                )
                self.last_attack_ts = exec_time
                self.hunting_active = True
                # 점프 발동 후 대기(점프 전용 post-delay)
                post_delay = self._sample_delay(getattr(skill, 'jump_post_delay_min', 0.0), getattr(skill, 'jump_post_delay_max', 0.0))
                if post_delay > 0.0:
                    self._set_command_cooldown(post_delay)
                    self._log_delay_message(f"점프공격 '{skill.name}'", post_delay)

            if pre_delay > 0.0:
                if self._start_pre_delay(profile, pre_delay, f"점프 '{skill.name}' 발동 전", emit):
                    return True
            emit()
            return True
        except Exception:
            return False

    def _compute_primary_window_width_threshold(self) -> tuple[float, int]:
        """주 스킬 범위 슬라이딩 윈도우의 폭과 임계 마릿수를 계산한다.

        - 대칭 모드: 폭 = radius*2
        - 전/후 비대칭 모드: 폭 = front + back
        - 임계: primary_monster_threshold_spinbox (>=1)
        """
        # 임계 마릿수 계산
        try:
            widget = getattr(self, 'primary_monster_threshold_spinbox', None)
            threshold = int(widget.value()) if widget else 1
        except Exception:
            threshold = 1
        threshold = max(1, threshold)

        # 폭 계산
        width = 0.0
        mode_on = bool(getattr(self, 'facing_range_checkbox', None) and self.facing_range_checkbox.isChecked())
        if mode_on:
            try:
                front = max(0.0, float(self.primary_front_spinbox.value()))
                back = max(0.0, float(self.primary_back_spinbox.value()))
                width = max(1.0, front + back)
            except Exception:
                width = 0.0
        else:
            try:
                radius = float(self.primary_skill_range_spinbox.value())
                width = max(1.0, radius * 2.0)
            except Exception:
                width = 0.0
        return (width, threshold)

    def _find_best_primary_cluster(
        self,
        candidates: list,
        width: float,
        threshold: int,
        char_x: float,
    ) -> Optional[tuple[float, int]]:
        """슬라이딩 윈도우로 후보 몬스터들 중 주 스킬 폭 내 임계 이상 군집을 탐색한다.

        우선순위: 더 많은 마릿수 → 캐릭터와의 거리 → 현재 바라보는 방향.
        반환: (군집 중심 X, 군집 마릿수) 또는 None
        """
        boxes = sorted(candidates, key=lambda b: b.center_x)
        if not boxes or width <= 0.0 or threshold <= 0:
            return None
        xs = [b.center_x for b in boxes]
        # prefix sum으로 빠른 구간 합 계산
        prefix = [0.0]
        for x in xs:
            prefix.append(prefix[-1] + float(x))

        n = len(xs)
        best_center: Optional[float] = None
        best_count: int = 0
        best_distance: float = float('inf')
        last_facing = self.last_facing if self.last_facing in ('left', 'right') else None

        j = 0
        for i in range(n):
            while j < n and (xs[j] - xs[i]) <= width + 1e-6:
                j += 1
            count = j - i
            if count >= threshold:
                sum_x = prefix[j] - prefix[i]
                center = sum_x / float(count)
                distance = abs(center - char_x)

                # 새 우선순위: 마릿수 → 거리 → 바라보는 방향
                better = False
                if count > best_count:
                    better = True
                elif count == best_count:
                    if distance + 1e-6 < best_distance:
                        better = True
                    elif abs(distance - best_distance) <= 1e-6 and last_facing in ('left', 'right') and best_center is not None:
                        # 여전히 동률이면 현재 바라보는 방향 우선
                        new_side = 'left' if center < char_x else 'right'
                        old_side = 'left' if best_center < char_x else 'right'
                        if new_side == last_facing and old_side != last_facing:
                            better = True

                if better:
                    best_center = center
                    best_count = count
                    best_distance = distance

            # i 증가에 맞춰 j 최소 i+1 유지
            if j < i + 1:
                j = i + 1

        if best_center is None:
            return None
        return (best_center, best_count)

    def _get_map_preferred_side(self) -> Optional[str]:
        """맵 탭 스냅샷으로부터 진행 우선 방향을 추정한다.

        우선순위:
        - metadata에 'nav_arrow_side' 또는 'nav_preferred_side'가 'left'/'right'로 제공되면 사용
        - 없으면 last_move_command에서 좌/우 파싱
        - 실패 시 None
        """
        try:
            snap = self._get_latest_map_snapshot_payload()
        except Exception:
            snap = None
        if not isinstance(snap, dict):
            return None
        # 1) 메타 내 명시적 키
        md = snap.get('metadata') if isinstance(snap.get('metadata'), dict) else {}
        for key in ('nav_arrow_side', 'nav_preferred_side', 'preferred_side'):
            val = md.get(key)
            if val in ('left', 'right'):
                return val
        # 2) 마지막 이동 명령으로 추정
        try:
            last_cmd = snap.get('last_move_command') or ''
            if isinstance(last_cmd, str):
                if '우' in last_cmd:
                    return 'right'
                if '좌' in last_cmd:
                    return 'left'
        except Exception:
            pass
        return None

    def _is_primary_reachable_from_hunt(self) -> bool:
        """사냥범위 내 몬스터들로 주 스킬 기준(폭/임계)을 만족하는 군집이 존재하는지 평가한다.

        공통 헬퍼를 사용하여 폭/임계를 일관되게 적용하고, 군집 존재 여부만 반환한다.
        """
        if not (self.latest_snapshot and self.current_hunt_area):
            return False
        monsters = self._get_recent_monster_boxes()
        if not monsters:
            return False
        hunt_monsters = [box for box in monsters if box.intersects(self.current_hunt_area)]
        if not hunt_monsters:
            return False

        width, primary_threshold = self._compute_primary_window_width_threshold()
        if width <= 0.0 or primary_threshold <= 0:
            return False

        # 캐릭터 기준은 동률 처리에만 사용됨
        try:
            char_box = self._select_reference_character_box(self.latest_snapshot.character_boxes)
            char_x = char_box.center_x
        except Exception:
            char_x = 0.0

        cluster = self._find_best_primary_cluster(hunt_monsters, width, primary_threshold, char_x)
        return cluster is not None

    def _issue_walk_command(self, side: str, distance: float) -> bool:
        if side not in ('left', 'right'):
            return False
        mode_key = f"walk_{side}"
        if self._movement_mode == mode_key:
            self._mark_walk_teleport_started(side)
            return True
        command = "걷기(좌)" if side == 'left' else "걷기(우)"
        reason = f"몬스터 접근 ({'좌' if side == 'left' else '우'}, {distance:.0f}픽셀)"
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
        reason = f"몬스터에게 이동 ({distance:.0f}픽셀)"
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
        reason = f"걷기({direction_text}, {distance:.0f}픽셀) 유지"
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
        # 클린업 상태에서는 주 스킬에 한해 최소 마릿수 조건을 1로 완화
        try:
            if getattr(self, '_cleanup_active', False) and getattr(skill, 'is_primary', False):
                min_required = 1
            # [신규] purge 세션에서도 주 스킬 최소 마릿수는 1로 완화
            if getattr(self, '_ladder_purge_session_active', False) and getattr(skill, 'is_primary', False):
                min_required = 1
        except Exception:
            pass
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
                detail_parts.append(f"목표 {direction_label} {int(round(target_distance))}픽셀")
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
        # [신규] purge 세션 중에는 주 스킬만 사용
        try:
            if getattr(self, '_ladder_purge_session_active', False):
                return primary_skill if (primary_skill and primary_skill.enabled) else None
        except Exception:
            pass
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
        # 좌/우 마릿수 비교 및 맵 진행 방향 우선
        left_list = [box for box in candidates if box.center_x < char_x]
        right_list = [box for box in candidates if box.center_x >= char_x]
        forced_side: Optional[str] = None
        if len(left_list) != len(right_list):
            forced_side = 'left' if len(left_list) > len(right_list) else 'right'
        elif len(left_list) == 1 and len(right_list) == 1:
            pref = self._get_map_preferred_side()
            if pref in ('left', 'right'):
                forced_side = pref
        # 강제 측면이 정해졌으면 해당 측면으로 후보 축소
        if forced_side == 'left' and left_list:
            candidates = left_list
        elif forced_side == 'right' and right_list:
            candidates = right_list
        else:
            # 강제 선택이 없다면 기존 바라보는 방향 기반 축소 유지
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
        dialog = AttackSkillDialog(
            self,
            misc_commands=self._get_misc_command_profiles(),
            skill_commands=self._get_skill_command_profiles(),
        )
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
            skill_commands=self._get_skill_command_profiles(),
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
            dir_label = "방향전환" if getattr(skill, 'use_direction', True) else "방향무시"
            jump_label = ""
            if getattr(skill, 'jump_attack_enabled', False):
                try:
                    jump_label = f" | 점프 d={int(getattr(skill, 'jump_attack_distance_px', 0))}px@{int(getattr(skill, 'jump_attack_probability', 0))}%"
                except Exception:
                    jump_label = " | 점프"
            item.setText(4, f"{condition_label} | {dir_label} | {skill.probability}%{jump_label}")
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

    def _get_skill_command_profiles(self) -> List[str]:
        if not self.data_manager or not hasattr(self.data_manager, 'list_command_profiles'):
            return []
        try:
            profiles = self.data_manager.list_command_profiles(('스킬',))
        except Exception:
            return []
        if isinstance(profiles, dict):
            names = profiles.get('스킬', [])
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
        # [NEW] 모니터링 탭으로 전달(현재 수준의 메인 로그만)
        try:
            self.hunt_log_emitted.emit(line, color_map.get(level, 'white'))
        except Exception:
            pass

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
            reason_text = reason.strip() if isinstance(reason, str) else ""
            if reason_text.startswith("사냥 권한 없음") and self.map_link_enabled:
                self._release_pending = False
                self.hunting_active = False
                self._movement_mode = None
            else:
                self._issue_all_keys_release(reason)


class _AreaSettingsDialog(QDialog):
    def __init__(self, hunt_tab: HuntTab) -> None:
        super().__init__(hunt_tab)
        self._hunt_tab = hunt_tab
        self.setWindowTitle("사냥 영역 설정")
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        area_row = QHBoxLayout()
        area_row.setSpacing(8)
        self.set_area_btn = QPushButton("영역 지정", self)
        self.set_area_btn.clicked.connect(self._hunt_tab._set_manual_area)
        area_row.addWidget(self.set_area_btn)

        self.add_area_btn = QPushButton("+", self)
        self.add_area_btn.setFixedWidth(28)
        self.add_area_btn.clicked.connect(self._hunt_tab._add_manual_area)
        area_row.addWidget(self.add_area_btn)
        area_row.addStretch(1)
        layout.addLayout(area_row)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(8)
        self.save_btn = QPushButton("저장", self)
        self.save_btn.clicked.connect(self._handle_save)
        profile_row.addWidget(self.save_btn)

        self.load_btn = QPushButton("불러오기", self)
        self.load_btn.clicked.connect(self._handle_load)
        profile_row.addWidget(self.load_btn)

        self.profile_combo = QComboBox(self)
        self.profile_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        profile_row.addWidget(self.profile_combo, 1)
        layout.addLayout(profile_row)

        self.active_label = QLabel(self)
        self.active_label.setWordWrap(True)
        layout.addWidget(self.active_label)

        self.summary_label = QLabel(self)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.resize(420, self.sizeHint().height())

    def update_state(self) -> None:
        has_area = bool(self._hunt_tab.manual_capture_region)
        self.add_area_btn.setEnabled(has_area)
        self.save_btn.setEnabled(has_area)

        names = sorted(self._hunt_tab.manual_area_profiles.keys())
        previous_text = self.profile_combo.currentText()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(names)

        target_name = self._hunt_tab.active_area_profile or previous_text
        if target_name and target_name in names:
            index = self.profile_combo.findText(target_name)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
        elif names:
            self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)

        has_profiles = bool(names)
        self.load_btn.setEnabled(has_profiles)
        self.profile_combo.setEnabled(has_profiles)

        active_text = self._hunt_tab.active_area_profile or "(저장되지 않음)"
        self.active_label.setText(f"현재 프로필: {active_text}")
        self.summary_label.setText(self._build_summary_text())

    def _build_summary_text(self) -> str:
        if not self._hunt_tab.manual_capture_region:
            return "설정된 탐지 영역이 없습니다."
        region = self._hunt_tab.manual_capture_region
        count = len(self._hunt_tab.manual_capture_regions)
        if count > 1:
            return f"합성 영역: {region} (영역 {count}개)"
        return f"합성 영역: {region}"

    def _handle_save(self) -> None:
        if not self._hunt_tab.manual_capture_regions:
            QMessageBox.warning(self, "오류", "저장할 탐지 영역이 없습니다.")
            return
        default_name = self._hunt_tab.active_area_profile or ""
        name, ok = QInputDialog.getText(self, "프로필 저장", "프로필 이름을 입력하세요:", text=default_name)
        if not ok:
            return
        normalized = name.strip()
        if not normalized:
            QMessageBox.warning(self, "오류", "프로필 이름을 입력해주세요.")
            return
        if normalized in self._hunt_tab.manual_area_profiles:
            reply = QMessageBox.question(
                self,
                "덮어쓰기 확인",
                f"'{normalized}' 프로필을 덮어쓰시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self._hunt_tab._save_area_profile(normalized):
            self.update_state()

    def _handle_load(self) -> None:
        if not self._hunt_tab.manual_area_profiles:
            QMessageBox.warning(self, "오류", "불러올 프로필이 없습니다.")
            return
        name = self.profile_combo.currentText().strip()
        if not name:
            QMessageBox.warning(self, "오류", "불러올 프로필을 선택하세요.")
            return
        if self._hunt_tab._apply_area_profile(name):
            self.update_state()
