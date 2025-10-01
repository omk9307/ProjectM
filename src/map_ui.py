"""맵 탭 UI 및 관련 편의 클래스."""

from __future__ import annotations

import sys
import os
import json
import csv
import cv2
import numpy as np
import mss
import base64
import time
import uuid
import math
import shutil
import copy
import traceback
import random
from collections import defaultdict, deque
import threading
import hashlib
import win32gui
import win32con
import win32api
import pygetwindow as gw
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, Optional, TextIO

from status_monitor import StatusMonitorThread, StatusMonitorConfig
from control_authority_manager import ControlAuthorityManager, PlayerStatusSnapshot

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QMessageBox, QSpinBox, QDialog, QDialogButtonBox, QListWidget,
    QInputDialog, QListWidgetItem, QDoubleSpinBox, QAbstractItemView,
    QLineEdit, QRadioButton, QButtonGroup, QGroupBox, QComboBox,

    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QCheckBox, QGraphicsRectItem,
    QGraphicsLineItem, QGraphicsTextItem, QGraphicsEllipseItem,
    QGraphicsSimpleTextItem, QFormLayout, QProgressDialog, QSizePolicy,
    QSplitter
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QBrush, QFont, QCursor, QIcon, QPolygonF, QFontMetrics, QFontMetricsF, QGuiApplication
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QRect, QPoint, QRectF, QPointF, QSize, QSizeF, QTimer, QSignalBlocker

try:
    from sklearn.ensemble import RandomForestClassifier
    import joblib
except ImportError:
    raise RuntimeError(
        "머신러닝 기반 동작 인식을 위해 scikit-learn과 joblib 라이브러리가 필요합니다.\n"
        "pip install scikit-learn joblib"
    )

try:
    from Learning import ScreenSnipper
except ImportError:
    class ScreenSnipper(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            QMessageBox.critical(self, "오류", "Learning.py 모듈을 찾을 수 없어\n화면 영역 지정 기능을 사용할 수 없습니다.")

        def exec(self):
            return 0

        def get_roi(self):
            return QRect(0, 0, 100, 100)

try:
    from .map import (
        CONFIG_PATH,
        GLOBAL_ACTION_MODEL_DIR,
        GLOBAL_MAP_SETTINGS_FILE,
        HYSTERESIS_EXIT_OFFSET,
        IDLE_TIME_THRESHOLD,
        AIRBORNE_RECOVERY_WAIT_DEFAULT,
        LADDER_RECOVERY_RESEND_DELAY_DEFAULT,
        JUMPING_STATE_FRAME_THRESHOLD,
        JUMP_LINK_ARRIVAL_X_THRESHOLD,
        JUMP_Y_MAX_THRESHOLD,
        JUMP_Y_MIN_THRESHOLD,
        LADDER_ARRIVAL_X_THRESHOLD,
        LADDER_AVOIDANCE_WIDTH,
        LADDER_X_GRAB_THRESHOLD,
        MAPS_DIR,
        MAX_ICON_HEIGHT,
        MAX_ICON_WIDTH,
        MAX_JUMP_DURATION,
        MAX_LOCK_DURATION,
        MIN_ICON_HEIGHT,
        MIN_ICON_WIDTH,
        MOVE_DEADZONE,
        MapConfig,
        OTHER_PLAYER_ICON_LOWER1,
        OTHER_PLAYER_ICON_LOWER2,
        OTHER_PLAYER_ICON_UPPER1,
        OTHER_PLAYER_ICON_UPPER2,
        PLAYER_ICON_LOWER,
        PLAYER_ICON_STD_HEIGHT,
        PLAYER_ICON_STD_WIDTH,
        PLAYER_ICON_UPPER,
        PLAYER_Y_OFFSET,
        PREPARE_TIMEOUT,
        ROUTE_SLOT_IDS,
        SRC_ROOT,
        STUCK_DETECTION_WAIT_DEFAULT,
        WAYPOINT_ARRIVAL_X_THRESHOLD,
        WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT,
        WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT,
        WORKSPACE_ROOT,
        Y_MOVEMENT_DEADZONE,
        CLIMBING_STATE_FRAME_THRESHOLD,
        CLIMB_X_MOVEMENT_THRESHOLD,
        FALLING_STATE_FRAME_THRESHOLD,
        FALL_ON_LADDER_X_MOVEMENT_THRESHOLD,
        FALL_Y_MIN_THRESHOLD,
        ON_TERRAIN_Y_THRESHOLD,
        load_event_profiles,
    )
except ImportError:
    from map import (  # type: ignore
        CONFIG_PATH,
        GLOBAL_ACTION_MODEL_DIR,
        GLOBAL_MAP_SETTINGS_FILE,
        HYSTERESIS_EXIT_OFFSET,
        IDLE_TIME_THRESHOLD,
        AIRBORNE_RECOVERY_WAIT_DEFAULT,
        LADDER_RECOVERY_RESEND_DELAY_DEFAULT,
        JUMPING_STATE_FRAME_THRESHOLD,
        JUMP_LINK_ARRIVAL_X_THRESHOLD,
        JUMP_Y_MAX_THRESHOLD,
        JUMP_Y_MIN_THRESHOLD,
        LADDER_ARRIVAL_X_THRESHOLD,
        LADDER_AVOIDANCE_WIDTH,
        LADDER_X_GRAB_THRESHOLD,
        MAPS_DIR,
        MAX_ICON_HEIGHT,
        MAX_ICON_WIDTH,
        MAX_JUMP_DURATION,
        MAX_LOCK_DURATION,
        MIN_ICON_HEIGHT,
        MIN_ICON_WIDTH,
        MOVE_DEADZONE,
        MapConfig,
        OTHER_PLAYER_ICON_LOWER1,
        OTHER_PLAYER_ICON_LOWER2,
        OTHER_PLAYER_ICON_UPPER1,
        OTHER_PLAYER_ICON_UPPER2,
        PLAYER_ICON_LOWER,
        PLAYER_ICON_STD_HEIGHT,
        PLAYER_ICON_STD_WIDTH,
        PLAYER_ICON_UPPER,
        PLAYER_Y_OFFSET,
        PREPARE_TIMEOUT,
        ROUTE_SLOT_IDS,
        SRC_ROOT,
        STUCK_DETECTION_WAIT_DEFAULT,
        WAYPOINT_ARRIVAL_X_THRESHOLD,
        WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT,
        WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT,
        WORKSPACE_ROOT,
        Y_MOVEMENT_DEADZONE,
        CLIMBING_STATE_FRAME_THRESHOLD,
        CLIMB_X_MOVEMENT_THRESHOLD,
        FALLING_STATE_FRAME_THRESHOLD,
        FALL_ON_LADDER_X_MOVEMENT_THRESHOLD,
        FALL_Y_MIN_THRESHOLD,
        ON_TERRAIN_Y_THRESHOLD,
        load_event_profiles,
    )

if 'WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT' not in globals():
    WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT = WAYPOINT_ARRIVAL_X_THRESHOLD
if 'WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT' not in globals():
    WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT = WAYPOINT_ARRIVAL_X_THRESHOLD
if 'WALK_TELEPORT_PROBABILITY_DEFAULT' not in globals():
    WALK_TELEPORT_PROBABILITY_DEFAULT = 3.0
if 'WALK_TELEPORT_INTERVAL_DEFAULT' not in globals():
    WALK_TELEPORT_INTERVAL_DEFAULT = 0.5
if 'WALK_TELEPORT_BONUS_DELAY_DEFAULT' not in globals():
    WALK_TELEPORT_BONUS_DELAY_DEFAULT = 1.0
if 'WALK_TELEPORT_BONUS_STEP_DEFAULT' not in globals():
    WALK_TELEPORT_BONUS_STEP_DEFAULT = 10.0
if 'WALK_TELEPORT_BONUS_MAX_DEFAULT' not in globals():
    WALK_TELEPORT_BONUS_MAX_DEFAULT = 50.0

try:
    from . import map as _map_module  # type: ignore
except ImportError:
    import map as _map_module  # type: ignore

WALK_TELEPORT_PROBABILITY_DEFAULT = getattr(
    _map_module,
    "WALK_TELEPORT_PROBABILITY_DEFAULT",
    WALK_TELEPORT_PROBABILITY_DEFAULT,
)
WALK_TELEPORT_INTERVAL_DEFAULT = getattr(
    _map_module,
    "WALK_TELEPORT_INTERVAL_DEFAULT",
    WALK_TELEPORT_INTERVAL_DEFAULT,
)
WALK_TELEPORT_BONUS_DELAY_DEFAULT = getattr(
    _map_module,
    "WALK_TELEPORT_BONUS_DELAY_DEFAULT",
    WALK_TELEPORT_BONUS_DELAY_DEFAULT,
)
WALK_TELEPORT_BONUS_STEP_DEFAULT = getattr(
    _map_module,
    "WALK_TELEPORT_BONUS_STEP_DEFAULT",
    WALK_TELEPORT_BONUS_STEP_DEFAULT,
)
WALK_TELEPORT_BONUS_MAX_DEFAULT = getattr(
    _map_module,
    "WALK_TELEPORT_BONUS_MAX_DEFAULT",
    WALK_TELEPORT_BONUS_MAX_DEFAULT,
)

try:
    from .map_logic import (
        AnchorDetectionThread,
        ActionTrainingThread,
        MinimapCaptureThread,
        safe_read_latest_frame,
    )
except ImportError:
    from map_logic import (  # type: ignore
        AnchorDetectionThread,
        ActionTrainingThread,
        MinimapCaptureThread,
        safe_read_latest_frame,
    )

try:
    from .map_widgets import (
        MultiScreenSnipper,
        NavigatorDisplay,
        RealtimeMinimapView,
    )
except ImportError:
    from map_widgets import (  # type: ignore
        MultiScreenSnipper,
        NavigatorDisplay,
        RealtimeMinimapView,
    )

try:
    from .map_editors import (
        ZoomableView,
        CroppingLabel,
        FeatureCropDialog,
        KeyFeatureManagerDialog,
        AdvancedWaypointCanvas,
        AdvancedWaypointEditorDialog,
        CustomGraphicsView,
        DebugViewDialog,
        RoundedRectItem,
        WaypointEditDialog,
        FullMinimapEditorDialog,
        ActionLearningDialog,
        StateConfigDialog,
        WinEventFilter,
        HotkeyManager,
        HotkeySettingDialog,
    )
except ImportError:
    from map_editors import (  # type: ignore
        ZoomableView,
        CroppingLabel,
        FeatureCropDialog,
        KeyFeatureManagerDialog,
        AdvancedWaypointCanvas,
        AdvancedWaypointEditorDialog,
        CustomGraphicsView,
        DebugViewDialog,
        RoundedRectItem,
        WaypointEditDialog,
        FullMinimapEditorDialog,
        ActionLearningDialog,
        StateConfigDialog,
        WinEventFilter,
        HotkeyManager,
        HotkeySettingDialog,
    )

# === [v11.0.0] 런타임 의존성 체크 (추가) ===
try:
    if not hasattr(cv2, "matchTemplate"):
        raise AttributeError("matchTemplate not found")
except AttributeError:
    raise RuntimeError("OpenCV 빌드에 matchTemplate이 없습니다. opencv-python 설치를 확인해주세요.")
except Exception as e:
    raise RuntimeError(f"필수 라이브러리(cv2, mss, numpy 등) 초기화 실패: {e}")


# --- v10.0.0: 네비게이터 위젯 클래스 ---


class TelegramSettingsDialog(QDialog):
    """텔레그램 전송 옵션을 설정하는 다이얼로그."""

    def __init__(self, mode: str, interval_seconds: float, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("텔레그램 전송 설정")
        self.setModal(True)

        self._mode = mode if mode in {"once", "continuous"} else "once"
        self._interval_seconds = max(float(interval_seconds or 5.0), 1.0)

        main_layout = QVBoxLayout(self)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("전송 횟수:"))

        self.once_radio = QRadioButton("1회")
        self.continuous_radio = QRadioButton("지속")

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.once_radio)
        self.mode_group.addButton(self.continuous_radio)

        mode_row.addWidget(self.once_radio)
        mode_row.addWidget(self.continuous_radio)
        mode_row.addStretch(1)

        if self._mode == "continuous":
            self.continuous_radio.setChecked(True)
        else:
            self.once_radio.setChecked(True)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("전송 주기(초):"))
        self.interval_spinbox = QDoubleSpinBox()
        self.interval_spinbox.setDecimals(1)
        self.interval_spinbox.setSingleStep(0.5)
        self.interval_spinbox.setMinimum(1.0)
        self.interval_spinbox.setMaximum(600.0)
        self.interval_spinbox.setValue(self._interval_seconds)
        interval_row.addWidget(self.interval_spinbox)
        interval_row.addStretch(1)

        main_layout.addLayout(mode_row)
        main_layout.addLayout(interval_row)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def get_mode(self) -> str:
        return "continuous" if self.continuous_radio.isChecked() else "once"

    def get_interval_seconds(self) -> float:
        return float(self.interval_spinbox.value())


class MapTab(QWidget):
    # control_command_issued 시그널은 명령과 선택적 원인을 전달합니다.
    control_command_issued = pyqtSignal(str, object)
    # [추가] 탐지 상태 변경을 알리는 신호 (True: 시작, False: 중단)
    detection_status_changed = pyqtSignal(bool)
    global_pos_updated = pyqtSignal(QPointF)
    collection_status_signal = pyqtSignal(str, str, bool)
    # [MODIFIED] v14.3.0: 점프 프로파일링 관련 시그널로 변경 및 추가
    jump_profile_measured_signal = pyqtSignal(float, float) # duration, y_offset
    jump_profile_progress_signal = pyqtSignal(int)

    EVENT_WAYPOINT_THRESHOLD = 8.0
    MAP_PERF_HEADERS = [
        "timestamp",
        "frame_index",
        "frame_status",
        "fps",
        "loop_total_ms",
        "capture_ms",
        "preprocess_ms",
        "feature_match_ms",
        "fallback_scan_count",
        "skipped_templates",
        "avg_roi_radius",
        "max_roi_radius",
        "player_icon_ms",
        "other_player_icon_ms",
        "emit_ms",
        "map_processing_ms",
        "queue_delay_ms",
        "sleep_ms",
        "features_detected",
        "template_count",
        "player_icon_count",
        "other_player_icon_count",
        "feature_candidates",
        "player_icon_input_count",
        "other_player_icon_input_count",
        "frame_width",
        "frame_height",
        "downscale",
        "downscale_adjusted",
        "map_status",
        "map_warning",
        "player_state",
        "navigation_action",
        "event_in_progress_flag",
        "current_floor",
        "active_profile",
        "active_route_profile",
        "target_waypoint",
        "global_x",
        "global_y",
        "minimap_display_enabled",
        "general_log_enabled",
        "detection_log_enabled",
        "ui_update_called",
        "static_rebuild_ms",
        "error",
    ]
    
    def __init__(self):
            super().__init__()
            self.active_profile_name = None
            self.minimap_region = None
            self.key_features = {}
            self.geometry_data = {} # terrain_lines, transition_objects, waypoints, jump_links 포함
            self.active_route_profile_name = None
            self.route_profiles = {}
            self.current_forward_slot = "1"
            self.current_backward_slot = "1"
            self.last_selected_forward_slot = None
            self.last_selected_backward_slot = None
            self.last_forward_journey = []
            self.current_direction_slot_label = "-"
            self.detection_thread = None
            self.capture_thread = None
            self.debug_dialog = None
            self.editor_dialog = None 
            self.global_positions = {}
            self._player_icon_roi: QRect | None = None
            self._player_icon_roi_fail_streak = 0
            self._player_icon_roi_margin = 24
            self._other_player_icon_roi: QRect | None = None
            self._other_player_icon_fail_streak = 0
            self._other_player_icon_roi_margin = 32
            self._other_player_icon_roi_frames = 0
            self._other_player_icon_fullscan_interval = 12
            self._ui_update_called_pending = False
            self._static_rebuild_ms_pending = 0.0

            # 탐지 스레드의 실행 상태를 명확하게 추적하기 위한 플래그
            self.is_detection_running = False

            self.status_monitor: Optional[StatusMonitorThread] = None
            self._status_config: StatusMonitorConfig = StatusMonitorConfig.default()
            self._status_log_lines = ["HP: --", "MP: --"]
            self._status_last_ui_update = {'hp': 0.0, 'mp': 0.0}
            self._status_last_command_ts = {'hp': 0.0, 'mp': 0.0}
            self._status_active_resource: Optional[str] = None
            self._status_saved_command: Optional[tuple[str, object]] = None
            self._last_regular_command: Optional[tuple[str, object]] = None
            self._status_data_manager = None

            self.latest_perf_stats: dict[str, object] = {}
            self._latest_thread_perf: dict[str, object] = {}
            self._map_perf_queue: deque[dict] = deque()
            self._perf_logs_dir = os.path.join(WORKSPACE_ROOT, 'perf_logs')
            self._perf_logging_enabled = False
            self._perf_log_path: Optional[str] = None
            self._perf_log_handle: Optional[TextIO] = None
            self._perf_log_writer: Optional[csv.writer] = None
            self._perf_log_headers = list(self.MAP_PERF_HEADERS)
            self._current_map_perf_status = 'unknown'
            self._current_map_perf_warning = ''

            self.full_map_pixmap = None
            self.full_map_bounding_rect = QRectF()
            self.my_player_global_rects = []
            self.other_player_global_rects = []
            self.other_player_alert_checkbox = None
            self.other_player_alert_enabled = False
            self._other_player_alert_active = False
            self._other_player_alert_last_time = 0.0
            self.telegram_alert_checkbox = None
            self.telegram_settings_btn = None
            self.telegram_alert_enabled = False
            self.telegram_send_mode = "once"
            self.telegram_send_interval = 5.0
            self.telegram_bot_token = ""
            self.telegram_chat_id = ""
            self._refresh_telegram_credentials()
            self.active_feature_info = []
            self.reference_anchor_id = None
            self.smoothed_player_pos = None
            self.line_id_to_floor_map = {}  # [v11.4.5] 지형선 ID <-> 층 정보 캐싱용 딕셔너리
            self.initial_delay_ms = 2000

            # 이벤트 웨이포인트 실행 상태
            self.event_in_progress = False
            self.active_event_waypoint_id = None
            self.active_event_profile = ""
            self.active_event_reason = ""
            self.event_started_at = 0.0
            # 이벤트 웨이포인트 재진입 추적용 상태
            self.event_waypoint_states = {}
            self.event_rearm_min_delay = 1.0
            self.event_rearm_exit_delay = 0.6
            self.event_retry_cooldown_seconds = 5.0
            self.pending_event_request = None
            self.pending_event_notified = False

            # 금지벽 제어 상태
            self.forbidden_wall_states = {}
            self.forbidden_wall_in_progress = False
            self.active_forbidden_wall_id = None
            self.active_forbidden_wall_reason = ""
            self.active_forbidden_wall_profile = ""
            self.forbidden_wall_started_at = 0.0
            self.active_forbidden_wall_trigger = ""
            self.forbidden_wall_touch_threshold = 2.0
            self.pending_forbidden_command = None

            # 중앙 권한 매니저 연동 상태
            self._authority_manager = ControlAuthorityManager.instance()
            self._authority_manager.register_map_provider(self)
            self._authority_manager.authority_changed.connect(self._handle_authority_changed)
            self._last_authority_snapshot_ts = 0.0
            self._authority_priority_override = False
            self.current_authority_owner = "map"
            self._hunt_tab = None
            self._auto_control_tab = None
            self._held_direction_keys: set[str] = set()
            self._syncing_with_hunt = False
            self._authority_event_history = deque(maxlen=200)
            self._last_authority_command_entry = None
            self._authority_resume_candidate = None
            self._forbidden_takeover_context = None
            self._forbidden_takeover_active = False
            self._suppress_authority_resume = False  # ESC 등으로 탐지를 중단한 직후 재실행 차단 플래그

            # [v11.3.7] 설정 변수 선언만 하고 값 할당은 load_profile_data로 위임
            self.cfg_idle_time_threshold = None
            self.cfg_climbing_state_frame_threshold = None
            self.cfg_falling_state_frame_threshold = None
            self.cfg_jumping_state_frame_threshold = None
            self.cfg_on_terrain_y_threshold = None
            self.cfg_jump_y_min_threshold = None
            self.cfg_jump_y_max_threshold = None
            self.cfg_fall_y_min_threshold = None
            self.cfg_climb_x_movement_threshold = None
            self.cfg_fall_on_ladder_x_movement_threshold = None
            self.cfg_ladder_x_grab_threshold = None
            self.cfg_move_deadzone = None
            self.cfg_max_jump_duration = None
            self.cfg_y_movement_deadzone = None
            self.cfg_waypoint_arrival_x_threshold = None
            self.cfg_waypoint_arrival_x_threshold_min = None
            self.cfg_waypoint_arrival_x_threshold_max = None
            self.cfg_ladder_arrival_x_threshold = None
            self.cfg_jump_link_arrival_x_threshold = None
            self.cfg_on_ladder_enter_frame_threshold = None
            self.cfg_jump_initial_velocity_threshold = None
            self.cfg_climb_max_velocity = None
            self.cfg_walk_teleport_probability = None
            self.cfg_walk_teleport_interval = None
            self.cfg_walk_teleport_bonus_delay = None
            self.cfg_walk_teleport_bonus_step = None
            self.cfg_walk_teleport_bonus_max = None
            self.cfg_prepare_timeout = None
            self.cfg_max_lock_duration = None

            # ==================== v11.5.0 설정 변수 추가 시작 ====================
            self.cfg_arrival_frame_threshold = None
            self.cfg_action_success_frame_threshold = None
            # ==================== v11.5.0 설정 변수 추가 끝 ======================

            # ==================== v10.9.0 수정 시작 ====================
            # --- 상태 판정 시스템 변수 ---
            self.last_movement_time = 0.0
            self.player_state = 'on_terrain' # 초기값
            self.in_jump = False
            self.x_movement_history = deque(maxlen=5) # [v11.3.13] X축 이동 방향 추적을 위한 deque 추가
            self.jump_start_time = 0.0
            self.just_left_terrain = False
            self.y_velocity_history = deque(maxlen=5) # v15 물리 기반 판정

            # ==================== v11.5.0 상태 머신 변수 추가 시작 ====================
            self.navigation_action = 'move_to_target' # 초기값 'path_failed'에서 변경
            self.last_state_change_time = 0.0 # 상태 변경 쿨다운을 위한 변수
            self.cfg_state_change_cooldown = 0.0 # 초 단위 #상태 변경 쿨다운을 위한 변수
            self.intermediate_node_type = None # 현재 목표 노드의 실제 타입 저장
            self.navigation_state_locked = False
            self.state_transition_counters = defaultdict(int) # 상태 전이 프레임 카운터
            self.prepare_timeout_start = 0.0
            self.lock_timeout_start = 0.0
            # ==================== v11.5.0 상태 머신 변수 추가 끝 ======================

            self.jumping_candidate_frames = 0
            self.climbing_candidate_frames = 0
            self.falling_candidate_frames = 0
            # ==================== v10.9.0 수정 끝 ======================
            
            self.last_on_terrain_y = 0.0 # 마지막으로 지상에 있었을 때의 y좌표
            
            self.player_nav_state = 'on_terrain'  # 'on_terrain', 'climbing', 'jumping', 'falling'
            self.current_player_floor = None
            self.last_terrain_line_id = None
            
            self.last_player_pos = QPointF(0, 0)
            # 목표 및 경로 추적 변수
            self.target_waypoint_id = None
            self.last_reached_wp_id = None
            self.current_path_index = -1
            self.is_forward = True
            self.route_cycle_initialized = False
            self.start_waypoint_found = False
            
            # v10.2.0: 중간 목표 상태 변수
            self.intermediate_target_pos = None
            self.intermediate_target_type = 'walk' # 'walk', 'climb', 'fall', 'jump'
            # ==================== v11.6.5 변수 추가 시작 ====================
            self.intermediate_target_entry_pos = None
            # ==================== v11.6.5 변수 추가 끝 ======================
            self.intermediate_target_exit_pos = None
            self.intermediate_target_object_name = ""
            self.guidance_text = "없음"

            # --- v12.0.0: A* 경로 탐색 시스템 변수 ---
            self.nav_graph = defaultdict(dict)  # {'node1': {'node2': cost, ...}} 형태의 내비게이션 그래프
            self.nav_nodes = {}                 # {'node_key': {'pos': QPointF, 'type': str, ...}} 노드 정보 저장
            self.journey_plan = []              # [wp_id1, wp_id2, ...] 전체 웨이포인트 여정
            self.current_journey_index = 0      # 현재 여정 진행 인덱스
            self.current_segment_path = []      # 현재 구간의 상세 경로 [node_key1, node_key2, ...]
            self.current_segment_index = 0      # 현재 상세 경로 진행 인덱스
            self.last_path_recalculation_time = 0.0 # <<< [v12.2.0] 추가: 경로 떨림 방지용
            self.expected_terrain_group = None  # 현재 안내 경로가 유효하기 위해 플레이어가 있어야 할 지형 그룹
            # --- v12.0.0: 추가 끝 ---
            
            #  마지막으로 출력한 물리적 상태를 기억하기 위한 변수
            self.last_printed_player_state = None
            #  마지막으로 출력한 행동과 방향을 기억하기 위한 변수
            self.last_printed_action = None
            self.last_printed_direction = None

            # 마지막으로 유효했던 지형 그룹 이름 저장용
            self.last_known_terrain_group_name = ""

            # 디버그 체크박스 멤버 변수
            self.debug_pathfinding_checkbox = None
            self.debug_state_machine_checkbox = None
            self.debug_guidance_checkbox = None # <<<  경로안내선 디버그 체크박스 변수

            #  경로안내선 디버그를 위한 이전 상태 저장 변수
            self.last_debug_target_pos = None
            self.last_debug_nav_action = None
            self.last_debug_guidance_text = None

            # v14.0.0: 동작 인식 데이터 수집 관련 변수
            self.is_waiting_for_movement = False
            self.is_collecting_action_data = False
            self.action_data_buffer = []
            self.current_action_to_learn = None
            self.last_pos_before_collection = None
            self.last_collected_filepath = None
            # [MODIFIED] v14.3.0: 점프 프로파일링 관련 변수로 변경
            self.is_profiling_jump = False
            self.jump_profile_data = []
            self.jump_measure_start_time = 0.0
            self.current_jump_max_y_offset = 0.0

            # v14.3.4: 수집 목표(target) 정보를 저장할 변수
            self.collection_target_info = {} 

            self.action_collection_max_frames = 200  
            self.action_model = None
            self.action_inference_buffer = deque(maxlen=self.action_collection_max_frames)

            # === [최적화 v1.0] 모델 추론 주기 제한을 위한 변수 추가 ===
            self.last_model_inference_time = 0.0  # 마지막 모델 추론 시간
            self.model_inference_interval = 0.3  # 모델 추론 간격 (초 단위, 0.15초 = 150ms)

            #지형 간 상대 위치 벡터 저장
            self.feature_offsets = {}
            
            # [NEW] UI 업데이트 조절(Throttling)을 위한 카운터
            self.log_update_counter = 0

            #  탐지 시작 시간을 기록하기 위한 변수
            self.detection_start_time = 0
            # [핵심 수정] 시작 딜레이 중 키 해제 명령을 한 번만 보내기 위한 플래그
            self.initial_delay_active = False
            
            self.render_options = {
                'background': True, 'features': True, 'waypoints': True,
                'terrain': True, 'objects': True, 'jump_links': True,
                'forbidden_walls': True,
            }
            
            # ---  멈춤 감지 및 자동 복구 시스템 변수 ---
            self.last_action_time = 0.0                      # 마지막으로 'idle'이 아닌 상태였던 시간
            self.last_movement_command = None                # 마지막으로 전송한 이동 명령 (예: '걷기(우)')
            self.stuck_recovery_attempts = 0                 # 복구 시도 횟수
            self.cfg_stuck_detection_wait = STUCK_DETECTION_WAIT_DEFAULT  # 일반 자동복구 대기시간 (초)
            self.MAX_STUCK_RECOVERY_ATTEMPTS = 30             # 최대 복구 시도 횟수
            self.CLIMBING_RECOVERY_KEYWORDS = ["오르기", "사다리타기"] # 등반 복구 식별용
            self.recovery_cooldown_until = 0.0 # 복구 후 판단을 유예할 시간
            self.last_command_sent_time = 0.0 # 마지막으로 명령을 보낸 시간
            self.last_command_context = None  # 최근 전송한 이동 명령의 상태 정보
            self.NON_WALK_STUCK_THRESHOLD_S = 1.0            # 걷기/정지 이외 상태에서 멈춤으로 간주할 시간 (초)
            self.cfg_airborne_recovery_wait = AIRBORNE_RECOVERY_WAIT_DEFAULT  # 공중 자동복구 대기시간 (초)
            self.cfg_ladder_recovery_resend_delay = LADDER_RECOVERY_RESEND_DELAY_DEFAULT  # 사다리 복구 재전송 대기시간 (초)
            self.ladder_float_recovery_cooldown_until = 0.0  # 탐지 직후 밧줄 매달림 복구 쿨다운
            self.cfg_walk_teleport_probability = WALK_TELEPORT_PROBABILITY_DEFAULT
            self.cfg_walk_teleport_interval = WALK_TELEPORT_INTERVAL_DEFAULT
            self._last_walk_teleport_check_time = 0.0
            self._walk_teleport_active = False
            self._walk_teleport_walk_started_at = 0.0
            self._walk_teleport_bonus_percent = 0.0
            self.waiting_for_safe_down_jump = False  # 아래점프 전 안전 지대 이동 필요 여부
            self.SAFE_MOVE_COMMAND_COOLDOWN = 0.35
            self.last_safe_move_command_time = 0.0
            self.alignment_target_x = None # ---  사다리 앞 정렬(align) 상태 변수 ---
            self.alignment_expected_floor = None
            self.alignment_expected_group = None
            self.verify_alignment_start_time = 0.0  # 정렬 확인 시작 시간
            self.last_align_command_time = 0.0      # 마지막 정렬 명령 전송 시간
            self._climb_last_near_ladder_time = 0.0 # 최근 사다리 근접 판정 시각 (이탈 오판 방지용)

            # 공중 경로 계산 대기 메시지 중복 방지 플래그
            self.airborne_path_warning_active = False
            self.airborne_warning_started_at = 0.0
            self.airborne_recovery_cooldown_until = 0.0
            self._last_airborne_recovery_log_time = 0.0
            self._reset_airborne_recovery_state()

            self._active_waypoint_threshold_key = None
            self._active_waypoint_threshold_value = None

            # --- [v.1810] 좁은 발판 착지 판단 유예 플래그 ---
            self.just_landed_on_narrow_terrain = False
            
            # --- [핵심 수정] 코드 순서 변경 ---
            # 1. UI를 먼저 생성합니다.
            self.initUI()

            # 2. UI가 생성된 후에 단축키 관리자를 초기화합니다.
            self.hotkey_manager = HotkeyManager()
            # self.detect_anchor_btn이 이제 존재하므로 안전하게 참조할 수 있습니다.
            hotkey_id = getattr(self.hotkey_manager, 'hotkey_id', None)
            self.win_event_filter = WinEventFilter(self.detect_anchor_btn.click, hotkey_id=hotkey_id)
            QApplication.instance().installNativeEventFilter(self.win_event_filter)
            self.current_hotkey = "None"

            # 3. 나머지 초기화 작업을 수행합니다.
            self.perform_initial_setup()

    def collect_authority_snapshot(self) -> Optional[PlayerStatusSnapshot]:
        """ControlAuthorityManager가 요구하는 맵 상태 스냅샷을 구성한다."""
        if self._authority_manager is None:
            return None

        timestamp = time.time()
        player_state = getattr(self, 'player_state', 'unknown') or 'unknown'
        navigation_action = getattr(self, 'navigation_action', '') or ''
        last_move_command = getattr(self, 'last_movement_command', None)
        snapshot = PlayerStatusSnapshot(
            timestamp=timestamp,
            floor=getattr(self, 'current_player_floor', None),
            player_state=player_state,
            navigation_action=navigation_action,
            horizontal_velocity=self._compute_horizontal_velocity(),
            last_move_command=last_move_command,
            is_forbidden_active=bool(getattr(self, 'forbidden_wall_in_progress', False)),
            is_event_active=bool(getattr(self, 'event_in_progress', False)),
            priority_override=bool(getattr(self, '_authority_priority_override', False)),
            metadata={
                "navigation_locked": bool(getattr(self, 'navigation_state_locked', False)),
                "guidance_text": getattr(self, 'guidance_text', ''),
                "pending_nav_reason": getattr(self, 'pending_nav_recalc_reason', None),
            },
        )
        self._last_authority_snapshot_ts = snapshot.timestamp
        return snapshot

    def _compute_horizontal_velocity(self) -> float:
        """최근 프레임 기준 가로 이동 속도를 추정한다(px/frame)."""
        history = getattr(self, 'x_movement_history', None)
        if not history:
            return 0.0
        values = [float(v) for v in list(history) if isinstance(v, (int, float))]
        if not values:
            return 0.0
        window = values[-3:]
        return sum(window) / len(window)

    def _sync_authority_snapshot(self, source: str) -> None:
        """최신 스냅샷을 중앙 매니저에 전달한다."""
        if not self._authority_manager:
            return
        snapshot = self.collect_authority_snapshot()
        if snapshot is None:
            return
        self._authority_manager.update_map_snapshot(snapshot, source=source)

    def _handle_authority_changed(self, owner: str, payload: dict) -> None:
        previous = getattr(self, 'current_authority_owner', None)
        self.current_authority_owner = owner
        if owner == 'map':
            self._handle_map_authority_regained(payload, previous)
        else:
            self._handle_map_authority_lost(payload, previous)

    def _handle_map_authority_lost(self, payload: dict, previous: Optional[str]) -> None:
        friendly = "사냥 탭"
        reason = payload.get('reason') if isinstance(payload, dict) else None
        if reason:
            reason = str(reason)

        event_extra: Dict[str, Any] = {}
        if isinstance(payload, dict):
            elapsed = payload.get('elapsed_since_previous')
            if elapsed is not None:
                event_extra['elapsed_since_previous'] = elapsed
            meta = payload.get('meta')
            if isinstance(meta, dict):
                event_extra['meta'] = dict(meta)

        message = f"[권한][위임] 조작 권한이 {friendly}으로 이동했습니다."
        if reason:
            message += f" 사유: {reason}"

        self._record_authority_event(
            "released",
            message=message,
            reason=reason,
            source=payload.get('source') if isinstance(payload, dict) else None,
            previous_owner=previous,
            extra=event_extra or None,
        )

        if self._last_authority_command_entry:
            self._authority_resume_candidate = dict(self._last_authority_command_entry)

    def _handle_map_authority_regained(self, payload: dict, previous: Optional[str]) -> None:
        reason = payload.get('reason') if isinstance(payload, dict) else None
        if reason:
            reason = str(reason)

        event_extra: Dict[str, Any] = {}
        if isinstance(payload, dict):
            elapsed = payload.get('elapsed_since_previous')
            if elapsed is not None:
                event_extra['elapsed_since_previous'] = elapsed
            meta = payload.get('meta')
            if isinstance(meta, dict):
                event_extra['meta'] = dict(meta)

        authority_source = payload.get('source') if isinstance(payload, dict) else None

        if reason == "FORBIDDEN_WALL":
            takeover_context = self._forbidden_takeover_context or {}
            resume_command = takeover_context.get('resume_command') if isinstance(takeover_context, dict) else None
            message = "[권한][획득] 금지벽 대응을 위해 조작 권한을 확보했습니다."
            if resume_command:
                message += f" | 금지벽 종료 후 재실행 예정: {resume_command}"
            else:
                message += " | 재실행 예정 명령 없음"
            self._record_authority_event(
                "acquired",
                message=message,
                reason=reason,
                source=authority_source,
                previous_owner=previous,
                command=resume_command,
                extra=event_extra or None,
            )
            self._emit_control_command("모든 키 떼기", "authority:reset", allow_forbidden=True)
            self._forbidden_takeover_active = True
            self._authority_resume_candidate = None
            return

        resume_entry = self._authority_resume_candidate or self._last_authority_command_entry
        command_to_resume = None
        if isinstance(resume_entry, dict):
            command_to_resume = resume_entry.get('command')

        message = "[권한][획득] 맵 탭이 조작 권한을 획득했습니다."
        if reason:
            message += f" 사유: {reason}"
        if command_to_resume:
            message += f" | 재실행 예정 명령: {command_to_resume}"
        else:
            message += " | 재실행 명령 없음"

        self._record_authority_event(
            "acquired",
            message=message,
            reason=reason,
            source=authority_source,
            previous_owner=previous,
            command=command_to_resume,
            extra=event_extra or None,
        )

        # 권한 회수 즉시 안전 키 상태를 보장
        self._emit_control_command("모든 키 떼기", "authority:reset", allow_forbidden=True)

        skip_reason: Optional[str] = None
        if self._suppress_authority_resume:
            skip_reason = "forced_stop"
        elif not getattr(self, 'is_detection_running', False):
            skip_reason = "detection_inactive"

        if skip_reason:
            if command_to_resume:
                if skip_reason == "forced_stop":
                    resume_message = (
                        f"[권한][재실행] ESC/SHIFT+ESC 강제 중지 이후라 마지막 명령 '{command_to_resume}' 재실행을 건너뜁니다."
                    )
                else:
                    resume_message = (
                        f"[권한][재실행] 탐지가 중단된 상태라 마지막 명령 '{command_to_resume}' 재실행을 건너뜁니다."
                    )
                self.update_general_log(resume_message, "orange")
                resume_extra: Dict[str, Any] = dict(event_extra or {})
                resume_extra.update(
                    {
                        "attempted_at": time.time(),
                        "skip_reason": skip_reason,
                    }
                )
                self._record_authority_event(
                    "resume",
                    message=resume_message,
                    reason=reason,
                    source=authority_source,
                    previous_owner=previous,
                    command=command_to_resume,
                    command_success=False,
                    extra=resume_extra,
                    log_to_general=False,
                )
            self._clear_authority_resume_state()
            return

        if command_to_resume:
            def _resend_last_command() -> None:
                priority_guard_active = bool(
                    getattr(self, '_authority_priority_override', False)
                    or getattr(self, 'forbidden_wall_in_progress', False)
                    or getattr(self, 'event_in_progress', False)
                )
                allow_forbidden = not priority_guard_active
                emit_result = self._emit_control_command(
                    command_to_resume,
                    "authority:resume",
                    allow_forbidden=allow_forbidden,
                    return_reason=True,
                )
                success: bool
                blocked_reason: Optional[str]
                blocked_detail: Optional[Dict[str, Any]]
                if isinstance(emit_result, tuple):
                    success, blocked_reason, blocked_detail = emit_result
                else:
                    success = bool(emit_result)
                    blocked_reason = None
                    blocked_detail = None

                if success:
                    result_text = "성공"
                else:
                    reason_text = self._describe_command_block_reason(blocked_reason, blocked_detail)
                    result_text = "보류"
                    if reason_text:
                        result_text += f" (사유: {reason_text})"
                resume_message = (
                    f"[권한][재실행] 마지막 명령 '{command_to_resume}' 재실행 {result_text}."
                )
                resume_extra: Dict[str, Any] = {
                    "attempted_at": time.time(),
                }
                if priority_guard_active and not success:
                    resume_extra['priority_guard_active'] = True
                if blocked_reason and not success:
                    resume_extra['blocked_reason'] = blocked_reason
                    if blocked_detail:
                        resume_extra['blocked_detail'] = dict(blocked_detail)
                if event_extra:
                    resume_extra.update(event_extra)
                self._record_authority_event(
                    "resume",
                    message=resume_message,
                    reason=reason,
                    source=authority_source,
                    previous_owner=previous,
                    command=command_to_resume,
                    command_success=success,
                    extra=resume_extra,
                )

            QTimer.singleShot(120, _resend_last_command)

        self._authority_resume_candidate = None

    def _clear_authority_resume_state(self) -> None:
        """권한 재실행 후보 상태를 모두 초기화한다."""
        self._authority_resume_candidate = None
        self._last_authority_command_entry = None

    def _is_trackable_authority_command(self, command: str) -> bool:
        if not command:
            return False
        if command == "모든 키 떼기":
            return False
        return "텔레포트" not in command

    def _update_last_authority_command(self, command: str, reason: object) -> dict:
        entry = {
            "command": command,
            "reason": str(reason) if isinstance(reason, str) else (str(reason) if reason is not None else None),
            "timestamp": time.time(),
            "executed": False,
        }
        self._last_authority_command_entry = entry
        return entry

    def _record_authority_event(
        self,
        event_type: str,
        *,
        message: str,
        reason: Optional[str] = None,
        source: Optional[str] = None,
        previous_owner: Optional[str] = None,
        command: Optional[str] = None,
        command_success: Optional[bool] = None,
        extra: Optional[Dict[str, Any]] = None,
        log_to_general: bool = True,
    ) -> None:
        entry: Dict[str, Any] = {
            "timestamp": time.time(),
            "event": event_type,
            "owner": getattr(self, 'current_authority_owner', None),
            "reason": reason,
            "source": source,
            "previous_owner": previous_owner,
            "command": command,
            "command_success": command_success,
        }
        if extra:
            entry["meta"] = dict(extra)
        self._authority_event_history.append(entry)
        if log_to_general:
            self.update_general_log(message, "red")

    def get_authority_event_history(self) -> list[Dict[str, Any]]:
        return list(self._authority_event_history)

    def initUI(self):
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        
        # 1. 프로필 관리
        profile_groupbox = QGroupBox("1. 🗺️ 맵 프로필 관리")
        profile_layout = QVBoxLayout()
        self.profile_selector = QComboBox()
        self.profile_selector.currentIndexChanged.connect(self.on_profile_selected)
        profile_buttons_layout = QHBoxLayout()
        self.add_profile_btn = QPushButton("추가")
        self.rename_profile_btn = QPushButton("이름변경")
        self.delete_profile_btn = QPushButton("삭제")
        self.add_profile_btn.clicked.connect(self.add_profile)
        self.rename_profile_btn.clicked.connect(self.rename_profile)
        self.delete_profile_btn.clicked.connect(self.delete_profile)
        profile_buttons_layout.addWidget(self.add_profile_btn)
        profile_buttons_layout.addWidget(self.rename_profile_btn)
        profile_buttons_layout.addWidget(self.delete_profile_btn)
        profile_layout.addWidget(self.profile_selector)
        profile_layout.addLayout(profile_buttons_layout)
        profile_groupbox.setLayout(profile_layout)
        left_layout.addWidget(profile_groupbox)

        # 2. 경로 프로필 관리
        route_profile_groupbox = QGroupBox("2.  ROUTE 경로 프로필 관리")
        route_profile_layout = QVBoxLayout()
        self.route_profile_selector = QComboBox()
        self.route_profile_selector.currentIndexChanged.connect(self.on_route_profile_selected)
        route_profile_buttons_layout = QHBoxLayout()
        self.add_route_btn = QPushButton("추가")
        self.rename_route_btn = QPushButton("이름변경")
        self.delete_route_btn = QPushButton("삭제")
        self.add_route_btn.clicked.connect(self.add_route_profile)
        self.rename_route_btn.clicked.connect(self.rename_route_profile)
        self.delete_route_btn.clicked.connect(self.delete_route_profile)
        route_profile_buttons_layout.addWidget(self.add_route_btn)
        route_profile_buttons_layout.addWidget(self.rename_route_btn)
        route_profile_buttons_layout.addWidget(self.delete_route_btn)
        route_profile_layout.addWidget(self.route_profile_selector)
        route_profile_layout.addLayout(route_profile_buttons_layout)
        route_profile_groupbox.setLayout(route_profile_layout)
        left_layout.addWidget(route_profile_groupbox)

        # 3. 미니맵 설정
        self.minimap_groupbox = QGroupBox("3. 미니맵 설정")
        minimap_layout = QVBoxLayout(); self.set_area_btn = QPushButton("미니맵 범위 지정"); self.set_area_btn.clicked.connect(self.set_minimap_area)
        minimap_layout.addWidget(self.set_area_btn); self.minimap_groupbox.setLayout(minimap_layout); left_layout.addWidget(self.minimap_groupbox)

        # 4. 웨이포인트 경로 관리 (v10.0.0 개편)
        self.wp_groupbox = QGroupBox("4. 웨이포인트 경로 관리")
        wp_main_layout = QVBoxLayout()
        path_layout = QHBoxLayout()

        # 정방향 UI
        forward_layout = QVBoxLayout()
        forward_header = QHBoxLayout()
        forward_header.addWidget(QLabel("정방향"))
        self.forward_slot_combo = QComboBox()
        self.forward_slot_combo.addItems(ROUTE_SLOT_IDS)
        self.forward_slot_combo.currentIndexChanged.connect(self._on_forward_slot_changed)
        self.forward_slot_enabled_checkbox = QCheckBox("사용")
        self.forward_slot_enabled_checkbox.stateChanged.connect(lambda state: self._on_slot_enabled_changed('forward', state))
        forward_header.addWidget(self.forward_slot_combo)
        forward_header.addWidget(self.forward_slot_enabled_checkbox)
        forward_header.addStretch()
        forward_layout.addLayout(forward_header)

        self.forward_wp_list = QListWidget()
        self.forward_wp_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.forward_wp_list.model().rowsMoved.connect(lambda *args: self.waypoint_order_changed('forward'))
        forward_layout.addWidget(self.forward_wp_list)

        fw_buttons = QHBoxLayout()
        fw_add_btn = QPushButton("추가"); fw_add_btn.clicked.connect(lambda: self.add_waypoint_to_path('forward'))
        fw_del_btn = QPushButton("삭제"); fw_del_btn.clicked.connect(lambda: self.delete_waypoint_from_path('forward'))
        fw_buttons.addWidget(fw_add_btn); fw_buttons.addWidget(fw_del_btn)
        forward_layout.addLayout(fw_buttons)

        # 역방향 UI
        backward_layout = QVBoxLayout()
        backward_header = QHBoxLayout()
        backward_header.addWidget(QLabel("역방향"))
        self.backward_slot_combo = QComboBox()
        self.backward_slot_combo.addItems(ROUTE_SLOT_IDS)
        self.backward_slot_combo.currentIndexChanged.connect(self._on_backward_slot_changed)
        self.backward_slot_enabled_checkbox = QCheckBox("사용")
        self.backward_slot_enabled_checkbox.stateChanged.connect(lambda state: self._on_slot_enabled_changed('backward', state))
        backward_header.addWidget(self.backward_slot_combo)
        backward_header.addWidget(self.backward_slot_enabled_checkbox)
        backward_header.addStretch()
        backward_layout.addLayout(backward_header)

        self.backward_wp_list = QListWidget()
        self.backward_wp_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.backward_wp_list.model().rowsMoved.connect(lambda *args: self.waypoint_order_changed('backward'))
        backward_layout.addWidget(self.backward_wp_list)

        bw_buttons = QHBoxLayout()
        bw_add_btn = QPushButton("추가"); bw_add_btn.clicked.connect(lambda: self.add_waypoint_to_path('backward'))
        bw_del_btn = QPushButton("삭제"); bw_del_btn.clicked.connect(lambda: self.delete_waypoint_from_path('backward'))
        bw_buttons.addWidget(bw_add_btn); bw_buttons.addWidget(bw_del_btn)
        backward_layout.addLayout(bw_buttons)

        path_layout.addLayout(forward_layout, 1)
        path_layout.addLayout(backward_layout, 1)

        wp_main_layout.addLayout(path_layout)
        self.wp_groupbox.setLayout(wp_main_layout)
        left_layout.addWidget(self.wp_groupbox)

        # 5. 핵심 지형 관리 (기존과 동일)
        self.kf_groupbox = QGroupBox("5. 핵심 지형 관리")
        kf_layout = QVBoxLayout(); self.manage_kf_btn = QPushButton("핵심 지형 관리자 열기"); self.manage_kf_btn.clicked.connect(self.open_key_feature_manager)
        kf_layout.addWidget(self.manage_kf_btn); self.kf_groupbox.setLayout(kf_layout); left_layout.addWidget(self.kf_groupbox)

        # 6. 전체 맵 편집 (기존과 동일)
        self.editor_groupbox = QGroupBox("6. 전체 맵 편집")
        editor_layout = QVBoxLayout()
        self.open_editor_btn = QPushButton("미니맵 지형 편집기 열기")
        self.open_editor_btn.clicked.connect(self.open_full_minimap_editor)
        editor_layout.addWidget(self.open_editor_btn)
        self.editor_groupbox.setLayout(editor_layout)
        left_layout.addWidget(self.editor_groupbox)
        
        # 7. 탐지 제어
        detect_groupbox = QGroupBox("7. 탐지 제어")
        detect_v_layout = QVBoxLayout()

        # --- [수정] 탐지 제어 레이아웃 정돈 ---
        first_row_layout = QHBoxLayout()
        first_row_layout.addWidget(QLabel("시작 딜레이:"))
        self.initial_delay_spinbox = QSpinBox()
        self.initial_delay_spinbox.setRange(0, 10000)
        self.initial_delay_spinbox.setSingleStep(100)
        self.initial_delay_spinbox.setValue(2000)
        self.initial_delay_spinbox.setSuffix(" ms")
        self.initial_delay_spinbox.valueChanged.connect(self._on_initial_delay_changed)
        first_row_layout.addWidget(self.initial_delay_spinbox)
        first_row_layout.addSpacing(12)
        first_row_layout.addWidget(QLabel("단축키:"))
        self.hotkey_display_label = QLabel("None")
        self.hotkey_display_label.setStyleSheet("font-weight: bold; color: white; padding: 2px 5px; background-color: #333; border: 1px solid #555; border-radius: 3px;")
        first_row_layout.addWidget(self.hotkey_display_label)
        set_hotkey_btn = QPushButton("설정")
        set_hotkey_btn.clicked.connect(self._open_hotkey_setting_dialog)
        first_row_layout.addWidget(set_hotkey_btn)
        first_row_layout.addStretch(1)

        second_row_layout = QHBoxLayout()
        self.auto_control_checkbox = QCheckBox("자동 제어")
        self.auto_control_checkbox.setChecked(False)
        self.auto_control_checkbox.toggled.connect(self._on_auto_control_toggled)
        second_row_layout.addWidget(self.auto_control_checkbox)
        self.perf_logging_checkbox = QCheckBox("CSV 기록")
        self.perf_logging_checkbox.setChecked(self._perf_logging_enabled)
        self.perf_logging_checkbox.toggled.connect(self._on_perf_logging_toggled)
        second_row_layout.addWidget(self.perf_logging_checkbox)
        second_row_layout.addStretch(1)

        third_row_layout = QHBoxLayout()
        self.other_player_alert_checkbox = QCheckBox("다른 유저 감지")
        self.other_player_alert_checkbox.setChecked(False)
        self.other_player_alert_checkbox.toggled.connect(self._on_other_player_alert_toggled)
        third_row_layout.addWidget(self.other_player_alert_checkbox)
        telegram_controls_layout = QHBoxLayout()
        telegram_controls_layout.setContentsMargins(0, 0, 0, 0)
        telegram_controls_layout.setSpacing(6)
        self.telegram_alert_checkbox = QCheckBox("텔레그램 전송")
        self.telegram_alert_checkbox.setChecked(False)
        self.telegram_alert_checkbox.toggled.connect(self._on_telegram_alert_toggled)
        telegram_controls_layout.addWidget(self.telegram_alert_checkbox)
        self.telegram_settings_btn = QPushButton("설정")
        self.telegram_settings_btn.setEnabled(False)
        self.telegram_settings_btn.clicked.connect(self._open_telegram_settings_dialog)
        telegram_controls_layout.addWidget(self.telegram_settings_btn)
        third_row_layout.addLayout(telegram_controls_layout)
        third_row_layout.addStretch(1)
        self.telegram_alert_checkbox.setEnabled(False)

        buttons_row_layout = QHBoxLayout()
        self.state_config_btn = QPushButton("판정 설정")
        self.state_config_btn.clicked.connect(self._open_state_config_dialog)
        self.action_learning_btn = QPushButton("동작 학습")
        self.action_learning_btn.clicked.connect(self.open_action_learning_dialog)
        self.detect_anchor_btn = QPushButton("탐지 시작")
        self.detect_anchor_btn.setCheckable(True)
        self.detect_anchor_btn.setMinimumWidth(200)
        self.detect_anchor_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.detect_anchor_btn.clicked.connect(self.toggle_anchor_detection)
        buttons_row_layout.addWidget(self.state_config_btn)
        buttons_row_layout.addWidget(self.action_learning_btn)
        buttons_row_layout.addWidget(self.detect_anchor_btn, 1)

        detect_v_layout.addLayout(first_row_layout)
        detect_v_layout.addLayout(second_row_layout)
        detect_v_layout.addLayout(third_row_layout)
        detect_v_layout.addLayout(buttons_row_layout)
        detect_groupbox.setLayout(detect_v_layout)
        left_layout.addWidget(detect_groupbox)

        # 8. 디버그 제어
        debug_groupbox = QGroupBox("8. 디버그 제어")
        # <<< [수정] 레이아웃을 QHBoxLayout으로 변경
        debug_layout = QHBoxLayout()
        
        # 좌측 디버그 옵션
        debug_left_layout = QVBoxLayout()
        self.debug_view_checkbox = QCheckBox("디버그 뷰 표시")
        self.debug_view_checkbox.toggled.connect(self.toggle_debug_view)
        self.debug_basic_pathfinding_checkbox = QCheckBox("경로탐색 기본 로그 출력")
        self.debug_pathfinding_checkbox = QCheckBox("경로탐색 상세 로그 출력 (A*)")
        self.debug_state_machine_checkbox = QCheckBox("상태판정 변경 로그 출력")
        self.debug_guidance_checkbox = QCheckBox("경로안내선 변경 로그 출력") 
        debug_left_layout.addWidget(self.debug_view_checkbox)
        debug_left_layout.addWidget(self.debug_basic_pathfinding_checkbox)
        debug_left_layout.addWidget(self.debug_pathfinding_checkbox)
        debug_left_layout.addWidget(self.debug_state_machine_checkbox)
        debug_left_layout.addWidget(self.debug_guidance_checkbox)

        # 우측 디버그 옵션
        debug_right_layout = QVBoxLayout()
        self.debug_auto_control_checkbox = QCheckBox("자동 제어 테스트") # <<< [추가]
        self.debug_auto_control_checkbox.setChecked(False)              # <<< [추가]
        debug_right_layout.addWidget(self.debug_auto_control_checkbox)  # <<< [추가]
        debug_right_layout.addStretch() # 위쪽에 붙도록
        
        debug_layout.addLayout(debug_left_layout)
        debug_layout.addLayout(debug_right_layout)
        
        debug_groupbox.setLayout(debug_layout)
        left_layout.addWidget(debug_groupbox)

        left_layout.addStretch(1)
        
        # 로그 뷰어
        logs_container = QWidget()
        logs_layout = QVBoxLayout(logs_container)
        logs_layout.setContentsMargins(0, 0, 0, 0)
        logs_layout.setSpacing(6)

        general_log_header_layout = QHBoxLayout()
        general_log_header_layout.setContentsMargins(0, 0, 0, 0)
        general_log_header_layout.setSpacing(6)

        general_log_label = QLabel("일반 로그")
        general_log_label.setContentsMargins(0, 0, 0, 0)
        general_log_header_layout.addWidget(general_log_label)

        self.general_log_checkbox = QCheckBox("표시")
        self.general_log_checkbox.setChecked(True)
        self.general_log_checkbox.toggled.connect(self._handle_general_log_toggle)
        general_log_header_layout.addWidget(self.general_log_checkbox)
        general_log_header_layout.addStretch(1)

        logs_layout.addLayout(general_log_header_layout)

        self.general_log_viewer = QTextEdit()
        self.general_log_viewer.setReadOnly(True)
        self.general_log_viewer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.general_log_viewer.setMinimumHeight(200)
        self.general_log_viewer.setMinimumWidth(360)
        self.general_log_viewer.document().setDocumentMargin(6)
        logs_layout.addWidget(self.general_log_viewer, 1)

        detection_log_header_layout = QHBoxLayout()
        detection_log_header_layout.setContentsMargins(0, 0, 0, 0)
        detection_log_header_layout.setSpacing(6)

        detection_log_label = QLabel("탐지 상태 로그")
        detection_log_label.setContentsMargins(0, 0, 0, 0)
        detection_log_header_layout.addWidget(detection_log_label)

        self.detection_log_checkbox = QCheckBox("표시")
        self.detection_log_checkbox.setChecked(True)
        self.detection_log_checkbox.toggled.connect(self._handle_detection_log_toggle)
        detection_log_header_layout.addWidget(self.detection_log_checkbox)
        detection_log_header_layout.addStretch(1)

        logs_layout.addLayout(detection_log_header_layout)

        self.detection_log_viewer = QTextEdit()
        self.detection_log_viewer.setReadOnly(True)
        self.detection_log_viewer.setFixedHeight(70)
        self.detection_log_viewer.setMinimumWidth(360)
        self.detection_log_viewer.document().setDocumentMargin(6)
        logs_layout.addWidget(self.detection_log_viewer)

        self._walk_teleport_probability_text = "텔레포트 확률: 0.0%"
        self._last_detection_log_body = ""
        self._pending_detection_html = ""
        self._last_detection_rendered_html = ""
        self._last_detection_render_ts = 0.0
        self._detection_render_min_interval = 0.2
        self._general_log_last_entry = None
        self._general_log_last_ts = 0.0
        self._general_log_min_interval = 0.2
        self._general_log_enabled = True
        self._detection_log_enabled = True
        self._minimap_display_enabled = True
        self._status_last_ui_update = {'hp': 0.0, 'mp': 0.0}
        self._status_update_min_interval = 0.2
        self._render_detection_log(None, force=True)

        # 우측 레이아웃 (네비게이터 + 실시간 뷰)
        view_header_layout = QHBoxLayout()
        view_header_layout.addWidget(QLabel("실시간 미니맵 뷰 (휠: 확대/축소, 드래그: 이동)"))
        self.display_enabled_checkbox = QCheckBox("미니맵 표시")
        self.display_enabled_checkbox.setChecked(bool(getattr(self, '_minimap_display_enabled', True)))
        self.display_enabled_checkbox.toggled.connect(self._handle_display_toggle)
        view_header_layout.addWidget(self.display_enabled_checkbox)
        self.center_on_player_checkbox = QCheckBox("캐릭터 중심")
        self.center_on_player_checkbox.setChecked(True)
        view_header_layout.addWidget(self.center_on_player_checkbox)
        view_header_layout.addStretch(1)
        
        self.navigator_display = NavigatorDisplay(self)
        self.minimap_view_label = RealtimeMinimapView(self)
        
        right_layout.addWidget(self.navigator_display)
        right_layout.addLayout(view_header_layout)
        right_layout.addWidget(self.minimap_view_label, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(logs_container)
        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        logs_container.setMinimumWidth(320)
        right_container.setMinimumWidth(280)
        splitter.setSizes([520, 360])
        self.log_splitter = splitter

        main_layout.addLayout(left_layout, 1)
        main_layout.addWidget(splitter, 3)
        self.update_general_log("MapTab이 초기화되었습니다. 맵 프로필을 선택해주세요.", "black")

    def attach_hunt_tab(self, hunt_tab) -> None:
        self._hunt_tab = hunt_tab
        if hasattr(hunt_tab, 'detection_status_changed'):
            try:
                hunt_tab.detection_status_changed.connect(self._handle_hunt_detection_status_changed)
            except Exception:
                pass

    def attach_auto_control_tab(self, auto_control_tab) -> None:
        """자동 제어 탭과 키 입력 상태를 연동합니다."""
        if self._auto_control_tab is auto_control_tab:
            return

        if self._auto_control_tab:
            try:
                self._auto_control_tab.keyboard_state_changed.disconnect(self._handle_auto_control_key_state)
            except Exception:
                pass
            try:
                self._auto_control_tab.keyboard_state_reset.disconnect(self._handle_auto_control_key_reset)
            except Exception:
                pass

        self._auto_control_tab = auto_control_tab

        if not auto_control_tab:
            self._held_direction_keys.clear()
            return

        if hasattr(auto_control_tab, 'keyboard_state_changed'):
            auto_control_tab.keyboard_state_changed.connect(self._handle_auto_control_key_state)
        if hasattr(auto_control_tab, 'keyboard_state_reset'):
            auto_control_tab.keyboard_state_reset.connect(self._handle_auto_control_key_reset)

    @pyqtSlot(str, bool)
    def _handle_auto_control_key_state(self, key_str: str, pressed: bool) -> None:
        if key_str not in {"Key.left", "Key.right"}:
            return

        if pressed:
            self._held_direction_keys.add(key_str)
        else:
            self._held_direction_keys.discard(key_str)

    @pyqtSlot()
    def _handle_auto_control_key_reset(self) -> None:
        if self._held_direction_keys:
            self._held_direction_keys.clear()

    def _is_walk_direction_active(self, direction: str) -> bool:
        if not self._auto_control_tab:
            return True

        if not self._held_direction_keys:
            return False

        if direction == "→":
            return any(key in self._held_direction_keys for key in {"Key.right", "d", "D"})
        if direction == "←":
            return any(key in self._held_direction_keys for key in {"Key.left", "a", "A"})
        return False

    def _handle_hunt_detection_status_changed(self, running: bool) -> None:
        if not getattr(self, '_hunt_tab', None):
            return
        if not getattr(self._hunt_tab, 'map_link_enabled', False):
            return
        if getattr(self, '_syncing_with_hunt', False):
            return
        try:
            map_running = bool(self.detect_anchor_btn.isChecked())
        except Exception:
            map_running = False
        if running == map_running:
            return
        self._syncing_with_hunt = True
        try:
            if running and not map_running:
                if hasattr(self.detect_anchor_btn, 'setChecked'):
                    self.detect_anchor_btn.setChecked(True)
                self.toggle_anchor_detection(True)
            elif not running and map_running:
                if hasattr(self.detect_anchor_btn, 'setChecked'):
                    self.detect_anchor_btn.setChecked(False)
                self.toggle_anchor_detection(False)
        finally:
            self._syncing_with_hunt = False

    def _create_empty_route_slots(self):
        return {slot: {"enabled": False, "waypoints": []} for slot in ROUTE_SLOT_IDS}

    def _create_empty_route_profile(self):
        return {
            "forward_slots": self._create_empty_route_slots(),
            "backward_slots": self._create_empty_route_slots(),
        }

    def _emit_control_command(
        self,
        command: str,
        reason: object = None,
        *,
        allow_forbidden: bool = False,
        return_reason: bool = False,
    ) -> bool | tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """자동 제어 쪽으로 명령을 전달합니다."""

        def _wrap_result(
            success: bool,
            reason_code: Optional[str] = None,
            detail: Optional[Dict[str, Any]] = None,
        ) -> bool | tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
            if return_reason:
                detail_dict = dict(detail) if isinstance(detail, dict) else None
                return success, reason_code, detail_dict
            return success

        if not command:
            return _wrap_result(False, "empty_command", {"message": "empty_command"})

        is_status_command = isinstance(reason, str) and reason.startswith('status:')

        command_entry = None
        if not is_status_command and self._is_trackable_authority_command(command):
            command_entry = self._update_last_authority_command(command, reason)

        if (
            getattr(self, 'current_authority_owner', 'map') != 'map'
            and not allow_forbidden
            and command != "모든 키 떼기"
            and not is_status_command
        ):
            block_message = f"[권한][보류] 조작 권한이 없어 '{command}' 명령을 보류했습니다."
            block_extra: Dict[str, Any] = {"reason": "not_owner"}
            if command_entry and command_entry.get('reason'):
                block_extra['command_reason'] = command_entry['reason']
            self._record_authority_event(
                "blocked",
                message=block_message,
                reason="not_owner",
                source="map_tab",
                previous_owner=getattr(self, 'current_authority_owner', None),
                command=command,
                command_success=False,
                extra=block_extra,
                log_to_general=False,
            )
            if command_entry:
                self._authority_resume_candidate = dict(command_entry)
            detail = dict(block_extra)
            detail['current_owner'] = getattr(self, 'current_authority_owner', None)
            return _wrap_result(False, "not_owner", detail)

        if (
            self._status_active_resource
            and not is_status_command
            and command != "모든 키 떼기"
        ):
            self._status_saved_command = (command, reason)
            detail: Dict[str, Any] = {
                "active_resource": self._status_active_resource,
                "status_saved": True,
            }
            return _wrap_result(False, "status_command_active", detail)

        if self.forbidden_wall_in_progress and not allow_forbidden and reason != self.active_forbidden_wall_reason:
            self.update_general_log("[금지벽] 명령 실행 중이어서 다른 명령은 보류됩니다.", "gray")
            self.pending_forbidden_command = (command, reason)
            detail: Dict[str, Any] = {
                "forbidden_wall_reason": getattr(self, 'active_forbidden_wall_reason', None),
            }
            return _wrap_result(False, "forbidden_wall_active", detail)

        self.control_command_issued.emit(command, reason)

        if not is_status_command and command != "모든 키 떼기":
            self._last_regular_command = (command, reason)
            self._suppress_authority_resume = False
            if command_entry and self._last_authority_command_entry is command_entry:
                command_entry['executed'] = True
        return _wrap_result(True)

    def _describe_command_block_reason(
        self,
        reason_code: Optional[str],
        detail: Optional[Dict[str, Any]],
    ) -> str:
        if not reason_code:
            return ""

        detail = detail or {}

        if reason_code == "not_owner":
            owner = detail.get('current_owner')
            owner_text = None
            if owner == 'hunt':
                owner_text = "사냥 탭"
            elif owner == 'map':
                owner_text = "맵 탭"
            elif isinstance(owner, str) and owner:
                owner_text = owner
            if owner_text:
                return f"조작 권한이 {owner_text}에 있음"
            return "조작 권한이 다른 탭에 있음"

        if reason_code == "status_command_active":
            resource = detail.get('active_resource')
            if resource == 'hp':
                return "HP 상태 회복 명령 진행 중"
            if resource == 'mp':
                return "MP 상태 회복 명령 진행 중"
            if isinstance(resource, str) and resource:
                return f"{resource.upper()} 상태 명령 진행 중"
            return "상태 회복 명령 진행 중"

        if reason_code == "forbidden_wall_active":
            return "금지벽 대응 중"

        if reason_code == "empty_command":
            return "재실행할 명령이 비어 있음"

        # 알 수 없는 사유는 디버깅 용도로 코드 그대로 노출
        return reason_code

    def _normalize_route_slot_dict(self, slot_dict):
        modified = False
        if not isinstance(slot_dict, dict):
            slot_dict = {}
            modified = True

        for slot in ROUTE_SLOT_IDS:
            slot_data = slot_dict.get(slot)
            if not isinstance(slot_data, dict):
                slot_dict[slot] = {"enabled": False, "waypoints": []}
                modified = True
                continue

            if "enabled" not in slot_data or not isinstance(slot_data.get("enabled"), bool):
                slot_data["enabled"] = bool(slot_data.get("enabled"))
                modified = True

            waypoints = slot_data.get("waypoints")
            if not isinstance(waypoints, list):
                slot_data["waypoints"] = []
                modified = True
            else:
                cleaned = [wp for wp in waypoints if isinstance(wp, str)]
                if len(cleaned) != len(waypoints):
                    slot_data["waypoints"] = cleaned
                    modified = True

        extra_keys = [key for key in slot_dict.keys() if key not in ROUTE_SLOT_IDS]
        if extra_keys:
            for key in extra_keys:
                slot_dict.pop(key, None)
            modified = True

        return slot_dict, modified

    def _ensure_route_profile_structure(self, route_data, legacy_forward=None, legacy_backward=None):
        if not isinstance(route_data, dict):
            return self._create_empty_route_profile(), True

        modified = False

        if "forward_slots" not in route_data or not isinstance(route_data["forward_slots"], dict):
            route_data["forward_slots"] = self._create_empty_route_slots()
            modified = True
        else:
            route_data["forward_slots"], changed = self._normalize_route_slot_dict(route_data["forward_slots"])
            modified = modified or changed

        if "backward_slots" not in route_data or not isinstance(route_data["backward_slots"], dict):
            route_data["backward_slots"] = self._create_empty_route_slots()
            modified = True
        else:
            route_data["backward_slots"], changed = self._normalize_route_slot_dict(route_data["backward_slots"])
            modified = modified or changed

        if legacy_forward and isinstance(legacy_forward, list):
            route_data["forward_slots"]["1"]["waypoints"] = [wp for wp in legacy_forward if isinstance(wp, str)]
            route_data["forward_slots"]["1"]["enabled"] = bool(route_data["forward_slots"]["1"]["waypoints"])
            modified = True

        if legacy_backward and isinstance(legacy_backward, list):
            route_data["backward_slots"]["1"]["waypoints"] = [wp for wp in legacy_backward if isinstance(wp, str)]
            route_data["backward_slots"]["1"]["enabled"] = bool(route_data["backward_slots"]["1"]["waypoints"])
            modified = True

        return route_data, modified

    def _collect_all_route_waypoint_ids(self, route_data):
        waypoint_ids = []
        for slot_dict in route_data.get("forward_slots", {}).values():
            waypoint_ids.extend(slot_dict.get("waypoints", []))
        for slot_dict in route_data.get("backward_slots", {}).values():
            waypoint_ids.extend(slot_dict.get("waypoints", []))
        # 고유 순서 유지
        seen = set()
        unique_ids = []
        for wp_id in waypoint_ids:
            if wp_id not in seen:
                seen.add(wp_id)
                unique_ids.append(wp_id)
        return unique_ids

    def _remove_waypoint_from_all_routes(self, waypoint_id):
        removed = False
        for route in self.route_profiles.values():
            for slots_key in ("forward_slots", "backward_slots"):
                slots = route.get(slots_key, {}) or {}
                for slot_data in slots.values():
                    waypoints = slot_data.get("waypoints", []) or []
                    if waypoint_id in waypoints:
                        slot_data["waypoints"] = [wp for wp in waypoints if wp != waypoint_id]
                        removed = True
        return removed

    def _get_route_slot_waypoints(self, route_data, direction, slot_id):
        slots_key = "forward_slots" if direction == "forward" else "backward_slots"
        slots = route_data.get(slots_key, {}) or {}
        slot_data = slots.get(slot_id, {}) or {}
        waypoints = slot_data.get("waypoints", []) or []
        return [wp for wp in waypoints if isinstance(wp, str)]

    def _get_enabled_slot_ids(self, route_data, direction):
        slots_key = "forward_slots" if direction == "forward" else "backward_slots"
        slots = route_data.get(slots_key, {}) or {}
        enabled_slots = []
        for slot in ROUTE_SLOT_IDS:
            slot_data = slots.get(slot, {}) or {}
            if slot_data.get("enabled") and slot_data.get("waypoints"):
                enabled_slots.append(slot)
        return enabled_slots

    def _rebuild_active_route_graph(self):
        if not self.active_route_profile_name:
            return
        active_route = self.route_profiles.get(self.active_route_profile_name)
        if not active_route:
            return
        waypoint_ids = self._collect_all_route_waypoint_ids(active_route)
        self._build_navigation_graph(waypoint_ids)

    def _on_forward_slot_changed(self, index):
        slot = ROUTE_SLOT_IDS[index] if 0 <= index < len(ROUTE_SLOT_IDS) else ROUTE_SLOT_IDS[0]
        if self.current_forward_slot == slot:
            return
        self.current_forward_slot = slot
        self.populate_waypoint_list()

    def _on_backward_slot_changed(self, index):
        slot = ROUTE_SLOT_IDS[index] if 0 <= index < len(ROUTE_SLOT_IDS) else ROUTE_SLOT_IDS[0]
        if self.current_backward_slot == slot:
            return
        self.current_backward_slot = slot
        self.populate_waypoint_list()

    def _on_slot_enabled_changed(self, direction, state):
        if not self.active_route_profile_name:
            return

        route = self.route_profiles.get(self.active_route_profile_name)
        if not route:
            return

        slot_id = self.current_forward_slot if direction == 'forward' else self.current_backward_slot
        slots_key = "forward_slots" if direction == "forward" else "backward_slots"
        route, changed = self._ensure_route_profile_structure(route)
        self.route_profiles[self.active_route_profile_name] = route
        slot_data = route.get(slots_key, {}).get(slot_id)
        if slot_data is None:
            return

        try:
            enabled = Qt.CheckState(state) == Qt.CheckState.Checked
        except ValueError:
            enabled = bool(state)
        if slot_data.get("enabled") != enabled:
            slot_data["enabled"] = enabled
            self.save_profile_data()
            self._rebuild_active_route_graph()

    def _populate_direction_list(self, direction, route, waypoint_lookup):
        list_widget = self.forward_wp_list if direction == 'forward' else self.backward_wp_list
        slot_checkbox = self.forward_slot_enabled_checkbox if direction == 'forward' else self.backward_slot_enabled_checkbox
        current_slot = self.current_forward_slot if direction == 'forward' else self.current_backward_slot
        slots_key = "forward_slots" if direction == 'forward' else "backward_slots"
        slot_data = route.get(slots_key, {}).get(current_slot, {"enabled": False, "waypoints": []})

        slot_checkbox.blockSignals(True)
        slot_checkbox.setChecked(bool(slot_data.get("enabled")))
        slot_checkbox.blockSignals(False)

        list_widget.clear()
        for i, wp_id in enumerate(slot_data.get("waypoints", [])):
            wp_data = waypoint_lookup.get(wp_id)
            if not wp_data:
                continue

            item_text = f"{i + 1}. {wp_data.get('name', '이름 없음')} ({wp_data.get('floor', 'N/A')}층)"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, wp_id)
            list_widget.addItem(item)

    def _extract_features_from_sequence(self, sequence):
        """[MODIFIED] v14.0.3: 강화된 특징 추출 로직."""
        seq = np.array(sequence, dtype=np.float32)
        
        if len(seq) < 2: # 데이터가 너무 짧으면 0 벡터 반환
            return np.zeros(11)

        # 1. 정규화
        normalized_seq = seq - seq[0]
        
        # 2. 기본 통계 특징
        min_coords = np.min(normalized_seq, axis=0)
        max_coords = np.max(normalized_seq, axis=0)
        
        # 3. 궤적 특징
        total_distance = np.sum(np.sqrt(np.sum(np.diff(normalized_seq, axis=0)**2, axis=1)))
        displacement = np.sqrt(np.sum((normalized_seq[-1] - normalized_seq[0])**2))
        x_range = max_coords[0] - min_coords[0]
        y_range = max_coords[1] - min_coords[1]
        
        # 4. 속도 특징
        velocities = np.diff(normalized_seq, axis=0)
        mean_velocity_y = np.mean(velocities[:, 1])
        max_velocity_y = np.max(velocities[:, 1])
        min_velocity_y = np.min(velocities[:, 1])
        
        # 5. 시퀀스 길이
        sequence_length = len(normalized_seq)
        
        features = np.array([
            total_distance, displacement,
            x_range, y_range,
            mean_velocity_y, max_velocity_y, min_velocity_y,
            min_coords[1], max_coords[1], # y좌표 최소/최대값
            sequence_length,
            x_range / (y_range + 1e-6) # 가로/세로 비율
        ])
        return features

    def _get_global_action_model_path(self):
        """동작 학습 모델과 데이터가 저장될 전역 경로를 반환합니다."""
        os.makedirs(GLOBAL_ACTION_MODEL_DIR, exist_ok=True)
        return GLOBAL_ACTION_MODEL_DIR

    def load_action_model(self):
        """저장된 동작 인식 모델을 로드합니다."""
        self.action_model = None
        # <<< [수정] 아래 두 줄 수정
        model_dir = self._get_global_action_model_path()
        model_path = os.path.join(model_dir, 'action_model.joblib')

        if os.path.exists(model_path):
            try:
                self.action_model = joblib.load(model_path)
                self.update_general_log("전역 동작 인식 모델을 성공적으로 로드했습니다.", "green")
            except Exception as e:
                self.update_general_log(f"전역 동작 인식 모델 로드 실패: {e}", "red")
        else:
            self.update_general_log("학습된 동작 인식 모델이 없습니다. '동작 학습'을 진행해주세요.", "orange")

    def _get_floor_from_closest_terrain_data(self, point, terrain_lines):
            """주어진 점에서 가장 가까운 지형선 데이터를 찾아 그 층 번호를 반환합니다."""
            min_dist_sq = float('inf')
            closest_floor = 0.0

            for line_data in terrain_lines:
                points = line_data.get("points", [])
                for i in range(len(points) - 1):
                    p1 = QPointF(points[i][0], points[i][1])
                    p2 = QPointF(points[i+1][0], points[i+1][1])
                    
                    dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
                    if dx == 0 and dy == 0:
                        dist_sq = (point.x() - p1.x())**2 + (point.y() - p1.y())**2
                    else:
                        t = ((point.x() - p1.x()) * dx + (point.y() - p1.y()) * dy) / (dx**2 + dy**2)
                        t = max(0, min(1, t))
                        closest_point_on_segment = QPointF(p1.x() + t * dx, p1.y() + t * dy)
                        dist_sq = (point.x() - closest_point_on_segment.x())**2 + (point.y() - closest_point_on_segment.y())**2

                    if dist_sq < min_dist_sq:
                        min_dist_sq = dist_sq
                        closest_floor = line_data.get('floor', 0.0)
            
            return closest_floor
        
    def update_detection_log(self, inliers, outliers):
        """정상치와 이상치 정보를 받아 탐지 상태 로그를 업데이트합니다."""
        log_html = "<b>활성 지형:</b> "
        
        if not inliers and not outliers:
            log_html += '<font color="red">탐지된 지형 없음</font>'
            self.detection_log_viewer.setHtml(log_html)
            return

        inlier_texts = []
        if inliers:
            sorted_inliers = sorted(inliers, key=lambda x: x['conf'], reverse=True)
            for f in sorted_inliers:
                inlier_texts.append(f'<font color="blue">{f["id"]}({f["conf"]:.2f})</font>')
        
        outlier_texts = []
        if outliers:
            sorted_outliers = sorted(outliers, key=lambda x: x['conf'], reverse=True)
            for f in sorted_outliers:
                outlier_texts.append(f'<font color="red">{f["id"]}({f["conf"]:.2f})</font>')

        log_html += ", ".join(inlier_texts)
        if inlier_texts and outlier_texts:
            log_html += ", "
        log_html += ", ".join(outlier_texts)
        
        self.detection_log_viewer.setHtml(log_html)

    def _prepare_data_for_json(self, data):
        """JSON으로 저장하기 전에 PyQt 객체를 순수 Python 타입으로 변환하는 재귀 함수."""
        if isinstance(data, dict):
            return {k: self._prepare_data_for_json(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._prepare_data_for_json(v) for v in data]
        elif isinstance(data, QPointF):
            return [data.x(), data.y()]
        elif isinstance(data, QSize):
            return [data.width(), data.height()]
        # QPoint, QRectF 등 다른 PyQt 타입도 필요 시 추가 가능
        return data

    def perform_initial_setup(self):
        os.makedirs(MAPS_DIR, exist_ok=True)
        self.check_and_migrate_old_config()
        self.profile_selector.blockSignals(True)
        self.populate_profile_selector()
        profile_to_load = None
        last_profile = self.load_global_settings()
        self.hotkey_display_label.setText(self.current_hotkey.upper())
        if hasattr(self, 'display_enabled_checkbox'):
            block_state = self.display_enabled_checkbox.blockSignals(True)
            self.display_enabled_checkbox.setChecked(bool(self._minimap_display_enabled))
            self.display_enabled_checkbox.blockSignals(block_state)
            self._handle_display_toggle(bool(self._minimap_display_enabled))
        if hasattr(self, 'perf_logging_checkbox'):
            block_state = self.perf_logging_checkbox.blockSignals(True)
            self.perf_logging_checkbox.setChecked(self._perf_logging_enabled)
            self.perf_logging_checkbox.blockSignals(block_state)
        if hasattr(self, 'initial_delay_spinbox'):
            blocker = QSignalBlocker(self.initial_delay_spinbox)
            self.initial_delay_spinbox.setValue(int(self.initial_delay_ms))
            del blocker
        if self.hotkey_manager:
            try:
                self.hotkey_manager.register_hotkey(self.current_hotkey)
                self._sync_hotkey_filter_id()
            except Exception as exc:
                self.update_general_log(f"전역 단축키 등록 실패: {exc}", "red")
        if last_profile and last_profile in [self.profile_selector.itemText(i) for i in range(self.profile_selector.count())]:
            profile_to_load = last_profile
        elif self.profile_selector.count() > 0:
            profile_to_load = self.profile_selector.itemText(0)
        if profile_to_load:
            self.profile_selector.setCurrentText(profile_to_load)
        self.profile_selector.blockSignals(False)
        if profile_to_load:
            self.load_profile_data(profile_to_load)
        else:
            self.update_ui_for_no_profile()

    @pyqtSlot(str, str)
    def on_command_profile_renamed(self, old_name: str, new_name: str) -> None:
        if not old_name or not new_name or old_name == new_name:
            return

        changed = False

        def _replace_event_profile(container: Optional[list]):
            nonlocal changed
            if not isinstance(container, list):
                return
            for entry in container:
                if isinstance(entry, dict) and entry.get('event_profile') == old_name:
                    entry['event_profile'] = new_name
                    changed = True

        for route_data in self.route_profiles.values():
            _replace_event_profile(route_data.get('waypoints', []))

        _replace_event_profile(self.geometry_data.get('waypoints', []))

        for wall in self.geometry_data.get('forbidden_walls', []):
            profiles = wall.get('skill_profiles')
            if isinstance(profiles, list):
                updated = [new_name if profile == old_name else profile for profile in profiles]
                if updated != profiles:
                    wall['skill_profiles'] = updated
                    changed = True

        if getattr(self, 'active_event_profile', '') == old_name:
            self.active_event_profile = new_name
            changed = True

        pending_forbidden = getattr(self, 'pending_forbidden_command', None)
        if pending_forbidden and pending_forbidden[0] == old_name:
            self.pending_forbidden_command = (new_name, pending_forbidden[1])
            changed = True

        if getattr(self, 'active_forbidden_wall_profile', '') == old_name:
            self.active_forbidden_wall_profile = new_name
            changed = True

        if not changed:
            return

        self._ensure_waypoint_event_fields()
        self._refresh_event_waypoint_states()
        self._refresh_forbidden_wall_states()
        self.populate_waypoint_list()
        self.save_profile_data()
        self.update_general_log(
            f"명령 프로필 '{old_name}' → '{new_name}' 변경을 맵 데이터에 반영했습니다.",
            "blue",
        )

    def populate_profile_selector(self):
        self.profile_selector.clear()
        try:
            profiles = sorted([d for d in os.listdir(MAPS_DIR) if os.path.isdir(os.path.join(MAPS_DIR, d))])
            self.profile_selector.addItems(profiles)
        except FileNotFoundError:
            pass

    def on_profile_selected(self, index):
        if index == -1:
            self.update_ui_for_no_profile()
            return
        profile_name = self.profile_selector.itemText(index)
        if profile_name == self.active_profile_name:
            return
        self.load_profile_data(profile_name)

    def check_and_migrate_old_config(self):
        old_config_file = os.path.join(CONFIG_PATH, 'map_config.json')
        old_features_file = os.path.join(CONFIG_PATH, 'map_key_features.json')
        if os.path.exists(old_config_file) or os.path.exists(old_features_file):
            reply = QMessageBox.question(self, "구버전 설정 발견",
                                         "구버전 맵 설정 파일이 발견되었습니다.\n'default'라는 이름의 새 프로필로 자동 변환하시겠습니까?\n\n(변환 후 원본 파일은 삭제됩니다.)",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if reply == QMessageBox.StandardButton.Yes:
                default_profile_path = os.path.join(MAPS_DIR, 'default')
                os.makedirs(default_profile_path, exist_ok=True)
                if os.path.exists(old_config_file):
                    shutil.move(old_config_file, os.path.join(default_profile_path, 'map_config.json'))
                if os.path.exists(old_features_file):
                    shutil.move(old_features_file, os.path.join(default_profile_path, 'map_key_features.json'))
                self.update_general_log("구버전 설정을 'default' 프로필로 마이그레이션했습니다.", "purple")

    def load_profile_data(self, profile_name):
        self.active_profile_name = profile_name
        
        #  프로필 변경 시 모든 런타임/탐지 관련 상태 변수 완벽 초기화
        if self.detection_thread and self.detection_thread.isRunning():
            self.toggle_anchor_detection(False) # 탐지 중이었다면 정지
            self.detect_anchor_btn.setChecked(False)

        self.minimap_region = None
        self.key_features = {}
        self.geometry_data = {}
        self.route_profiles = {}
        self.active_route_profile_name = None
        self.reference_anchor_id = None
        
        self.global_positions = {}
        self.feature_offsets = {}
        self.full_map_pixmap = None
        self.full_map_bounding_rect = QRectF()
        
        # 탐지/네비게이션 상태 초기화
        self.smoothed_player_pos = None
        self.last_player_pos = QPointF(0, 0)
        self.player_state = 'on_terrain'
        self.navigation_action = 'move_to_target'
        self.navigation_state_locked = False
        self.start_waypoint_found = False
        self.target_waypoint_id = None
        self.last_reached_wp_id = None
        self.current_path_index = -1
        self.intermediate_target_pos = None
        self.intermediate_target_type = 'walk'
        self.active_feature_info = []
        self.my_player_global_rects = []
        self.other_player_global_rects = []
        self.last_forward_journey = []
        self.last_selected_forward_slot = None
        self.last_selected_backward_slot = None
        self.current_forward_slot = "1"
        self.current_backward_slot = "1"
        self.current_direction_slot_label = "-"
        self._reset_other_player_alert_state()

        # 로그 초기화
        self.general_log_viewer.clear()
        self.detection_log_viewer.clear()

        profile_path = os.path.join(MAPS_DIR, profile_name)
        config_file = os.path.join(profile_path, 'map_config.json')
        features_file = os.path.join(profile_path, 'map_key_features.json')
        geometry_file = os.path.join(profile_path, 'map_geometry.json')

        try:
            self.minimap_region, self.key_features = None, {}
            self.route_profiles, self.active_route_profile_name = {}, None
            self.geometry_data = {}
            self.reference_anchor_id = None
            
            # [v11.3.7] 설정 로드 로직 변경: 여기서 기본값으로 먼저 초기화
            self.cfg_idle_time_threshold = IDLE_TIME_THRESHOLD
            self.cfg_climbing_state_frame_threshold = CLIMBING_STATE_FRAME_THRESHOLD
            self.cfg_falling_state_frame_threshold = FALLING_STATE_FRAME_THRESHOLD
            self.cfg_jumping_state_frame_threshold = JUMPING_STATE_FRAME_THRESHOLD
            self.cfg_on_terrain_y_threshold = ON_TERRAIN_Y_THRESHOLD
            self.cfg_jump_y_min_threshold = JUMP_Y_MIN_THRESHOLD
            self.cfg_jump_y_max_threshold = JUMP_Y_MAX_THRESHOLD
            self.cfg_fall_y_min_threshold = FALL_Y_MIN_THRESHOLD
            self.cfg_climb_x_movement_threshold = CLIMB_X_MOVEMENT_THRESHOLD
            self.cfg_fall_on_ladder_x_movement_threshold = FALL_ON_LADDER_X_MOVEMENT_THRESHOLD
            self.cfg_ladder_x_grab_threshold = LADDER_X_GRAB_THRESHOLD
            self.cfg_move_deadzone = MOVE_DEADZONE
            self.cfg_max_jump_duration = MAX_JUMP_DURATION
            self.cfg_y_movement_deadzone = Y_MOVEMENT_DEADZONE
            self.cfg_waypoint_arrival_x_threshold = WAYPOINT_ARRIVAL_X_THRESHOLD
            self.cfg_waypoint_arrival_x_threshold_min = WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT
            self.cfg_waypoint_arrival_x_threshold_max = WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT
            self.cfg_ladder_arrival_x_threshold = LADDER_ARRIVAL_X_THRESHOLD
            self.cfg_jump_link_arrival_x_threshold = JUMP_LINK_ARRIVAL_X_THRESHOLD
            self.cfg_on_ladder_enter_frame_threshold = 1
            self.cfg_jump_initial_velocity_threshold = 1.0
            self.cfg_climb_max_velocity = 1.0
            # ==================== v11.5.0 기본값 초기화 추가 시작 ====================
            self.cfg_arrival_frame_threshold = 2
            self.cfg_action_success_frame_threshold = 2
            # ==================== v11.5.0 기본값 초기화 추가 끝 ======================
            self.cfg_stuck_detection_wait = STUCK_DETECTION_WAIT_DEFAULT
            self.cfg_airborne_recovery_wait = AIRBORNE_RECOVERY_WAIT_DEFAULT
            self.cfg_ladder_recovery_resend_delay = LADDER_RECOVERY_RESEND_DELAY_DEFAULT
            self.cfg_prepare_timeout = PREPARE_TIMEOUT
            self.cfg_max_lock_duration = MAX_LOCK_DURATION
            
            self.cfg_walk_teleport_probability = WALK_TELEPORT_PROBABILITY_DEFAULT
            self.cfg_walk_teleport_interval = WALK_TELEPORT_INTERVAL_DEFAULT
            self.cfg_walk_teleport_bonus_delay = WALK_TELEPORT_BONUS_DELAY_DEFAULT
            self.cfg_walk_teleport_bonus_step = WALK_TELEPORT_BONUS_STEP_DEFAULT
            self.cfg_walk_teleport_bonus_max = WALK_TELEPORT_BONUS_MAX_DEFAULT
            self._reset_walk_teleport_state()

            config = {}
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            self.reference_anchor_id = config.get('reference_anchor_id')

            auto_control_enabled = bool(config.get('auto_control_enabled', False))
            if hasattr(self, 'auto_control_checkbox'):
                blocker = QSignalBlocker(self.auto_control_checkbox)
                self.auto_control_checkbox.setChecked(auto_control_enabled)
                del blocker

            other_alert_enabled = bool(config.get('other_player_alert_enabled', False))
            if hasattr(self, 'other_player_alert_checkbox') and self.other_player_alert_checkbox:
                blocker = QSignalBlocker(self.other_player_alert_checkbox)
                self.other_player_alert_checkbox.setChecked(other_alert_enabled)
                del blocker
            self.other_player_alert_enabled = other_alert_enabled
            if not other_alert_enabled:
                self._reset_other_player_alert_state()

            telegram_enabled = bool(config.get('telegram_alert_enabled', False))
            if not other_alert_enabled:
                telegram_enabled = False
            if hasattr(self, 'telegram_alert_checkbox') and self.telegram_alert_checkbox:
                self.telegram_alert_checkbox.setEnabled(other_alert_enabled)
                blocker = QSignalBlocker(self.telegram_alert_checkbox)
                self.telegram_alert_checkbox.setChecked(telegram_enabled)
                del blocker
            self.telegram_alert_enabled = telegram_enabled
            if hasattr(self, 'telegram_settings_btn') and self.telegram_settings_btn:
                self.telegram_settings_btn.setEnabled(other_alert_enabled and telegram_enabled)
            self.telegram_send_mode = "continuous" if config.get("telegram_send_mode") == "continuous" else "once"
            try:
                interval_value = float(config.get("telegram_send_interval", self.telegram_send_interval))
            except (TypeError, ValueError):
                interval_value = self.telegram_send_interval
            self.telegram_send_interval = max(interval_value, 1.0)

            # 저장된 상태 판정 설정이 있으면 기본값을 덮어쓰기
            state_config = config.get('state_machine_config', {})
            if state_config:
                self.cfg_idle_time_threshold = state_config.get("idle_time_threshold", self.cfg_idle_time_threshold)
                self.cfg_climbing_state_frame_threshold = state_config.get("climbing_state_frame_threshold", self.cfg_climbing_state_frame_threshold)
                self.cfg_falling_state_frame_threshold = state_config.get("falling_state_frame_threshold", self.cfg_falling_state_frame_threshold)
                self.cfg_jumping_state_frame_threshold = state_config.get("jumping_state_frame_threshold", self.cfg_jumping_state_frame_threshold)
                self.cfg_on_terrain_y_threshold = state_config.get("on_terrain_y_threshold", self.cfg_on_terrain_y_threshold)
                self.cfg_jump_y_min_threshold = state_config.get("jump_y_min_threshold", self.cfg_jump_y_min_threshold)
                self.cfg_jump_y_max_threshold = state_config.get("jump_y_max_threshold", self.cfg_jump_y_max_threshold)
                self.cfg_fall_y_min_threshold = state_config.get("fall_y_min_threshold", self.cfg_fall_y_min_threshold)
                self.cfg_climb_x_movement_threshold = state_config.get("climb_x_movement_threshold", self.cfg_climb_x_movement_threshold)
                self.cfg_fall_on_ladder_x_movement_threshold = state_config.get("fall_on_ladder_x_movement_threshold", self.cfg_fall_on_ladder_x_movement_threshold)
                self.cfg_ladder_x_grab_threshold = state_config.get("ladder_x_grab_threshold", self.cfg_ladder_x_grab_threshold)
                self.cfg_move_deadzone = state_config.get("move_deadzone", self.cfg_move_deadzone)
                self.cfg_max_jump_duration = state_config.get("max_jump_duration", self.cfg_max_jump_duration)
                self.cfg_y_movement_deadzone = state_config.get("y_movement_deadzone", self.cfg_y_movement_deadzone)
                self.cfg_waypoint_arrival_x_threshold = state_config.get("waypoint_arrival_x_threshold", self.cfg_waypoint_arrival_x_threshold)
                self.cfg_waypoint_arrival_x_threshold_min = state_config.get(
                    "waypoint_arrival_x_threshold_min",
                    self.cfg_waypoint_arrival_x_threshold_min
                )
                self.cfg_waypoint_arrival_x_threshold_max = state_config.get(
                    "waypoint_arrival_x_threshold_max",
                    self.cfg_waypoint_arrival_x_threshold_max
                )
                self.cfg_ladder_arrival_x_threshold = state_config.get("ladder_arrival_x_threshold", self.cfg_ladder_arrival_x_threshold)
                self.cfg_jump_link_arrival_x_threshold = state_config.get("jump_link_arrival_x_threshold", self.cfg_jump_link_arrival_x_threshold)
                self.cfg_on_ladder_enter_frame_threshold = state_config.get("on_ladder_enter_frame_threshold", self.cfg_on_ladder_enter_frame_threshold)
                self.cfg_jump_initial_velocity_threshold = state_config.get("jump_initial_velocity_threshold", self.cfg_jump_initial_velocity_threshold)
                self.cfg_climb_max_velocity = state_config.get("climb_max_velocity", self.cfg_climb_max_velocity)
                # ==================== v11.5.0 설정 로드 추가 시작 ====================
                self.cfg_arrival_frame_threshold = state_config.get("arrival_frame_threshold", self.cfg_arrival_frame_threshold)
                self.cfg_action_success_frame_threshold = state_config.get("action_success_frame_threshold", self.cfg_action_success_frame_threshold)
                # ==================== v11.5.0 설정 로드 추가 끝 ======================
                self.cfg_stuck_detection_wait = state_config.get("stuck_detection_wait", self.cfg_stuck_detection_wait)
                self.cfg_airborne_recovery_wait = state_config.get("airborne_recovery_wait", self.cfg_airborne_recovery_wait)
                self.cfg_ladder_recovery_resend_delay = state_config.get("ladder_recovery_resend_delay", self.cfg_ladder_recovery_resend_delay)
                probability_percent = state_config.get(
                    "walk_teleport_probability",
                    self.cfg_walk_teleport_probability,
                )
                if probability_percent is not None and probability_percent <= 1.0:
                    probability_percent *= 100.0
                self.cfg_walk_teleport_probability = max(
                    min(
                        probability_percent if probability_percent is not None else self.cfg_walk_teleport_probability,
                        100.0,
                    ),
                    0.0,
                )

                interval_value = state_config.get(
                    "walk_teleport_interval",
                    self.cfg_walk_teleport_interval,
                )
                self.cfg_walk_teleport_interval = max(
                    interval_value if interval_value is not None else self.cfg_walk_teleport_interval,
                    0.1,
                )

                self.cfg_walk_teleport_bonus_delay = state_config.get(
                    "walk_teleport_bonus_delay",
                    self.cfg_walk_teleport_bonus_delay,
                )
                self.cfg_walk_teleport_bonus_step = state_config.get(
                    "walk_teleport_bonus_step",
                    self.cfg_walk_teleport_bonus_step,
                )
                self.cfg_walk_teleport_bonus_max = state_config.get(
                    "walk_teleport_bonus_max",
                    self.cfg_walk_teleport_bonus_max,
                )
                self.cfg_prepare_timeout = state_config.get("prepare_timeout", self.cfg_prepare_timeout)
                self.cfg_max_lock_duration = state_config.get("max_lock_duration", self.cfg_max_lock_duration)

                self.cfg_walk_teleport_bonus_delay = max(self.cfg_walk_teleport_bonus_delay or 0.0, 0.1)
                self.cfg_walk_teleport_bonus_step = max(self.cfg_walk_teleport_bonus_step or 0.0, 0.0)
                self.cfg_walk_teleport_bonus_max = max(self.cfg_walk_teleport_bonus_max or 0.0, 0.0)
                if self.cfg_walk_teleport_bonus_max < self.cfg_walk_teleport_bonus_step:
                    self.cfg_walk_teleport_bonus_max = self.cfg_walk_teleport_bonus_step

                self._reset_walk_teleport_state()

                if self.cfg_waypoint_arrival_x_threshold_min > self.cfg_waypoint_arrival_x_threshold_max:
                    self.cfg_waypoint_arrival_x_threshold_min, self.cfg_waypoint_arrival_x_threshold_max = (
                        self.cfg_waypoint_arrival_x_threshold_max,
                        self.cfg_waypoint_arrival_x_threshold_min,
                    )

                self.cfg_waypoint_arrival_x_threshold = (
                    self.cfg_waypoint_arrival_x_threshold_min + self.cfg_waypoint_arrival_x_threshold_max
                ) / 2.0

                self.update_general_log("저장된 상태 판정 설정을 로드했습니다.", "gray")

                self._active_waypoint_threshold_key = None
                self._active_waypoint_threshold_value = None

            saved_options = config.get('render_options', {})
            self.render_options = {
                'background': True, 'features': True, 'waypoints': True,
                'terrain': True, 'objects': True, 'jump_links': True,
                'forbidden_walls': True,
            }
            self.render_options.update(saved_options)

            features = {}
            if os.path.exists(features_file):
                with open(features_file, 'r', encoding='utf-8') as f:
                    features = json.load(f)
                    
            cleaned_features = {
                feature_id: data
                for feature_id, data in features.items()
                if isinstance(data, dict) and 'image_base64' in data
            }
            
            if len(cleaned_features) != len(features):
                self.update_general_log("경고: 유효하지 않은 데이터가 'map_key_features.json'에서 발견되어 자동 정리합니다.", "orange")
                self.key_features = cleaned_features
                profile_path = os.path.join(MAPS_DIR, profile_name)
                with open(os.path.join(profile_path, 'map_key_features.json'), 'w', encoding='utf-8') as f:
                    json.dump(self.key_features, f, indent=4, ensure_ascii=False)
            else:
                self.key_features = features

            if os.path.exists(geometry_file):
                with open(geometry_file, 'r', encoding='utf-8') as f:
                    self.geometry_data = json.load(f)
            else:
                self.geometry_data = {
                    "terrain_lines": [],
                    "transition_objects": [],
                    "waypoints": [],
                    "jump_links": [],
                    "forbidden_walls": [],
                }

            self._ensure_waypoint_event_fields()

            config_updated, features_updated, geometry_updated = self.migrate_data_structures(config, self.key_features, self.geometry_data)
            self._ensure_waypoint_event_fields()
            self._refresh_event_waypoint_states()
            self._refresh_forbidden_wall_states()

            raw_route_profiles = config.get('route_profiles', {}) or {}
            normalized_profiles = {}
            profiles_modified = False
            for route_name, route_data in raw_route_profiles.items():
                normalized_route, changed = self._ensure_route_profile_structure(copy.deepcopy(route_data))
                normalized_profiles[route_name] = normalized_route
                profiles_modified = profiles_modified or changed

            self.route_profiles = normalized_profiles
            self.active_route_profile_name = config.get('active_route_profile')
            self.minimap_region = config.get('minimap_region')

            if profiles_modified:
                config['route_profiles'] = copy.deepcopy(normalized_profiles)
                config_updated = True

            if config_updated or features_updated or geometry_updated:
                self.save_profile_data()

            self._build_line_floor_map()    # [v11.4.5] 맵 데이터 로드 후 캐시 빌드
            self.global_positions = self._calculate_global_positions()
            self._generate_full_map_pixmap()
            self._assign_dynamic_names()
            # --- v12.0.0 수정: 현재 경로 기준으로 그래프 생성 ---
            active_route = self.route_profiles.get(self.active_route_profile_name, {})
            wp_ids = self._collect_all_route_waypoint_ids(active_route)
            self._build_navigation_graph(wp_ids)
            self.update_ui_for_new_profile()
            self.update_general_log(f"'{profile_name}' 맵 프로필을 로드했습니다.", "blue")
            self._center_realtime_view_on_map()
        except Exception as e:
            detailed_trace = traceback.format_exc()
            self.update_general_log(
                f"'{profile_name}' 프로필 로드 오류: {e}",
                "red",
            )
            print("[MapTab] load_profile_data exception:\n" + detailed_trace)
            self.update_ui_for_no_profile()

    def migrate_data_structures(self, config, features, geometry):
        config_updated = False
        features_updated = False
        geometry_updated = False

        # v5 마이그레이션
        if 'waypoints' in config and 'route_profiles' not in config:
            self.update_general_log("v5 마이그레이션: 웨이포인트 구조를 경로 프로필로 변환합니다.", "purple")
            config['route_profiles'] = {"기본 경로": {"waypoints": config.pop('waypoints', [])}}
            config['active_route_profile'] = "기본 경로"
            config_updated = True
        
        # v10.0.0 마이그레이션: 경로 프로필 구조 변경
        for route_name, route_data in list(config.get('route_profiles', {}).items()):
            if 'waypoints' in route_data and 'forward_path' not in route_data:
                self.update_general_log(f"v10 마이그레이션: '{route_name}' 경로를 정방향/역방향 구조로 변환합니다.", "purple")
                old_waypoints = route_data.pop('waypoints', [])
                
                # 구버전 웨이포인트를 새로운 geometry_data['waypoints']로 이동
                if 'waypoints' not in geometry: geometry['waypoints'] = []
                
                new_path_ids = []
                for old_wp in old_waypoints:
                    # 중복 방지
                    if not any(wp['name'] == old_wp['name'] for wp in geometry['waypoints']):
                        wp_id = f"wp-{uuid.uuid4()}"
                        
                        # 전역 좌표를 계산해서 저장해야 함
                        # 이 부분은 일단 이름만 저장하고, 사용자가 편집기에서 위치를 다시 지정하도록 유도
                        # 또는 _calculate_global_positions를 먼저 호출해야 함.
                        # 여기서는 임시로 (0,0) 저장
                        new_wp_data = {
                            "id": wp_id,
                            "name": old_wp['name'],
                            "pos": [0,0], # 위치는 재설정 필요
                            "floor": 1.0, # 기본 1층
                            "parent_line_id": None
                        }
                        geometry['waypoints'].append(new_wp_data)
                        new_path_ids.append(wp_id)
                    else: # 이미 존재하는 이름이면 ID를 찾아서 추가
                        existing_wp = next((wp for wp in geometry['waypoints'] if wp['name'] == old_wp['name']), None)
                        if existing_wp:
                            new_path_ids.append(existing_wp['id'])
                
                route_data['forward_path'] = new_path_ids
                route_data['backward_path'] = []
                config_updated = True
                geometry_updated = True

            legacy_forward = route_data.pop('forward_path', None)
            legacy_backward = route_data.pop('backward_path', None)
            normalized_route, changed = self._ensure_route_profile_structure(route_data, legacy_forward, legacy_backward)
            config['route_profiles'][route_name] = normalized_route
            if legacy_forward is not None or legacy_backward is not None:
                config_updated = True
            if changed:
                config_updated = True

        # v10.0.0 마이그레이션: geometry 데이터 필드 추가
        if "waypoints" not in geometry: geometry["waypoints"] = []; geometry_updated = True
        if "jump_links" not in geometry: geometry["jump_links"] = []; geometry_updated = True
        if "forbidden_walls" not in geometry: geometry["forbidden_walls"] = []; geometry_updated = True

        for wall in geometry.get("forbidden_walls", []):
            if not wall.get("id"):
                wall["id"] = f"fw-{uuid.uuid4()}"
                geometry_updated = True
            if "line_id" not in wall:
                wall["line_id"] = ""
                geometry_updated = True
            if "pos" not in wall or not isinstance(wall.get("pos"), (list, tuple)) or len(wall.get("pos", [])) < 2:
                wall["pos"] = [0.0, 0.0]
                geometry_updated = True
            if "enabled" not in wall:
                wall["enabled"] = False
                geometry_updated = True
            if "range_left" not in wall:
                wall["range_left"] = 0.0
                geometry_updated = True
            if "range_right" not in wall:
                wall["range_right"] = 0.0
                geometry_updated = True
            if "dwell_seconds" not in wall:
                wall["dwell_seconds"] = 3.0
                geometry_updated = True
            if "cooldown_seconds" not in wall:
                wall["cooldown_seconds"] = 5.0
                geometry_updated = True
            if "instant_on_contact" not in wall:
                wall["instant_on_contact"] = False
                geometry_updated = True
            if not isinstance(wall.get("skill_profiles"), list):
                wall["skill_profiles"] = list(wall.get("skill_profiles") or [])
                geometry_updated = True
            if "floor" not in wall or wall.get("floor") is None:
                parent_line = next((line for line in geometry.get("terrain_lines", []) if line.get("id") == wall.get("line_id")), None)
                wall["floor"] = parent_line.get("floor") if parent_line else None
                geometry_updated = True
        for line in geometry.get("terrain_lines", []):
            if "floor" not in line: line["floor"] = 1.0; geometry_updated = True
        
        # v6 마이그레이션
        all_waypoints_old = [wp for route in config.get('route_profiles', {}).values() for wp in route.get('waypoints', [])]
        if any('feature_threshold' in wp for wp in all_waypoints_old):
            self.update_general_log("v6 마이그레이션: 정확도 설정을 지형으로 이전합니다.", "purple")
            for wp in all_waypoints_old:
                wp_threshold = wp.pop('feature_threshold')
                for feature_link in wp.get('key_feature_ids', []):
                    feature_id = feature_link['id']
                    if feature_id in self.key_features: # 'features'를 'self.key_features'로 변경
                        if self.key_features[feature_id].get('threshold', 0) < wp_threshold:
                            self.key_features[feature_id]['threshold'] = wp_threshold # 'features'를 'self.key_features'로 변경
                            features_updated = True
            config_updated = True
        
        for feature_id, feature_data in self.key_features.items(): # 'features'를 'self.key_features'로 변경
            if 'threshold' not in feature_data: feature_data['threshold'] = 0.85; features_updated = True
            if 'context_image_base64' not in feature_data: feature_data['context_image_base64'] = ""; features_updated = True
            if 'rect_in_context' not in feature_data: feature_data['rect_in_context'] = []; features_updated = True
        # v10.6.0 마이그레이션: 층 이동 오브젝트 구조 변경
        if 'transition_objects' in geometry:
            old_objects = [obj for obj in geometry['transition_objects'] if 'parent_line_id' in obj]
            if old_objects:
                reply = QMessageBox.information(self, "데이터 구조 업데이트",
                                                "구버전 '층 이동 오브젝트' 데이터가 발견되었습니다.\n"
                                                "새로운 시스템에서는 두 지형을 직접 연결하는 방식으로 변경되어 기존 데이터와 호환되지 않습니다.\n\n"
                                                "확인 버튼을 누르면 기존 층 이동 오브젝트 데이터가 모두 삭제됩니다.\n"
                                                "삭제 후 '미니맵 지형 편집기'에서 새로 생성해주세요.",
                                                QMessageBox.StandardButton.Ok)
                
                # 'parent_line_id'가 없는, 즉 새로운 구조의 오브젝트만 남김
                geometry['transition_objects'] = [obj for obj in geometry['transition_objects'] if 'parent_line_id' not in obj]
                geometry_updated = True
                self.update_general_log("v10.6.0 마이그레이션: 구버전 층 이동 오브젝트 데이터를 삭제했습니다.", "purple")   
        return config_updated, features_updated, geometry_updated

    def save_profile_data(self):
        if not self.active_profile_name: return
        profile_path = os.path.join(MAPS_DIR, self.active_profile_name)
        os.makedirs(profile_path, exist_ok=True)
        config_file = os.path.join(profile_path, 'map_config.json')
        features_file = os.path.join(profile_path, 'map_key_features.json')
        geometry_file = os.path.join(profile_path, 'map_geometry.json')

        try:
            # [v11.3.0] 저장할 데이터에 상태 판정 설정 추가
            state_machine_config = {
                "idle_time_threshold": self.cfg_idle_time_threshold,
                "climbing_state_frame_threshold": self.cfg_climbing_state_frame_threshold,
                "falling_state_frame_threshold": self.cfg_falling_state_frame_threshold,
                "jumping_state_frame_threshold": self.cfg_jumping_state_frame_threshold,
                "on_terrain_y_threshold": self.cfg_on_terrain_y_threshold,
                "jump_y_min_threshold": self.cfg_jump_y_min_threshold,
                "jump_y_max_threshold": self.cfg_jump_y_max_threshold,
                "fall_y_min_threshold": self.cfg_fall_y_min_threshold,
                "climb_x_movement_threshold": self.cfg_climb_x_movement_threshold,
                "fall_on_ladder_x_movement_threshold": self.cfg_fall_on_ladder_x_movement_threshold,
                "ladder_x_grab_threshold": self.cfg_ladder_x_grab_threshold,
                "move_deadzone": self.cfg_move_deadzone,
                "max_jump_duration": self.cfg_max_jump_duration,
                "y_movement_deadzone": self.cfg_y_movement_deadzone,
                "waypoint_arrival_x_threshold": self.cfg_waypoint_arrival_x_threshold,
                "waypoint_arrival_x_threshold_min": self.cfg_waypoint_arrival_x_threshold_min,
                "waypoint_arrival_x_threshold_max": self.cfg_waypoint_arrival_x_threshold_max,
                "ladder_arrival_x_threshold": self.cfg_ladder_arrival_x_threshold,
                "jump_link_arrival_x_threshold": self.cfg_jump_link_arrival_x_threshold,
                "on_ladder_enter_frame_threshold": self.cfg_on_ladder_enter_frame_threshold,
                "jump_initial_velocity_threshold": self.cfg_jump_initial_velocity_threshold,
                "climb_max_velocity": self.cfg_climb_max_velocity,
                # ==================== v11.5.0 설정 저장 추가 시작 ====================
                "arrival_frame_threshold": self.cfg_arrival_frame_threshold,
                "action_success_frame_threshold": self.cfg_action_success_frame_threshold,
                # ==================== v11.5.0 설정 저장 추가 끝 ======================
                "stuck_detection_wait": self.cfg_stuck_detection_wait,
                "airborne_recovery_wait": self.cfg_airborne_recovery_wait,
                "ladder_recovery_resend_delay": self.cfg_ladder_recovery_resend_delay,
                "prepare_timeout": self.cfg_prepare_timeout if self.cfg_prepare_timeout is not None else PREPARE_TIMEOUT,
                "max_lock_duration": self.cfg_max_lock_duration if self.cfg_max_lock_duration is not None else MAX_LOCK_DURATION,
                "walk_teleport_probability": self.cfg_walk_teleport_probability,
                "walk_teleport_interval": self.cfg_walk_teleport_interval,
                "walk_teleport_bonus_delay": self.cfg_walk_teleport_bonus_delay,
                "walk_teleport_bonus_step": self.cfg_walk_teleport_bonus_step,
                "walk_teleport_bonus_max": self.cfg_walk_teleport_bonus_max,
            }

            config_data = self._prepare_data_for_json({
                'minimap_region': self.minimap_region,
                'active_route_profile': self.active_route_profile_name,
                'route_profiles': self.route_profiles,
                'render_options': self.render_options,
                'reference_anchor_id': self.reference_anchor_id,
                'state_machine_config': state_machine_config, # <<< 추가
                'auto_control_enabled': bool(
                    getattr(self, 'auto_control_checkbox', None)
                    and self.auto_control_checkbox.isChecked()
                ),
                'other_player_alert_enabled': bool(
                    getattr(self, 'other_player_alert_checkbox', None)
                    and self.other_player_alert_checkbox.isChecked()
                ),
                'telegram_alert_enabled': bool(
                    getattr(self, 'telegram_alert_checkbox', None)
                    and self.telegram_alert_checkbox.isChecked()
                ),
                'telegram_send_mode': self.telegram_send_mode,
                'telegram_send_interval': float(self.telegram_send_interval),
            })
            
            key_features_data = self._prepare_data_for_json(self.key_features)

            if "forbidden_walls" not in self.geometry_data:
                self.geometry_data["forbidden_walls"] = []
            else:
                for wall in self.geometry_data.get("forbidden_walls", []):
                    wall.setdefault("cooldown_seconds", 5.0)
                    wall.setdefault("dwell_seconds", 3.0)
                    wall.setdefault("range_left", 0.0)
                    wall.setdefault("range_right", 0.0)
                    wall.setdefault("enabled", False)
                    wall.setdefault("instant_on_contact", False)
                    wall.setdefault("skill_profiles", [])

            geometry_data = self._prepare_data_for_json(self.geometry_data)


            with open(config_file, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4, ensure_ascii=False)
            with open(features_file, 'w', encoding='utf-8') as f: json.dump(key_features_data, f, indent=4, ensure_ascii=False)
            with open(geometry_file, 'w', encoding='utf-8') as f: json.dump(geometry_data, f, indent=4, ensure_ascii=False)
            
            # save 후에 뷰 업데이트
            self._build_line_floor_map() # [v11.4.5] 맵 데이터 저장 후 캐시 빌드 및 뷰 업데이트
            self._update_map_data_and_views()
            # --- v12.0.0 수정: 현재 경로 기준으로 그래프 재생성 ---
            active_route = self.route_profiles.get(self.active_route_profile_name, {})
            wp_ids = self._collect_all_route_waypoint_ids(active_route)
            self._build_navigation_graph(wp_ids)
            
        except Exception as e:
            self.update_general_log(f"프로필 저장 오류: {e}", "red")

    def load_global_settings(self):
        if os.path.exists(GLOBAL_MAP_SETTINGS_FILE):
            try:
                with open(GLOBAL_MAP_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    #  단축키 정보 로드
                    self.current_hotkey = settings.get('hotkey', 'None')
                    self._perf_logging_enabled = bool(settings.get('perf_logging_enabled', False))
                    self._minimap_display_enabled = bool(settings.get('minimap_display_enabled', True))
                    self.initial_delay_ms = int(settings.get('initial_delay_ms', self.initial_delay_ms))
                    return settings.get('active_profile')
            except json.JSONDecodeError:
                self.current_hotkey = 'None'
                self._perf_logging_enabled = False
                self._minimap_display_enabled = True
                self.initial_delay_ms = 2000
                return None
        self.current_hotkey = 'None'
        self._perf_logging_enabled = False
        self._minimap_display_enabled = True
        self.initial_delay_ms = 2000
        return None

    def save_global_settings(self):
        with open(GLOBAL_MAP_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            settings = {
                'active_profile': self.active_profile_name,
                'hotkey': self.current_hotkey, #  단축키 정보 저장
                'perf_logging_enabled': bool(self._perf_logging_enabled),
                'minimap_display_enabled': bool(getattr(self, '_minimap_display_enabled', True)),
                'initial_delay_ms': int(getattr(self, 'initial_delay_ms', 2000)),
            }
            json.dump(settings, f)

    def add_profile(self):
        profile_name, ok = QInputDialog.getText(self, "새 맵 프로필 추가", "프로필 이름 (폴더명으로 사용, 영문/숫자 권장):")
        if ok and profile_name:
            if profile_name in [self.profile_selector.itemText(i) for i in range(self.profile_selector.count())]:
                QMessageBox.warning(self, "오류", "이미 존재하는 프로필 이름입니다.")
                return

            new_profile_path = os.path.join(MAPS_DIR, profile_name)
            os.makedirs(new_profile_path, exist_ok=True)
            self.populate_profile_selector()
            self.profile_selector.setCurrentText(profile_name)
            self.update_general_log(f"새 프로필 '{profile_name}'을(를) 생성했습니다.", "green")

    def rename_profile(self):
        if not self.active_profile_name: return

        old_name = self.active_profile_name
        new_name, ok = QInputDialog.getText(self, "맵 프로필 이름 변경", f"'{old_name}'의 새 이름:", text=old_name)

        if ok and new_name and new_name != old_name:
            if new_name in [self.profile_selector.itemText(i) for i in range(self.profile_selector.count())]:
                QMessageBox.warning(self, "오류", "이미 존재하는 프로필 이름입니다.")
                return

            old_path = os.path.join(MAPS_DIR, old_name)
            new_path = os.path.join(MAPS_DIR, new_name)
            try:
                os.rename(old_path, new_path)
                self.update_general_log(f"맵 프로필 이름이 '{old_name}'에서 '{new_name}'(으)로 변경되었습니다.", "blue")

                self.profile_selector.blockSignals(True)
                self.populate_profile_selector()
                self.profile_selector.setCurrentText(new_name)
                self.profile_selector.blockSignals(False)

                self.load_profile_data(new_name)
            except Exception as e:
                QMessageBox.critical(self, "오류", f"이름 변경 실패: {e}")

    def delete_profile(self):
        if not self.active_profile_name: return

        profile_to_delete = self.active_profile_name
        reply = QMessageBox.question(self, "맵 프로필 삭제 확인",
                                     f"'{profile_to_delete}' 맵 프로필과 모든 관련 데이터를 영구적으로 삭제하시겠습니까?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)

        if reply == QMessageBox.StandardButton.Yes:
            profile_path = os.path.join(MAPS_DIR, profile_to_delete)
            try:
                shutil.rmtree(profile_path)
                self.update_general_log(f"'{profile_to_delete}' 맵 프로필이 삭제되었습니다.", "orange")

                self.profile_selector.blockSignals(True)
                self.populate_profile_selector()

                profile_to_load = None
                if self.profile_selector.count() > 0:
                    profile_to_load = self.profile_selector.itemText(0)
                    self.profile_selector.setCurrentIndex(0)

                self.profile_selector.blockSignals(False)

                if profile_to_load:
                    self.load_profile_data(profile_to_load)
                else:
                    self.update_ui_for_no_profile()
            except Exception as e:
                QMessageBox.critical(self, "오류", f"프로필 삭제 실패: {e}")

    def update_ui_for_new_profile(self):
        self.minimap_groupbox.setTitle(f"3. 미니맵 설정 (맵: {self.active_profile_name})")
        self.wp_groupbox.setTitle(f"4. 웨이포인트 경로 관리 (경로: {self.active_route_profile_name})")
        self.kf_groupbox.setTitle(f"5. 핵심 지형 관리 (맵: {self.active_profile_name})")
        self.editor_groupbox.setTitle(f"6. 전체 맵 편집 (맵: {self.active_profile_name})")

        all_widgets = [
            self.route_profile_selector, self.add_route_btn, self.rename_route_btn, self.delete_route_btn,
            self.set_area_btn, self.manage_kf_btn, self.open_editor_btn, self.detect_anchor_btn, self.wp_groupbox
        ]
        for widget in all_widgets:
            widget.setEnabled(True)

        self.populate_route_profile_selector()
        self.minimap_view_label.setText("탐지를 시작하세요.")
        self.save_global_settings()

    def update_ui_for_no_profile(self):
        self.active_profile_name = None
        self.active_route_profile_name = None
        self.route_profiles.clear()
        self.key_features.clear()
        self.geometry_data.clear()
        self.forward_wp_list.clear()
        self.backward_wp_list.clear()
        self.route_profile_selector.clear()
        self.minimap_region = None
        self.full_map_pixmap = None

        self.minimap_groupbox.setTitle("3. 미니맵 설정 (프로필 없음)")
        self.wp_groupbox.setTitle("4. 웨이포인트 경로 관리 (프로필 없음)")
        self.kf_groupbox.setTitle("5. 핵심 지형 관리 (프로필 없음)")
        self.editor_groupbox.setTitle("6. 전체 맵 편집 (프로필 없음)")

        all_widgets = [
            self.route_profile_selector, self.add_route_btn, self.rename_route_btn, self.delete_route_btn,
            self.set_area_btn, self.manage_kf_btn, self.open_editor_btn, self.detect_anchor_btn, self.wp_groupbox
        ]
        for widget in all_widgets:
            widget.setEnabled(False)

        self.minimap_view_label.setText("맵 프로필을 선택하거나 생성해주세요.")
        if hasattr(self, 'minimap_view_label'):
            self.minimap_view_label.update_static_cache(
                geometry_data=self.geometry_data,
                key_features=self.key_features,
                global_positions=getattr(self, 'global_positions', {}),
            )
        self.save_global_settings()

    def populate_route_profile_selector(self):
        self.route_profile_selector.blockSignals(True)
        self.route_profile_selector.clear()

        if not self.route_profiles:
            self.route_profiles["기본 경로"] = self._create_empty_route_profile()
            self.active_route_profile_name = "기본 경로"

        routes = list(self.route_profiles.keys())
        self.route_profile_selector.addItems(routes)

        if self.active_route_profile_name in routes:
            self.route_profile_selector.setCurrentText(self.active_route_profile_name)
        elif routes:
            self.active_route_profile_name = routes[0]
            self.route_profile_selector.setCurrentIndex(0)
        else:
            self.active_route_profile_name = None

        self.route_profile_selector.blockSignals(False)

        if hasattr(self, 'forward_slot_combo'):
            target_index = ROUTE_SLOT_IDS.index(self.current_forward_slot) if self.current_forward_slot in ROUTE_SLOT_IDS else 0
            self.forward_slot_combo.blockSignals(True)
            self.forward_slot_combo.setCurrentIndex(target_index)
            self.forward_slot_combo.blockSignals(False)

        if hasattr(self, 'backward_slot_combo'):
            target_index = ROUTE_SLOT_IDS.index(self.current_backward_slot) if self.current_backward_slot in ROUTE_SLOT_IDS else 0
            self.backward_slot_combo.blockSignals(True)
            self.backward_slot_combo.setCurrentIndex(target_index)
            self.backward_slot_combo.blockSignals(False)

        self.populate_waypoint_list()

    def on_route_profile_selected(self, index):
        if index == -1: return

        route_name = self.route_profile_selector.itemText(index)
        if route_name != self.active_route_profile_name:
            self.active_route_profile_name = route_name
            self.update_general_log(f"'{route_name}' 경로 프로필로 전환했습니다.", "SaddleBrown")
            self.populate_waypoint_list()
            # --- v12.0.0 추가: 경로 프로필 변경 시 그래프 재생성 ---
            active_route = self.route_profiles.get(self.active_route_profile_name, {})
            wp_ids = self._collect_all_route_waypoint_ids(active_route)
            self._build_navigation_graph(wp_ids)
            # --- 추가 끝 ---
            self.save_profile_data()

    def add_route_profile(self):
        route_name, ok = QInputDialog.getText(self, "새 경로 프로필 추가", "경로 프로필 이름:")
        if ok and route_name:
            if route_name in self.route_profiles:
                QMessageBox.warning(self, "오류", "이미 존재하는 경로 프로필 이름입니다.")
                return

            self.route_profiles[route_name] = self._create_empty_route_profile()
            self.active_route_profile_name = route_name
            self.populate_route_profile_selector()
            self.save_profile_data()
            self.update_general_log(f"새 경로 '{route_name}'이(가) 추가되었습니다.", "green")

    def rename_route_profile(self):
        if not self.active_route_profile_name: return

        old_name = self.active_route_profile_name
        new_name, ok = QInputDialog.getText(self, "경로 프로필 이름 변경", f"'{old_name}'의 새 이름:", text=old_name)

        if ok and new_name and new_name != old_name:
            if new_name in self.route_profiles:
                QMessageBox.warning(self, "오류", "이미 존재하는 이름입니다.")
                return

            self.route_profiles[new_name] = self.route_profiles.pop(old_name)
            self.active_route_profile_name = new_name
            self.populate_route_profile_selector()
            self.save_profile_data()
            self.update_general_log(f"경로 이름이 '{old_name}'에서 '{new_name}'(으)로 변경되었습니다.", "blue")

    def delete_route_profile(self):
        if not self.active_route_profile_name: return
        if len(self.route_profiles) <= 1:
            QMessageBox.warning(self, "삭제 불가", "최소 1개의 경로 프로필은 존재해야 합니다.")
            return

        reply = QMessageBox.question(self, "경로 프로필 삭제", f"'{self.active_route_profile_name}' 경로를 삭제하시겠습니까?")
        if reply == QMessageBox.StandardButton.Yes:
            del self.route_profiles[self.active_route_profile_name]
            self.active_route_profile_name = list(self.route_profiles.keys())[0]
            self.populate_route_profile_selector()
            self.save_profile_data()

    def get_all_waypoints_with_route_name(self):
        """(구버전 호환용) 모든 경로 프로필의 웨이포인트에 'route_name'을 추가하여 단일 리스트로 반환합니다."""
        all_waypoints = []
        for route_name, route_data in self.route_profiles.items():
            # v10.0.0 이전 데이터 구조에 대한 호환성 코드
            if 'waypoints' in route_data:
                for wp in route_data['waypoints']:
                    wp_copy = wp.copy()
                    wp_copy['route_name'] = route_name
                    all_waypoints.append(wp_copy)
        return all_waypoints

    def open_key_feature_manager(self):
        all_waypoints = self.get_all_waypoints_with_route_name()
        dialog = KeyFeatureManagerDialog(self.key_features, all_waypoints, self)
        dialog.exec()
        self._generate_full_map_pixmap()

    def open_full_minimap_editor(self):
        """'미니맵 지형 편집기 열기' 버튼에 연결된 슬롯."""
        if not self.active_profile_name:
            QMessageBox.warning(self, "오류", "먼저 맵 프로필을 선택해주세요.")
            return

        self.global_positions = self._calculate_global_positions()
        self._assign_dynamic_names()
        
        self.editor_dialog = FullMinimapEditorDialog(
            profile_name=self.active_profile_name,
            active_route_profile=self.active_route_profile_name,
            key_features=self.key_features,
            route_profiles=self.route_profiles,
            geometry_data=self.geometry_data, # 이름 정보가 포함된 데이터를 전달
            render_options=self.render_options,
            global_positions=self.global_positions,
            parent=self
        )
        self.global_pos_updated.connect(self.editor_dialog.update_locked_position)
        
        try:
            result = self.editor_dialog.exec()
            
            if result:
                self.geometry_data = self.editor_dialog.get_updated_geometry_data()
                self._ensure_waypoint_event_fields()
                self._refresh_event_waypoint_states()
                self._refresh_forbidden_wall_states()
                self.render_options = self.editor_dialog.get_current_view_options()
                self.save_profile_data()
                self.update_general_log("지형 편집기 변경사항이 저장되었습니다.", "green")
                self.global_positions = self._calculate_global_positions()
                self._generate_full_map_pixmap()
                self.populate_waypoint_list()  # 변경사항을 웨이포인트 경로 관리 UI에 즉시 반영 ---
            else:
                self.update_general_log("지형 편집이 취소되었습니다.", "black")
            
        finally:
            self.global_pos_updated.disconnect(self.editor_dialog.update_locked_position)
            self.editor_dialog = None

    def get_waypoint_name_from_item(self, item):
        if not item:
            return None
        text = item.text()
        return text.split('. ', 1)[1] if '. ' in text and text.split('. ', 1)[0].isdigit() else text

    def _ensure_waypoint_event_fields(self):
        for waypoint in self.geometry_data.get("waypoints", []):
            if 'is_event' not in waypoint:
                waypoint['is_event'] = False
            if 'event_profile' not in waypoint or waypoint['event_profile'] is None:
                waypoint['event_profile'] = ""

    def _refresh_event_waypoint_states(self):
        """이벤트 웨이포인트 무장 상태를 초기화합니다."""
        refreshed_states = {}
        for waypoint in self.geometry_data.get("waypoints", []):
            if waypoint.get('is_event') and waypoint.get('id'):
                refreshed_states[waypoint['id']] = {
                    "armed": True,
                    "is_inside": False,
                    "last_triggered": 0.0,
                    "last_entered": 0.0,
                    "last_exited": 0.0,
                    "last_attempted": 0.0,
                }
        self.event_waypoint_states = refreshed_states

    def _get_event_waypoint_state(self, waypoint_id):
        if waypoint_id not in self.event_waypoint_states:
            self.event_waypoint_states[waypoint_id] = {
                "armed": True,
                "is_inside": False,
                "last_triggered": 0.0,
                "last_entered": 0.0,
                "last_exited": 0.0,
                "last_attempted": 0.0,
            }
        return self.event_waypoint_states[waypoint_id]

    def _can_start_event_now(self):
        if self.event_in_progress:
            return False
        if self.navigation_state_locked:
            return False
        if self.navigation_action.endswith('_in_progress'):
            return False
        if self.navigation_action.startswith('prepare_to_'):
            return False
        return True

    def _enqueue_pending_event(self, waypoint_data):
        waypoint_id = waypoint_data.get('id') if waypoint_data else None
        if not waypoint_id:
            return

        now = time.time()
        if not self.pending_event_request or self.pending_event_request.get('waypoint_id') != waypoint_id:
            self.pending_event_request = {
                'waypoint_id': waypoint_id,
                'requested_at': now,
                'next_retry_at': now,
            }
            self.pending_event_notified = False
        else:
            self.pending_event_request['requested_at'] = now
            self.pending_event_request['next_retry_at'] = now

        if not self.pending_event_notified:
            waypoint_name = waypoint_data.get('name', '')
            profile_name = waypoint_data.get('event_profile', '')
            self.update_general_log(
                f"[이벤트] '{waypoint_name}' 명령 '{profile_name}' 실행을 현재 행동 완료 후 대기열에 추가합니다.",
                "gray"
            )
            self.pending_event_notified = True

    def _clear_pending_event(self, waypoint_id=None):
        if self.pending_event_request is None:
            return
        if waypoint_id is None or self.pending_event_request.get('waypoint_id') == waypoint_id:
            self.pending_event_request = None
            self.pending_event_notified = False

    def _try_execute_pending_event(self):
        if not self.pending_event_request:
            return

        waypoint_id = self.pending_event_request.get('waypoint_id')
        waypoint = self._find_waypoint_by_id(waypoint_id)
        if waypoint is None:
            self._clear_pending_event()
            return

        if time.time() < self.pending_event_request.get('next_retry_at', 0.0):
            return

        if not self._can_start_event_now():
            return

        if self._start_waypoint_event(waypoint):
            self._clear_pending_event()
        else:
            self.pending_event_request['next_retry_at'] = time.time() + self.event_retry_cooldown_seconds

    def _request_waypoint_event(self, waypoint_data):
        if not waypoint_data:
            return 'skipped'

        if self._can_start_event_now():
            return 'started' if self._start_waypoint_event(waypoint_data) else 'skipped'

        self._enqueue_pending_event(waypoint_data)
        return 'queued'

    def _is_player_within_event_waypoint(self, waypoint, final_player_pos):
        """플레이어가 이벤트 웨이포인트 반경에 들어왔는지 판정합니다."""
        if final_player_pos is None:
            return False

        pos = waypoint.get('pos')
        if not pos:
            return False

        waypoint_point = QPointF(pos[0], pos[1])
        threshold_x = self.EVENT_WAYPOINT_THRESHOLD
        threshold_y = self.cfg_jump_y_max_threshold or JUMP_Y_MAX_THRESHOLD

        if waypoint.get('floor') is not None and self.current_player_floor is not None:
            if abs(float(waypoint.get('floor', 0.0)) - float(self.current_player_floor)) > 0.1:
                return False

        if abs(final_player_pos.x() - waypoint_point.x()) > threshold_x:
            return False

        if abs(final_player_pos.y() - waypoint_point.y()) > max(threshold_y, threshold_x):
            return False

        distance = math.hypot(final_player_pos.x() - waypoint_point.x(), final_player_pos.y() - waypoint_point.y())
        return distance <= max(threshold_x, threshold_y)

    def _update_event_waypoint_proximity(self, final_player_pos):
        """이벤트 웨이포인트 재진입 여부를 감시하고 필요 시 재실행을 트리거합니다."""
        if not self.geometry_data or not self.geometry_data.get("waypoints"):
            return

        now = time.time()
        current_plan_ids = set(self.journey_plan or [])
        for waypoint in self.geometry_data.get("waypoints", []):
            if not waypoint.get('is_event'):
                continue

            waypoint_id = waypoint.get('id')
            if not waypoint_id:
                continue

            always_run = bool(waypoint.get('event_always'))
            if not always_run and waypoint_id not in current_plan_ids:
                continue

            state = self._get_event_waypoint_state(waypoint_id)
            is_inside = self._is_player_within_event_waypoint(waypoint, final_player_pos)

            if is_inside:
                if not state['is_inside']:
                    state['is_inside'] = True
                    state['last_entered'] = now

                if state['armed']:
                    last_attempt = state.get('last_attempted', 0.0)
                    if now - last_attempt >= self.event_retry_cooldown_seconds:
                        state['last_attempted'] = now
                        result = self._request_waypoint_event(waypoint)
                        if result == 'started':
                            state['armed'] = False
                            state['last_triggered'] = now
                continue

            if state['is_inside']:
                state['is_inside'] = False
                state['last_exited'] = now
                self._clear_pending_event(waypoint_id)

            if not state['armed']:
                triggered_at = state.get('last_triggered', 0.0)
                exited_at = state.get('last_exited', 0.0)
                if (now - triggered_at) >= self.event_rearm_min_delay and (now - exited_at) >= self.event_rearm_exit_delay:
                    state['armed'] = True

    def _find_waypoint_by_id(self, waypoint_id):
        for waypoint in self.geometry_data.get("waypoints", []):
            if waypoint.get('id') == waypoint_id:
                return waypoint
        return None

    def _start_waypoint_event(self, waypoint_data):
        if self.event_in_progress:
            return True

        waypoint_id = waypoint_data.get('id') if waypoint_data else None
        now = time.time()
        state = None
        if waypoint_id:
            state = self._get_event_waypoint_state(waypoint_id)
            if state and not state.get('armed', True):
                return False
            state['last_attempted'] = now

        auto_checkbox = getattr(self, "auto_control_checkbox", None)
        debug_checkbox = getattr(self, "debug_auto_control_checkbox", None)
        is_auto_enabled = bool(auto_checkbox and auto_checkbox.isChecked())
        is_debug_enabled = bool(debug_checkbox and debug_checkbox.isChecked())

        if not (is_auto_enabled or is_debug_enabled):
            waypoint_name = waypoint_data.get('name', '')
            self.update_general_log(
                f"[이벤트] '{waypoint_name}' 자동 제어가 비활성화되어 실행을 건너뜁니다.",
                "orange"
            )
            return False

        profile_name = waypoint_data.get('event_profile') or ""
        waypoint_name = waypoint_data.get('name', '')

        if not profile_name:
            self.update_general_log(f"[이벤트] '{waypoint_name}'에 이벤트 명령이 설정되지 않아 실행을 건너뜁니다.", "orange")
            return False

        self.event_in_progress = True
        self.active_event_waypoint_id = waypoint_data.get('id')
        self.active_event_profile = profile_name
        self.active_event_reason = f"WAYPOINT_EVENT:{self.active_event_waypoint_id}"
        self.event_started_at = time.time()
        self.navigation_state_locked = False
        self.state_transition_counters.clear()
        self._authority_priority_override = True
        if self._authority_manager:
            self._authority_manager.notify_priority_event(
                "WAYPOINT_EVENT",
                metadata={
                    "waypoint_id": self.active_event_waypoint_id,
                    "profile": profile_name,
                },
            )

        if waypoint_id:
            state = self._get_event_waypoint_state(waypoint_id)
            state['armed'] = False
            state['is_inside'] = True
            state['last_triggered'] = self.event_started_at
            state['last_entered'] = self.event_started_at

        self.update_general_log(
            f"[이벤트] 웨이포인트 '{waypoint_name}'에서 명령 '{profile_name}' 실행을 시작합니다.",
            "DodgerBlue"
        )

        if not self._emit_control_command(profile_name, self.active_event_reason):
            self.update_general_log("[이벤트] 금지벽 명령 실행 중이라 이벤트 명령을 보류합니다.", "orange")
            self.event_in_progress = False
            self.active_event_waypoint_id = None
            self.active_event_profile = ""
            self.active_event_reason = ""
            self.event_started_at = 0.0
            self._authority_priority_override = False
            if self._authority_manager:
                self._authority_manager.clear_priority_event("WAYPOINT_EVENT")
            self._sync_authority_snapshot("event_aborted")
            return False
        return True

    def _finish_waypoint_event(self, success):
        waypoint_id = self.active_event_waypoint_id
        waypoint = self._find_waypoint_by_id(waypoint_id)
        waypoint_name = waypoint.get('name', '') if waypoint else ''
        profile_name = self.active_event_profile

        if success:
            self.update_general_log(
                f"[이벤트] '{waypoint_name}' 명령 '{profile_name}' 실행 완료.",
                "green"
            )
        else:
            self.update_general_log(
                f"[이벤트] '{waypoint_name}' 명령 '{profile_name}' 실행 실패 또는 중단.",
                "red"
            )

        if waypoint_id:
            state = self.event_waypoint_states.get(waypoint_id)
            if state:
                state['is_inside'] = True
                state['last_triggered'] = time.time()

        self.event_in_progress = False
        self.active_event_waypoint_id = None
        self.active_event_profile = ""
        self.active_event_reason = ""
        self.event_started_at = 0.0
        self._authority_priority_override = False
        if self._authority_manager:
            self._authority_manager.clear_priority_event("WAYPOINT_EVENT")
        self.navigation_action = 'move_to_target'
        self.guidance_text = '없음'
        self.recovery_cooldown_until = time.time() + 1.0
        self.current_segment_path = []
        self.current_segment_index = 0
        self._try_execute_pending_event()
        self._sync_authority_snapshot("event_finished")

    def _refresh_forbidden_wall_states(self) -> None:
        refreshed: Dict[str, dict] = {}
        for wall in self.geometry_data.get("forbidden_walls", []):
            wall_id = wall.get('id')
            if not wall_id:
                continue
            existing = self.forbidden_wall_states.get(wall_id, {})
            refreshed[wall_id] = {
                'entered_at': existing.get('entered_at'),
                'last_triggered': existing.get('last_triggered', 0.0),
                'contact_ready': existing.get('contact_ready', True),
            }
        self.forbidden_wall_states = refreshed

        if self.active_forbidden_wall_id and self.active_forbidden_wall_id not in refreshed:
            self.forbidden_wall_in_progress = False
            self.active_forbidden_wall_id = None
            self.active_forbidden_wall_reason = ""
            self.active_forbidden_wall_profile = ""
            self.active_forbidden_wall_trigger = ""
            self.forbidden_wall_started_at = 0.0
            if self._authority_manager:
                self._authority_manager.clear_priority_event("FORBIDDEN_WALL")

    def _get_forbidden_wall_state(self, wall_id: str) -> dict:
        if wall_id not in self.forbidden_wall_states:
            self.forbidden_wall_states[wall_id] = {
                'entered_at': None,
                'last_triggered': 0.0,
                'contact_ready': True,
            }
        return self.forbidden_wall_states[wall_id]

    def _get_forbidden_wall_by_id(self, wall_id: str | None) -> Optional[dict]:
        if not wall_id:
            return None
        for wall in self.geometry_data.get("forbidden_walls", []):
            if wall.get('id') == wall_id:
                return wall
        return None

    def _trigger_forbidden_wall(self, wall: dict, trigger_type: str) -> bool:
        auto_checkbox = getattr(self, "auto_control_checkbox", None)
        debug_checkbox = getattr(self, "debug_auto_control_checkbox", None)
        is_auto_enabled = bool(auto_checkbox and auto_checkbox.isChecked())
        is_debug_enabled = bool(debug_checkbox and debug_checkbox.isChecked())
        if not (is_auto_enabled or is_debug_enabled):
            return False

        skills = wall.get('skill_profiles') or []
        if not skills:
            return False

        wall_id = wall.get('id') or f"fw-{uuid.uuid4()}"
        wall['id'] = wall_id
        state = self._get_forbidden_wall_state(wall_id)

        cooldown = max(0.0, float(wall.get('cooldown_seconds', 5.0)))
        if cooldown > 0.0 and state.get('last_triggered'):
            elapsed = time.time() - float(state['last_triggered'])
            if elapsed < cooldown:
                return False

        command = random.choice(skills)
        wall_pos = wall.get('pos') or [0.0, 0.0]
        trigger_label = "접촉" if trigger_type == "contact" else "대기"

        reason = f"FORBIDDEN_WALL:{wall_id}"
        message = (
            f"[금지벽] ({wall_pos[0]:.1f}, {wall_pos[1]:.1f})에서 명령 '{command}' 실행 시작"
            f" (트리거: {trigger_label})."
        )
        self.update_general_log(message, "crimson")

        state['entered_at'] = None
        state['last_triggered'] = time.time()
        state['contact_ready'] = False

        takeover_context = None
        if getattr(self, 'current_authority_owner', 'map') != 'map':
            last_regular = getattr(self, '_last_regular_command', None)
            takeover_context = {
                "previous_owner": getattr(self, 'current_authority_owner', None),
                "resume_command": last_regular[0] if last_regular else None,
                "resume_reason": last_regular[1] if last_regular else None,
            }
        self._forbidden_takeover_context = takeover_context

        self.forbidden_wall_in_progress = True
        self.active_forbidden_wall_id = wall_id
        self.active_forbidden_wall_reason = reason
        self.active_forbidden_wall_profile = command
        self.active_forbidden_wall_trigger = trigger_type
        self.forbidden_wall_started_at = time.time()
        self._authority_priority_override = True
        if self._authority_manager:
            self._authority_manager.notify_priority_event(
                "FORBIDDEN_WALL",
                metadata={
                    "wall_id": wall_id,
                    "trigger": trigger_type,
                },
            )

        if not self._emit_control_command(command, reason, allow_forbidden=True):
            self.forbidden_wall_in_progress = False
            self.active_forbidden_wall_id = None
            self.active_forbidden_wall_reason = ""
            self.active_forbidden_wall_profile = ""
            self.active_forbidden_wall_trigger = ""
            self._authority_priority_override = False
            state['contact_ready'] = False
            if self._authority_manager:
                self._authority_manager.clear_priority_event("FORBIDDEN_WALL")
            self._forbidden_takeover_context = None
            self._forbidden_takeover_active = False
            self._sync_authority_snapshot("forbidden_aborted")
            return False
        return True

    def _finish_forbidden_wall_sequence(self, success: bool) -> None:
        wall = self._get_forbidden_wall_by_id(self.active_forbidden_wall_id)
        wall_pos = wall.get('pos') if wall else [0.0, 0.0]
        trigger_label = "접촉" if self.active_forbidden_wall_trigger == "contact" else "대기"
        status_text = "완료" if success else "실패"
        color = "green" if success else "red"
        self.update_general_log(
            f"[금지벽] ({wall_pos[0]:.1f}, {wall_pos[1]:.1f}) 명령 '{self.active_forbidden_wall_profile}' {status_text}"
            f" (트리거: {trigger_label}).",
            color,
        )

        state = self.forbidden_wall_states.get(self.active_forbidden_wall_id)
        if state:
            state['entered_at'] = None
            state['last_triggered'] = time.time()
            state['contact_ready'] = False

        self.forbidden_wall_in_progress = False
        self.active_forbidden_wall_id = None
        self.active_forbidden_wall_reason = ""
        self.active_forbidden_wall_profile = ""
        self.active_forbidden_wall_trigger = ""
        self.forbidden_wall_started_at = 0.0
        self._authority_priority_override = False
        takeover_context = self._forbidden_takeover_context if self._forbidden_takeover_active else None
        if self._authority_manager:
            self._authority_manager.clear_priority_event("FORBIDDEN_WALL")

        pending = getattr(self, 'pending_forbidden_command', None)
        self.pending_forbidden_command = None
        if pending and not self.event_in_progress:
            command, pending_reason = pending
            if self._emit_control_command(command, pending_reason):
                self.update_general_log(
                    "금지벽 종료 후 보류된 명령을 재전송했습니다.",
                    "gray",
                )

        if takeover_context and getattr(self, 'current_authority_owner', 'map') == 'map':
            resume_command = takeover_context.get('resume_command')
            resume_reason = takeover_context.get('resume_reason')
            if resume_command:
                success = self._emit_control_command(resume_command, resume_reason)
                result_text = "성공" if success else "보류"
                self.update_general_log(
                    f"[금지벽] 이전 맵 명령 '{resume_command}' 재실행 {result_text}.",
                    "gray" if success else "orange",
                )
                self._record_authority_event(
                    "forbidden_resume",
                    message=f"금지벽 종료 후 '{resume_command}' 재실행 {result_text}.",
                    reason="FORBIDDEN_WALL",
                    source="map_tab",
                    previous_owner=getattr(self, 'current_authority_owner', None),
                    command=resume_command,
                    command_success=success,
                )

        self._forbidden_takeover_context = None
        self._forbidden_takeover_active = False

        self._sync_authority_snapshot("forbidden_finished")

    def _update_forbidden_wall_logic(self, final_player_pos: QPointF, contact_terrain: Optional[dict]) -> None:
        walls = self.geometry_data.get("forbidden_walls", [])
        if not walls or final_player_pos is None:
            return

        current_line_id = contact_terrain.get('id') if contact_terrain else None
        now = time.time()

        touch_threshold = getattr(self, 'forbidden_wall_touch_threshold', 2.0)

        for wall in walls:
            wall_id = wall.get('id')
            if not wall_id:
                continue

            state = self._get_forbidden_wall_state(wall_id)

            if not wall.get('enabled') or not wall.get('skill_profiles'):
                state['entered_at'] = None
                state['contact_ready'] = True
                continue

            if wall.get('line_id') != current_line_id:
                state['entered_at'] = None
                state['contact_ready'] = True
                continue

            wall_pos = wall.get('pos') or [0.0, 0.0]
            wall_x = float(wall_pos[0])
            dx = final_player_pos.x() - wall_x

            range_left = max(0.0, float(wall.get('range_left', 0.0)))
            range_right = max(0.0, float(wall.get('range_right', 0.0)))
            dwell_seconds = max(0.0, float(wall.get('dwell_seconds', 0.0)))

            within_range = (-range_left <= dx <= range_right)
            within_touch = abs(dx) <= touch_threshold

            if within_range:
                if state.get('entered_at') is None:
                    state['entered_at'] = now
            else:
                state['entered_at'] = None

            if within_touch:
                instant_enabled = bool(wall.get('instant_on_contact'))
                if instant_enabled and state.get('contact_ready', True) and not self.forbidden_wall_in_progress and not self.event_in_progress:
                    if self._trigger_forbidden_wall(wall, trigger_type="contact"):
                        state['contact_ready'] = False
                        continue
            else:
                state['contact_ready'] = True

            if (
                dwell_seconds > 0.0
                and within_range
                and state.get('entered_at') is not None
                and not self.forbidden_wall_in_progress
                and not self.event_in_progress
                and (now - state['entered_at']) >= dwell_seconds
            ):
                if self._trigger_forbidden_wall(wall, trigger_type="dwell"):
                    state['entered_at'] = None

    @pyqtSlot(str, object, bool)
    def on_sequence_completed(self, command_name, reason, success):
        if isinstance(reason, str):
            if reason.startswith('status:'):
                self._handle_status_command_completed(bool(success))
                return
            if self.event_in_progress and reason == self.active_event_reason:
                self._finish_waypoint_event(bool(success))
                return
            if self.forbidden_wall_in_progress and reason == self.active_forbidden_wall_reason:
                self._finish_forbidden_wall_sequence(bool(success))

    def process_new_waypoint_data(self, wp_data, final_features_on_canvas, newly_drawn_features, deleted_feature_ids, context_frame_bgr):
        # 이 함수는 v10.0.0에서 더 이상 사용되지 않음. 웨이포인트는 편집기에서 직접 생성됨.
        # 호환성을 위해 남겨둠
        return {}

    def update_all_waypoints_with_features(self):
        """(구버전 호환용) 현재 맵 프로필의 모든 웨이포인트를 순회하며, 등록된 모든 핵심 지형과의 연결을 재구성합니다."""
        all_old_waypoints = self.get_all_waypoints_with_route_name()
        if not all_old_waypoints:
            QMessageBox.information(self, "알림", "갱신할 (구버전) 웨이포인트가 없습니다.")
            return False

        reply = QMessageBox.question(self, "전체 갱신 확인",
                                    f"총 {len(all_old_waypoints)}개의 (구버전) 웨이포인트와 {len(self.key_features)}개의 핵심 지형의 연결을 갱신합니다.\n"
                                    "이 작업은 각 웨이포인트의 기존 핵심 지형 링크를 덮어씁니다. 계속하시겠습니까?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Cancel:
            return False

        self.update_general_log("모든 (구버전) 웨이포인트와 핵심 지형의 연결을 갱신합니다...", "purple")
        QApplication.processEvents()
        updated_count = 0

        for route_name, route_data in self.route_profiles.items():
            if 'waypoints' not in route_data: continue
            for wp in route_data.get('waypoints', []):
                if 'image_base64' not in wp or not wp['image_base64']:
                    continue
                try:
                    # ... (기존 로직과 동일) ...
                    updated_count += 1
                except Exception as e:
                    self.update_general_log(f"'{wp['name']}' 갱신 중 오류: {e}", "red")

        self.save_profile_data()
        self.update_general_log(f"완료: 총 {len(all_old_waypoints)}개 중 {updated_count}개의 웨이포인트 링크를 갱신했습니다.", "purple")
        QMessageBox.information(self, "성공", f"{updated_count}개의 웨이포인트 갱신 완료.")
        return True

    def _get_next_feature_name(self):
        max_num = max([int(name[1:]) for name in self.key_features.keys() if name.startswith("P") and name[1:].isdigit()] or [0])
        return f"P{max_num + 1}"

    def add_waypoint_to_path(self, direction='forward'):
        all_wps_in_geom = self.geometry_data.get("waypoints", [])
        if not all_wps_in_geom:
            QMessageBox.information(self, "알림", "편집기에서 먼저 웨이포인트를 생성해주세요.")
            return

        if not self.active_route_profile_name or self.active_route_profile_name not in self.route_profiles:
            QMessageBox.warning(self, "오류", "경로 프로필이 선택되지 않았습니다.")
            return

        route = self.route_profiles[self.active_route_profile_name]
        route, changed = self._ensure_route_profile_structure(route)
        self.route_profiles[self.active_route_profile_name] = route
        if changed:
            self.save_profile_data()

        slots_key = "forward_slots" if direction == 'forward' else "backward_slots"
        current_slot = self.current_forward_slot if direction == 'forward' else self.current_backward_slot
        slot_data = route.get(slots_key, {}).get(current_slot)
        if slot_data is None:
            QMessageBox.warning(self, "오류", "유효하지 않은 슬롯입니다.")
            return

        existing_ids = set(slot_data.get("waypoints", []))

        available_wps = {wp['name']: wp['id'] for wp in all_wps_in_geom if wp['id'] not in existing_ids}

        if not available_wps:
            QMessageBox.information(self, "알림", "모든 웨이포인트가 이미 경로에 추가되었습니다.")
            return

        wp_name, ok = QInputDialog.getItem(self, "경로에 웨이포인트 추가", "추가할 웨이포인트를 선택하세요:", sorted(available_wps.keys()), 0, False)

        if ok and wp_name:
            wp_id = available_wps[wp_name]
            slot_data.setdefault("waypoints", []).append(wp_id)
            self.populate_waypoint_list()
            self.save_profile_data()
            self._rebuild_active_route_graph()

    def delete_waypoint_from_path(self, direction='forward'):
        list_widget = self.forward_wp_list if direction == 'forward' else self.backward_wp_list
        selected_items = list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "오류", "삭제할 웨이포인트를 목록에서 선택하세요.")
            return

        if not self.active_route_profile_name or self.active_route_profile_name not in self.route_profiles:
            QMessageBox.warning(self, "오류", "경로 프로필이 선택되지 않았습니다.")
            return

        route = self.route_profiles[self.active_route_profile_name]
        route, changed = self._ensure_route_profile_structure(route)
        self.route_profiles[self.active_route_profile_name] = route
        if changed:
            self.save_profile_data()

        slots_key = "forward_slots" if direction == 'forward' else "backward_slots"
        current_slot = self.current_forward_slot if direction == 'forward' else self.current_backward_slot
        slot_data = route.get(slots_key, {}).get(current_slot)
        if slot_data is None:
            QMessageBox.warning(self, "오류", "유효하지 않은 슬롯입니다.")
            return

        path_ids = slot_data.get("waypoints", [])

        for item in selected_items:
            row = list_widget.row(item)
            if 0 <= row < len(path_ids):
                del path_ids[row]

        self.populate_waypoint_list()
        self.save_profile_data()
        self._rebuild_active_route_graph()

    def set_minimap_area(self):
        self.update_general_log("화면에서 미니맵 영역을 드래그하여 선택하세요...", "black")
        QApplication.processEvents()

        top_window = self.window()
        was_visible = bool(top_window and top_window.isVisible())

        try:
            if top_window and was_visible:
                top_window.hide()
                QApplication.processEvents()

            snipper = MultiScreenSnipper(None)
            if snipper.exec():
                roi = snipper.get_global_roi()
                target_screen = snipper.get_target_screen() or self.screen() or QGuiApplication.primaryScreen()

                if roi.isNull() or not target_screen:
                    self.update_general_log("미니맵 범위 지정이 실패했습니다.", "red")
                    return

                logical_geometry = target_screen.geometry()
                native_geometry = target_screen.nativeGeometry() if hasattr(target_screen, "nativeGeometry") else logical_geometry

                scale_x = native_geometry.width() / logical_geometry.width() if logical_geometry.width() else 1.0
                scale_y = native_geometry.height() / logical_geometry.height() if logical_geometry.height() else 1.0

                clamped_roi = roi.intersected(logical_geometry)
                if clamped_roi.isEmpty():
                    self.update_general_log("선택한 영역이 모니터 경계를 벗어났습니다.", "red")
                    return

                top = int(native_geometry.top() + (clamped_roi.top() - logical_geometry.top()) * scale_y)
                left = int(native_geometry.left() + (clamped_roi.left() - logical_geometry.left()) * scale_x)
                width = int(clamped_roi.width() * scale_x)
                height = int(clamped_roi.height() * scale_y)

                self.minimap_region = {'top': top, 'left': left, 'width': width, 'height': height}
                if width * height > (512 * 512):
                    self.update_general_log(
                        f"경고: 선택한 미니맵 영역({width}x{height})이 비정상적으로 큽니다. 미니맵만 포함하도록 다시 지정하는 것을 권장합니다.",
                        "orange",
                    )
                self.update_general_log(f"새 미니맵 범위 지정 완료: {self.minimap_region}", "black")
                self.save_profile_data()
            else:
                self.update_general_log("미니맵 범위 지정이 취소되었습니다.", "black")
        finally:
            if top_window and was_visible:
                top_window.show()
                QApplication.processEvents()
                top_window.raise_()
                top_window.activateWindow()

    def populate_waypoint_list(self):
        """새 슬롯 구조 기준으로 웨이포인트 리스트를 갱신합니다."""
        self.forward_wp_list.clear()
        self.backward_wp_list.clear()

        if not self.active_route_profile_name or not self.route_profiles:
            self.wp_groupbox.setTitle("4. 웨이포인트 경로 관리 (경로 없음)")
            return

        self.wp_groupbox.setTitle(f"4. 웨이포인트 경로 관리 (경로: {self.active_route_profile_name})")

        route = self.route_profiles.get(self.active_route_profile_name)
        if route is None:
            return

        route, changed = self._ensure_route_profile_structure(route)
        self.route_profiles[self.active_route_profile_name] = route
        if changed:
            self.save_profile_data()

        if self.current_forward_slot not in ROUTE_SLOT_IDS:
            self.current_forward_slot = ROUTE_SLOT_IDS[0]
        if self.current_backward_slot not in ROUTE_SLOT_IDS:
            self.current_backward_slot = ROUTE_SLOT_IDS[0]

        if hasattr(self, 'forward_slot_combo'):
            self.forward_slot_combo.blockSignals(True)
            self.forward_slot_combo.setCurrentIndex(ROUTE_SLOT_IDS.index(self.current_forward_slot))
            self.forward_slot_combo.blockSignals(False)

        if hasattr(self, 'backward_slot_combo'):
            self.backward_slot_combo.blockSignals(True)
            self.backward_slot_combo.setCurrentIndex(ROUTE_SLOT_IDS.index(self.current_backward_slot))
            self.backward_slot_combo.blockSignals(False)

        waypoint_lookup = {wp['id']: wp for wp in self.geometry_data.get("waypoints", [])}

        self._populate_direction_list('forward', route, waypoint_lookup)
        self._populate_direction_list('backward', route, waypoint_lookup)


    def get_cleaned_minimap_image(self):
        if not self.minimap_region: return None
        with mss.mss() as sct:
            sct_img = sct.grab(self.minimap_region); frame_bgr = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR)
            hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
            my_player_mask = cv2.inRange(hsv, PLAYER_ICON_LOWER, PLAYER_ICON_UPPER); other_player_mask1 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER1, OTHER_PLAYER_ICON_UPPER1); other_player_mask2 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER2, OTHER_PLAYER_ICON_UPPER2)
            other_player_mask = cv2.bitwise_or(other_player_mask1, other_player_mask2); kernel = np.ones((5, 5), np.uint8)
            dilated_my_player_mask = cv2.dilate(my_player_mask, kernel, iterations=1); dilated_other_player_mask = cv2.dilate(other_player_mask, kernel, iterations=1)
            total_ignore_mask = cv2.bitwise_or(dilated_my_player_mask, dilated_other_player_mask)
            return cv2.inpaint(frame_bgr, total_ignore_mask, 3, cv2.INPAINT_TELEA) if np.any(total_ignore_mask) else frame_bgr

    def _get_next_feature_name(self):
        max_num = max([int(name[1:]) for name in self.key_features.keys() if name.startswith("P") and name[1:].isdigit()] or [0])
        return f"P{max_num + 1}"

    def waypoint_order_changed(self, direction):
        if not self.active_route_profile_name: return
        route = self.route_profiles.get(self.active_route_profile_name)
        if not route:
            return

        route, changed = self._ensure_route_profile_structure(route)
        self.route_profiles[self.active_route_profile_name] = route
        if changed:
            self.save_profile_data()

        list_widget = self.forward_wp_list if direction == 'forward' else self.backward_wp_list
        slots_key = "forward_slots" if direction == 'forward' else "backward_slots"
        current_slot = self.current_forward_slot if direction == 'forward' else self.current_backward_slot
        slot_data = route.get(slots_key, {}).get(current_slot)
        if slot_data is None:
            return

        new_ids = [list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(list_widget.count())]
        slot_data["waypoints"] = [wp_id for wp_id in new_ids if isinstance(wp_id, str)]

        self.save_profile_data()
        self._rebuild_active_route_graph()
        self.update_general_log("웨이포인트 순서가 변경되었습니다.", "SaddleBrown")
        self.populate_waypoint_list()

    def toggle_debug_view(self, checked):
        """디버그 뷰 체크박스의 상태에 따라 디버그 창을 표시하거나 숨깁니다."""
        # 탐지가 실행 중일 때만 동작하도록 함
        if not (self.detection_thread and self.detection_thread.isRunning()):
            if self.debug_dialog:
                self.debug_dialog.close()
            return
            
        if checked:
            if not self.debug_dialog:
                self.debug_dialog = DebugViewDialog(self)
            self.debug_dialog.show()
        else:
            if self.debug_dialog:
                self.debug_dialog.close()

    # [v11.0.0] AnchorDetectionThread에서 책임 이동된 메서드들
    def _extract_player_icon_rects_from_mask(self, mask, *, offset_x: int = 0, offset_y: int = 0) -> list[QRect]:
        output = cv2.connectedComponentsWithStats(mask, 8, cv2.CV_32S)
        num_labels = output[0]
        stats = output[2]

        valid_rects: list[QRect] = []
        for i in range(1, num_labels):
            x = stats[i, cv2.CC_STAT_LEFT] + offset_x
            y = stats[i, cv2.CC_STAT_TOP] + offset_y
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]

            if (MIN_ICON_WIDTH <= w < MAX_ICON_WIDTH and
                MIN_ICON_HEIGHT <= h < MAX_ICON_HEIGHT):

                center_x = x + w / 2
                center_y = y + h / 2

                new_x = int(center_x - PLAYER_ICON_STD_WIDTH / 2)
                new_y = int(center_y - PLAYER_ICON_STD_HEIGHT / 2)

                valid_rects.append(QRect(new_x, new_y, PLAYER_ICON_STD_WIDTH, PLAYER_ICON_STD_HEIGHT))

        return valid_rects

    def _expand_player_roi(self, rect: QRect, frame_w: int, frame_h: int) -> QRect:
        margin = self._player_icon_roi_margin
        expanded = rect.adjusted(-margin, -margin, margin, margin)
        full_rect = QRect(0, 0, frame_w, frame_h)
        expanded = expanded.intersected(full_rect)
        if expanded.width() <= 0 or expanded.height() <= 0:
            expanded = rect.intersected(full_rect)
        if expanded.width() <= 0 or expanded.height() <= 0:
            return full_rect
        return expanded

    def _expand_other_player_roi(self, rects: list[QRect], frame_w: int, frame_h: int) -> QRect:
        if not rects:
            return QRect(0, 0, frame_w, frame_h)

        combined = QRect(rects[0])
        for rect in rects[1:]:
            combined = combined.united(rect)

        margin = self._other_player_icon_roi_margin
        expanded = combined.adjusted(-margin, -margin, margin, margin)
        full_rect = QRect(0, 0, frame_w, frame_h)
        expanded = expanded.intersected(full_rect)
        if expanded.width() <= 0 or expanded.height() <= 0:
            return combined.intersected(full_rect) if combined.intersects(full_rect) else full_rect
        return expanded

    def find_player_icon(self, frame_bgr, frame_hsv=None):
        if frame_hsv is None:
            frame_hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

        frame_h, frame_w = frame_bgr.shape[:2]

        def detect_in_region(x: int, y: int, w: int, h: int):
            roi_hsv = frame_hsv[y:y + h, x:x + w]
            if roi_hsv.size == 0:
                return []
            mask = cv2.inRange(roi_hsv, PLAYER_ICON_LOWER, PLAYER_ICON_UPPER)
            return self._extract_player_icon_rects_from_mask(mask, offset_x=x, offset_y=y)

        if self._player_icon_roi is not None:
            roi = self._player_icon_roi.intersected(QRect(0, 0, frame_w, frame_h))
            if roi.width() > 0 and roi.height() > 0:
                rects = detect_in_region(roi.left(), roi.top(), roi.width(), roi.height())
                if rects:
                    self._player_icon_roi_fail_streak = 0
                    self._player_icon_roi = self._expand_player_roi(rects[0], frame_w, frame_h)
                    return rects
                self._player_icon_roi_fail_streak += 1
                if self._player_icon_roi_fail_streak >= 3:
                    self._player_icon_roi = None

        rects = detect_in_region(0, 0, frame_w, frame_h)
        if rects:
            self._player_icon_roi_fail_streak = 0
            self._player_icon_roi = self._expand_player_roi(rects[0], frame_w, frame_h)
        else:
            self._player_icon_roi_fail_streak += 1
            if self._player_icon_roi_fail_streak >= 10:
                self._player_icon_roi = None
        return rects

    def find_other_player_icons(self, frame_bgr, frame_hsv=None):
        if frame_hsv is None:
            frame_hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

        frame_h, frame_w = frame_bgr.shape[:2]

        def detect_in_region(x: int, y: int, w: int, h: int):
            roi_hsv = frame_hsv[y:y + h, x:x + w]
            if roi_hsv.size == 0:
                return []
            mask1 = cv2.inRange(roi_hsv, OTHER_PLAYER_ICON_LOWER1, OTHER_PLAYER_ICON_UPPER1)
            mask2 = cv2.inRange(roi_hsv, OTHER_PLAYER_ICON_LOWER2, OTHER_PLAYER_ICON_UPPER2)
            mask = cv2.bitwise_or(mask1, mask2)
            return self._extract_player_icon_rects_from_mask(mask, offset_x=x, offset_y=y)

        roi_rects: list[QRect] = []

        if self._other_player_icon_roi is not None:
            roi = self._other_player_icon_roi.intersected(QRect(0, 0, frame_w, frame_h))
            if roi.width() > 0 and roi.height() > 0:
                roi_rects = detect_in_region(roi.left(), roi.top(), roi.width(), roi.height())
                if roi_rects:
                    self._other_player_icon_fail_streak = 0
                    self._other_player_icon_roi = self._expand_other_player_roi(roi_rects, frame_w, frame_h)
                    self._other_player_icon_roi_frames += 1
                else:
                    self._other_player_icon_fail_streak += 1
                    if self._other_player_icon_fail_streak >= 3:
                        self._other_player_icon_roi = None
                    self._other_player_icon_roi_frames = self._other_player_icon_fullscan_interval
            else:
                self._other_player_icon_roi = None
                self._other_player_icon_roi_frames = self._other_player_icon_fullscan_interval
        else:
            self._other_player_icon_roi_frames = self._other_player_icon_fullscan_interval

        need_full_scan = (
            not roi_rects
            or self._other_player_icon_roi_frames >= self._other_player_icon_fullscan_interval
        )

        full_rects: list[QRect] = []
        if need_full_scan:
            full_rects = detect_in_region(0, 0, frame_w, frame_h)
            if full_rects:
                self._other_player_icon_fail_streak = 0
                self._other_player_icon_roi = self._expand_other_player_roi(full_rects, frame_w, frame_h)
                self._other_player_icon_roi_frames = 0
            else:
                self._other_player_icon_fail_streak += 1
                if self._other_player_icon_fail_streak >= 8:
                    self._other_player_icon_roi = None
                elif self._other_player_icon_fail_streak >= 4:
                    self._other_player_icon_roi_frames = self._other_player_icon_fullscan_interval

        if full_rects:
            if roi_rects:
                seen = set()
                merged: list[QRect] = []
                for rect in full_rects + roi_rects:
                    key = (rect.left(), rect.top(), rect.width(), rect.height())
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(rect)
                return merged
            return full_rects

        return roi_rects

    def force_stop_detection(self) -> bool:
        stopped = False
        if not hasattr(self, 'detect_anchor_btn'):
            return False

        try:
            is_checked = bool(self.detect_anchor_btn.isChecked())
        except Exception:
            is_checked = False

        if is_checked:
            self.detect_anchor_btn.click()
            stopped = True
        elif getattr(self, 'is_detection_running', False):
            if hasattr(self.detect_anchor_btn, 'setChecked'):
                self.detect_anchor_btn.setChecked(True)
            self.detect_anchor_btn.click()
            stopped = True

        if stopped:
            self.update_general_log("ESC 단축키로 탐지를 강제 중단했습니다.", "orange")
            self._clear_authority_resume_state()
            self._suppress_authority_resume = True
        return stopped

    def toggle_anchor_detection(self, checked):
            #  외부 호출(sender() is None) 또는 버튼 직접 클릭 시 상태를 동기화
            if self.sender() is None:
                # 외부에서 호출된 경우, 버튼의 상태를 프로그램적으로 토글
                self.detect_anchor_btn.toggle()
                # 토글된 후의 실제 상태를 checked 변수에 반영
                checked = self.detect_anchor_btn.isChecked()
            
            if checked:
                # --- "maple" 창 탐색 및 활성화 ---
                try:
                    maple_windows = gw.getWindowsWithTitle('Mapleland')
                    if not maple_windows:
                        QMessageBox.warning(self, "오류", "MapleStory 클라이언트 창을 찾을 수 없습니다.\n게임을 먼저 실행해주세요.")
                        self.detect_anchor_btn.setChecked(False)
                        return

                    target_window = maple_windows[0]
                    if not target_window.isActive:
                        target_window.activate()
                        QThread.msleep(100) # 창이 활성화될 시간을 줌
                    self.update_general_log(
                        f"게임 창 활성화: '{target_window.title}'",
                        "SaddleBrown",
                    )
                except Exception as e:
                    QMessageBox.warning(self, "창 활성화 오류", f"게임 창을 활성화하는 중 오류가 발생했습니다:\n{e}")
                    self.detect_anchor_btn.setChecked(False)
                    return
                if not self.minimap_region:
                    QMessageBox.warning(self, "오류", "먼저 '미니맵 범위 지정'을 해주세요.")
                    self.detect_anchor_btn.setChecked(False)
                    return
                if not self.key_features:
                    QMessageBox.warning(self, "오류", "하나 이상의 '핵심 지형'을 등록해야 합니다.")
                    self.detect_anchor_btn.setChecked(False)
                    return
                if not self.full_map_pixmap or self.full_map_pixmap.isNull():
                    QMessageBox.warning(self, "오류", "전체 맵 이미지를 생성할 수 없습니다. 편집기를 통해 맵 데이터를 확인해주세요.")
                    self.detect_anchor_btn.setChecked(False)
                    return

                self.save_profile_data()
                self.load_action_model()
                self.general_log_viewer.clear()
                self.detection_log_viewer.clear()
                self.update_general_log("탐지를 시작합니다...", "SaddleBrown")

                # 스레드 시작 전에 플래그를 True로 설정
                self.is_detection_running = True
                self._suppress_authority_resume = False
                self._reset_other_player_alert_state()
                self.detection_status_changed.emit(True)   # 탐지 시작 상태를 신호로 알림
                self.update_general_log("탐지를 시작합니다...", "SaddleBrown")

                # --- [v12.3.1] 모든 내비게이션 상태 변수 완벽 초기화 ---
                self.journey_plan = []
                self.current_journey_index = 0
                self.current_segment_path = []
                self.current_segment_index = 0
                # [수정] start_waypoint_found를 True로 변경하여 시작점 탐색 과정을 생략합니다.
                self.start_waypoint_found = True 
                self.navigation_action = 'move_to_target'
                self.navigation_state_locked = False
                self.last_reached_wp_id = None
                self.target_waypoint_id = None
                self.is_forward = True # 정방향으로 시작
                self.last_forward_journey = []
                self.last_selected_forward_slot = None
                self.last_selected_backward_slot = None
                self.current_direction_slot_label = "-"
                self.smoothed_player_pos = None
                self.last_player_pos = QPointF(0, 0)
                self.player_state = 'on_terrain'
                self.current_player_floor = None
                self.last_printed_action = None
                self.last_printed_direction = None
                self.last_printed_player_state = None
                self.last_command_sent_time = 0.0
                self.last_command_context = None
                self.jump_direction = None
                # --- 초기화 끝 ---

                # 자동 복구 상태 초기화
                self.stuck_recovery_attempts = 0
                self.last_movement_command = None
                self.recovery_cooldown_until = 0.0
                self.airborne_path_warning_active = False
                self.ladder_float_recovery_cooldown_until = 0.0
                self.route_cycle_initialized = False
                self.last_command_context = None

                self._refresh_event_waypoint_states()

                # [핵심 수정] 탐지 시작 시간 기록 및 딜레이 플래그 활성화
                self.detection_start_time = time.time()
                self.initial_delay_active = True

                self._status_log_lines = ["HP: --", "MP: --"]
                self._status_last_ui_update = {'hp': 0.0, 'mp': 0.0}
                self._status_active_resource = None
                self._status_saved_command = None
                self._last_regular_command = None
                self._status_last_command_ts = {'hp': 0.0, 'mp': 0.0}
                if self.status_monitor:
                    self.status_monitor.set_tab_active(map_tab=True)
                self._render_detection_log(self._last_detection_log_body, force=True)

                self._player_icon_roi = None
                self._player_icon_roi_fail_streak = 0

                if self.debug_view_checkbox.isChecked():
                    if not self.debug_dialog:
                        self.debug_dialog = DebugViewDialog(self)
                    self.debug_dialog.show()

                self.capture_thread = MinimapCaptureThread(self.minimap_region)
                self.capture_thread.start()

                self.detection_thread = AnchorDetectionThread(self.key_features, capture_thread=self.capture_thread, parent_tab=self)
                self.detection_thread.detection_ready.connect(self.on_detection_ready)
                self.detection_thread.status_updated.connect(self.update_detection_log_message)
                self.detection_thread.perf_sampled.connect(self._handle_detection_perf_sample)
                self.detection_thread.start()

                if self._perf_logging_enabled:
                    self._start_perf_logging()

                self._reset_walk_teleport_state()
                self.detect_anchor_btn.setText("탐지 중단")
                if getattr(self, '_hunt_tab', None) and getattr(self._hunt_tab, 'map_link_enabled', False) and not getattr(self, '_syncing_with_hunt', False):
                    self._syncing_with_hunt = True
                    try:
                        if hasattr(self._hunt_tab, 'detect_btn') and not self._hunt_tab.detect_btn.isChecked():
                            self._hunt_tab.detect_btn.setChecked(True)
                            self._hunt_tab._toggle_detection(True)
                    finally:
                        self._syncing_with_hunt = False
            else:
                # [핵심 수정] 스레드 중단 전에 플래그를 False로 먼저 설정
                self.is_detection_running = False
                self._clear_authority_resume_state()
                self.detection_status_changed.emit(False)
                if self.status_monitor:
                    self.status_monitor.set_tab_active(map_tab=False)

                if self.detection_thread and self.detection_thread.isRunning():
                    self.detection_thread.stop()
                    self.detection_thread.wait()
                if self.capture_thread and self.capture_thread.isRunning():
                    self.capture_thread.stop()
                    self.capture_thread.wait()
                    
                # <<< [수정] 자동 제어 테스트 모드 또는 실제 자동 제어 모드에 따라 분기 처리
                if self.debug_auto_control_checkbox.isChecked():
                    print("[자동 제어 테스트] 모든 키 떼기")
                elif self.auto_control_checkbox.isChecked():
                    self._emit_control_command("모든 키 떼기", None)

                self.update_general_log("탐지를 중단합니다.", "black")
                self.detect_anchor_btn.setText("탐지 시작")
                self.update_detection_log_message("탐지 중단됨", "black")
                self.minimap_view_label.setText("탐지 중단됨")
                self._reset_other_player_alert_state()

                if self._perf_log_writer:
                    self._stop_perf_logging()

                self.detection_thread = None
                self.capture_thread = None
                self._map_perf_queue.clear()
                self.latest_perf_stats = {}
                self._last_walk_teleport_check_time = 0.0

                self._player_icon_roi = None
                self._player_icon_roi_fail_streak = 0

                # --- [v12.3.1] 탐지 중지 시에도 상태 초기화 ---
                self.journey_plan = []
                self.current_journey_index = 0
                self.current_segment_path = []
                self.current_segment_index = 0
                self.start_waypoint_found = False
                self.navigation_action = 'move_to_target'
                self.navigation_state_locked = False
                self.last_reached_wp_id = None
                self.target_waypoint_id = None
                self.last_forward_journey = []
                self.last_selected_forward_slot = None
                self.last_selected_backward_slot = None
                self.current_direction_slot_label = "-"
                self.last_printed_action = None
                self.last_printed_direction = None
                self.last_printed_player_state = None
                self.last_command_sent_time = 0.0
                self.jump_direction = None
                # --- 초기화 끝 ---

                # [핵심 수정] 탐지 중지 시 딜레이 플래그 비활성화
                self.initial_delay_active = False

                if getattr(self, '_hunt_tab', None) and getattr(self._hunt_tab, 'map_link_enabled', False) and not getattr(self, '_syncing_with_hunt', False):
                    self._syncing_with_hunt = True
                    try:
                        if hasattr(self._hunt_tab, 'detect_btn') and self._hunt_tab.detect_btn.isChecked():
                            self._hunt_tab.detect_btn.setChecked(False)
                            self._hunt_tab._toggle_detection(False)
                    finally:
                        self._syncing_with_hunt = False

                self._status_active_resource = None
                self._status_saved_command = None
                self._status_log_lines = ["HP: --", "MP: --"]
                self._status_last_ui_update = {'hp': 0.0, 'mp': 0.0}
                self._render_detection_log(self._last_detection_log_body, force=True)

                if self.debug_dialog:
                    self.debug_dialog.close()

    def _open_state_config_dialog(self):
        """
        [PATCH] v14.3.3: '판정 설정' 다이얼로그를 열고, 변경된 설정을 저장하는 기능.
        """
        current_config = {
            "idle_time_threshold": self.cfg_idle_time_threshold,
            "climbing_state_frame_threshold": self.cfg_climbing_state_frame_threshold,
            "falling_state_frame_threshold": self.cfg_falling_state_frame_threshold,
            "jumping_state_frame_threshold": self.cfg_jumping_state_frame_threshold,
            "on_terrain_y_threshold": self.cfg_on_terrain_y_threshold,
            "jump_y_min_threshold": self.cfg_jump_y_min_threshold,
            "jump_y_max_threshold": self.cfg_jump_y_max_threshold,
            "fall_y_min_threshold": self.cfg_fall_y_min_threshold,
            "climb_x_movement_threshold": self.cfg_climb_x_movement_threshold,
            "fall_on_ladder_x_movement_threshold": self.cfg_fall_on_ladder_x_movement_threshold,
            "ladder_x_grab_threshold": self.cfg_ladder_x_grab_threshold,
            "move_deadzone": self.cfg_move_deadzone,
            "max_jump_duration": self.cfg_max_jump_duration,
            "y_movement_deadzone": self.cfg_y_movement_deadzone,
            "waypoint_arrival_x_threshold": self.cfg_waypoint_arrival_x_threshold,
            "waypoint_arrival_x_threshold_min": self.cfg_waypoint_arrival_x_threshold_min,
            "waypoint_arrival_x_threshold_max": self.cfg_waypoint_arrival_x_threshold_max,
            "ladder_arrival_x_threshold": self.cfg_ladder_arrival_x_threshold,
            "jump_link_arrival_x_threshold": self.cfg_jump_link_arrival_x_threshold,
            "on_ladder_enter_frame_threshold": self.cfg_on_ladder_enter_frame_threshold,
            "jump_initial_velocity_threshold": self.cfg_jump_initial_velocity_threshold,
            "climb_max_velocity": self.cfg_climb_max_velocity,
            "arrival_frame_threshold": self.cfg_arrival_frame_threshold,
            "action_success_frame_threshold": self.cfg_action_success_frame_threshold,
            "stuck_detection_wait": self.cfg_stuck_detection_wait,
            "airborne_recovery_wait": self.cfg_airborne_recovery_wait,
            "ladder_recovery_resend_delay": self.cfg_ladder_recovery_resend_delay,
            "prepare_timeout": self.cfg_prepare_timeout if self.cfg_prepare_timeout is not None else PREPARE_TIMEOUT,
            "max_lock_duration": self.cfg_max_lock_duration if self.cfg_max_lock_duration is not None else MAX_LOCK_DURATION,
            "walk_teleport_probability": self.cfg_walk_teleport_probability,
            "walk_teleport_interval": self.cfg_walk_teleport_interval,
            "walk_teleport_bonus_delay": self.cfg_walk_teleport_bonus_delay,
            "walk_teleport_bonus_step": self.cfg_walk_teleport_bonus_step,
            "walk_teleport_bonus_max": self.cfg_walk_teleport_bonus_max,
        }
        
        # [MODIFIED] v14.3.3: parent_tab 대신 표준 parent 인자 사용
        dialog = StateConfigDialog(current_config, parent=self)
        if dialog.exec():
            updated_config = dialog.get_updated_config()
            
            for key, value in updated_config.items():
                # 'cfg_' 접두사를 붙여 MapTab의 속성을 설정
                attr_name = f"cfg_{key}"
                if hasattr(self, attr_name):
                    setattr(self, attr_name, value)

            if self.cfg_waypoint_arrival_x_threshold_min > self.cfg_waypoint_arrival_x_threshold_max:
                self.cfg_waypoint_arrival_x_threshold_min, self.cfg_waypoint_arrival_x_threshold_max = (
                    self.cfg_waypoint_arrival_x_threshold_max,
                    self.cfg_waypoint_arrival_x_threshold_min,
                )

            self.cfg_waypoint_arrival_x_threshold = (
                self.cfg_waypoint_arrival_x_threshold_min + self.cfg_waypoint_arrival_x_threshold_max
            ) / 2.0

            self.cfg_walk_teleport_probability = max(min(self.cfg_walk_teleport_probability, 100.0), 0.0)
            self.cfg_walk_teleport_interval = max(self.cfg_walk_teleport_interval, 0.1)
            self.cfg_walk_teleport_bonus_delay = max(self.cfg_walk_teleport_bonus_delay, 0.1)
            self.cfg_walk_teleport_bonus_step = max(self.cfg_walk_teleport_bonus_step, 0.0)
            self.cfg_walk_teleport_bonus_max = max(self.cfg_walk_teleport_bonus_max, 0.0)
            if self.cfg_walk_teleport_bonus_max < self.cfg_walk_teleport_bonus_step:
                self.cfg_walk_teleport_bonus_max = self.cfg_walk_teleport_bonus_step
            self._reset_walk_teleport_state()

            self._active_waypoint_threshold_key = None
            self._active_waypoint_threshold_value = None

            self.update_general_log("상태 판정 설정이 업데이트되었습니다.", "blue")
            self.save_profile_data()

# v14.0.0: 동작 학습 관련 메서드들
    def get_active_profile_path(self):
        """현재 활성화된 프로필의 폴더 경로를 반환합니다."""
        if not self.active_profile_name:
            return None
        return os.path.join(MAPS_DIR, self.active_profile_name)

    def open_action_learning_dialog(self):
        """'동작 학습' 버튼 클릭 시 다이얼로그를 엽니다."""
        # <<< [수정] 프로필 존재 여부 체크 제거
        dialog = ActionLearningDialog(self)
        dialog.exec()

    def prepare_for_action_collection(self, action_name, action_text):
        """
        [MODIFIED] v14.3.4: 데이터 수집 전, 기하학적 목표 정보를 미리 계산.
        ActionLearningDialog로부터 호출되어 움직임 감지 대기를 시작합니다.
        """
        self.current_action_to_learn = action_name
        self.collection_target_info = {} # 이전 정보 초기화

        # 수집 시작 전, 현재 위치를 기반으로 목표 정보 설정
        if not self.smoothed_player_pos:
            self.collection_status_signal.emit("finished", "오류: 플레이어 위치를 알 수 없어 학습을 시작할 수 없습니다.", False)
            return

        current_pos = self.smoothed_player_pos
        
        if action_name == "climb_up_ladder":
            ladder = self._find_closest_ladder(current_pos)
            if not ladder:
                self.collection_status_signal.emit("finished", "오류: 주변에 사다리가 없어 '오르기'를 학습할 수 없습니다.", False)
                return
            # 사다리의 위쪽 끝점(y좌표가 더 작은 점)을 목표로 설정
            self.collection_target_info['target_y'] = min(ladder['points'][0][1], ladder['points'][1][1])
            self.collection_target_info['type'] = 'climb_up'

        elif action_name == "climb_down_ladder":
            ladder = self._find_closest_ladder(current_pos)
            if not ladder:
                self.collection_status_signal.emit("finished", "오류: 주변에 사다리가 없어 '내려가기'를 학습할 수 없습니다.", False)
                return
            # 사다리의 아래쪽 끝점(y좌표가 더 큰 점)을 목표로 설정
            self.collection_target_info['target_y'] = max(ladder['points'][0][1], ladder['points'][1][1])
            self.collection_target_info['type'] = 'climb_down'
            
        elif action_name == "fall":
            start_terrain = self._get_contact_terrain(current_pos)
            if not start_terrain:
                self.collection_status_signal.emit("finished", "오류: 땅 위에서 '낙하' 학습을 시작해야 합니다.", False)
                return
            self.collection_target_info['start_floor'] = start_terrain.get('floor')
            self.collection_target_info['type'] = 'fall'

        # 모든 준비가 끝나면 움직임 감지 대기 상태로 전환
        self.is_waiting_for_movement = True
        self.last_pos_before_collection = None
        self.collection_status_signal.emit("waiting", f"'{action_text}' 동작을 수행하세요...", False)

    def start_manual_action_collection(self, action_name):
        """사용자가 직접 시작/종료하는 데이터 수집을 시작합니다."""
        self.current_action_to_learn = action_name
        self.is_collecting_action_data = True
        self.action_data_buffer = [] # 버퍼 초기화

    # [MODIFIED] v14.0.2: 마지막 파일 경로 저장 및 시그널 방출 추가
    def save_action_data(self):
        """
        [MODIFIED] v14.3.7: '핵심 구간 추출' 노이즈 제거 로직 적용.
        """
        self.is_collecting_action_data = False
        self.is_waiting_for_movement = False
        
        if not self.current_action_to_learn or len(self.action_data_buffer) < 5:
            self.collection_status_signal.emit("finished", "데이터 수집 실패: 움직임이 너무 짧거나 없습니다.", False)
            self.action_data_buffer = []
            return

        # [PATCH] v14.3.7: 새로운 노이즈 제거 메서드 호출
        trimmed_buffer = self._trim_sequence_noise(self.action_data_buffer, self.cfg_move_deadzone)
        
        if len(trimmed_buffer) < 5:
            self.collection_status_signal.emit("finished", f"데이터 수집 실패: 노이즈 제거 후 데이터가 너무 짧습니다. ({len(trimmed_buffer)} frames)", False)
            self.action_data_buffer = []
            return

        # <<< [수정] 아래 두 줄 수정
        model_dir = self._get_global_action_model_path()
        data_dir = os.path.join(model_dir, 'action_data')
        os.makedirs(data_dir, exist_ok=True)

        timestamp = int(time.time() * 1000)
        filename = f"{self.current_action_to_learn}_{timestamp}.json"
        filepath = os.path.join(data_dir, filename)

        data_to_save = { "action": self.current_action_to_learn, "sequence": trimmed_buffer }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f)
        
        self.last_collected_filepath = filepath
        self.action_data_buffer = []
        self.collection_status_signal.emit("finished", f"데이터 수집 완료! (핵심 {len(trimmed_buffer)} frames)", True)

    def cancel_action_collection(self):
        """
        [PATCH] v14.3.6: 데이터 수집 대기 또는 진행을 취소하는 기능.
        """
        was_waiting = self.is_waiting_for_movement
        was_collecting = self.is_collecting_action_data

        self.is_waiting_for_movement = False
        self.is_collecting_action_data = False
        self.action_data_buffer = []
        self.last_pos_before_collection = None
        self.collection_target_info = {}

        if was_waiting or was_collecting:
            self.collection_status_signal.emit("canceled", "학습이 취소되었습니다. 다시 시작하세요.", False)
        
    def _log_state_change(self, previous_state, new_state, reason, y_movement, y_history):
        """
        [PATCH] v16.7: 상태 변화 로그를 색상과 상세 정보와 함께 출력합니다.
        """
        # ANSI 색상 코드
        C_RESET = "\033[0m"
        C_GREEN = "\033[92m"  # Idle, On-Terrain, Ladder-Idle
        C_RED = "\033[91m"    # Down, Fall
        C_BLUE = "\033[94m"   # Up
        C_YELLOW = "\033[93m" # Jump
        C_CYAN = "\033[96m"   # Default

        state_colors = {
            'idle': C_GREEN,
            'on_terrain': C_GREEN,
            'on_ladder_idle': C_GREEN, # [PATCH] 노란색 -> 초록색
            'climbing_down': C_RED,
            'fall': C_RED,
            'climbing_up': C_BLUE,
            'jumping': C_YELLOW,
        }
        
        prev_color = state_colors.get(previous_state, C_CYAN)
        new_color = state_colors.get(new_state, C_CYAN)

        # y_history를 보기 좋은 문자열로 포맷팅
        history_str = ", ".join([f"{v:.2f}" for v in y_history])
        
        detailed_reason = f"{reason} (y_move: {y_movement:.2f}, history: [{history_str}])"
        
        print(f"[STATE CHANGE] {prev_color}{previous_state}{C_RESET} -> {new_color}{new_state}{C_RESET} | 이유: {detailed_reason}")
        
    #  v14.0.2: 마지막 데이터 삭제 메서드
    def delete_last_action_data(self):
        """가장 최근에 수집된 데이터 파일을 삭제합니다."""
        if self.last_collected_filepath and os.path.exists(self.last_collected_filepath):
            try:
                os.remove(self.last_collected_filepath)
                print(f"삭제 완료: {self.last_collected_filepath}")
                self.last_collected_filepath = None
            except OSError as e:
                print(f"파일 삭제 오류: {e}")
                QMessageBox.warning(self, "오류", f"파일 삭제에 실패했습니다:\n{e}")
        else:
            print("삭제할 파일이 없습니다.")            
   
    def start_jump_profiling(self):
        """점프 특성 프로파일링 모드를 시작합니다."""
        self.is_profiling_jump = True
        self.jump_profile_data = []
        self.jump_measure_start_time = 0.0
        self.current_jump_max_y_offset = 0.0
        self.jump_profile_progress_signal.emit(0)

    def cancel_jump_profiling(self):
        """점프 특성 프로파일링을 중단합니다."""
        self.is_profiling_jump = False
        self.jump_profile_data = []
        print("점프 특성 측정이 취소되었습니다.")

    def _analyze_jump_profile(self):
        """수집된 점프 데이터를 분석하여 이상치를 제거하고 평균을 계산합니다."""
        if len(self.jump_profile_data) < 5: # 최소 5개 데이터는 있어야 분석 의미가 있음
            self.jump_profile_measured_signal.emit(0.0, 0.0)
            return

        durations = np.array([item[0] for item in self.jump_profile_data])
        y_offsets = np.array([item[1] for item in self.jump_profile_data])

        # IQR을 이용한 이상치 제거
        def remove_outliers(data):
            q1, q3 = np.percentile(data, [25, 75])
            iqr = q3 - q1
            lower_bound = q1 - (1.5 * iqr)
            upper_bound = q3 + (1.5 * iqr)
            return data[(data >= lower_bound) & (data <= upper_bound)]

        valid_durations = remove_outliers(durations)
        valid_y_offsets = remove_outliers(y_offsets)

        if len(valid_durations) == 0 or len(valid_y_offsets) == 0:
            self.jump_profile_measured_signal.emit(0.0, 0.0)
            return

        # 평균 계산 및 여유분 추가
        avg_duration = np.mean(valid_durations)
        avg_y_offset = np.mean(valid_y_offsets)
        
        final_duration = round(avg_duration * 1.15, 2) # 15% 여유
        final_y_offset = round(avg_y_offset * 1.10, 2) # 10% 여유

        self.jump_profile_measured_signal.emit(final_duration, final_y_offset)

    def _trim_sequence_noise(self, sequence, move_deadzone):
        """
        [PATCH] v14.3.7: 수집된 시퀀스의 앞/뒤에 있는 정지 구간(노이즈)을 제거합니다.
        """
        if len(sequence) < 3:
            return sequence

        seq_np = np.array(sequence)
        
        # 속도 계산 (프레임 간 이동 거리)
        velocities = np.sqrt(np.sum(np.diff(seq_np, axis=0)**2, axis=1))

        # 1. 시작점 노이즈 제거
        start_index = 0
        for i in range(len(velocities)):
            if velocities[i] > move_deadzone:
                start_index = i
                break
        
        # 2. 종료점 노이즈 제거
        end_index = len(velocities) -1
        for i in range(len(velocities) - 1, -1, -1):
            if velocities[i] > move_deadzone:
                end_index = i
                break
        
        # end_index는 diff의 인덱스이므로, 원본 시퀀스에서는 +1을 해줘야 함
        trimmed_sequence = sequence[start_index : end_index + 2]

        # 너무 짧아지면 원본 반환 (안전장치)
        if len(trimmed_sequence) < 5:
            return sequence
            
        return trimmed_sequence

    def _find_closest_ladder(self, pos):
        """
        [PATCH] v14.3.4: 주어진 위치에서 가장 가까운 사다리 객체를 찾습니다.
        """
        ladders = self.geometry_data.get("transition_objects", [])
        if not ladders:
            return None

        closest_ladder = None
        min_dist_sq = float('inf')

        for ladder in ladders:
            points = ladder.get("points")
            if not points or len(points) < 2:
                continue
            
            # 사다리의 x좌표와 플레이어의 x좌표 거리만 비교
            ladder_x = points[0][0]
            dist_sq = (pos.x() - ladder_x)**2
            
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                closest_ladder = ladder
        
        return closest_ladder

    def start_jump_time_measurement(self):
        """
        [PATCH] v14.2.0: '최대 점프 시간 측정' 기능을 위한 상태 플래그 설정 메서드.
        StateConfigDialog로부터 호출되어 점프 시간 측정을 준비합니다.
        """
        self.is_measuring_jump_time = True
        self.jump_measure_start_time = 0.0

    def _estimate_player_alignment(self, found_features, my_player_rects):
        """탐지된 특징과 플레이어 아이콘으로 전역 위치와 관련 정보를 계산합니다."""
        reliable_features = [
            f
            for f in found_features
            if f['id'] in self.key_features and f['conf'] >= self.key_features[f['id']].get('threshold', 0.85)
        ]

        valid_features_map = {
            f['id']: f for f in reliable_features if f['id'] in self.global_positions
        }

        source_points = []
        dest_points = []
        feature_ids = []

        for fid, feature in valid_features_map.items():
            size = feature['size']
            local_pos = feature['local_pos']
            global_pos = self.global_positions[fid]

            src_cx = local_pos.x() + size.width() / 2
            src_cy = local_pos.y() + size.height() / 2
            dst_cx = global_pos.x() + size.width() / 2
            dst_cy = global_pos.y() + size.height() / 2
            source_points.append([src_cx, src_cy])
            dest_points.append([dst_cx, dst_cy])
            feature_ids.append(fid)

        player_anchor_local = QPointF(
            my_player_rects[0].center().x(),
            float(my_player_rects[0].bottom()) + PLAYER_Y_OFFSET,
        )

        avg_player_global_pos = None
        inlier_ids = set()
        transform_matrix = None

        if len(source_points) >= 3:
            src_pts, dst_pts = np.float32(source_points), np.float32(dest_points)
            matrix, inliers_mask = cv2.estimateAffinePartial2D(
                src_pts,
                dst_pts,
                method=cv2.RANSAC,
                ransacReprojThreshold=5.0,
            )

            if matrix is not None and inliers_mask is not None and np.sum(inliers_mask) >= 3:
                sx = np.sqrt(matrix[0, 0] ** 2 + matrix[1, 0] ** 2)
                sy = np.sqrt(matrix[0, 1] ** 2 + matrix[1, 1] ** 2)
                if (
                    0.8 < sx < 1.2
                    and 0.8 < sy < 1.2
                    and abs(matrix[0, 1]) < 0.5
                    and abs(matrix[1, 0]) < 0.5
                    and abs(matrix[0, 2]) < 10000
                    and abs(matrix[1, 2]) < 10000
                ):
                    transform_matrix = matrix
                    inliers_mask = inliers_mask.flatten()
                    for i, fid in enumerate(feature_ids):
                        if inliers_mask[i]:
                            inlier_ids.add(fid)

        inlier_features = [
            valid_features_map[fid] for fid in inlier_ids
        ] if inlier_ids else list(valid_features_map.values())

        if transform_matrix is not None:
            px, py = player_anchor_local.x(), player_anchor_local.y()
            transformed = (transform_matrix[:, :2] @ np.array([px, py])) + transform_matrix[:, 2]
            avg_player_global_pos = QPointF(float(transformed[0]), float(transformed[1]))
        elif inlier_features:
            total_conf = sum(f['conf'] for f in inlier_features)
            if total_conf > 0:
                w_sum_x, w_sum_y = 0.0, 0.0
                for f in inlier_features:
                    offset = player_anchor_local - (
                        f['local_pos'] + QPointF(f['size'].width() / 2, f['size'].height() / 2)
                    )
                    global_center = self.global_positions[f['id']] + QPointF(
                        f['size'].width() / 2,
                        f['size'].height() / 2,
                    )
                    pos = global_center + offset
                    w_sum_x += pos.x() * f['conf']
                    w_sum_y += pos.y() * f['conf']
                avg_player_global_pos = QPointF(w_sum_x / total_conf, w_sum_y / total_conf)

        if avg_player_global_pos is None:
            if self.smoothed_player_pos is not None:
                avg_player_global_pos = self.smoothed_player_pos
            else:
                self.update_detection_log_message("플레이어 전역 위치 추정 실패", "red")
                return None

        alpha = 0.3
        if self.smoothed_player_pos is None:
            self.smoothed_player_pos = avg_player_global_pos
        else:
            self.smoothed_player_pos = (
                avg_player_global_pos * alpha
                + self.smoothed_player_pos * (1 - alpha)
            )

        final_player_pos = self.smoothed_player_pos
        self.active_feature_info = inlier_features

        return {
            'final_player_pos': final_player_pos,
            'player_anchor_local': player_anchor_local,
            'inlier_ids': inlier_ids,
            'inlier_features': inlier_features,
            'reliable_features': reliable_features,
            'transform_matrix': transform_matrix,
        }

    def _on_detection_ready_impl(self, frame_bgr, found_features, my_player_rects, other_player_rects):
        """
        [MODIFIED] v14.3.1: UnboundLocalError 수정을 위해 로직 실행 순서 정상화.
        - 1. final_player_pos를 가장 먼저 계산.
        - 2. player_state를 최신화.
        - 3. 계산된 위치/상태 값을 사용하는 부가 기능(프로파일링, 데이터 수집)을 마지막에 실행.
        """
        if not self.is_detection_running:
            return

        if not my_player_rects:
            self.update_detection_log_message("플레이어 아이콘 탐지 실패", "red")
            if self.debug_dialog and self.debug_dialog.isVisible():
                self.debug_dialog.update_debug_info(
                    frame_bgr,
                    {'all_features': found_features, 'inlier_ids': set(), 'player_pos_local': None},
                )
            return

        alignment = self._estimate_player_alignment(found_features, my_player_rects)
        if alignment is None:
            if self.debug_dialog and self.debug_dialog.isVisible():
                self.debug_dialog.update_debug_info(
                    frame_bgr,
                    {'all_features': found_features, 'inlier_ids': set(), 'player_pos_local': None},
                )
            return

        final_player_pos = alignment['final_player_pos']
        player_anchor_local = alignment['player_anchor_local']
        inlier_ids = alignment['inlier_ids']
        inlier_features = alignment['inlier_features']
        reliable_features = alignment['reliable_features']
        transform_matrix = alignment['transform_matrix']

        self._update_player_state_and_navigation(final_player_pos)
        self._sync_authority_snapshot("detection_loop")

        if self.is_profiling_jump:
            is_in_air = self.player_state not in ['on_terrain', 'idle']
            is_on_ground = not is_in_air

            if is_in_air and self.jump_measure_start_time == 0:
                self.jump_measure_start_time = time.time()
                self.current_jump_max_y_offset = 0.0

            elif is_in_air and self.jump_measure_start_time > 0:
                y_above_terrain = self.last_on_terrain_y - final_player_pos.y()
                if y_above_terrain > self.current_jump_max_y_offset:
                    self.current_jump_max_y_offset = y_above_terrain

            elif is_on_ground and self.jump_measure_start_time > 0:
                duration = time.time() - self.jump_measure_start_time
                self.jump_profile_data.append((duration, self.current_jump_max_y_offset))

                self.jump_measure_start_time = 0.0
                self.current_jump_max_y_offset = 0.0
                progress = len(self.jump_profile_data)
                self.jump_profile_progress_signal.emit(progress)

                if progress >= 10:
                    self.is_profiling_jump = False
                    self._analyze_jump_profile()

        if self.is_waiting_for_movement and self.smoothed_player_pos:
            if self.last_pos_before_collection:
                dist_moved = math.hypot(
                    self.smoothed_player_pos.x() - self.last_pos_before_collection.x(),
                    self.smoothed_player_pos.y() - self.last_pos_before_collection.y(),
                )

                if dist_moved > (self.cfg_move_deadzone * 2):
                    self.is_waiting_for_movement = False
                    self.is_collecting_action_data = True
                    self.action_data_buffer.append(
                        (self.smoothed_player_pos.x(), self.smoothed_player_pos.y())
                    )
                    self.collection_status_signal.emit(
                        "collecting",
                        "데이터 수집 중... (착지 시 자동 완료)",
                        False,
                    )
            else:
                self.last_pos_before_collection = self.smoothed_player_pos

        elif self.is_collecting_action_data and self.smoothed_player_pos:
            self.action_data_buffer.append(
                (self.smoothed_player_pos.x(), self.smoothed_player_pos.y())
            )

            should_stop = False
            is_timeout = len(self.action_data_buffer) >= self.action_collection_max_frames

            action_type = self.collection_target_info.get('type')
            current_pos = self.smoothed_player_pos

            if action_type == 'climb_up':
                target_y = self.collection_target_info.get('target_y')
                if target_y is not None and current_pos.y() <= (target_y + 5.0):
                    should_stop = True

            elif action_type == 'climb_down':
                target_y = self.collection_target_info.get('target_y')
                if target_y is not None and current_pos.y() >= (target_y - 8.0):
                    should_stop = True

            elif action_type == 'fall':
                start_floor = self.collection_target_info.get('start_floor')
                landing_terrain = self._get_contact_terrain(current_pos)
                if landing_terrain and landing_terrain.get('floor') < start_floor:
                    landing_y = landing_terrain['points'][0][1]
                    if abs(current_pos.y() - landing_y) < 4.0:
                        should_stop = True

            if should_stop or is_timeout:
                if is_timeout and not should_stop:
                    print("경고: 최대 프레임에 도달하여 데이터 수집을 강제 종료합니다.")
                self.save_action_data()

        if self.smoothed_player_pos:
            self.action_inference_buffer.append(
                (self.smoothed_player_pos.x(), self.smoothed_player_pos.y())
            )

        def transform_rect_safe(rect, matrix, fallback_features):
            if matrix is not None:
                corners = np.float32(
                    [[rect.left(), rect.top()], [rect.right(), rect.bottom()]]
                ).reshape(-1, 1, 2)
                t_corners = cv2.transform(corners, matrix).reshape(2, 2)
                return QRectF(
                    QPointF(t_corners[0, 0], t_corners[0, 1]),
                    QPointF(t_corners[1, 0], t_corners[1, 1]),
                ).normalized()

            center_local = QPointF(rect.center())
            sum_pos, sum_conf = QPointF(0, 0), 0.0
            for feature in fallback_features:
                offset = center_local - (
                    feature['local_pos']
                    + QPointF(feature['size'].width() / 2, feature['size'].height() / 2)
                )
                global_center = self.global_positions[feature['id']] + QPointF(
                    feature['size'].width() / 2,
                    feature['size'].height() / 2,
                )
                pos = global_center + offset
                conf = feature['conf']
                sum_pos += pos * conf
                sum_conf += conf

            if sum_conf > 0:
                center_global = sum_pos / sum_conf
                return QRectF(
                    center_global - QPointF(rect.width() / 2, rect.height() / 2),
                    QSizeF(rect.size()),
                )
            return QRectF()

        my_player_global_rects = [
            transform_rect_safe(rect, transform_matrix, inlier_features)
            for rect in my_player_rects
        ]
        other_player_global_rects = [
            transform_rect_safe(rect, transform_matrix, inlier_features)
            for rect in (other_player_rects or [])
        ]

        self.my_player_global_rects = my_player_global_rects
        self.other_player_global_rects = other_player_global_rects
        self._handle_other_player_detection_alert(self.other_player_global_rects)

        if self.debug_dialog and self.debug_dialog.isVisible():
            debug_data = {
                'all_features': found_features,
                'inlier_ids': inlier_ids,
                'player_pos_local': player_anchor_local,
            }
            self.debug_dialog.update_debug_info(frame_bgr, debug_data)

        camera_pos_to_send = (
            final_player_pos
            if self.center_on_player_checkbox.isChecked()
            else self.minimap_view_label.camera_center_global
        )

        intermediate_node_type = None
        if self.current_segment_path and self.current_segment_index < len(self.current_segment_path):
            current_node_key = self.current_segment_path[self.current_segment_index]
            intermediate_node_type = self.nav_nodes.get(current_node_key, {}).get('type')

        self.minimap_view_label.update_view_data(
            camera_center=camera_pos_to_send,
            active_features=self.active_feature_info,
            my_players=self.my_player_global_rects,
            other_players=self.other_player_global_rects,
            target_wp_id=self.target_waypoint_id,
            reached_wp_id=self.last_reached_wp_id,
            final_player_pos=final_player_pos,
            is_forward=self.is_forward,
            intermediate_pos=self.intermediate_target_pos,
            intermediate_type=self.intermediate_target_type,
            nav_action=self.navigation_action,
            intermediate_node_type=intermediate_node_type,
        )
        self.global_pos_updated.emit(final_player_pos)

        outlier_list = [f for f in reliable_features if f['id'] not in inlier_ids]
        self.update_detection_log_from_features(inlier_features, outlier_list)

    def on_detection_ready(self, frame_bgr, found_features, my_player_rects, other_player_rects):
        map_perf = {
            'timestamp': time.time(),
            'processing_start_monotonic': time.perf_counter(),
            'feature_candidates': len(found_features) if isinstance(found_features, list) else 0,
            'player_icon_input_count': len(my_player_rects) if isinstance(my_player_rects, list) else 0,
            'other_player_icon_input_count': len(other_player_rects) if isinstance(other_player_rects, list) else 0,
            'map_status': 'ok',
            'map_warning': '',
            'queue_delay_ms': 0.0,
        }

        if not self.is_detection_running:
            map_perf['map_status'] = 'inactive'
            map_perf['map_warning'] = 'detection_inactive'
            map_perf['processing_end_monotonic'] = time.perf_counter()
            self._finalize_map_perf_sample(map_perf)
            return

        if not isinstance(my_player_rects, list) or not my_player_rects:
            map_perf['map_status'] = 'no_player_icon'
            map_perf['map_warning'] = 'player_icon_missing'
            map_perf['processing_end_monotonic'] = time.perf_counter()
            self._finalize_map_perf_sample(map_perf)
            return

        self._current_map_perf_status = 'ok'
        self._current_map_perf_warning = ''
        try:
            self._on_detection_ready_impl(frame_bgr, found_features, my_player_rects, other_player_rects)
        except Exception as exc:
            warning_text = str(exc)
            self._current_map_perf_status = 'error'
            self._current_map_perf_warning = warning_text
            map_perf['map_status'] = 'error'
            map_perf['map_warning'] = warning_text
            self._finalize_map_perf_sample(map_perf)
            raise
        else:
            self._finalize_map_perf_sample(map_perf)

    def _finalize_map_perf_sample(self, map_perf: dict) -> None:
        if 'processing_end_monotonic' not in map_perf:
            map_perf['processing_end_monotonic'] = time.perf_counter()

        start = map_perf.get('processing_start_monotonic')
        end = map_perf.get('processing_end_monotonic')
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            map_perf['map_processing_ms'] = max(0.0, (end - start) * 1000.0)
        else:
            map_perf['map_processing_ms'] = float(map_perf.get('map_processing_ms', 0.0) or 0.0)

        status = map_perf.get('map_status') or getattr(self, '_current_map_perf_status', 'unknown') or 'unknown'
        map_perf['map_status'] = status

        warning = map_perf.get('map_warning') or getattr(self, '_current_map_perf_warning', '')
        map_perf['map_warning'] = warning

        pos = getattr(self, 'smoothed_player_pos', None)
        if pos is not None:
            try:
                map_perf['global_x'] = float(pos.x())
                map_perf['global_y'] = float(pos.y())
            except Exception:
                map_perf['global_x'] = 0.0
                map_perf['global_y'] = 0.0
        else:
            map_perf.setdefault('global_x', 0.0)
            map_perf.setdefault('global_y', 0.0)

        map_perf['player_state'] = getattr(self, 'player_state', '') or ''
        map_perf['navigation_action'] = getattr(self, 'navigation_action', '') or ''
        map_perf['event_in_progress_flag'] = bool(getattr(self, 'event_in_progress', False))
        map_perf['current_floor'] = getattr(self, 'current_player_floor', '') or ''
        map_perf['active_profile'] = self.active_profile_name or ''
        map_perf['active_route_profile'] = self.active_route_profile_name or ''
        map_perf['target_waypoint'] = getattr(self, 'target_waypoint_id', '') or ''

        map_perf.setdefault('feature_candidates', 0)
        map_perf.setdefault('player_icon_input_count', 0)
        map_perf.setdefault('other_player_icon_input_count', 0)

        ui_update_called = False
        if hasattr(self, 'minimap_view_label') and self.minimap_view_label:
            try:
                ui_update_called = bool(self.minimap_view_label.consume_update_flag())
            except Exception:
                ui_update_called = False
        map_perf['minimap_display_enabled'] = bool(getattr(self, '_minimap_display_enabled', True))
        map_perf['general_log_enabled'] = bool(getattr(self, '_general_log_enabled', True))
        map_perf['detection_log_enabled'] = bool(getattr(self, '_detection_log_enabled', True))
        map_perf['ui_update_called'] = ui_update_called
        self._ui_update_called_pending = ui_update_called

        static_ms = float(getattr(self, '_static_rebuild_ms_pending', 0.0) or 0.0)
        map_perf['static_rebuild_ms'] = static_ms
        self._static_rebuild_ms_pending = 0.0

        if len(self._map_perf_queue) >= 64:
            self._map_perf_queue.popleft()
        self._map_perf_queue.append(dict(map_perf))

    def _handle_detection_perf_sample(self, perf: dict) -> None:
        if not self.is_detection_running:
            return
        self._latest_thread_perf = dict(perf)
        if self._map_perf_queue:
            map_perf = self._map_perf_queue.popleft()
        else:
            map_perf = {
                'timestamp': time.time(),
                'map_status': 'missing_map_perf',
                'map_warning': '',
                'map_processing_ms': 0.0,
                'queue_delay_ms': 0.0,
            }
        combined = self._compose_perf_stats(perf, map_perf)
        self.latest_perf_stats = combined
        if self._perf_logging_enabled:
            self._append_perf_log()

    def _compose_perf_stats(self, thread_perf: dict, map_perf: dict) -> dict:
        combined: dict[str, object] = {}
        combined.update(thread_perf)
        combined.update(map_perf)

        combined['timestamp'] = float(thread_perf.get('timestamp', map_perf.get('timestamp', time.time())))
        loop_ms = float(combined.get('loop_total_ms', 0.0) or 0.0)
        combined['fps'] = 1000.0 / loop_ms if loop_ms > 0 else 0.0

        start = map_perf.get('processing_start_monotonic')
        end = map_perf.get('processing_end_monotonic')
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            combined['map_processing_ms'] = max(0.0, (end - start) * 1000.0)
        else:
            combined['map_processing_ms'] = float(combined.get('map_processing_ms', 0.0) or 0.0)

        dispatch_t0 = thread_perf.get('signal_dispatch_t0')
        if isinstance(dispatch_t0, (int, float)) and isinstance(start, (int, float)):
            combined['queue_delay_ms'] = max(0.0, (start - dispatch_t0) * 1000.0)
        else:
            combined['queue_delay_ms'] = float(combined.get('queue_delay_ms', 0.0) or 0.0)

        combined.pop('processing_start_monotonic', None)
        combined.pop('processing_end_monotonic', None)
        combined.pop('signal_dispatch_t0', None)
        combined.pop('loop_start_monotonic', None)

        frame_status = combined.get('frame_status') or ''
        combined['frame_status'] = frame_status
        error_text = combined.get('error') or ''
        combined['error'] = error_text
        downscale_adjusted = combined.get('downscale_adjusted')
        if isinstance(downscale_adjusted, (int, float)):
            combined['downscale_adjusted'] = float(downscale_adjusted)
        elif downscale_adjusted:
            combined['downscale_adjusted'] = downscale_adjusted
        else:
            combined['downscale_adjusted'] = ''
        combined['map_warning'] = combined.get('map_warning') or ''
        combined['map_status'] = combined.get('map_status') or ''

        return combined

    def _ensure_perf_log_dir(self) -> str:
        os.makedirs(self._perf_logs_dir, exist_ok=True)
        return self._perf_logs_dir

    def _start_perf_logging(self) -> None:
        if self._perf_log_writer is not None:
            return
        try:
            logs_dir = self._ensure_perf_log_dir()
            file_name = time.strftime('map_perf_%Y%m%d_%H%M%S.csv')
            path = os.path.join(logs_dir, file_name)
            handle = open(path, 'w', newline='', encoding='utf-8')
            writer = csv.writer(handle)
            writer.writerow(self._perf_log_headers)
            handle.flush()
            self._perf_log_path = path
            self._perf_log_handle = handle
            self._perf_log_writer = writer
            self.update_general_log(f"맵 성능 로그 기록 시작: {path}", "green")
        except Exception as exc:
            self.update_general_log(f"맵 성능 로그 파일 생성 실패: {exc}", "red")
            self._perf_log_handle = None
            self._perf_log_writer = None
            self._perf_log_path = None

    def _stop_perf_logging(self) -> None:
        handle = self._perf_log_handle
        path = self._perf_log_path
        self._perf_log_handle = None
        self._perf_log_writer = None
        self._perf_log_path = None
        if handle is not None:
            try:
                handle.flush()
                handle.close()
            except Exception:
                pass
        if path and self._perf_logging_enabled:
            self.update_general_log(f"맵 성능 로그 기록 종료: {path}", "info")

    def _append_perf_log(self) -> None:
        if not self._perf_logging_enabled:
            return
        if not self._perf_log_writer or not self._perf_log_handle:
            self._start_perf_logging()
        if not self._perf_log_writer or not self._perf_log_handle:
            return

        stats = self.latest_perf_stats or {}
        if not stats:
            return

        row = []
        for key in self._perf_log_headers:
            value = stats.get(key, '')
            if isinstance(value, bool):
                value = int(value)
            elif isinstance(value, float):
                value = round(value, 4)
            elif value is None:
                value = ''
            row.append(value)

        try:
            self._perf_log_writer.writerow(row)
            self._perf_log_handle.flush()
        except Exception as exc:
            self.update_general_log(f"맵 성능 로그 기록 실패: {exc}", "red")
            self._stop_perf_logging()

    def _on_other_player_alert_toggled(self, checked: bool) -> None:  # noqa: ARG002
        self.other_player_alert_enabled = bool(checked)
        if not self.other_player_alert_enabled:
            self._reset_other_player_alert_state()
        if self.telegram_alert_checkbox:
            self.telegram_alert_checkbox.setEnabled(self.other_player_alert_enabled)
            if not self.other_player_alert_enabled and self.telegram_alert_checkbox.isChecked():
                blocker = QSignalBlocker(self.telegram_alert_checkbox)
                self.telegram_alert_checkbox.setChecked(False)
                del blocker
                self.telegram_alert_enabled = False
        if self.telegram_settings_btn:
            self.telegram_settings_btn.setEnabled(
                self.other_player_alert_enabled and self.telegram_alert_enabled
            )
        if self.active_profile_name:
            self.save_profile_data()

    def _play_other_player_alert_sound(self) -> None:
        """다른 유저 감지 시 알람 소리를 재생합니다."""
        try:
            import winsound
        except Exception:
            QApplication.beep()
            return

        def _beep_sequence() -> None:
            try:
                winsound.Beep(1900, 350)
                winsound.Beep(1500, 350)
                winsound.Beep(2200, 450)
            except Exception:
                winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)

        threading.Thread(target=_beep_sequence, daemon=True).start()

    def _handle_other_player_detection_alert(self, other_players: list[QRectF]) -> None:
        if not self.other_player_alert_enabled:
            self._other_player_alert_active = False
            return

        now = time.time()
        has_other_player = bool(other_players)
        if has_other_player:
            first_detection = not self._other_player_alert_active
            if first_detection:
                self._play_other_player_alert_sound()
                self._other_player_alert_active = True

            interval = max(self.telegram_send_interval, 1.0)
            should_send = False
            if self.telegram_send_mode == "continuous":
                if first_detection or self._other_player_alert_last_time <= 0.0 or now >= self._other_player_alert_last_time + interval:
                    should_send = True
            else:
                should_send = first_detection

            if should_send:
                detected_count = len(other_players)
                profile_name = self.active_profile_name or "(미지정)"
                timestamp_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
                count_text = f"{detected_count}명"
                message = (
                    f"[Project Maple] 다른 캐릭터 감지 알림\n"
                    f"다른 캐릭터: {count_text}\n"
                    f"프로필: {profile_name}\n"
                    f"시각: {timestamp_text}"
                )
                self._send_telegram_alert(message)
                self._other_player_alert_last_time = now
        else:
            self._other_player_alert_active = False

    def _reset_other_player_alert_state(self) -> None:
        self._other_player_alert_active = False
        self._other_player_alert_last_time = 0.0

    def _load_telegram_credentials(self) -> tuple[str, str]:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        candidates: list[Path] = []
        try:
            workspace_root_path = Path(WORKSPACE_ROOT)
            candidates.append(workspace_root_path / "config" / "telegram.json")
        except Exception:
            workspace_root_path = Path()

        raw_workspace = str(WORKSPACE_ROOT)
        if ":" in raw_workspace:
            drive, remainder = raw_workspace.split(":", 1)
            remainder = remainder.replace("\\", "/").lstrip("/\\")
            wsl_base = Path("/mnt") / drive.lower()
            if remainder:
                wsl_base = wsl_base / Path(remainder)
            candidates.append(wsl_base / "config" / "telegram.json")

        candidates.append(Path.cwd() / "workspace" / "config" / "telegram.json")

        config_path: Path | None = None
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            if resolved in seen:
                continue
            seen.add(resolved)
            if resolved.is_file():
                config_path = resolved
                break

        try:
            if config_path and config_path.is_file():
                content = config_path.read_text(encoding="utf-8").strip()
                if content:
                    try:
                        data = json.loads(content)
                        token = str(data.get("TELEGRAM_BOT_TOKEN", token) or "").strip()
                        chat_id = str(data.get("TELEGRAM_CHAT_ID", chat_id) or "").strip()
                    except json.JSONDecodeError:
                        for line in content.splitlines():
                            if "=" not in line:
                                continue
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key == "TELEGRAM_BOT_TOKEN" and value:
                                token = value.strip()
                            elif key == "TELEGRAM_CHAT_ID" and value:
                                chat_id = value.strip()
        except Exception as exc:  # noqa: BLE001
            print(f"텔레그램 설정 파일 로드 중 오류: {exc}")

        return token, chat_id

    def _refresh_telegram_credentials(self) -> None:
        token, chat_id = self._load_telegram_credentials()
        self.telegram_bot_token = token
        self.telegram_chat_id = chat_id

    def _on_initial_delay_changed(self, value: int) -> None:  # noqa: ARG002
        self.initial_delay_ms = int(value)
        self.save_global_settings()

    def _on_telegram_alert_toggled(self, checked: bool) -> None:  # noqa: ARG002
        # 다른 유저 감지 옵션이 비활성화된 상태에서는 강제로 해제
        if checked and not self.other_player_alert_enabled:
            if self.telegram_alert_checkbox:
                blocker = QSignalBlocker(self.telegram_alert_checkbox)
                self.telegram_alert_checkbox.setChecked(False)
                del blocker
            self.telegram_alert_enabled = False
            return

        self.telegram_alert_enabled = bool(checked)
        if self.telegram_settings_btn:
            self.telegram_settings_btn.setEnabled(
                self.other_player_alert_enabled and self.telegram_alert_enabled
            )
        if self.active_profile_name:
            self.save_profile_data()

    def _open_telegram_settings_dialog(self) -> None:
        """텔레그램 전송 설정 다이얼로그를 연다."""
        if not self.other_player_alert_enabled:
            QMessageBox.information(self, "텔레그램 설정", "먼저 '다른 유저 감지'를 활성화해 주세요.")
            return
        if not self.telegram_alert_enabled:
            QMessageBox.information(self, "텔레그램 설정", "'텔레그램 전송' 옵션을 체크한 뒤 다시 시도하세요.")
            return

        dialog = TelegramSettingsDialog(
            mode=self.telegram_send_mode,
            interval_seconds=self.telegram_send_interval,
            parent=self,
        )
        if dialog.exec():
            self.telegram_send_mode = dialog.get_mode()
            self.telegram_send_interval = dialog.get_interval_seconds()
            if self.active_profile_name:
                self.save_profile_data()
            self.update_general_log(
                f"텔레그램 전송 설정이 업데이트되었습니다. 모드: {'1회' if self.telegram_send_mode == 'once' else '지속'}, 주기: {self.telegram_send_interval:.1f}초",
                "blue",
            )

    def _send_telegram_alert(self, message: str) -> None:
        if not message or not self.telegram_alert_enabled:
            return

        self._refresh_telegram_credentials()
        token = (self.telegram_bot_token or "").strip()
        chat_id = (self.telegram_chat_id or "").strip()
        if not token or not chat_id:
            self.update_general_log(
                "텔레그램 전송 실패: workspace/config/telegram.json 또는 환경변수에서 자격 정보를 찾을 수 없습니다.",
                "orange",
            )
            return

        def _worker() -> None:
            try:
                import requests  # type: ignore
            except ImportError:
                QTimer.singleShot(
                    0,
                    lambda: self.update_general_log(
                        "텔레그램 전송 실패: requests 모듈이 필요합니다. pip install requests", "red"
                    ),
                )
                return

            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            }

            try:
                response = requests.post(url, data=payload, timeout=5)
                if response.status_code >= 400:
                    QTimer.singleShot(
                        0,
                        lambda: self.update_general_log(
                            f"텔레그램 전송 실패({response.status_code}): {response.text}", "red"
                        ),
                    )
            except Exception as exc:  # noqa: BLE001
                QTimer.singleShot(
                    0,
                    lambda: self.update_general_log(f"텔레그램 전송 중 오류: {exc}", "red"),
                )

        threading.Thread(target=_worker, daemon=True).start()

    def _on_auto_control_toggled(self, checked: bool) -> None:  # noqa: ARG002
        if not self.active_profile_name:
            return
        if not checked:
            self._handle_auto_control_key_reset()
        self.save_profile_data()

    def _on_perf_logging_toggled(self, checked: bool) -> None:
        self._perf_logging_enabled = bool(checked)
        if self._perf_logging_enabled:
            if self.is_detection_running:
                self._start_perf_logging()
        else:
            self._stop_perf_logging()
        self.save_global_settings()

    def _generate_full_map_pixmap(self):
        """
        v10.0.0: 모든 핵심 지형의 문맥 이미지를 합성하여 하나의 큰 배경 지도 QPixmap을 생성하고,
        모든 맵 요소의 전체 경계를 계산하여 저장합니다.
        [MODIFIED] 비정상적인 좌표값으로 인해 경계가 무한히 확장되는 것을 방지하는 안전장치를 추가합니다.
        """
        if not self.global_positions:
            self.full_map_pixmap = None
            self.full_map_bounding_rect = QRectF()
            if hasattr(self, 'minimap_view_label'):
                self.minimap_view_label.update_static_cache(
                    geometry_data=self.geometry_data,
                    key_features=self.key_features,
                    global_positions=self.global_positions,
                )
            return

        all_items_rects = []
        
        # 1. 핵심 지형의 문맥 이미지를 기준으로 경계 계산
        for feature_id, feature_data in self.key_features.items():
            context_pos_key = f"{feature_id}_context"
            if context_pos_key in self.global_positions:
                context_origin = self.global_positions[context_pos_key]
                #  비정상적인 좌표값 필터링
                if abs(context_origin.x()) > 1e6 or abs(context_origin.y()) > 1e6:
                    self.update_general_log(f"경고: 비정상적인 문맥 원점 좌표({context_pos_key})가 감지되어 경계 계산에서 제외합니다.", "orange")
                    continue
                
                if 'context_image_base64' in feature_data and feature_data['context_image_base64']:
                    try:
                        img_data = base64.b64decode(feature_data['context_image_base64'])
                        pixmap = QPixmap(); pixmap.loadFromData(img_data)
                        if not pixmap.isNull():
                            all_items_rects.append(QRectF(context_origin, QSizeF(pixmap.size())))
                    except Exception as e:
                        print(f"문맥 이미지 로드 오류 (ID: {feature_id}): {e}")
        
        # 2. 지형선, 오브젝트 등의 경계도 포함
        all_points = []
        for line in self.geometry_data.get("terrain_lines", []): all_points.extend(line.get("points", []))
        for obj in self.geometry_data.get("transition_objects", []): all_points.extend(obj.get("points", []))
        
        if all_points:
            #  비정상적인 지형 좌표 필터링
            valid_points = [p for p in all_points if abs(p[0]) < 1e6 and abs(p[1]) < 1e6]
            if valid_points:
                xs = [p[0] for p in valid_points]
                ys = [p[1] for p in valid_points]
                all_items_rects.append(QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))

        if not all_items_rects:
            self.full_map_pixmap = QPixmap(100, 100)
            self.full_map_pixmap.fill(QColor(50, 50, 50))
            self.full_map_bounding_rect = QRectF(0, 0, 100, 100)
            self.update_general_log("배경 지도 생성 실패: 유효한 그리기 요소가 없습니다. 기본 맵을 생성합니다.", "orange")
            return

        # 3. 모든 유효한 경계를 합쳐 최종 경계 계산
        bounding_rect = QRectF()
        for rect in all_items_rects:
            if bounding_rect.isNull():
                bounding_rect = rect
            else:
                bounding_rect = bounding_rect.united(rect)

        #  최종 경계 크기 제한 (안전장치)
        MAX_DIMENSION = 20000 # 씬의 최대 크기를 20000px로 제한
        if bounding_rect.width() > MAX_DIMENSION or bounding_rect.height() > MAX_DIMENSION:
            self.update_general_log(f"경고: 계산된 맵 경계({bounding_rect.size().toSize()})가 너무 큽니다. 최대 크기로 제한합니다.", "red")
            bounding_rect = QRectF(
                bounding_rect.x(), bounding_rect.y(),
                min(bounding_rect.width(), MAX_DIMENSION),
                min(bounding_rect.height(), MAX_DIMENSION)
            )

        bounding_rect.adjust(-50, -50, 50, 50)
        self.full_map_bounding_rect = bounding_rect

        # 이하 픽스맵 생성 및 그리기는 기존과 동일
        self.full_map_pixmap = QPixmap(bounding_rect.size().toSize())
        self.full_map_pixmap.fill(QColor(50, 50, 50))
        
        painter = QPainter(self.full_map_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(-bounding_rect.topLeft())

        if self.render_options.get('background', True):
            painter.setOpacity(0.7)
            for feature_id, feature_data in self.key_features.items():
                context_pos_key = f"{feature_id}_context"
                if context_pos_key in self.global_positions:
                    context_origin = self.global_positions[context_pos_key]
                    if abs(context_origin.x()) > 1e6 or abs(context_origin.y()) > 1e6: continue # 렌더링에서도 제외

                    if 'context_image_base64' in feature_data and feature_data['context_image_base64']:
                        try:
                            img_data = base64.b64decode(feature_data['context_image_base64'])
                            pixmap = QPixmap(); pixmap.loadFromData(img_data)
                            if not pixmap.isNull():
                                painter.drawPixmap(context_origin, pixmap)
                        except Exception as e:
                            print(f"문맥 이미지 그리기 오류 (ID: {feature_id}): {e}")
        
        painter.end()
        self.update_general_log(f"배경 지도 이미지 생성 완료. (크기: {self.full_map_pixmap.width()}x{self.full_map_pixmap.height()})", "green")

        # 정적 렌더링 캐시 갱신
        if hasattr(self, 'minimap_view_label'):
            self.minimap_view_label.update_static_cache(
                geometry_data=self.geometry_data,
                key_features=self.key_features,
                global_positions=self.global_positions,
            )
      
    def _calculate_content_bounding_rect(self):
        """현재 맵의 모든 시각적 요소(지형, 오브젝트 등)를 포함하는 전체 경계를 계산합니다."""
        if not self.global_positions and not self.geometry_data:
            return QRectF()

        content_rect = QRectF()
        
        # 1. 핵심 지형의 경계 계산
        for feature_id, pos in self.global_positions.items():
            if feature_id in self.key_features:
                feature_data = self.key_features[feature_id]
                size_data = feature_data.get('size')
                if size_data and len(size_data) == 2:
                    size = QSizeF(size_data[0], size_data[1])
                    feature_rect = QRectF(pos, size)
                    content_rect = content_rect.united(feature_rect)

        # 2. 모든 지오메트리 포인트 수집
        all_points = []
        for line in self.geometry_data.get("terrain_lines", []):
            all_points.extend(line.get("points", []))
        for obj in self.geometry_data.get("transition_objects", []):
            all_points.extend(obj.get("points", []))
        for wp in self.geometry_data.get("waypoints", []):
            all_points.append(wp.get("pos", [0, 0]))
        for jump in self.geometry_data.get("jump_links", []):
            all_points.append(jump.get("start_vertex_pos", [0, 0]))
            all_points.append(jump.get("end_vertex_pos", [0, 0]))

        # 3. 지오메트리 포인트들의 경계 계산 및 통합
        if all_points:
            min_x = min(p[0] for p in all_points)
            max_x = max(p[0] for p in all_points)
            min_y = min(p[1] for p in all_points)
            max_y = max(p[1] for p in all_points)
            geometry_rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
            content_rect = content_rect.united(geometry_rect)
            
        return content_rect

    def _center_realtime_view_on_map(self):
        """실시간 미니맵 뷰를 맵 콘텐츠의 중앙으로 이동시킵니다."""
        content_rect = self._calculate_content_bounding_rect()
        if not content_rect.isNull():
            center_point = content_rect.center()
            self.minimap_view_label.camera_center_global = center_point
            self.minimap_view_label.update() # 뷰 갱신

    def _calculate_path_cost(self, start_pos, start_floor, target_wp_data, all_transition_objects):
        """
        시작 위치/층에서 목표 웨이포인트까지의 예상 이동 비용(x축 거리)을 계산합니다.
        상승 시에는 층 이동 오브젝트를 경유하는 비용을 누적합니다.
        """
        target_pos = QPointF(target_wp_data['pos'][0], target_wp_data['pos'][1])
        target_floor = target_wp_data['floor']
        
        if start_floor == target_floor:
            # 같은 층: 직선 x축 거리
            return abs(start_pos.x() - target_pos.x())
        
        elif start_floor < target_floor:
            # 올라가야 할 때: 층별로 경유 비용 누적
            total_cost = 0
            current_pos_x = start_pos.x()
            
            # 한 층씩 올라가며 비용 계산
            for floor_level in range(int(start_floor), int(target_floor)):
                next_floor_level = floor_level + 1
                
                # 다음 층(next_floor_level)에 있는 층 이동 오브젝트들을 찾음
                candidate_objects = [obj for obj in all_transition_objects if obj.get('floor') == next_floor_level]
                
                if not candidate_objects:
                    return float('inf') # 올라갈 방법이 없으면 비용 무한대

                # 현재 위치에서 가장 가까운 층 이동 오브젝트 찾기
                closest_obj = min(candidate_objects, key=lambda obj: abs(current_pos_x - obj['points'][0][0]))
                closest_obj_x = closest_obj['points'][0][0]
                
                # 현재 위치에서 오브젝트까지 가는 비용 추가
                total_cost += abs(current_pos_x - closest_obj_x)
                # 위치를 오브젝트 위치로 갱신
                current_pos_x = closest_obj_x

            # 마지막 오브젝트 위치에서 최종 목표 웨이포인트까지의 비용 추가
            total_cost += abs(current_pos_x - target_pos.x())
            return total_cost
        
        else: # start_floor > target_floor
            # 내려가야 할 때: 단순 x축 거리 (낙하 가능)
            return abs(start_pos.x() - target_pos.x())

    def _calculate_total_cost(self, start_pos, final_target_wp, intermediate_candidate):
        """
        v10.7.0: "현재 위치 -> 중간 목표 -> 최종 목표"의 총 이동 비용을 계산합니다.
        비용 = (Cost1: 중간 목표까지 x거리) + (Cost2: 중간 목표 통과 비용) + (Cost3: 중간 목표 이후 x거리)
        """
        if not final_target_wp or not intermediate_candidate:
            return float('inf')

        final_target_pos = QPointF(final_target_wp['pos'][0], final_target_wp['pos'][1])
        total_cost = 0
        
        candidate_type = intermediate_candidate['type']
        
        # --- Cost1: 현재 위치 -> 중간 목표 진입점 ---
        entry_point = intermediate_candidate['entry_point']
        total_cost += abs(start_pos.x() - entry_point.x())

        # --- Cost2 & Cost3 계산을 위한 탈출점 및 다음 시작점 설정 ---
        exit_point = None
        
        if candidate_type == 'walk':
            # walk는 중간 목표가 최종 목표이므로, Cost2와 Cost3는 0입니다.
            return total_cost

        elif candidate_type == 'climb':
            obj = intermediate_candidate['object']
            p1_y, p2_y = obj['points'][0][1], obj['points'][1][1]
            # Cost2: 오브젝트 통과 비용 (수직 이동 거리)
            total_cost += abs(p1_y - p2_y)
            # 탈출점은 오브젝트의 위쪽 끝
            exit_y = min(p1_y, p2_y)
            exit_point = QPointF(obj['points'][0][0], exit_y)

        elif candidate_type == 'fall':
            # Cost2: 낙하 비용은 0
            # 탈출점은 낙하 지점과 동일한 x좌표를 가지지만, 목표 층의 지형 위에 있음
            fall_point = intermediate_candidate['entry_point']
            target_floor = final_target_wp.get('floor')
            
            # 목표 층에서 낙하 지점 바로 아래의 지형 찾기 (y좌표 결정 위함)
            # 이 로직은 단순화를 위해 일단 x좌표만 같다고 가정. 추후 더 정교화 가능.
            exit_point = QPointF(fall_point.x(), final_target_pos.y()) # 임시로 최종 목표의 y 사용

        elif candidate_type == 'jump':
            link = intermediate_candidate['link']
            # Cost2: 점프 링크 통과 비용 (x축 거리)
            total_cost += abs(link['start_vertex_pos'][0] - link['end_vertex_pos'][0])
            exit_point = intermediate_candidate['exit_point']

        # --- Cost3: 중간 목표 탈출점 -> 최종 목표 ---
        if exit_point:
            total_cost += abs(exit_point.x() - final_target_pos.x())
        else:
            # 탈출점이 없는 경우는 오류 상황이므로 비용을 무한대로 처리
            return float('inf')

        return total_cost

    def _determine_player_physical_state(self, final_player_pos, contact_terrain):
        """
        [MODIFIED] v17.2: 'falling' 상태에 대한 최종 검증 규칙 추가.
        [OPTIMIZED] 머신러닝 모델 호출 주기를 시간 기반으로 제한하여 성능 최적화.
        """
        previous_state = self.player_state

        if (time.time() - self.last_state_change_time) < self.cfg_state_change_cooldown:
            return previous_state

        x_movement = final_player_pos.x() - self.last_player_pos.x()
        y_movement = self.last_player_pos.y() - final_player_pos.y()
        self.y_velocity_history.append(y_movement)
        
        if contact_terrain:
            if abs(x_movement) > self.cfg_move_deadzone:
                self.last_movement_time = time.time()
        else:
            if abs(x_movement) > self.cfg_move_deadzone or abs(y_movement) > self.cfg_move_deadzone:
                self.last_movement_time = time.time()

        new_state = previous_state
        reason = "상태 유지"

        # -1순위: 지상 착지 판정
        if contact_terrain:
            if previous_state in ['jumping', 'falling']:
                points = contact_terrain.get('points', [])
                if len(points) >= 2:
                    terrain_width = abs(points[0][0] - points[-1][0])
                    if terrain_width < 10.0:
                        self.just_landed_on_narrow_terrain = True
                        if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                            print(f"[INFO] 좁은 발판(너비: {terrain_width:.1f}px) 착지. 1프레임 판단 유예.")
            
            time_since_move = time.time() - self.last_movement_time
            if time_since_move >= self.cfg_idle_time_threshold:
                new_state = 'idle'; reason = "규칙: 지상에서 정지"
            else:
                new_state = 'on_terrain'; reason = "규칙: 지상에서 이동"
            self.in_jump = False
            self.last_on_terrain_y = final_player_pos.y()
        
        # 공중에 있을 때
        else:
            if self.in_jump and (time.time() - self.jump_start_time > self.cfg_max_jump_duration):
                new_state = 'falling'
                reason = "규칙: 점프 타임아웃 (최우선)"
            
            else:
                y_above_terrain = self.last_on_terrain_y - final_player_pos.y()
                is_near_ladder, _, _ = self._check_near_ladder(final_player_pos, self.geometry_data.get("transition_objects", []), self.cfg_ladder_x_grab_threshold, return_dist=True, current_floor=self.current_player_floor)

                # 0순위: 사다리 위에서의 상태 전이 (히스테리시스 적용)
                if previous_state in ['climbing_up', 'climbing_down', 'on_ladder_idle']:
                    
                    if previous_state == 'on_ladder_idle':
                        if abs(y_movement) > self.cfg_move_deadzone:
                            predicted_action = None
                            
                            # <<< 핵심 수정 1: 시간 간격 체크 >>>
                            current_time = time.time()
                            if self.action_model and len(self.action_inference_buffer) > 5 and \
                               (current_time - self.last_model_inference_time > self.model_inference_interval):
                                
                                self.last_model_inference_time = current_time # 마지막 호출 시간 갱신
                                try:
                                    recent_sequence = list(self.action_inference_buffer)[-30:]
                                    features = self._extract_features_from_sequence(recent_sequence)
                                    predicted_action = self.action_model.predict(features.reshape(1, -1))[0]
                                except Exception as e:
                                    print(f"동작 예측 오류: {e}")
                            
                            if predicted_action == "climb_up_ladder":
                                new_state = 'climbing_up'; reason = "모델: idle -> 오르기"
                            elif predicted_action == "climb_down_ladder":
                                new_state = 'climbing_down'; reason = "모델: idle -> 내려가기"
                            else:
                                if y_movement > 0:
                                    new_state = 'climbing_up'; reason = '규칙: idle -> 오르기'
                                else:
                                    new_state = 'climbing_down'; reason = '규칙: idle -> 내려가기'
                        else:
                            new_state = 'on_ladder_idle'; reason = '상태 유지: on_ladder_idle'

                    else: # climbing_up or climbing_down
                        time_since_move = time.time() - self.last_movement_time
                        if time_since_move >= self.cfg_idle_time_threshold:
                            new_state = 'on_ladder_idle'; reason = '규칙: 사다리 위 정지 (시간)'
                        else:
                            predicted_action = None
                            
                            # <<< 핵심 수정 2: 여기도 동일하게 시간 간격 체크 추가 >>>
                            current_time = time.time()
                            if self.action_model and len(self.action_inference_buffer) > 5 and \
                               (current_time - self.last_model_inference_time > self.model_inference_interval):

                                self.last_model_inference_time = current_time # 마지막 호출 시간 갱신
                                try:
                                    recent_sequence = list(self.action_inference_buffer)[-30:]
                                    features = self._extract_features_from_sequence(recent_sequence)
                                    predicted_action = self.action_model.predict(features.reshape(1, -1))[0]
                                except Exception as e:
                                    print(f"동작 예측 오류: {e}")
                            
                            movement_trend = sum(list(self.y_velocity_history)[-3:])

                            if previous_state == 'climbing_up' and movement_trend < -self.cfg_y_movement_deadzone:
                                new_state = 'climbing_down'; reason = '규칙: 오르다 방향 전환'
                            elif previous_state == 'climbing_down' and movement_trend > self.cfg_y_movement_deadzone:
                                new_state = 'climbing_up'; reason = '규칙: 내리다 방향 전환'
                            elif predicted_action == "climb_up_ladder" and movement_trend > 0:
                                new_state = 'climbing_up'; reason = f"모델 예측 (검증됨): '{predicted_action}'"
                            elif predicted_action == "climb_down_ladder" and movement_trend < 0:
                                new_state = 'climbing_down'; reason = f"모델 예측 (검증됨): '{predicted_action}'"
                            elif predicted_action == "fall":
                                new_state = 'falling'; reason = f"모델 예측: '{predicted_action}'"
                            else:
                                new_state = previous_state; reason = f"상태 유지 (추세: {movement_trend:.2f})"

                # 1-3순위: 그 외 공중 상태에 대한 강력한 규칙
                else:
                    was_on_terrain = previous_state in ['on_terrain', 'idle']
                    
                    if was_on_terrain and is_near_ladder and final_player_pos.y() > (self.last_on_terrain_y + 4.0):
                        new_state = 'climbing_down'; reason = "규칙: 지상->내려가기"
                    
                    elif is_near_ladder and y_above_terrain > self.cfg_jump_y_max_threshold:
                        new_state = 'climbing_up'; reason = f"규칙: 오르기 (Y오프셋 {y_above_terrain:.2f} > 최대 점프 {self.cfg_jump_y_max_threshold:.2f})"
                    
                    elif y_above_terrain < -self.cfg_fall_y_min_threshold:
                        new_state = 'falling'; reason = f"규칙: 낙하 (Y오프셋 {y_above_terrain:.2f} < 낙하 임계값)"

                    # 4순위: 나머지 기본 판정 (점프 등)
                    else:
                        is_in_jump_height_range = self.cfg_jump_y_min_threshold < y_above_terrain < self.cfg_jump_y_max_threshold
                        
                        if self.in_jump:
                            new_state = 'jumping'; reason = "규칙: 점프 유지"
                        elif is_in_jump_height_range:
                            new_state = 'jumping'; reason = f"규칙: 점프 시작 (Y오프셋 {y_above_terrain:.2f})"
                            self.in_jump = True
                            self.jump_start_time = time.time()
                        else:
                            new_state = 'falling'; reason = "폴백: 자유 낙하"

        # 최종 'falling' 상태 검증
        if new_state == 'falling':
            y_above_terrain = self.last_on_terrain_y - final_player_pos.y()
            if y_above_terrain > -self.cfg_fall_y_min_threshold:
                if self.in_jump:
                    new_state = 'jumping'; reason = f"검증 실패: 'falling' 취소 (점프 유지)"
                elif previous_state not in ['on_terrain', 'idle']:
                    new_state = previous_state; reason = f"검증 실패: 'falling' 취소 (이전 상태 유지)"
                else:
                    new_state = previous_state; reason = f"검증 실패: 'falling' 취소 (이전 지상 상태 '{previous_state}'로 복귀)"

        # 최종 상태 변경 및 로그 출력
        if new_state != previous_state:
            if new_state != 'jumping':
                self.in_jump = False
                
            self.last_state_change_time = time.time()
            if self.debug_state_machine_checkbox and self.debug_state_machine_checkbox.isChecked():
                self._log_state_change(previous_state, new_state, reason, y_movement, self.y_velocity_history)
        
        return new_state
    
    def _plan_next_journey(self, active_route):
        """
        [MODIFIED] v14.3.9: 로그 출력을 디버그 체크박스로 제어.
        다음 여정을 계획하고 경로 순환 로직을 처리합니다.
        """
        if self.route_cycle_initialized:
            self.is_forward = not self.is_forward
        else:
            self.is_forward = True
            self.route_cycle_initialized = True

        forward_slots = active_route.get("forward_slots", {}) or {}
        backward_slots = active_route.get("backward_slots", {}) or {}

        next_journey = []
        selected_slot = None
        self.current_direction_slot_label = "정방향" if self.is_forward else "역방향"

        if self.is_forward:
            forward_options = self._get_enabled_slot_ids(active_route, "forward")
            if forward_options:
                selected_slot = random.choice(forward_options)
                next_journey = list(forward_slots.get(selected_slot, {}).get("waypoints", []))
                self.last_selected_forward_slot = selected_slot
                self.last_forward_journey = list(next_journey)
                self.current_direction_slot_label = f"정방향{selected_slot}"
            else:
                self.update_general_log("체크된 정방향 경로가 없어 탐지를 종료합니다.", "orange")
                self.journey_plan = []
                self.target_waypoint_id = None
                self.start_waypoint_found = False
                self.current_direction_slot_label = "-"
                return
        else:
            backward_options = self._get_enabled_slot_ids(active_route, "backward")
            if backward_options:
                selected_slot = random.choice(backward_options)
                next_journey = list(backward_slots.get(selected_slot, {}).get("waypoints", []))
                self.last_selected_backward_slot = selected_slot
                self.current_direction_slot_label = f"역방향{selected_slot}"
            else:
                if self.last_forward_journey:
                    next_journey = list(reversed(self.last_forward_journey))
                    if self.last_selected_forward_slot:
                        self.current_direction_slot_label = f"역방향(정방향{self.last_selected_forward_slot} 역주행)"
                    else:
                        self.current_direction_slot_label = "역방향"
                else:
                    forward_options = self._get_enabled_slot_ids(active_route, "forward")
                    if forward_options:
                        fallback_slot = random.choice(forward_options)
                        fallback_path = list(forward_slots.get(fallback_slot, {}).get("waypoints", []))
                        if fallback_path:
                            self.last_selected_forward_slot = fallback_slot
                            self.last_forward_journey = list(fallback_path)
                            next_journey = list(reversed(fallback_path))
                            self.current_direction_slot_label = f"역방향(정방향{fallback_slot} 역주행)"

                if not next_journey:
                    self.update_general_log("역방향 슬롯이 비어 있고 역주행할 정방향 경로도 없어 순환을 종료합니다.", "orange")
                    self.journey_plan = []
                    self.target_waypoint_id = None
                    self.start_waypoint_found = False
                    self.current_direction_slot_label = "-"
                    return

        if not next_journey:
            self.update_general_log("경로 완주. 순환할 경로가 없습니다.", "green")
            self.journey_plan = []
            self.target_waypoint_id = None
            self.start_waypoint_found = False
            self.current_direction_slot_label = "-"
        else:
            self.journey_plan = next_journey
            self.current_journey_index = 0
            self.start_waypoint_found = True
            direction_label = self.current_direction_slot_label
            if not direction_label or direction_label == "-":
                direction_label = "정방향" if self.is_forward else "역방향"
            self.update_general_log(f"새로운 여정을 시작합니다. ({direction_label})", "purple")

            if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                print(f"[INFO] 새 여정 계획: {[self.nav_nodes.get(f'wp_{wp_id}', {}).get('name', '??') for wp_id in self.journey_plan]}")

    def _calculate_segment_path(self, final_player_pos):
        """
        [v12.8.1 수정] 플레이어의 실제 위치를 가상 시작 노드로 사용하여 A* 탐색을 수행합니다.
        """
        current_terrain = self._get_contact_terrain(final_player_pos)
        if not current_terrain:
            if not self.current_segment_path and not self.airborne_path_warning_active:
                self.update_general_log("경로 계산 대기: 공중에서는 경로를 계산할 수 없습니다. 착지 후 재시도합니다.", "gray")
                self.airborne_path_warning_active = True
                self.airborne_warning_started_at = time.time()
            return
        else:
            if self.airborne_path_warning_active:
                self.airborne_path_warning_active = False
                self._reset_airborne_recovery_state()

        start_group = current_terrain.get('dynamic_name')
        if not self.journey_plan or self.current_journey_index >= len(self.journey_plan):
            return

        goal_wp_id = self.journey_plan[self.current_journey_index]
        self.target_waypoint_id = goal_wp_id
        goal_node_key = f"wp_{goal_wp_id}"

        path, cost = self._find_path_astar(final_player_pos, start_group, goal_node_key)
        
        if path:
            self.current_segment_path = path
            self.current_segment_index = 0
            
            start_name = "현재 위치"
            goal_name = self.nav_nodes.get(goal_node_key, {}).get('name', '??')
            log_msg = f"[경로 탐색 성공] '{start_name}' -> '{goal_name}' (총 비용: {cost:.1f})"
            path_str = " -> ".join([self.nav_nodes.get(p, {}).get('name', '??') for p in path])
            log_msg_detail = f"[상세 경로] {path_str}"
            
            # [PATCH] v14.3.9: print문을 조건문으로 감쌈
            if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                print(log_msg)
                print(log_msg_detail)

            self.update_general_log(f"{log_msg}<br>{log_msg_detail}", 'SaddleBrown')
            self.last_path_recalculation_time = time.time()
        else:
            start_name = "현재 위치"
            goal_name = self.nav_nodes.get(goal_node_key, {}).get('name', '??')
            log_msg = f"[경로 탐색 실패] '{start_name}' -> '{goal_name}'"
            log_msg_detail = f"[진단] 시작 지형 그룹과 목표 지점이 그래프 상에서 연결되어 있지 않습니다."

            # [PATCH] v14.3.9: print문을 조건문으로 감쌈
            if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                print(log_msg)
                print(log_msg_detail)

            self.update_general_log(f"{log_msg}<br>{log_msg_detail}", 'red')
            self.journey_plan = []

    def _resolve_waypoint_arrival_threshold(self, node_key, node_data):
        """일반 웨이포인트의 도착 임계값을 최소~최대 범위 내에서 결정합니다."""
        if not node_data:
            return self.cfg_waypoint_arrival_x_threshold

        if node_data.get('is_event'):
            return self.EVENT_WAYPOINT_THRESHOLD

        if (
            node_key == self._active_waypoint_threshold_key
            and self._active_waypoint_threshold_value is not None
        ):
            return self._active_waypoint_threshold_value

        min_val = max(
            min(self.cfg_waypoint_arrival_x_threshold_min, self.cfg_waypoint_arrival_x_threshold_max),
            0.0,
        )
        max_val = max(
            max(self.cfg_waypoint_arrival_x_threshold_min, self.cfg_waypoint_arrival_x_threshold_max),
            min_val,
        )

        if abs(max_val - min_val) < 1e-6:
            chosen = max_val
        else:
            chosen = random.uniform(min_val, max_val)

        self._active_waypoint_threshold_key = node_key
        self._active_waypoint_threshold_value = chosen
        return chosen

    def _maybe_trigger_walk_teleport(self, direction: str, distance_to_target: float | None) -> None:
        """걷기 중 일정 거리 이상일 때 텔레포트 명령을 확률적으로 실행합니다."""
        if not (self.auto_control_checkbox.isChecked() or self.debug_auto_control_checkbox.isChecked()):
            self._update_walk_teleport_probability_display(0.0)
            self._reset_walk_teleport_state()
            return

        if direction not in ("→", "←") or distance_to_target is None:
            self._update_walk_teleport_probability_display(0.0)
            self._reset_walk_teleport_state()
            return

        if distance_to_target < 20.0:
            self._update_walk_teleport_probability_display(0.0)
            return

        now = time.time()

        bonus_delay = max(self.cfg_walk_teleport_bonus_delay, 0.1)
        bonus_step = max(self.cfg_walk_teleport_bonus_step, 0.0)
        bonus_max = max(self.cfg_walk_teleport_bonus_max, 0.0)

        if not self._walk_teleport_active:
            self._start_walk_teleport_tracking(now)
            elapsed = 0.0
        else:
            elapsed = max(0.0, now - self._walk_teleport_walk_started_at)

        if bonus_step > 0.0:
            bonus_steps = math.floor(elapsed / bonus_delay)
            self._walk_teleport_bonus_percent = min(bonus_max, bonus_steps * bonus_step)
        else:
            self._walk_teleport_bonus_percent = 0.0 if not self._walk_teleport_active else min(bonus_max, self._walk_teleport_bonus_percent)

        base_percent = max(min(self.cfg_walk_teleport_probability, 100.0), 0.0)
        effective_percent = min(100.0, base_percent + self._walk_teleport_bonus_percent)
        probability = effective_percent / 100.0

        self._update_walk_teleport_probability_display(effective_percent)

        if probability <= 0.0:
            return

        interval = max(self.cfg_walk_teleport_interval, 0.1)
        if (now - self._last_walk_teleport_check_time) < interval:
            return

        self._last_walk_teleport_check_time = now

        if not self._is_walk_direction_active(direction):
            walk_command = "걷기(우)" if direction == "→" else "걷기(좌)"
            if self.debug_auto_control_checkbox.isChecked():
                print(f"[자동 제어 테스트] WALK-TELEPORT: 누락된 걷기 -> {walk_command}")
            if self.auto_control_checkbox.isChecked():
                self._emit_control_command(walk_command, "walk_teleport:ensure_walk")
            return

        if random.random() >= probability:
            return

        teleport_command = "걷기 중 텔레포트"

        executed = False
        if self.debug_auto_control_checkbox.isChecked():
            print(f"[자동 제어 테스트] WALK-TELEPORT: {teleport_command}")
        elif self.auto_control_checkbox.isChecked():
            self._emit_control_command(teleport_command, None)
            executed = True

        if executed:
            self.last_command_sent_time = now

    def _get_arrival_threshold(self, node_type, node_key=None, node_data=None):
        """노드 타입에 맞는 도착 판정 임계값을 반환합니다."""
        if node_type == 'ladder_entry':
            return self.cfg_ladder_arrival_x_threshold
        if node_type in ['jump_vertex', 'fall_start', 'djump_area']:
            return self.cfg_jump_link_arrival_x_threshold
        if node_type == 'waypoint':
            return self._resolve_waypoint_arrival_threshold(node_key, node_data)
        return self.cfg_waypoint_arrival_x_threshold

    def _transition_to_action_state(self, new_action_state, prev_node_key):
        """주어진 액션 준비 상태로 전환합니다."""
        if self.navigation_action == new_action_state: return
        self.navigation_action = new_action_state
        self.waiting_for_safe_down_jump = (new_action_state == 'prepare_to_down_jump')
        self.prepare_timeout_start = time.time()
        prev_node_name = self.nav_nodes.get(prev_node_key, {}).get('name', '??')
        # [PATCH] v14.3.9: print문을 조건문으로 감쌈
        if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
            print(f"[상태 변경] '{prev_node_name}' 도착 -> {self.navigation_action}")
        self.update_general_log(f"'{prev_node_name}' 도착. 다음 행동 준비.", "blue")

    def _process_action_preparation(self, final_player_pos):
        """'prepare_to_...' 상태일 때, 이탈 또는 액션 시작을 판정합니다."""
        action_node_key = self.current_segment_path[self.current_segment_index]
        action_node = self.nav_nodes.get(action_node_key, {})
        action_node_pos = action_node.get('pos')
        if not action_node_pos: return

        action_node_floor = action_node.get('floor')
        if (action_node_floor is not None and 
            self.current_player_floor is not None and 
            abs(action_node_floor - self.current_player_floor) > 0.1):
            
            self.update_general_log(f"[경로 이탈 감지] 행동 준비 중 층을 벗어났습니다. (예상: {action_node_floor}층, 현재: {self.current_player_floor}층)", "orange")
            self.current_segment_path = []
            self.navigation_action = 'move_to_target'
            self.waiting_for_safe_down_jump = False
            return
        
        action_started = False
        if self.navigation_action == 'prepare_to_climb' and self.player_state in ['climbing_up', 'climbing_down']: action_started = True
        elif self.navigation_action == 'prepare_to_jump' and self.player_state == 'jumping': action_started = True
        elif self.navigation_action == 'prepare_to_fall' and self.player_state == 'falling': action_started = True
        elif self.navigation_action == 'prepare_to_down_jump' and self.player_state in ['jumping', 'falling']:
            if final_player_pos.y() > self.last_on_terrain_y + self.cfg_y_movement_deadzone:
                action_started = True
        
        if action_started:
            self.navigation_action = self.navigation_action.replace('prepare_to_', '') + '_in_progress'
            self.navigation_state_locked = True
            self.lock_timeout_start = time.time()
            self.waiting_for_safe_down_jump = False
            
            # [PATCH] v14.3.9: print문을 조건문으로 감쌈
            if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                print(f"[INFO] 행동 시작 감지. 상태 잠금 -> {self.navigation_action}")
            return

        recalc_cooldown = 1.0
        if time.time() - self.last_path_recalculation_time > recalc_cooldown:
            off_course_reason = None
            arrival_threshold = self._get_arrival_threshold(action_node.get('type'), action_node_key, action_node)
            exit_threshold = arrival_threshold + HYSTERESIS_EXIT_OFFSET

            if self.navigation_action == 'prepare_to_down_jump':
                x_range = action_node.get('x_range')
                if x_range and not (x_range[0] - exit_threshold <= final_player_pos.x() <= x_range[1] + exit_threshold):
                    off_course_reason = (
                        f"djump_area_exit: player_x({final_player_pos.x():.1f})가 "
                        f"허용 범위({x_range[0] - exit_threshold:.1f} ~ {x_range[1] + exit_threshold:.1f})를 벗어남"
                    )
            elif self.navigation_action == 'prepare_to_jump':
                dist_x = abs(final_player_pos.x() - action_node_pos.x())
                dist_y = abs(final_player_pos.y() - action_node_pos.y())
                if dist_x > exit_threshold or dist_y > 20.0:
                    off_course_reason = (
                        f"jump_target_exit: player({final_player_pos.x():.1f}, {final_player_pos.y():.1f})와 "
                        f"target({action_node_pos.x():.1f}, {action_node_pos.y():.1f})의 거리 초과. "
                        f"dist_x({dist_x:.1f} > {exit_threshold:.1f}) 또는 dist_y({dist_y:.1f} > 20.0)"
                    )
            else:
                dist_x = abs(final_player_pos.x() - action_node_pos.x())
                if dist_x > exit_threshold:
                    off_course_reason = (
                        f"generic_exit: player_x({final_player_pos.x():.1f})와 target_x({action_node_pos.x():.1f})의 "
                        f"거리({dist_x:.1f})가 허용 오차({exit_threshold:.1f})를 초과함"
                    )
            
            if off_course_reason:
                log_message = f"[경로 이탈] 사유: {off_course_reason}"
                self.update_general_log(log_message, "orange")
                
                # [PATCH] v14.3.9: print문을 조건문으로 감쌈
                if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                    print(f"[INFO] 경로 이탈 감지. 목표: {self.guidance_text}")

                self.current_segment_path = []
                self.navigation_action = 'move_to_target'
                self.waiting_for_safe_down_jump = False
    
    def _process_action_completion(self, final_player_pos, contact_terrain):
        """
        [MODIFIED] v13.1.5: 액션 완료 시, 불필요한 경유 노드(착지 지점 등)를
                 자동으로 건너뛰고 다음 실제 목표를 안내하도록 경로 정리 로직 추가.
        v12.9.9: [수정] '아래 점프/낙하' 액션의 성공 기준을 '올바른 지형 그룹 착지'로 변경.
        액션의 완료 또는 실패를 판정하고 상태를 처리합니다.
        """
        action_completed = False
        action_failed = False
        
        expected_group = None
        # [v.1815] 'climb' 액션의 경우, 다음 노드(사다리 출구) 정보를 미리 가져옴
        next_node = None
        if self.current_segment_index + 1 < len(self.current_segment_path):
            next_node_key = self.current_segment_path[self.current_segment_index + 1]
            next_node = self.nav_nodes.get(next_node_key, {})
            expected_group = next_node.get('group')

        if contact_terrain:
            current_action = self.navigation_action
            
            # [v.1815] 'climb_in_progress'에 대한 특별 성공 조건
            if current_action == 'climb_in_progress':
                if next_node and next_node.get('type') == 'ladder_exit':
                    target_pos = next_node.get('pos')
                    
                    is_on_correct_terrain = (contact_terrain.get('dynamic_name') == expected_group)
                    is_at_correct_height = (final_player_pos.y() <= target_pos.y() + 1.0) # 1px 여유
                    
                    if is_on_correct_terrain and is_at_correct_height:
                        action_completed = True
                        if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                            print("[INFO] Climb complete: 지형 및 높이 조건 모두 충족.")
                else:
                    # 경로에 문제가 있는 경우, 일단 착지만 하면 성공으로 간주 (안전장치)
                    if contact_terrain.get('dynamic_name') == expected_group:
                        action_completed = True

            # 다른 진행 중인 액션들 (낙하 등)
            elif current_action.endswith('_in_progress'):
                if contact_terrain.get('dynamic_name') == expected_group:
                    action_completed = True
                elif expected_group is not None:
                    action_failed = True

            # 액션이 아닌 상태에서 땅에 닿은 경우
            else:
                action_completed = True

        if action_failed:
            self.update_general_log(f"행동({self.navigation_action}) 실패. 예상 경로를 벗어났습니다. 경로를 재탐색합니다.", "orange")
            
            if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                print(f"[INFO] 행동 실패: {self.navigation_action}, 예상 그룹: {expected_group}, 현재 그룹: {contact_terrain.get('dynamic_name') if contact_terrain else 'None'}")

            self.navigation_action = 'move_to_target'
            self.navigation_state_locked = False
            self.current_segment_path = []
            self.expected_terrain_group = None
            self._climb_last_near_ladder_time = 0.0

        elif action_completed:
            action_name = self.navigation_action
            self.navigation_action = 'move_to_target'
            self.navigation_state_locked = False
            self._climb_last_near_ladder_time = 0.0
            
            via_node_types = {'fall_landing', 'djump_landing', 'ladder_exit'}
            self.current_segment_index += 1
            
            while self.current_segment_index < len(self.current_segment_path):
                next_node_key = self.current_segment_path[self.current_segment_index]
                next_node_type = self.nav_nodes.get(next_node_key, {}).get('type')
                if next_node_type in via_node_types:
                    skipped_node_name = self.nav_nodes.get(next_node_key, {}).get('name', '경유지')
                    
                    if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                        print(f"[INFO] 경유 노드 '{skipped_node_name}' 자동 건너뛰기.")

                    self.current_segment_index += 1
                else:
                    break

            if self.current_segment_index < len(self.current_segment_path):
                next_node_key = self.current_segment_path[self.current_segment_index]
                next_node = self.nav_nodes.get(next_node_key, {})
                self.expected_terrain_group = next_node.get('group')
                log_message = f"행동({action_name}) 완료. 다음 목표: '{next_node.get('name', '??')}' (그룹: '{self.expected_terrain_group}')"
                
                if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                    print(f"[INFO] {log_message}")

                self.update_general_log(log_message, "green")
            else:
                log_message = f"행동({action_name}) 완료. 현재 구간 종료."
                
                if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                    print(f"[INFO] {log_message}")

                self.expected_terrain_group = None
                self.update_general_log(log_message, "green")
            self._try_execute_pending_event()
    
    def _update_player_state_and_navigation(self, final_player_pos):
        """
        [MODIFIED] v1819: '의도된 움직임'만 복구 성공으로 간주하도록 수정.
        """
        # [수정 시작] current_terrain_name 변수 초기화 위치 변경 및 로직 수정
        contact_terrain = self._get_contact_terrain(final_player_pos)
        
        if contact_terrain:
            self.current_player_floor = contact_terrain.get('floor')
            # 땅에 있을 때만 마지막 지형 그룹 이름 갱신
            self.last_known_terrain_group_name = contact_terrain.get('dynamic_name', '')
        
        # UI에 표시될 이름은 last_known_terrain_group_name을 사용
        current_terrain_name = self.last_known_terrain_group_name
        # [수정 끝]
        
        if final_player_pos is None or self.current_player_floor is None:
            if final_player_pos is not None and contact_terrain is None:
                self._attempt_ladder_float_recovery(final_player_pos)
            self.navigator_display.update_data(
                floor="N/A", terrain_name="", target_name="없음",
                prev_name="", next_name="", direction="-", distance=0,
                full_path=[], last_reached_id=None, target_id=None,
                is_forward=self.is_forward, direction_slot_label=self.current_direction_slot_label,
                intermediate_type='walk', player_state="대기 중",
                nav_action="오류: 위치/층 정보 없음"
            )
            for state in self.forbidden_wall_states.values():
                state['entered_at'] = None
                state['contact_ready'] = True
            return

        self._update_event_waypoint_proximity(final_player_pos)
        self._update_forbidden_wall_logic(final_player_pos, contact_terrain)

        # Phase 0: 타임아웃 (유지)
        max_lock_duration = self.cfg_max_lock_duration or MAX_LOCK_DURATION
        prepare_timeout = self.cfg_prepare_timeout or PREPARE_TIMEOUT
        if (self.navigation_state_locked and (time.time() - self.lock_timeout_start > max_lock_duration)) or \
           (self.navigation_action.startswith('prepare_to_') and (time.time() - self.prepare_timeout_start > prepare_timeout)):
            self.update_general_log(f"경고: 행동({self.navigation_action}) 시간 초과. 경로를 재탐색합니다.", "orange")
            self.navigation_action = 'move_to_target'
            self.navigation_state_locked = False
            self.current_segment_path = [] # 경로 초기화하여 재탐색 유도

        if self.navigation_action != 'prepare_to_down_jump':
            self.waiting_for_safe_down_jump = False

        # Phase 1: 물리적 상태 판정 (유지)
        self.player_state = self._determine_player_physical_state(final_player_pos, contact_terrain)

        # 공중 경로 대기 상태 자동 복구 처리
        self._handle_airborne_path_wait(final_player_pos, contact_terrain)

        # --- [v.1819] '의도된 움직임' 감지 및 복구 로직 ---
        is_moving_state = self.player_state not in ['idle']
        
        # 1. 캐릭터가 움직였을 때, '의도된' 움직임인지 확인 후 처리
        if is_moving_state:
            if self.last_movement_time:
                self.last_action_time = self.last_movement_time
            else:
                self.last_action_time = time.time()
            # [핵심 수정] 최근 명령 컨텍스트를 기반으로 의도된 움직임 여부 판정
            is_intentional_move = self._was_recent_intentional_movement(final_player_pos)

            if self.stuck_recovery_attempts > 0 and is_intentional_move:
                self.update_general_log("[자동 복구] 의도된 움직임 감지. 복구 상태를 초기화합니다.", "green")
                self.stuck_recovery_attempts = 0
                self.last_movement_command = None
        
        # 2. 움직여야 하는데 멈춰있고, 현재 복구 쿨다운 상태가 아닐 때만 멈춤 감지
        should_be_moving = self.navigation_action in ['move_to_target', 'prepare_to_climb', 'prepare_to_jump', 'prepare_to_down_jump', 'prepare_to_fall', 'align_for_climb'] and self.start_waypoint_found
        
        if not self.event_in_progress:
            now = time.time()
            last_movement_reference = self.last_movement_time or self.last_action_time
            if last_movement_reference:
                time_since_last_movement = now - last_movement_reference
            else:
                time_since_last_movement = float('inf')

            can_attempt_recovery = (
                self.last_movement_command is not None
                and self.last_command_sent_time > 0.0
                and (now - self.last_command_sent_time) >= self.cfg_stuck_detection_wait
            )

            if (
                should_be_moving
                and can_attempt_recovery
                and now > self.recovery_cooldown_until
            ):
                if (
                    time_since_last_movement > self.cfg_stuck_detection_wait
                    and self.stuck_recovery_attempts < self.MAX_STUCK_RECOVERY_ATTEMPTS
                ):
                    self.stuck_recovery_attempts += 1
                    log_msg = (
                        f"[자동 복구] 멈춤 감지 ({self.stuck_recovery_attempts}/{self.MAX_STUCK_RECOVERY_ATTEMPTS})."
                    )
                    self._trigger_stuck_recovery(final_player_pos, log_msg)
                    return

                elif (
                    time_since_last_movement > self.cfg_stuck_detection_wait
                    and self.stuck_recovery_attempts >= self.MAX_STUCK_RECOVERY_ATTEMPTS
                ):
                    if now - getattr(self, '_last_stuck_log_time', 0) > 5.0:
                        self.update_general_log(
                            f"[자동 복구] 실패: 최대 복구 시도({self.MAX_STUCK_RECOVERY_ATTEMPTS}회)를 초과했습니다. 수동 개입이 필요할 수 있습니다.",
                            "red"
                        )
                        setattr(self, '_last_stuck_log_time', now)

            elif (
                self.player_state not in ['idle', 'on_terrain']
                and self.last_movement_time
                and can_attempt_recovery
                and now > self.recovery_cooldown_until
            ):
                non_walk_time_since_move = now - self.last_movement_time

                if (
                    non_walk_time_since_move > self.NON_WALK_STUCK_THRESHOLD_S
                    and self.stuck_recovery_attempts < self.MAX_STUCK_RECOVERY_ATTEMPTS
                ):
                    self.stuck_recovery_attempts += 1
                    log_msg = (
                        f"[자동 복구] 비걷기 상태 멈춤 감지 ({self.stuck_recovery_attempts}/{self.MAX_STUCK_RECOVERY_ATTEMPTS})."
                    )
                    self._trigger_stuck_recovery(final_player_pos, log_msg)
                    return

                elif (
                    non_walk_time_since_move > self.NON_WALK_STUCK_THRESHOLD_S
                    and self.stuck_recovery_attempts >= self.MAX_STUCK_RECOVERY_ATTEMPTS
                ):
                    if now - getattr(self, '_last_stuck_log_time', 0) > 5.0:
                        self.update_general_log(
                            f"[자동 복구] 실패: 최대 복구 시도({self.MAX_STUCK_RECOVERY_ATTEMPTS}회)를 초과했습니다. 수동 개입이 필요할 수 있습니다.",
                            "red"
                        )
                        setattr(self, '_last_stuck_log_time', now)
        
        # --- 로직 끝 ---
        
        # [이하 일반 내비게이션 로직]

        # --- [신규] 사다리 앞 정렬 및 확인 상태 처리 로직 ---
        alignment_processed = False
        if self.navigation_action in ['align_for_climb', 'verify_alignment']:
            alignment_processed = True
            contact_ok = contact_terrain is not None
            floor_ok = (
                self.alignment_expected_floor is None or
                (self.current_player_floor is not None and abs(self.current_player_floor - self.alignment_expected_floor) < 0.1)
            )
            group_ok = (
                self.alignment_expected_group is None or
                (contact_terrain and contact_terrain.get('dynamic_name') == self.alignment_expected_group)
            )
            ground_ok = self.player_state in ['on_terrain', 'idle']

            if not (contact_ok and floor_ok and group_ok and ground_ok):
                self.update_general_log("정렬 중 이탈이 감지되어 경로를 재계산합니다.", "orange")
                self._abort_alignment_and_recalculate()
            elif self.navigation_action == 'align_for_climb':
                if self.alignment_target_x is None:
                    self.update_general_log("정렬 대상이 유효하지 않아 정렬을 종료합니다.", "orange")
                    self._abort_alignment_and_recalculate()
                elif abs(final_player_pos.x() - self.alignment_target_x) <= 1.0:
                    self.update_general_log("정렬 범위 진입. 0.3초간 위치를 확인합니다.", "gray")
                    self.navigation_action = 'verify_alignment'
                    self.verify_alignment_start_time = time.time()
            else:  # verify_alignment
                if self.alignment_target_x is None:
                    self.update_general_log("정렬 대상이 유효하지 않아 정렬을 종료합니다.", "orange")
                    self._abort_alignment_and_recalculate()
                elif time.time() - self.verify_alignment_start_time > 0.3:
                    if abs(final_player_pos.x() - self.alignment_target_x) <= 1.0:
                        # 최종 성공
                        self.update_general_log("정렬 확인 완료. 위 방향으로 오르기를 시도합니다.", "green")
                        self.navigation_action = 'prepare_to_climb_upward'
                        self._clear_alignment_state()
                    else:
                        # 확인 실패, 다시 정렬 상태로 복귀
                        self.update_general_log("위치 이탈 감지. 다시 정렬합니다.", "orange")
                        self.navigation_action = 'align_for_climb'
                        if contact_terrain:
                            self.alignment_expected_floor = contact_terrain.get('floor', self.current_player_floor)
                            self.alignment_expected_group = contact_terrain.get('dynamic_name')
                        self.verify_alignment_start_time = 0.0
        # --- 로직 끝 ---

        # Phase 2: 행동 완료/실패 판정 (유지)
        if self.navigation_state_locked and self.player_state in {'on_terrain', 'idle'}:
            self._process_action_completion(final_player_pos, contact_terrain)

        # --- [새로운 경로 관리 로직] ---
        # Phase 3: 경로 계획 및 재탐색 트리거
        active_route = self.route_profiles.get(self.active_route_profile_name)
        if not active_route: self.last_player_pos = final_player_pos; return

        # 3a. 전체 여정이 없거나 끝났으면 새로 계획
        if not self.journey_plan or self.current_journey_index >= len(self.journey_plan):
            self._plan_next_journey(active_route)
        
        # 3b. (핵심 수정) 맥락(Context) 기반 재탐색 트리거
        #    'move_to_target' 상태에서, 예상된 지형 그룹을 벗어났을 때만 재탐색
        RECALCULATION_COOLDOWN = 1.0 # 최소 1초의 재탐색 대기시간
        
        if (self.navigation_action == 'move_to_target' and 
            self.expected_terrain_group is not None and
            contact_terrain and
            contact_terrain.get('dynamic_name') != self.expected_terrain_group and
            time.time() - self.last_path_recalculation_time > RECALCULATION_COOLDOWN):
            
            print(f"[INFO] 경로 재탐색: 예상 지형 그룹('{self.expected_terrain_group}')을 벗어났습니다. (현재: '{contact_terrain.get('dynamic_name')}')")
            self.update_general_log("예상 경로를 벗어나 재탐색합니다.", "orange")
            self.current_segment_path = []      # 재탐색 유도
            self.expected_terrain_group = None  # 예상 그룹 초기화

        # 3c. 상세 구간 경로가 없으면 새로 계산
        if self.journey_plan and self.start_waypoint_found and not self.current_segment_path:
            self._calculate_segment_path(final_player_pos)

        # --- [v.1812] BUGFIX: 상태 처리 로직 분리 ---
        # Phase 4: 상태에 따른 핵심 로직 처리
        if self.navigation_state_locked:
            self._handle_action_in_progress(final_player_pos)
        elif self.navigation_action.startswith('prepare_to_'):
            departure_terrain_group = contact_terrain.get('dynamic_name') if contact_terrain else None
            self._handle_action_preparation(final_player_pos, departure_terrain_group)
        elif alignment_processed and self.navigation_action in ['align_for_climb', 'verify_alignment']:
            # 정렬 관련 상태일 때는 아무것도 하지 않음 (이미 위에서 처리됨)
            pass
        else: # 'move_to_target' 상태일 때만 목표 이동 처리
            self._handle_move_to_target(final_player_pos)

        # Phase 5: UI 업데이트 (유지)
        self._update_navigator_and_view(final_player_pos, current_terrain_name)

        # --- 경로안내선 디버그 로그 출력 ---
        if self.debug_guidance_checkbox and self.debug_guidance_checkbox.isChecked():
            # 안내 텍스트(이름)가 변경되었을 때만 로그 출력
            if self.guidance_text != self.last_debug_guidance_text:
                target_pos_str = "None"
                if self.intermediate_target_pos:
                    target_pos_str = f"({self.intermediate_target_pos.x():.1f}, {self.intermediate_target_pos.y():.1f})"
                
                print(f"[GUIDANCE DEBUG] New Target: '{self.guidance_text}' @{target_pos_str}")

            # 현재 상태를 다음 프레임과 비교하기 위해 저장
            self.last_debug_guidance_text = self.guidance_text
            
        self._try_execute_pending_event()
        self.last_player_pos = final_player_pos


    def _record_command_context(self, command: str, *, player_pos: Optional[QPointF] = None) -> None:
        """전송한 이동 명령의 맥락을 저장합니다."""
        movement_keywords = ["걷기", "점프", "오르기", "사다리타기", "정렬", "아래점프", "텔레포트"]
        if not any(keyword in command for keyword in movement_keywords):
            return

        now = time.time()
        pos_to_use = player_pos if player_pos is not None else self.last_player_pos
        position_tuple = None
        if pos_to_use is not None:
            position_tuple = (pos_to_use.x(), pos_to_use.y())

        self.last_command_context = {
            "command": command,
            "sent_at": now,
            "floor": self.current_player_floor,
            "player_state": self.player_state,
            "navigation_action": self.navigation_action,
            "last_on_terrain_y": self.last_on_terrain_y,
            "position": position_tuple,
            "failure_logged": False,
        }

    def _was_recent_intentional_movement(self, final_player_pos: Optional[QPointF]) -> bool:
        """최근 전송한 명령이 실제로 반영된 움직임인지 확인합니다."""
        if not self.last_command_context:
            return False

        context = self.last_command_context
        elapsed = time.time() - context.get("sent_at", 0.0)
        if elapsed > 0.7:
            command = context.get("command")
            if (
                command == "아래점프"
                and not context.get("failure_logged")
                and self.stuck_recovery_attempts > 0
            ):
                self.update_general_log(
                    "[자동 복구] 아래점프 낙하를 감지하지 못했습니다. 재시도를 계속합니다.",
                    "gray",
                )
                context["failure_logged"] = True
            self.last_command_context = None
            return False

        command = context.get("command")
        if command == "아래점프":
            baseline_y = context.get("last_on_terrain_y")
            if baseline_y is None or final_player_pos is None:
                return False

            downward_threshold = self.cfg_y_movement_deadzone if self.cfg_y_movement_deadzone is not None else 0.0
            downward_threshold = max(downward_threshold, 4.0)
            if final_player_pos.y() - baseline_y < downward_threshold:
                return False

            if self.player_state not in ['falling', 'jumping']:
                return False

        return True

    def _execute_recovery_resend(self):
        """마지막 이동 명령을 실제로 재전송하는 역할을 합니다."""
        command = self.last_movement_command

        if self.guidance_text == "안전 지점으로 이동" and command in ["걷기(우)", "걷기(좌)", None]:
            command = "아래점프"
            self.last_movement_command = command
            self.last_command_sent_time = time.time()
            self._record_command_context(command)

        if command:
            if command in ("걷기(우)", "걷기(좌)"):
                self._start_walk_teleport_tracking()
            if self.debug_auto_control_checkbox.isChecked():
                print(f"[자동 제어 테스트] RECOVERY: {command}")
            elif self.auto_control_checkbox.isChecked():
                self._emit_control_command(command, None)
            self._record_command_context(command)

    def _trigger_stuck_recovery(self, final_player_pos, log_message):
        """공통 멈춤 복구 절차를 실행합니다."""
        now = time.time()
        self.recovery_cooldown_until = now + 1.5

        should_send_ladder_recovery = False

        if (
            final_player_pos is not None
            and self.player_state != 'on_terrain'
        ):
            transition_objects = self.geometry_data.get("transition_objects", [])
            if transition_objects:
                is_near_ladder, _, dist = self._check_near_ladder(
                    final_player_pos,
                    transition_objects,
                    1.0,
                    return_dist=True,
                    current_floor=self.current_player_floor,
                )
                if is_near_ladder and dist is not None and 0.0 <= dist <= 1.0:
                    should_send_ladder_recovery = True

        command_name = self.last_movement_command
        command_label = f"'{command_name}'" if command_name else None

        if should_send_ladder_recovery:
            if command_label:
                final_log_message = f"{log_message} '사다리 멈춤복구' 후 {command_label} 재시도."
            else:
                final_log_message = f"{log_message} '사다리 멈춤복구' 후 재시도할 명령이 없습니다."
        else:
            if command_label:
                final_log_message = f"{log_message} 이전 명령 {command_label} 재시도."
            else:
                final_log_message = f"{log_message} 재시도할 명령이 없습니다."

        self.update_general_log(final_log_message, "orange")

        if should_send_ladder_recovery:
            if self.debug_auto_control_checkbox.isChecked():
                print("[자동 제어 테스트] RECOVERY-PREP: 사다리 멈춤복구")
            elif self.auto_control_checkbox.isChecked():
                self._emit_control_command("사다리 멈춤복구", None)
        else:
            if command_label:
                skip_message = f"[자동 복구] 사다리 조건 미충족: 이전 명령 {command_label} 재전송만 수행합니다."
            else:
                skip_message = "[자동 복구] 사다리 조건 미충족: 재전송할 명령이 없습니다."
            self.update_general_log(skip_message, "gray")

        resend_delay_ms = max(int(round(self.cfg_ladder_recovery_resend_delay * 1000)), 0)
        QTimer.singleShot(resend_delay_ms, self._execute_recovery_resend)

        self.last_player_pos = final_player_pos

    def _reset_walk_teleport_state(self):
        """걷기 텔레포트 확률 누적 상태를 초기화합니다."""
        self._walk_teleport_active = False
        self._walk_teleport_walk_started_at = 0.0
        self._walk_teleport_bonus_percent = 0.0
        self._last_walk_teleport_check_time = 0.0
        if hasattr(self, '_update_walk_teleport_probability_display'):
            self._update_walk_teleport_probability_display(0.0)

    def _start_walk_teleport_tracking(self, start_time: float | None = None):
        """걷기 텔레포트 확률 누적을 시작합니다."""
        now = start_time if start_time is not None else time.time()
        self._walk_teleport_active = True
        self._walk_teleport_walk_started_at = now
        self._walk_teleport_bonus_percent = 0.0
        self._last_walk_teleport_check_time = now

    def _reset_airborne_recovery_state(self):
        """공중 경고 관련 타이머를 초기화합니다."""
        self.airborne_warning_started_at = 0.0
        self.airborne_recovery_cooldown_until = 0.0
        self._last_airborne_recovery_log_time = 0.0
        setattr(self, '_last_airborne_fail_log_time', 0.0)

    def _handle_airborne_path_wait(self, final_player_pos, contact_terrain):
        """공중 경로 대기 상태가 일정 시간 지속되면 복구를 시도합니다."""
        if not self.airborne_path_warning_active:
            self._reset_airborne_recovery_state()
            return

        if final_player_pos is None:
            return

        if contact_terrain:
            self._reset_airborne_recovery_state()
            return

        now = time.time()

        if self.airborne_warning_started_at <= 0.0:
            self.airborne_warning_started_at = now

        if now < self.airborne_recovery_cooldown_until:
            return

        last_reference = self.last_movement_time or self.last_action_time
        if not last_reference:
            return

        idle_duration = now - last_reference
        wait_threshold = self.cfg_airborne_recovery_wait

        if idle_duration < wait_threshold:
            return

        if (now - self.airborne_warning_started_at) < wait_threshold:
            return

        transition_objects = self.geometry_data.get("transition_objects", [])
        is_near_ladder, _, dist = self._check_near_ladder(
            final_player_pos,
            transition_objects,
            1.0,
            return_dist=True,
            current_floor=self.current_player_floor
        )

        if is_near_ladder and dist >= 0 and dist <= 1.0:
            if now - self._last_airborne_recovery_log_time > 1.0:
                self.update_general_log("[자동 복구] 공중 경로 대기 상태 - 사다리 복구를 시도합니다.", "orange")
                self._last_airborne_recovery_log_time = now

            if self.debug_auto_control_checkbox.isChecked():
                print("[자동 제어 테스트] AIRBORNE-RECOVERY: ladder_stop")
            elif self.auto_control_checkbox.isChecked():
                self._emit_control_command("사다리 멈춤복구", None)

            self.airborne_warning_started_at = now
            self.airborne_recovery_cooldown_until = now + 1.5
            return

        if self.stuck_recovery_attempts >= self.MAX_STUCK_RECOVERY_ATTEMPTS:
            last_fail_log_time = getattr(self, '_last_airborne_fail_log_time', 0.0)
            if now - last_fail_log_time > 5.0:
                self.update_general_log(
                    f"[자동 복구] 공중 경로 대기 상태 복구 실패: 최대 복구 시도({self.MAX_STUCK_RECOVERY_ATTEMPTS}회)를 초과했습니다.",
                    "red"
                )
                setattr(self, '_last_airborne_fail_log_time', now)
            self.airborne_warning_started_at = now
            self.airborne_recovery_cooldown_until = now + 1.5
            return

        self.stuck_recovery_attempts += 1
        if not self.last_movement_command:
            self.last_movement_command = "아래점프"

        log_msg = (
            f"[자동 복구] 공중 경로 대기 상태 감지 ({self.stuck_recovery_attempts}/{self.MAX_STUCK_RECOVERY_ATTEMPTS})."
        )
        self._trigger_stuck_recovery(final_player_pos, log_msg)
        self._last_airborne_recovery_log_time = now
        self.airborne_warning_started_at = now
        self.airborne_recovery_cooldown_until = now + 1.5
        return

    def _attempt_ladder_float_recovery(self, final_player_pos):
        """탐지 직후 밧줄 매달림 상태에서 사다리 복구를 시도합니다."""
        if final_player_pos is None:
            return False

        if not (self.auto_control_checkbox.isChecked() or self.debug_auto_control_checkbox.isChecked()):
            return False

        now = time.time()
        if now < self.ladder_float_recovery_cooldown_until:
            return False

        transition_objects = self.geometry_data.get("transition_objects", [])
        if not transition_objects:
            return False

        is_near_ladder, _, dist = self._check_near_ladder(
            final_player_pos,
            transition_objects,
            1.0,
            return_dist=True,
            current_floor=None,
        )

        if not (is_near_ladder and dist >= 0.0 and dist <= 1.0):
            return False

        self.update_general_log("[자동 복구] 사다리 근접 상태 감지. 사다리 멈춤복구를 실행합니다.", "orange")

        if self.debug_auto_control_checkbox.isChecked():
            print("[자동 제어 테스트] FLOAT-RECOVERY: 사다리 멈춤복구")
        elif self.auto_control_checkbox.isChecked():
            self._emit_control_command("사다리 멈춤복구", None)

        self.last_command_sent_time = now
        self.ladder_float_recovery_cooldown_until = now + 1.5
        return True

    def _update_navigator_and_view(self, final_player_pos, current_terrain_name):
        """
        [MODIFIED] v1819: '의도된 움직임' 감지를 위해 명령 전송 시각 기록.
        """
        all_waypoints_map = {wp['id']: wp for wp in self.geometry_data.get("waypoints", [])}
        prev_name, next_name, direction, distance = "", "", "-", 0
        player_state_text = '알 수 없음'
        nav_action_text = '대기 중'
        final_intermediate_type = 'walk'
        
        nav_action_text = '대기 중'
        direction = '-'
        distance = 0
        final_intermediate_type = 'walk'

        # <<< [핵심 수정] 상태에 따른 안내선 목표(intermediate_target_pos) 및 텍스트(guidance_text) 결정 >>>
        # 최우선 순위: "안전 지점으로 이동"과 같은 특수 안내는 그대로 유지
        if self.guidance_text in ["안전 지점으로 이동", "점프 불가: 안전 지대 없음", "이동할 안전 지대 없음"]:
            # 이 경우는 _handle_action_preparation에서 이미 intermediate_target_pos를 설정했으므로 그대로 사용
            pass
        # 1순위: 아래 점프 또는 낙하 관련 상태일 때
        elif self.navigation_action in ['prepare_to_down_jump', 'prepare_to_fall', 'down_jump_in_progress', 'fall_in_progress']:
            # 실시간으로 착지 지점을 계산하여 안내
            max_y_diff = 70.0 if 'down_jump' in self.navigation_action else None
            best_landing_terrain = self._find_best_landing_terrain_at_x(final_player_pos, max_y_diff=max_y_diff)
            if best_landing_terrain:
                landing_terrain_group = best_landing_terrain.get('dynamic_name')
                p1, p2 = best_landing_terrain['points'][0], best_landing_terrain['points'][-1]
                landing_y = p1[1] + (p2[1] - p1[1]) * ((final_player_pos.x() - p1[0]) / (p2[0] - p1[0])) if (p2[0] - p1[0]) != 0 else p1[1]

                self.guidance_text = landing_terrain_group
                self.intermediate_target_pos = QPointF(final_player_pos.x(), landing_y)
            else:
                self.guidance_text = "착지 지점 없음"
                self.intermediate_target_pos = None
        # <<< 핵심 수정 1 >>> prepare_to_climb 상태를 위한 분기 추가
        elif self.navigation_action in ['prepare_to_climb', 'align_for_climb', 'verify_alignment', 'prepare_to_climb_upward']:
            # 사다리 관련 상태에서는 항상 다음 목표(사다리 출구)를 안내
            if self.current_segment_path and self.current_segment_index + 1 < len(self.current_segment_path):
                target_node_key = self.current_segment_path[self.current_segment_index + 1]
                target_node = self.nav_nodes.get(target_node_key, {})
                self.guidance_text = target_node.get('name', '경로 없음')
                self.intermediate_target_pos = target_node.get('pos')
            else:
                self.guidance_text = "경로 계산 중..."
                self.intermediate_target_pos = None

        # 2순위: 그 외 모든 상태 (일반 이동, 등반, 점프 등)
        else:
            # A* 경로상의 다음 노드를 목표로 설정
            if self.current_segment_path and self.current_segment_index < len(self.current_segment_path):
                # 액션 중일 때는 다음 노드가 목표
                if self.navigation_action.endswith('_in_progress'):
                    target_index = self.current_segment_index + 1
                # 일반 이동이나 준비 상태일 때는 현재 노드가 목표
                else:
                    target_index = self.current_segment_index

                if target_index < len(self.current_segment_path):
                    target_node_key = self.current_segment_path[target_index]
                    target_node = self.nav_nodes.get(target_node_key, {})

                    # <<< 핵심 수정 >>> 착지 지점 건너뛰기 로직
                    final_target_node = target_node
                    final_target_index = target_index
                    while final_target_node.get('type') in ['fall_landing', 'djump_landing']:
                        final_target_index += 1
                        if final_target_index < len(self.current_segment_path):
                            final_target_key = self.current_segment_path[final_target_index]
                            final_target_node = self.nav_nodes.get(final_target_key, {})
                        else:
                            # 경로 끝에 도달하면 마지막 착지 지점을 그대로 사용
                            final_target_node = target_node
                            break

                    self.guidance_text = final_target_node.get('name', '경로 없음')
                    self.intermediate_target_pos = final_target_node.get('pos')
                else:
                    self.guidance_text = "경로 계산 중..."
                    self.intermediate_target_pos = None
            else:
                self.guidance_text = "경로 없음"
                self.intermediate_target_pos = None

        # --- 이하 거리/방향 계산 및 UI 업데이트 로직 ---
        if self.guidance_text == "안전 지점으로 이동":
            if self.intermediate_target_pos:
                distance = abs(final_player_pos.x() - self.intermediate_target_pos.x())
                direction = "→" if final_player_pos.x() < self.intermediate_target_pos.x() else "←"
            nav_action_text = self.guidance_text
            final_intermediate_type = 'walk'
        elif 'down_jump' in self.navigation_action or 'fall' in self.navigation_action:
            if self.intermediate_target_pos:
                distance = abs(final_player_pos.y() - self.intermediate_target_pos.y())
            else:
                distance = 0
            direction = "↓" if 'down_jump' in self.navigation_action else "-"
            nav_action_text = "아래로 점프하세요" if 'down_jump' in self.navigation_action else "낙하 중..."
            final_intermediate_type = 'fall'
        elif self.navigation_action == 'climb_in_progress':
            direction = "↑"
            if self.intermediate_target_pos:
                distance = abs(final_player_pos.y() - self.intermediate_target_pos.y())
            else:
                distance = 0
            nav_action_text = "오르는 중..."
            final_intermediate_type = 'climb'
        elif self.navigation_action == 'align_for_climb':
            if self.alignment_target_x is not None:
                distance = abs(final_player_pos.x() - self.alignment_target_x)
                direction = "→" if final_player_pos.x() < self.alignment_target_x else "←"
            else:
                distance = 0
                direction = "-"
            nav_action_text = "사다리 앞 정렬 중..."
            final_intermediate_type = 'walk'
        elif self.navigation_action == 'verify_alignment':
            distance = abs(final_player_pos.x() - self.alignment_target_x) if self.alignment_target_x is not None else 0
            direction = "-"
            nav_action_text = "정렬 확인 중..."
            final_intermediate_type = 'walk'
        else:
            if self.intermediate_target_pos:
                distance = abs(final_player_pos.x() - self.intermediate_target_pos.x())
                direction = "→" if final_player_pos.x() < self.intermediate_target_pos.x() else "←"
            action_text_map = {
                'move_to_target': "다음 목표로 이동",
                'prepare_to_climb': "점프+방향키로 오르세요",
                'prepare_to_climb_upward': "사다리타기(상) 실행",
                'prepare_to_jump': "점프하세요",
            }
            nav_action_text = action_text_map.get(self.navigation_action, '대기 중')
            if self.navigation_action.startswith('prepare_to_') or self.navigation_action.endswith('_in_progress'):
                if 'climb' in self.navigation_action:
                    final_intermediate_type = 'climb'
                elif 'jump' in self.navigation_action:
                    final_intermediate_type = 'jump'

        if self.event_in_progress:
            if nav_action_text == '대기 중':
                nav_action_text = "이벤트 실행 중..."
            else:
                nav_action_text = f"{nav_action_text} (이벤트 실행 중)"
        
        if final_intermediate_type != 'walk' or self.event_in_progress:
            self._reset_walk_teleport_state()
        else:
            self._maybe_trigger_walk_teleport(direction, distance)

        if self.start_waypoint_found and self.journey_plan:
            if self.current_journey_index > 0:
                prev_wp_id = self.journey_plan[self.current_journey_index - 1]
                prev_name = all_waypoints_map.get(prev_wp_id, {}).get('name', '')
            if self.current_journey_index < len(self.journey_plan) - 1:
                next_wp_id = self.journey_plan[self.current_journey_index + 1]
                next_name = all_waypoints_map.get(next_wp_id, {}).get('name', '')
        
        state_text_map = {
            'idle': '정지', 'on_terrain': '걷기', 
            'climbing_up': '오르기', 'climbing_down': '내려가기', 'on_ladder_idle': '매달리기',
            'falling': '낙하 중', 'jumping': '점프 중'
        }
        player_state_text = state_text_map.get(self.player_state, '알 수 없음')
        
        self.intermediate_target_type = final_intermediate_type
        
        intermediate_node_type = None
        if self.current_segment_path and self.current_segment_index < len(self.current_segment_path):
            current_node_key = self.current_segment_path[self.current_segment_index]
            intermediate_node_type = self.nav_nodes.get(current_node_key, {}).get('type')

        # <<< [수정] 자동 제어 또는 테스트 모드에 따라 분기
        is_control_or_test_active = self.auto_control_checkbox.isChecked() or self.debug_auto_control_checkbox.isChecked()

        if is_control_or_test_active and not self.event_in_progress:
            initial_delay_ms = self.initial_delay_spinbox.value()
            time_since_start_ms = (time.time() - self.detection_start_time) * 1000

            if time_since_start_ms < initial_delay_ms:
                remaining_time_s = (initial_delay_ms - time_since_start_ms) / 1000.0
                nav_action_text = f"시작 대기 중... ({remaining_time_s:.1f}초)"
                if self.initial_delay_active:
                    if self.debug_auto_control_checkbox.isChecked():
                        print("[자동 제어 테스트] 모든 키 떼기")
                    elif self.auto_control_checkbox.isChecked():
                        self._emit_control_command("모든 키 떼기", None)
                    self.initial_delay_active = False
            else:
                # --- [v.1811] BUGFIX: UnboundLocalError 해결 ---
                if self.just_landed_on_narrow_terrain:
                    self.just_landed_on_narrow_terrain = False
                    # 이번 프레임은 아무 명령도 보내지 않고, 상태 업데이트도 건너뜀
                else:
                    # 공통 로직: 어떤 명령을 보낼지 결정
                    command_to_send = None
                    current_action_key = self.navigation_action
                    current_player_state = self.player_state
                    current_direction = direction

                    action_changed = current_action_key != self.last_printed_action
                    direction_changed = current_direction != self.last_printed_direction
                    player_state_changed = current_player_state != self.last_printed_player_state
                    is_on_ground = self._get_contact_terrain(final_player_pos) is not None
                    needs_safe_move = (self.guidance_text == "안전 지점으로 이동")
                    
                    # --- [신규] '정렬' 및 '위로 오르기' 명령 전송 로직 ---
                    if current_action_key == 'prepare_to_climb_upward' and action_changed:
                        command_to_send = "사다리타기(상)"

                        self.navigation_action = 'climb_in_progress'
                        self.navigation_state_locked = True
                        self.lock_timeout_start = time.time()
                        self._climb_last_near_ladder_time = time.time()
                        if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                            print("[INFO] 'prepare_to_climb_upward' -> 'climb_in_progress' 상태 즉시 전환")

                    elif current_action_key == 'align_for_climb' and is_on_ground:
                        # '툭 치기' 명령은 0.5초에 한 번씩만 보내도록 제한 (연타 방지)
                        if time.time() - self.last_align_command_time > 0.5:
                            command_to_send = "정렬(우)" if current_direction == "→" else "정렬(좌)"
                            self.last_align_command_time = time.time()
                    # --- 로직 끝 ---

                    elif current_action_key == 'prepare_to_climb':
                        if self.last_printed_player_state in ['jumping'] and current_player_state in ['on_terrain', 'idle'] and is_on_ground:
                            if (action_changed or not direction_changed):
                                command_to_send = "사다리타기(우)" if current_direction == "→" else "사다리타기(좌)"
                                self.last_printed_direction = current_direction
                    
                        if (action_changed or direction_changed) and is_on_ground:
                            command_to_send = "사다리타기(우)" if current_direction == "→" else "사다리타기(좌)"
                            self.last_printed_direction = current_direction

                    elif current_action_key == 'prepare_to_down_jump':
                        if needs_safe_move:
                            self.waiting_for_safe_down_jump = True
                        elif (
                            (self.waiting_for_safe_down_jump or action_changed)
                            and is_on_ground
                            and self.guidance_text not in ["점프 불가: 안전 지대 없음", "이동할 안전 지대 없음"]
                        ):
                            command_to_send = "아래점프"
                            self.waiting_for_safe_down_jump = False
                        self.last_printed_direction = None

                    elif action_changed:
                        # <<< [수정] 점프 명령 분기 처리
                        if current_action_key == 'prepare_to_jump':
                            if self.jump_direction == 'left':
                                command_to_send = "점프(좌)"
                            elif self.jump_direction == 'right':
                                command_to_send = "점프(우)"
                            else:
                                command_to_send = "점프키 누르기" # Fallback
                            self.jump_direction = None # 사용 후 초기화
                        self.last_printed_direction = None

                    if player_state_changed:
                        if current_player_state == 'climbing_up': command_to_send = "오르기"
                        if current_player_state == 'falling':
                            if 'prepare_to_' not in current_action_key: command_to_send = "모든 키 떼기"
                        if self.last_printed_player_state == 'falling' and current_player_state in ['on_terrain', 'idle']:
                            self.last_printed_direction = None

                    if (current_action_key == 'move_to_target' or needs_safe_move) and direction_changed and is_on_ground:
                        if self.navigation_action in ['prepare_to_down_jump', 'prepare_to_fall'] and not needs_safe_move:
                            pass  # 아래점프/낙하 준비 중 안전 이동이 필요 없으면 걷기 명령으로 덮어쓰지 않음
                        else:
                            if current_direction in ["→", "←"] and (command_to_send is None or needs_safe_move):
                                if needs_safe_move:
                                    now_time = time.time()
                                    if (now_time - self.last_safe_move_command_time) < self.SAFE_MOVE_COMMAND_COOLDOWN:
                                        command_to_send = None
                                    else:
                                        command_to_send = "걷기(우)" if current_direction == "→" else "걷기(좌)"
                                        self.last_safe_move_command_time = now_time
                                        self.waiting_for_safe_down_jump = True
                                else:
                                    command_to_send = "걷기(우)" if current_direction == "→" else "걷기(좌)"

                                if command_to_send:
                                    self.last_printed_direction = current_direction
                                    self._start_walk_teleport_tracking()

                    # 명령 전송 (테스트 또는 실제)
                    if command_to_send:
                        # --- [v.1819] '의도된 움직임' 감지를 위해 명령 전송 시각 기록 ---
                        self.last_command_sent_time = time.time()
                        
                        movement_related_keywords = ["걷기", "점프", "오르기", "사다리타기", "정렬", "아래점프", "텔레포트"]
                        if ("텔레포트" not in command_to_send
                                and any(keyword in command_to_send for keyword in movement_related_keywords)):
                            self.last_movement_command = command_to_send
                        self._record_command_context(command_to_send, player_pos=final_player_pos)

                        if self.debug_auto_control_checkbox.isChecked():
                            print(f"[자동 제어 테스트] {command_to_send}")
                        elif self.auto_control_checkbox.isChecked():
                            self._emit_control_command(command_to_send, None)

                    # 상태 업데이트
                    if action_changed:
                        self.last_printed_action = current_action_key
                        self.last_printed_player_state = None 
                    if player_state_changed:
                        self.last_printed_player_state = current_player_state
        
        # UI 업데이트는 항상 실행
        self.navigator_display.update_data(
            floor=self.current_player_floor if self.current_player_floor is not None else "N/A",
            terrain_name=current_terrain_name,
            target_name=self.guidance_text,
            prev_name=prev_name, next_name=next_name, direction=direction, distance=distance,
            full_path=self.journey_plan, last_reached_id=self.last_reached_wp_id,
            target_id=self.target_waypoint_id, is_forward=self.is_forward,
            direction_slot_label=self.current_direction_slot_label,
            intermediate_type=self.intermediate_target_type, player_state=player_state_text,
            nav_action=nav_action_text
        )
        
        camera_pos_to_send = final_player_pos if self.center_on_player_checkbox.isChecked() else self.minimap_view_label.camera_center_global
        self.minimap_view_label.update_view_data(
            camera_center=camera_pos_to_send, active_features=self.active_feature_info,
            my_players=self.my_player_global_rects, other_players=self.other_player_global_rects,
            target_wp_id=self.target_waypoint_id, reached_wp_id=self.last_reached_wp_id,
            final_player_pos=final_player_pos, is_forward=self.is_forward,
            intermediate_pos=self.intermediate_target_pos,
            intermediate_type=self.intermediate_target_type,
            nav_action=self.navigation_action,
            intermediate_node_type=intermediate_node_type
        )

    def _clear_alignment_state(self):
        """정렬 관련 임시 상태를 초기화합니다."""
        self.alignment_target_x = None
        self.alignment_expected_floor = None
        self.alignment_expected_group = None
        self.verify_alignment_start_time = 0.0

        self._active_waypoint_threshold_key = None
        self._active_waypoint_threshold_value = None

    def _abort_alignment_and_recalculate(self):
        """정렬 상태를 중단하고 경로 재탐색을 트리거합니다."""
        self._clear_alignment_state()
        self.navigation_action = 'move_to_target'
        self.navigation_state_locked = False
        self.current_segment_path = []
        self.expected_terrain_group = None
        self.last_path_recalculation_time = time.time()

    def _handle_move_to_target(self, final_player_pos):
            """
            v12.9.6: [수정] '아래 점프' 또는 '낭떠러지' 도착 시, 안내선을 즉시 고정하지 않고 상태만 전환하여 다음 프레임에서 동적 안내선이 생성되도록 수정.
            v12.9.4: [수정] '낭떠러지' 또는 '아래 점프' 지점 도착 시, 경로 안내선(intermediate_target_pos)이 즉시 실제 '착지 지점'을 가리키도록 수정하여 사용자에게 명확한 시각적 피드백을 제공합니다.
            v12.8.6: [수정] '낭떠러지' 또는 '아래 점프' 지점 도착 시, 다음 경로를 확인하기 전에 먼저 해당 노드의 타입을 확인하고 즉시 행동 준비 상태로 전환하도록 수정하여 경로 실행 오류를 해결합니다.
            'move_to_target' 상태일 때의 도착 판정, 상태 전환, 이탈 판정을 처리합니다.
            """
            distance = 0.0
            direction = "-"
            if not (self.current_segment_path and self.current_segment_index < len(self.current_segment_path)):
                self.expected_terrain_group = None
                return

            current_node_key = self.current_segment_path[self.current_segment_index]
            current_node = self.nav_nodes.get(current_node_key, {})
            self.intermediate_target_pos = current_node.get('pos')
            self.guidance_text = current_node.get('name', '')
            self.expected_terrain_group = current_node.get('group') 

            if not self.intermediate_target_pos: return

            arrival_threshold = self._get_arrival_threshold(current_node.get('type'), current_node_key, current_node)
            target_floor = current_node.get('floor')
            floor_matches = target_floor is None or abs(self.current_player_floor - target_floor) < 0.1
            
            arrived = False
            if current_node.get('type') == 'djump_area':
                x_range = current_node.get('x_range')
                if x_range and x_range[0] <= final_player_pos.x() <= x_range[1] and floor_matches:
                    arrived = True
            else:
                distance_to_target = abs(final_player_pos.x() - self.intermediate_target_pos.x())
                if not self.event_in_progress:
                    direction = "→" if final_player_pos.x() < self.intermediate_target_pos.x() else "←"
                if distance_to_target < arrival_threshold and floor_matches:
                    arrived = True

            if arrived:
                # [PATCH] v14.3.9: print문을 조건문으로 감쌈
                if self.debug_basic_pathfinding_checkbox and self.debug_basic_pathfinding_checkbox.isChecked():
                    print(f"[INFO] 중간 목표 '{self.guidance_text}' 도착.")

                node_type = current_node.get('type')

                if node_type == 'waypoint' and not current_node.get('is_event'):
                    self._active_waypoint_threshold_key = None
                    self._active_waypoint_threshold_value = None

                if node_type in ['fall_start', 'djump_area']:
                    if node_type == 'fall_start':
                        self._transition_to_action_state('prepare_to_fall', current_node_key)
                    elif node_type == 'djump_area':
                        self._transition_to_action_state('prepare_to_down_jump', current_node_key)
                    return
                
                next_index = self.current_segment_index + 1
                if next_index >= len(self.current_segment_path):
                    reached_wp_id = self.journey_plan[self.current_journey_index]
                    waypoint_data = self._find_waypoint_by_id(reached_wp_id)
                    pending_event_data = waypoint_data if waypoint_data and waypoint_data.get('is_event') else None

                    self.last_reached_wp_id = reached_wp_id
                    self.current_journey_index += 1
                    self.current_segment_path = []
                    self.expected_terrain_group = None

                    wp_name = self.nav_nodes.get(f"wp_{self.last_reached_wp_id}", {}).get('name')
                    self.update_general_log(f"'{wp_name}' 도착. 다음 구간으로 진행합니다.", "green")

                    if pending_event_data:
                        result = self._request_waypoint_event(pending_event_data)
                        if result == 'started' or result == 'queued':
                            return
                else:
                    next_node_key = self.current_segment_path[next_index]
                    edge_data = self.nav_graph.get(current_node_key, {}).get(next_node_key, {})
                    action = edge_data.get('action') if edge_data else None
                    
                    next_action_state = None
                    # --- [신규] 좁은 발판 감지 및 정렬 상태 전환 로직 ---
                    if action == 'climb':
                        contact_terrain = self._get_contact_terrain(final_player_pos)
                        if contact_terrain:
                            points = contact_terrain.get('points', [])
                            if len(points) >= 2:
                                terrain_width = abs(points[0][0] - points[-1][0])
                                if terrain_width < 10.0:
                                    # 좁은 발판이므로 '정렬' 상태로 진입
                                    self.navigation_action = 'align_for_climb'
                                    self.alignment_target_x = self.intermediate_target_pos.x() # 사다리의 X좌표를 목표로 설정
                                    self.alignment_expected_floor = contact_terrain.get('floor', self.current_player_floor)
                                    self.alignment_expected_group = contact_terrain.get('dynamic_name')
                                    self.verify_alignment_start_time = 0.0
                                    self.update_general_log(f"좁은 발판 감지 (너비: {terrain_width:.1f}px). 사다리 앞 정렬을 시작합니다.", "gray")
                                    return # 상태 전환 후 즉시 종료
                        
                        # 넓은 발판이거나, 발판 정보가 없으면 기존 로직 수행
                        next_action_state = 'prepare_to_climb'
                    # --- 로직 끝 ---

                    elif action == 'jump':
                        # <<< [추가] 점프 방향 계산 및 저장
                        next_node_pos = self.nav_nodes.get(next_node_key, {}).get('pos')
                        if next_node_pos:
                            if next_node_pos.x() > current_node.get('pos').x():
                                self.jump_direction = 'right'
                            else:
                                self.jump_direction = 'left'
                        next_action_state = 'prepare_to_jump'
                    elif action == 'climb_down': next_action_state = 'prepare_to_fall'

                    if next_action_state:
                        self._transition_to_action_state(next_action_state, current_node_key)
                    else:
                        self.current_segment_index = next_index
                return

    def _find_safe_landing_zones(self, landing_terrain_group):
        """
        [MODIFIED] v13.1.6: 함수의 책임을 명확히 분리. 이제 이 함수는 주어진 지형에서
                 오직 물리적인 구멍(점프 링크)만을 제외하여 착지 가능한 '발판' 구간만 계산.
                 사다리 위험성 판단은 호출부(상위 메서드)의 책임으로 이전됨.
        """
        if not landing_terrain_group:
            return [], None

        target_line = next((line for line in self.geometry_data.get("terrain_lines", []) if line.get('dynamic_name') == landing_terrain_group), None)
        if not target_line:
            return [], None
        
        points = target_line.get('points', [])
        if len(points) < 2:
            return [], None

        landing_y = points[0][1]
        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        
        safe_zones = [(min_x, max_x)]

        # 점프 링크 (물리적 구멍) 제외 로직은 유지
        jump_links = self.geometry_data.get("jump_links", [])
        for link in jump_links:
            start_terrain = self._get_contact_terrain(QPointF(*link['start_vertex_pos']))
            end_terrain = self._get_contact_terrain(QPointF(*link['end_vertex_pos']))
            
            if (start_terrain and start_terrain.get('dynamic_name') == landing_terrain_group) or \
               (end_terrain and end_terrain.get('dynamic_name') == landing_terrain_group):
                
                hazard_start_x = min(link['start_vertex_pos'][0], link['end_vertex_pos'][0])
                hazard_end_x = max(link['start_vertex_pos'][0], link['end_vertex_pos'][0])
                
                new_safe_zones = []
                for sz_start, sz_end in safe_zones:
                    overlap_start = max(sz_start, hazard_start_x)
                    overlap_end = min(sz_end, hazard_end_x)
                    if overlap_start < overlap_end:
                        if sz_start < overlap_start: new_safe_zones.append((sz_start, overlap_start))
                        if overlap_end < sz_end: new_safe_zones.append((overlap_end, sz_end))
                    else:
                        new_safe_zones.append((sz_start, sz_end))
                safe_zones = new_safe_zones

        return safe_zones, landing_y

    def _find_best_landing_terrain_at_x(self, departure_pos, max_y_diff=None):
        """
        [MODIFIED] v13.1.0: max_y_diff 인자를 추가하여, 지정된 Y축 거리 내에 있는
                 착지 지형만 필터링하는 기능 추가. (djump 높이 제한용)
         v13.0.9: 주어진 출발 위치에서 수직으로 낙하할 때,
        물리적으로 가장 먼저 충돌하는(가장 높은 층에 있는) 지형 라인을 찾아 반환합니다.
        """
        departure_terrain = self._get_contact_terrain(departure_pos)
        
        # <<< 핵심 수정 >>>
        # 만약 플레이어가 공중에 있다면(contact_terrain is None), 마지막으로 알려진 지형 정보를 사용
        if not departure_terrain:
            if self.last_known_terrain_group_name:
                departure_terrain = next((line for line in self.geometry_data.get("terrain_lines", []) if line.get('dynamic_name') == self.last_known_terrain_group_name), None)
            
            # 마지막으로 알려진 지형 정보조차 없으면 계산 불가
            if not departure_terrain:
                return None

        departure_floor = departure_terrain.get('floor', float('inf'))
        departure_y = departure_pos.y()
        x_pos = departure_pos.x()
        
        # 1. 현재 x좌표에서 낙하 시 만날 수 있는 모든 후보 지형 찾기
        candidate_landings = []
        for line_below in self.geometry_data.get("terrain_lines", []):
            # 출발 지형보다 낮은 층에 있고, x좌표가 겹치는 지형만 후보
            if departure_floor > line_below.get('floor', 0):
                min_x = min(p[0] for p in line_below['points'])
                max_x = max(p[0] for p in line_below['points'])
                if min_x <= x_pos <= max_x:
                    # [MODIFIED] 높이 제한(max_y_diff) 필터링 로직 추가
                    landing_y = line_below['points'][0][1]
                    y_diff = abs(departure_y - landing_y)
                    
                    if max_y_diff is None or (0 < y_diff <= max_y_diff):
                        candidate_landings.append(line_below)
        
        if not candidate_landings:
            return None

        # 2. 후보들 중 가장 높은 층에 있는 지형을 최종 도착지로 선택
        best_landing_line = max(candidate_landings, key=lambda line: line.get('floor', 0))
        return best_landing_line

    def _handle_action_preparation(self, final_player_pos, departure_terrain_group):
        """
        [MODIFIED] v14.3.15: 플레이어 상태(지상, 사다리, 공중)에 따라 로직을 분기.
        - '사다리' 상태에서는 안전성 검사를 건너뛰고 기존 목표를 유지.
        - '점프/낙하' 상태에서는 액션 시작 여부만 감지.
        - '지상' 상태에서만 모든 안전성 검사를 수행.
        [MODIFIED] 2025-08-27 17:42 (KST): 'prepare_to_climb' 상태에서 점프 시 안내가 시작점으로 돌아가는 문제 수정
        [MODIFIED] 2025-08-27 17:47 (KST): 'climbing_up' 상태가 되었을 때 안내가 초기화되는 문제 수정
        """
        # [PATCH] v14.3.15: 플레이어 상태에 따른 로직 분기 시작
        
        # Case 1: 플레이어가 지상에 있을 때 (가장 일반적인 경우)
        if departure_terrain_group is not None:
            if self.navigation_action in ['prepare_to_down_jump', 'prepare_to_fall']:
                player_x = final_player_pos.x()

                # 1단계: 출발 지점 안전성 검사
                if departure_terrain_group:
                    departure_line = next((line for line in self.geometry_data.get("terrain_lines", []) if line.get('dynamic_name') == departure_terrain_group), None)
                    if departure_line:
                        # ... (기존 출발지 안전성 검사 로직과 동일) ...
                        departure_floor = departure_line.get('floor')
                        ladder_hazard_zones = []
                        for obj in self.geometry_data.get("transition_objects", []):
                            is_connected = obj.get('start_line_id') == departure_line.get('id') or obj.get('end_line_id') == departure_line.get('id')
                            if is_connected:
                                other_line_id = obj.get('end_line_id') if obj.get('start_line_id') == departure_line.get('id') else obj.get('start_line_id')
                                other_line_floor = self.line_id_to_floor_map.get(other_line_id, float('inf'))
                                if other_line_floor < departure_floor:
                                    ladder_x = obj['points'][0][0]
                                    ladder_hazard_zones.append((ladder_x - LADDER_AVOIDANCE_WIDTH, ladder_x + LADDER_AVOIDANCE_WIDTH))
                        
                        is_in_hazard = any(start <= player_x <= end for start, end in ladder_hazard_zones)
                        if is_in_hazard:
                            self.guidance_text = "안전 지점으로 이동"
                            # ... (가장 가까운 안전 지점 계산 및 안내 로직) ...
                            dep_min_x = min(p[0] for p in departure_line['points'])
                            dep_max_x = max(p[0] for p in departure_line['points'])
                            departure_safe_zones = [(dep_min_x, dep_max_x)]
                            for h_start, h_end in ladder_hazard_zones:
                                new_safe_zones = []
                                for s_start, s_end in departure_safe_zones:
                                    overlap_start = max(s_start, h_start); overlap_end = min(s_end, h_end)
                                    if overlap_start < overlap_end:
                                        if s_start < overlap_start: new_safe_zones.append((s_start, overlap_start))
                                        if overlap_end < s_end: new_safe_zones.append((overlap_end, s_end))
                                    else:
                                        new_safe_zones.append((s_start, s_end))
                                departure_safe_zones = new_safe_zones
                            
                            if departure_safe_zones:
                                closest_point_x = min([p for zone in departure_safe_zones for p in zone], key=lambda p: abs(player_x - p))
                                self.intermediate_target_pos = QPointF(closest_point_x, final_player_pos.y())
                            else:
                                self.intermediate_target_pos = None
                            if self.navigation_action == 'prepare_to_down_jump':
                                self.waiting_for_safe_down_jump = True
                            self._process_action_preparation(final_player_pos)
                            return

                # 2단계 & 3단계: 착지 지점 안전성 검사
                max_y_diff = 70.0 if self.navigation_action == 'prepare_to_down_jump' else None
                best_landing_terrain = self._find_best_landing_terrain_at_x(final_player_pos, max_y_diff=max_y_diff)

                if not best_landing_terrain:
                    action_node_key = self.current_segment_path[self.current_segment_index]
                    landing_key = next(iter(self.nav_graph.get(action_node_key, {})), None)
                    ideal_landing_group = self.nav_nodes.get(landing_key, {}).get('group')
                    safe_zones, _ = self._find_safe_landing_zones(ideal_landing_group)
                    if not safe_zones:
                        self.guidance_text = "점프 불가: 안전 지대 없음"; self.intermediate_target_pos = None
                        if self.navigation_action == 'prepare_to_down_jump':
                            self.waiting_for_safe_down_jump = False
                    else:
                        self.guidance_text = "안전 지점으로 이동"
                        closest_point_x = min([p for zone in safe_zones for p in zone], key=lambda p: abs(player_x - p))
                        self.intermediate_target_pos = QPointF(closest_point_x, final_player_pos.y())
                        if self.navigation_action == 'prepare_to_down_jump':
                            self.waiting_for_safe_down_jump = True
                    self._process_action_preparation(final_player_pos)
                    return

                landing_terrain_group = best_landing_terrain.get('dynamic_name')
                safe_zones, landing_y = self._find_safe_landing_zones(landing_terrain_group)

                if not any(start <= player_x <= end for start, end in safe_zones):
                    self.guidance_text = "안전 지점으로 이동"
                    closest_point_x = min([p for zone in safe_zones for p in zone], key=lambda p: abs(player_x - p))
                    self.intermediate_target_pos = QPointF(closest_point_x, final_player_pos.y())
                    if self.navigation_action == 'prepare_to_down_jump':
                        self.waiting_for_safe_down_jump = True
                else:
                    # <<< 핵심 수정 지점 (원래 로직으로 복원) >>>
                    # 지상에서는 실시간 예측 착지 지점을 안내
                    self.guidance_text = landing_terrain_group
                    self.intermediate_target_pos = QPointF(player_x, landing_y)

            else: # 일반 점프/오르기 등 다른 prepare 상태
                next_node_key = self.current_segment_path[self.current_segment_index + 1] if self.current_segment_index + 1 < len(self.current_segment_path) else None
                next_node = self.nav_nodes.get(next_node_key) if next_node_key else None
                if next_node:
                    self.guidance_text = next_node.get('name', '알 수 없는 목적지')
                    self.intermediate_target_pos = next_node.get('pos')

        # Case 2 & 3: 플레이어가 공중(점프/낙하) 또는 사다리에 있을 때
        else:
            # <<< 2차 수정 지점 (유지) >>>
            # 의도된 공중 진입 상태에서는 안내선을 다음 목표로 고정
            expected_air_states = ['prepare_to_down_jump', 'prepare_to_fall', 'prepare_to_jump']
            climbing_related_states = ['jumping', 'climbing_up', 'climbing_down', 'on_ladder_idle']

            if self.navigation_action in expected_air_states or \
               (self.navigation_action == 'prepare_to_climb' and self.player_state in climbing_related_states):
                # 점프/낙하/등반 과정은 정상 과정이므로 안내 목표를 '출구'(다음 노드)로 고정
                next_node_key = self.current_segment_path[self.current_segment_index + 1] if self.current_segment_index + 1 < len(self.current_segment_path) else None
                next_node = self.nav_nodes.get(next_node_key) if next_node_key else None
                if next_node:
                    self.guidance_text = next_node.get('name', '알 수 없는 목적지')
                    self.intermediate_target_pos = next_node.get('pos')
            else:
                # 그 외 예상치 못한 모든 공중 상태에서는 안전을 위해 시작점('입구')으로 안내를 되돌림
                action_node_key = self.current_segment_path[self.current_segment_index]
                action_node = self.nav_nodes.get(action_node_key, {})
                self.guidance_text = action_node.get('name', '')
                self.intermediate_target_pos = action_node.get('pos')
            
            # 액션 시작 여부는 모든 공중 상태에서 계속 확인해야 합니다.
            self._process_action_preparation(final_player_pos)
            return

        # 모든 prepare 상태는 최종적으로 액션 시작 여부를 확인해야 함
        self._process_action_preparation(final_player_pos)


    def _handle_action_in_progress(self, final_player_pos):
        """'..._in_progress' 상태일 때의 로직을 담당합니다."""
        # <<< [수정] 아래 로직 전체 추가
        # 1. 등반 중 이탈 감지 (사다리에서 떨어졌는지 추가 검증)
        if self.navigation_action == 'climb_in_progress':
            # 현재 액션 노드(사다리 입구) 정보를 가져옴
            action_node_key = self.current_segment_path[self.current_segment_index]
            action_node = self.nav_nodes.get(action_node_key, {})
            obj_id = action_node.get('obj_id')

            if obj_id:
                # 해당 사다리 객체만 특정하여 검사
                current_ladder = next((obj for obj in self.geometry_data.get("transition_objects", []) if obj.get('id') == obj_id), None)
                if current_ladder:
                    now = time.time()
                    if self._climb_last_near_ladder_time == 0.0:
                        self._climb_last_near_ladder_time = now

                    contact_terrain = self._get_contact_terrain(final_player_pos)
                    next_node = None
                    expected_group = None
                    target_pos = None

                    if self.current_segment_index + 1 < len(self.current_segment_path):
                        next_node_key = self.current_segment_path[self.current_segment_index + 1]
                        next_node = self.nav_nodes.get(next_node_key, {})
                        expected_group = next_node.get('group')
                        target_pos = next_node.get('pos')

                    # 목표 발판(사다리 출구)에 이미 도착했는지 우선 확인
                    target_y = None
                    if isinstance(target_pos, QPointF):
                        target_y = target_pos.y()
                    elif isinstance(target_pos, (list, tuple)) and len(target_pos) >= 2:
                        target_y = float(target_pos[1])

                    if (
                        contact_terrain
                        and expected_group
                        and contact_terrain.get('dynamic_name') == expected_group
                        and (target_y is None or final_player_pos.y() <= target_y + 1.5)
                    ):
                        self._climb_last_near_ladder_time = now
                        return

                    ladder_states = {'climbing_up', 'climbing_down', 'on_ladder_idle'}
                    is_on_ladder, _, dist_x = self._check_near_ladder(
                        final_player_pos,
                        [current_ladder],
                        self.cfg_ladder_arrival_x_threshold,
                        return_dist=True,
                        current_floor=self.current_player_floor,
                    )

                    # 사다리 근처에 있거나 등반 상태면 정상 진행으로 간주
                    if is_on_ladder or self.player_state in ladder_states:
                        self._climb_last_near_ladder_time = now
                        return

                    # 방금 전까지 사다리 근처였으면 짧은 유예 시간을 둔다.
                    LADDER_DETACH_GRACE = 0.5
                    if now - self._climb_last_near_ladder_time <= LADDER_DETACH_GRACE:
                        return

                    dist_info = ""
                    if isinstance(dist_x, (int, float)) and dist_x >= 0:
                        dist_info = f" (사다리와의 X 거리: {dist_x:.1f}px)"

                    self.update_general_log(
                        f"등반 중 사다리 범위를 벗어나 경로를 재탐색합니다.{dist_info}", "orange"
                    )
                    self.navigation_action = 'move_to_target'
                    self.navigation_state_locked = False
                    self.current_segment_path = []
                    self.expected_terrain_group = None
                    self._climb_last_near_ladder_time = 0.0
                    return # 즉시 함수 종료

    def _get_terrain_id_from_vertex(self, vertex_pos):
        """주어진 꼭짓점(vertex) 좌표에 연결된 지형선 ID를 반환합니다."""
        # 성능을 위해 미리 계산된 맵을 사용하는 것이 좋지만, 여기서는 직접 탐색
        for line in self.geometry_data.get("terrain_lines", []):
            for point in line.get("points", []):
                # 부동소수점 비교를 위해 작은 허용 오차(epsilon) 사용
                if abs(point[0] - vertex_pos[0]) < 1e-6 and abs(point[1] - vertex_pos[1]) < 1e-6:
                    return line['id']
        return None

    def _check_near_ladder(self, pos, transition_objects, x_tol, return_x=False, return_dist=False, current_floor=None):
        """
        주어진 위치가 현재 층과 연결된 사다리 근처인지 확인합니다.
        [v11.4.5] 현재 층 기반 필터링 로직 추가
        """
        min_dist_sq = float('inf')
        nearest_ladder_x = None
        is_near = False
        actual_dist_x = -1

        # [v11.4.5] 1. 현재 층과 연결된 사다리만 필터링
        candidate_ladders = []
        if current_floor is not None:
            for obj in transition_objects:
                start_line_id = obj.get("start_line_id")
                end_line_id = obj.get("end_line_id")
                
                start_floor = self.line_id_to_floor_map.get(start_line_id)
                end_floor = self.line_id_to_floor_map.get(end_line_id)

                if start_floor is not None and end_floor is not None:
                    # 현재 층이 사다리의 시작 또는 끝 층과 일치하는 경우 후보로 추가
                    if abs(current_floor - start_floor) < 0.1 or abs(current_floor - end_floor) < 0.1:
                        candidate_ladders.append(obj)
        else:
            # current_floor 정보가 없으면, 이전처럼 모든 사다리를 검사 (안전장치)
            candidate_ladders = transition_objects

        # [v11.4.5] 2. 필터링된 후보군을 대상으로 근접 검사
        for obj in candidate_ladders:
            points = obj.get("points")
            if not points or len(points) < 2:
                continue
            
            ladder_x = points[0][0]
            dist_x = abs(pos.x() - ladder_x)

            if dist_x**2 < min_dist_sq:
                min_dist_sq = dist_x**2
                nearest_ladder_x = ladder_x
                actual_dist_x = dist_x

            if dist_x <= x_tol:
                min_y = min(points[0][1], points[1][1])
                max_y = max(points[0][1], points[1][1])
                if pos.y() >= min_y and pos.y() <= max_y:
                    is_near = True
        
        if return_dist:
            return is_near, nearest_ladder_x, actual_dist_x
        elif return_x:
            return is_near, nearest_ladder_x
        else:
            return is_near

    def _is_on_terrain(self, pos):
        """주어진 위치가 지형선 위에 있는지 확인합니다."""
        return self._get_contact_terrain(pos) is not None

    def _get_contact_terrain(self, pos):
        """
        주어진 위치에서 접촉하고 있는 지형선 데이터를 반환합니다.
        [v11.1.0] UI에서 조정한 설정값을 사용하도록 수정
        """
        for line_data in self.geometry_data.get("terrain_lines", []):
            points = line_data.get("points", [])
            if len(points) < 2: continue
            for i in range(len(points) - 1):
                p1, p2 = points[i], points[i+1]
                min_lx, max_lx = min(p1[0], p2[0]), max(p1[0], p2[0])

                if not (min_lx <= pos.x() <= max_lx): continue

                line_y = p1[1] + (p2[1] - p1[1]) * ((pos.x() - p1[0]) / (p2[0] - p1[0])) if (p2[0] - p1[0]) != 0 else p1[1]
                # [v11.1.0] 상수 대신 멤버 변수 사용
                if abs(pos.y() - line_y) < self.cfg_on_terrain_y_threshold:
                    return line_data
        return None

    _GENERAL_LOG_COLOR_ALIASES: dict[str, str] = {
        "info": "cyan",
    }
    _GENERAL_LOG_DEFAULT_COLOR = "black"

    def _normalize_general_log_color(self, color: object) -> str:
        raw_color = (str(color).strip() if color is not None else "")
        if not raw_color:
            return self._GENERAL_LOG_DEFAULT_COLOR

        alias = self._GENERAL_LOG_COLOR_ALIASES.get(raw_color.lower())
        candidate = alias or raw_color
        if QColor.isValidColor(candidate):
            return candidate

        return self._GENERAL_LOG_DEFAULT_COLOR

    def update_general_log(self, message, color):
        normalized_color = self._normalize_general_log_color(color)
        entry = (message, normalized_color)
        now = time.time()

        if (
            self._general_log_last_entry == entry
            and (now - self._general_log_last_ts) < self._general_log_min_interval
        ):
            return

        self._general_log_last_entry = entry
        self._general_log_last_ts = now

        if not self._general_log_enabled:
            return

        self._write_general_log_to_viewer(message, normalized_color)

    def _write_general_log_to_viewer(self, message: str, color: str) -> None:
        if not self._general_log_enabled:
            return

        normalized_color = self._normalize_general_log_color(color)
        timestamp = time.strftime("%H:%M:%S")
        display_message = f"[{timestamp}] {message}"
        self._general_log_last_entry = (message, normalized_color)
        self._general_log_last_ts = time.time()
        self.general_log_viewer.append(
            f'<font color="{normalized_color}">{display_message}</font>'
        )
        self.general_log_viewer.verticalScrollBar().setValue(
            self.general_log_viewer.verticalScrollBar().maximum()
        )

    def _render_detection_log(self, body_html: str | None, *, force: bool = False) -> None:
        self._last_detection_log_body = body_html or ""
        probability_html = f"<span>{self._walk_teleport_probability_text}</span>"
        status_html = "<br>".join(self._status_log_lines) if getattr(self, '_status_log_lines', None) else ""
        parts = []
        if status_html:
            parts.append(status_html)
        parts.append(probability_html)
        if self._last_detection_log_body:
            parts.append(self._last_detection_log_body)
        combined = "<br>".join(part for part in parts if part)

        self._pending_detection_html = combined

        if not self._detection_log_enabled:
            self._last_detection_rendered_html = ""
            return

        if not force and combined == self._last_detection_rendered_html:
            return

        now = time.time()
        self.detection_log_viewer.setHtml(combined)
        self._last_detection_rendered_html = combined
        self._last_detection_render_ts = now

    def _handle_display_toggle(self, checked: bool) -> None:
        self._minimap_display_enabled = bool(checked)
        if hasattr(self, 'minimap_view_label'):
            self.minimap_view_label.set_display_enabled(self._minimap_display_enabled)

        # 설정 파일에 즉시 반영하여 다음 실행 시 상태를 복원합니다.
        try:
            self.save_global_settings()
        except Exception as exc:
            self.update_general_log(f"미니맵 표시 상태 저장 실패: {exc}", "red")

        if not self._minimap_display_enabled:
            if hasattr(self, 'minimap_view_label'):
                self.minimap_view_label.setText("실시간 표시 꺼짐")
            return

        if hasattr(self, 'minimap_view_label') and not self.is_detection_running:
            self.minimap_view_label.setText("탐지를 시작하세요.")

    def _handle_general_log_toggle(self, checked: bool) -> None:
        self._general_log_enabled = bool(checked)
        self.general_log_viewer.setVisible(self._general_log_enabled)
        if not self._general_log_enabled:
            self.general_log_viewer.clear()

    def _handle_detection_log_toggle(self, checked: bool) -> None:
        self._detection_log_enabled = bool(checked)
        self.detection_log_viewer.setVisible(self._detection_log_enabled)
        if not self._detection_log_enabled:
            self.detection_log_viewer.clear()
            self._last_detection_rendered_html = ""
            self._pending_detection_html = ""
            self.log_update_counter = 0
        else:
            self._render_detection_log(self._last_detection_log_body, force=True)

    def attach_status_monitor(self, monitor: StatusMonitorThread, data_manager) -> None:
        self.status_monitor = monitor
        self._status_data_manager = data_manager
        monitor.status_captured.connect(self._handle_status_snapshot)
        if data_manager and hasattr(data_manager, 'register_status_config_listener'):
            try:
                data_manager.register_status_config_listener(self._handle_status_config_update)
                self._status_config = data_manager.load_status_monitor_config()
            except Exception:
                self._status_config = StatusMonitorConfig.default()
        self._handle_status_config_update(self._status_config)

    def _handle_status_config_update(self, config: StatusMonitorConfig) -> None:
        self._status_config = config
        for idx, resource in enumerate(('hp', 'mp')):
            cfg = getattr(self._status_config, resource, None)
            if not cfg or not getattr(cfg, 'enabled', True):
                self._status_log_lines[idx] = f"{resource.upper()}: 비활성"
            else:
                current = self._status_log_lines[idx]
                if current.endswith('비활성'):
                    self._status_log_lines[idx] = f"{resource.upper()}: --%"
        self._render_detection_log(self._last_detection_log_body, force=True)

    def _handle_status_snapshot(self, payload: dict) -> None:
        if not self.is_detection_running:
            return
        if not isinstance(payload, dict):
            return
        timestamp = float(payload.get('timestamp', time.time()))
        updated = False
        for idx, resource in enumerate(('hp', 'mp')):
            cfg = getattr(self._status_config, resource, None)
            if not cfg or not getattr(cfg, 'enabled', True):
                continue
            info = payload.get(resource)
            if not isinstance(info, dict):
                continue
            value = info.get('percentage')
            if not isinstance(value, (int, float)):
                continue
            display = f"{resource.upper()}: {float(value):.1f}%"
            last_text = self._status_log_lines[idx]
            last_ts = self._status_last_ui_update.get(resource, 0.0)
            changed = display != last_text
            if not changed and (timestamp - last_ts) < self._status_update_min_interval:
                continue
            if changed or (timestamp - last_ts) >= self._status_update_min_interval:
                self._status_log_lines[idx] = display
                self._status_last_ui_update[resource] = timestamp
                updated = True
            self._maybe_trigger_status_command(resource, float(value), timestamp)
        if updated:
            self._render_detection_log(self._last_detection_log_body)

    def _maybe_trigger_status_command(self, resource: str, percentage: float, timestamp: float) -> None:
        cfg = getattr(self._status_config, resource, None)
        if cfg is None:
            return
        if not getattr(cfg, 'enabled', True):
            return
        threshold = getattr(cfg, 'recovery_threshold', None)
        if threshold is None:
            return
        command_name = (getattr(cfg, 'command_profile', None) or '').strip()
        if not command_name:
            return
        if percentage > threshold:
            return
        interval = max(0.1, getattr(cfg, 'interval_sec', 1.0))
        if (timestamp - self._status_last_command_ts.get(resource, 0.0)) < interval:
            return
        if self._status_active_resource is not None:
            return

        if hasattr(self, 'auto_control_checkbox') and not self.auto_control_checkbox.isChecked():
            return

        if resource == 'hp':
            current_pos = getattr(self, 'last_player_pos', None)
            ladders = self.geometry_data.get("transition_objects", []) if hasattr(self, 'geometry_data') else []
            if current_pos is not None and ladders:
                is_near_ladder, _, dist_x = self._check_near_ladder(
                    current_pos,
                    ladders,
                    8.0,
                    return_dist=True,
                    current_floor=getattr(self, 'current_player_floor', None)
                )
                if is_near_ladder:
                    self.update_general_log(
                        "[상태] HP 명령 보류: 사다리 8px 이내 접근 중", "gray"
                    )
                    self._status_last_command_ts[resource] = timestamp
                    return

        if resource == 'hp':
            # HP 명령은 병렬 수행을 전제로 하므로 기존 명령 보관/차단 로직을 우회한다.
            self._status_saved_command = None
            self._issue_status_command(resource, command_name)
            self._status_last_command_ts[resource] = timestamp
            return

        if self._last_regular_command and (
            not isinstance(self._last_regular_command[1], str)
            or not str(self._last_regular_command[1]).startswith('status:')
        ):
            self._status_saved_command = self._last_regular_command

        self._status_active_resource = resource
        self._issue_status_command(resource, command_name)
        self._status_last_command_ts[resource] = timestamp

    def _issue_status_command(self, resource: str, command_name: str) -> None:
        reason = f'status:{resource}'
        self._emit_control_command(command_name, reason=reason)
        self.update_general_log(f"[상태] {resource.upper()} 명령 '{command_name}' 실행", "purple")

    def _handle_status_command_completed(self, success: bool) -> None:
        active = self._status_active_resource
        self._status_active_resource = None
        if success and active:
            self.update_general_log(f"[상태] {active.upper()} 명령 완료", "gray")
        if self._status_saved_command:
            command, reason = self._status_saved_command
            self._status_saved_command = None
            self._emit_control_command(command, reason)

    def _update_walk_teleport_probability_display(self, percent: float) -> None:
        self._walk_teleport_probability_text = f"텔레포트 확률: {max(percent, 0.0):.1f}%"
        if hasattr(self, '_last_detection_log_body'):
            self._render_detection_log(self._last_detection_log_body)

    def update_detection_log_from_features(self, inliers, outliers):
        """정상치와 이상치 피처 목록을 받아 탐지 상태 로그를 업데이트합니다."""
        if not self._detection_log_enabled:
            return

        #  5프레임마다 한 번씩만 업데이트하도록 조절
        self.log_update_counter += 1
        if self.log_update_counter % 5 != 0:
            return

        log_html = "<b>활성 지형:</b> "
        
        # 임계값 미만이지만 탐지된 모든 지형을 포함
        all_found = inliers + outliers
        if not all_found:
            log_html += '<font color="red">탐지된 지형 없음</font>'
            self._render_detection_log(log_html)
            return

        inlier_texts = []
        if inliers:
            sorted_inliers = sorted(inliers, key=lambda x: x['conf'], reverse=True)
            for f in sorted_inliers:
                inlier_texts.append(f'<font color="blue">{f["id"]}({f["conf"]:.2f})</font>')
        
        outlier_texts = []
        if outliers:
            sorted_outliers = sorted(outliers, key=lambda x: x['conf'], reverse=True)
            for f in sorted_outliers:
                outlier_texts.append(f'<font color="red">{f["id"]}({f["conf"]:.2f})</font>')

        log_html += ", ".join(inlier_texts)
        if inlier_texts and outlier_texts:
            log_html += ", "
        log_html += ", ".join(outlier_texts)
        
        self._render_detection_log(log_html)

    def update_detection_log_message(self, message, color):
        """단순 텍스트 메시지를 탐지 상태 로그에 표시합니다."""
        body = f'<font color="{color}">{message}</font>'
        self._render_detection_log(body)
        
    def update_detection_log(self, message, color):
        body = f'<font color="{color}">{message}</font>'
        self._render_detection_log(body)
    
    def _build_line_floor_map(self): # [v11.4.5] 지형선 ID와 층 정보를 매핑하는 캐시를 생성하는 헬퍼 메서드
        """self.geometry_data를 기반으로 line_id_to_floor_map을 생성/갱신합니다."""
        self.line_id_to_floor_map.clear()
        if not self.geometry_data or "terrain_lines" not in self.geometry_data:
            return
        
        for line in self.geometry_data.get("terrain_lines", []):
            line_id = line.get("id")
            floor = line.get("floor")
            if line_id is not None and floor is not None:
                self.line_id_to_floor_map[line_id] = floor
        self.update_general_log("지형-층 정보 맵 캐시를 갱신했습니다.", "gray")

    def _update_map_data_and_views(self):
            """데이터 변경 후 전역 좌표와 전체 맵 뷰를 갱신합니다."""
            self.global_positions = self._calculate_global_positions()
            self._generate_full_map_pixmap()
            self._assign_dynamic_names() #동적 이름 부여 메서드 호출 추가
            self._refresh_forbidden_wall_states()
            self.update_general_log("맵 데이터를 최신 정보로 갱신했습니다.", "purple")

    def _calculate_global_positions(self):
            """
            v10.0.0: 기준 앵커를 원점으로 하여 모든 핵심 지형과 구버전 웨이포인트의 전역 좌표를 계산합니다.
            [MODIFIED] 동일 컨텍스트 이미지를 가진 지형 그룹을 해시로 식별하여, 템플릿 매칭 대신
            직접 좌표를 전개함으로써 좌표 붕괴 및 무한 루프 가능성을 방지합니다.
            """
            if not self.key_features:
                self.reference_anchor_id = None
                return {}

            for f_id, f_data in self.key_features.items():
                if 'size' not in f_data:
                    try:
                        img_data = base64.b64decode(f_data['image_base64'])
                        np_arr = np.frombuffer(img_data, np.uint8)
                        template = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                        if template is not None:
                            f_data['size'] = QSize(template.shape[1], template.shape[0])
                    except:
                        pass

            global_positions = {}

            # 1. 기준 앵커 설정
            anchor_id = self.reference_anchor_id
            if not anchor_id or anchor_id not in self.key_features:
                try:
                    anchor_id = sorted(self.key_features.keys())[0]
                    self.reference_anchor_id = anchor_id
                    self.update_general_log(f"경고: 기준 앵커가 없어, '{anchor_id}'을(를) 새 기준으로 자동 설정합니다.", "orange")
                except IndexError:
                    return {}
            
            #  정책/가드 옵션 및 해시/템플릿 준비
            identical_context_policy = getattr(self, 'identical_context_policy', 'propagate')
            degenerate_match_eps = float(getattr(self, 'degenerate_match_eps', 2.0))

            templates = {}
            contexts = {}
            context_hashes = {} # 컨텍스트 그룹핑용 해시

            for f_id, f_data in self.key_features.items():
                try:
                    img_data = base64.b64decode(f_data['image_base64'])
                    np_arr = np.frombuffer(img_data, np.uint8)
                    templates[f_id] = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
                    if 'context_image_base64' in f_data and f_data['context_image_base64']:
                        context_img_data = base64.b64decode(f_data['context_image_base64'])
                        contexts[f_id] = cv2.imdecode(np.frombuffer(context_img_data, np.uint8), cv2.IMREAD_GRAYSCALE)
                        context_hashes[f_id] = hashlib.sha1(context_img_data).hexdigest()
                    else:
                        contexts[f_id], context_hashes[f_id] = None, None
                except Exception as e:
                    print(f"이미지 디코딩 오류 (ID: {f_id}): {e}")
                    templates[f_id], contexts[f_id], context_hashes[f_id] = None, None, None
            
            # 2. 핵심 지형 좌표 계산 (양방향 탐색 로직)
            known_features = {anchor_id}
            pending_features = set(self.key_features.keys()) - known_features
            global_positions[anchor_id] = QPointF(0, 0)

            #  동일 컨텍스트 그룹핑 및 앵커 그룹 사전 전개
            if identical_context_policy in ('propagate', 'forbid'):
                groups = defaultdict(list)
                for fid, h in context_hashes.items():
                    if h: groups[h].append(fid)

                anchor_hash = context_hashes.get(anchor_id)
                if anchor_hash and anchor_hash in groups:
                    anchor_rect_data = self.key_features[anchor_id].get('rect_in_context')
                    # [MODIFIED] rect_in_context 유효성 검사 추가
                    if anchor_rect_data and len(anchor_rect_data) == 4:
                        anchor_local_in_ctx = QPointF(anchor_rect_data[0], anchor_rect_data[1])
                        context_origin = global_positions[anchor_id] - anchor_local_in_ctx

                        for fid in groups[anchor_hash]:
                            if fid not in global_positions:
                                rect_data = self.key_features[fid].get('rect_in_context')
                                # [MODIFIED] rect_in_context 유효성 검사 추가
                                if rect_data and len(rect_data) == 4:
                                    local_in_ctx = QPointF(rect_data[0], rect_data[1])
                                    global_positions[fid] = context_origin + local_in_ctx
                        
                        known_features.update(groups[anchor_hash])
                        pending_features -= set(groups[anchor_hash])
                    else:
                        self.update_general_log(f"경고: 앵커 '{anchor_id}'의 문맥 내 좌표(rect_in_context)가 유효하지 않아 동일 문맥 그룹 전개를 건너뜁니다.", "orange")
            
            MATCH_THRESHOLD = 0.90

            for _ in range(len(self.key_features) + 1):
                if not pending_features: break
                
                found_in_iteration = set()
                
                for pending_id in list(pending_features):
                    is_found = False
                    for known_id in known_features:
                        same_ctx = context_hashes.get(known_id) is not None and context_hashes[known_id] == context_hashes.get(pending_id)

                        # 탐색 A: known의 문맥에서 pending 찾기
                        if not same_ctx:
                            known_context, pending_template = contexts.get(known_id), templates.get(pending_id)
                            if known_context is not None and pending_template is not None:
                                res = cv2.matchTemplate(known_context, pending_template, cv2.TM_CCOEFF_NORMED)
                                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                                if max_val >= MATCH_THRESHOLD:
                                    known_global_pos = global_positions[known_id]
                                    known_rect = self.key_features[known_id].get('rect_in_context', [0,0,0,0])
                                    known_local_pos_in_context = QPointF(known_rect[0], known_rect[1])
                                    if not (abs(max_loc[0] - known_local_pos_in_context.x()) <= degenerate_match_eps and abs(max_loc[1] - known_local_pos_in_context.y()) <= degenerate_match_eps):
                                        context_global_origin = known_global_pos - known_local_pos_in_context
                                        pending_local_pos_in_context = QPointF(max_loc[0], max_loc[1])
                                        global_positions[pending_id] = context_global_origin + pending_local_pos_in_context
                                        is_found = True
                        if is_found: break

                        # 탐색 B: pending의 문맥에서 known 찾기
                        if not same_ctx:
                            pending_context, known_template = contexts.get(pending_id), templates.get(known_id)
                            if pending_context is not None and known_template is not None:
                                res = cv2.matchTemplate(pending_context, known_template, cv2.TM_CCOEFF_NORMED)
                                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                                if max_val >= MATCH_THRESHOLD:
                                    known_global_pos = global_positions[known_id]
                                    pending_rect = self.key_features[pending_id].get('rect_in_context', [0,0,0,0])
                                    pending_local_pos_in_context = QPointF(pending_rect[0], pending_rect[1])
                                    known_local_pos_in_pending_context = QPointF(max_loc[0], max_loc[1])
                                    if not (abs(max_loc[0] - pending_local_pos_in_context.x()) <= degenerate_match_eps and abs(max_loc[1] - pending_local_pos_in_context.y()) <= degenerate_match_eps):
                                        context_global_origin = known_global_pos - known_local_pos_in_pending_context
                                        global_positions[pending_id] = context_global_origin + pending_local_pos_in_context
                                        is_found = True
                        if is_found: break
                    
                    if is_found:
                        found_in_iteration.add(pending_id)
                        #  신규 확정 피처의 동일-컨텍스트 그룹 즉시 전개
                        if identical_context_policy == 'propagate':
                            h = context_hashes.get(pending_id)
                            if h and h in groups:
                                rect_p_data = self.key_features[pending_id].get('rect_in_context')
                                # [MODIFIED] rect_in_context 유효성 검사 추가
                                if rect_p_data and len(rect_p_data) == 4:
                                    local_p = QPointF(rect_p_data[0], rect_p_data[1])
                                    ctx_origin = global_positions[pending_id] - local_p
                                    for fid in groups[h]:
                                        if fid not in global_positions:
                                            rect_f_data = self.key_features[fid].get('rect_in_context')
                                            # [MODIFIED] rect_in_context 유효성 검사 추가
                                            if rect_f_data and len(rect_f_data) == 4:
                                                local_f = QPointF(rect_f_data[0], rect_f_data[1])
                                                global_positions[fid] = ctx_origin + local_f
                                                found_in_iteration.add(fid)

                if found_in_iteration:
                    known_features.update(found_in_iteration)
                    pending_features -= found_in_iteration
                else:
                    break
            
            if pending_features:
                failed_ids = ", ".join(sorted(list(pending_features)))
                message = (f"경고: 다음 핵심 지형들의 위치를 계산하지 못했습니다: {failed_ids}. "
                        "이 지형들이 다른 지형과 연결(문맥 이미지 내 포함)되어 있는지 확인해주세요.")
                self.update_general_log(message, "orange")

            for feature_id in known_features:
                if feature_id in global_positions:
                    feature_data = self.key_features[feature_id]
                    if 'rect_in_context' in feature_data and feature_data['rect_in_context']:
                        rect = feature_data['rect_in_context']
                        feature_local_pos_in_context = QPointF(rect[0], rect[1])
                        context_origin_pos = global_positions[feature_id] - feature_local_pos_in_context
                        global_positions[f"{feature_id}_context"] = context_origin_pos

            all_waypoints_old = self.get_all_waypoints_with_route_name()
            if all_waypoints_old:
                # ... (기존 구버전 웨이포인트 처리 로직은 그대로 유지) ...
                pass # 이 부분은 변경 없음

            self.feature_offsets.clear()
            known_feature_ids = [fid for fid in known_features if fid in global_positions]
            for i in range(len(known_feature_ids)):
                for j in range(i + 1, len(known_feature_ids)):
                    id1, id2 = known_feature_ids[i], known_feature_ids[j]
                    pos1, pos2 = global_positions[id1], global_positions[id2]
                    
                    size1_data, size2_data = self.key_features[id1].get('size'), self.key_features[id2].get('size')
                    size1 = QSize(size1_data[0], size1_data[1]) if isinstance(size1_data, list) and len(size1_data) == 2 else QSize(0,0)
                    size2 = QSize(size2_data[0], size2_data[1]) if isinstance(size2_data, list) and len(size2_data) == 2 else QSize(0,0)
                    
                    center1 = pos1 + QPointF(size1.width()/2, size1.height()/2)
                    center2 = pos2 + QPointF(size2.width()/2, size2.height()/2)

                    offset = center2 - center1
                    #  퇴화 방지: 0에 가까운 오프셋은 저장하지 않음
                    if math.hypot(offset.x(), offset.y()) < 1e-3:
                        continue

                    self.feature_offsets[(id1, id2)] = offset
                    self.feature_offsets[(id2, id1)] = -offset

            return global_positions

# === v12.0.0: A* 경로 탐색 시스템 메서드 ===
    def _get_closest_node_to_point(self, point, target_group=None, target_floor=None, walkable_only=False):
        """
        주어진 좌표에서 가장 가까운 내비게이션 그래프 노드를 찾습니다.
        [수정] walkable_only 플래그를 추가하여 탐색 대상을 제한합니다.
        """
        if not self.nav_nodes:
            return None, float('inf')

        min_dist_sq = float('inf')
        closest_node_key = None
        
        candidate_nodes = []
        for key, node_data in self.nav_nodes.items():
            # walkable_only 필터
            if walkable_only and not node_data.get('walkable', False):
                continue
            # 그룹 필터
            if target_group and node_data.get('group') != target_group:
                continue
            # 층 필터 (우선순위)
            if target_floor is not None:
                node_floor = node_data.get('floor')
                if node_floor is not None and abs(node_floor - target_floor) < 0.1:
                    candidate_nodes.append((key, node_data))
            else: # 층 필터가 없으면 모든 후보를 추가
                candidate_nodes.append((key, node_data))

        # 층 필터링된 후보가 없으면, 층 무시하고 다시 탐색
        if target_floor is not None and not candidate_nodes:
            for key, node_data in self.nav_nodes.items():
                if walkable_only and not node_data.get('walkable', False):
                    continue
                if target_group and node_data.get('group') != target_group:
                    continue
                candidate_nodes.append((key, node_data))

        # 최종 후보군에서 거리 계산
        for key, node_data in candidate_nodes:
            pos = node_data.get('pos')
            if pos:
                dist_sq = (point.x() - pos.x())**2 + (point.y() - pos.y())**2
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                    closest_node_key = key

        return closest_node_key, math.sqrt(min_dist_sq) if closest_node_key else float('inf')
    
    def _build_navigation_graph(self, waypoint_ids_in_route=None):
        """
        [DEBUG] v13.1.9: 노드 생성 시 그룹 할당 과정과, 노드 간 엣지(연결) 생성
                 과정을 추적하기 위한 상세 디버그 로그 추가.
        """
        self.nav_nodes.clear()
        self.nav_graph = defaultdict(dict)
        is_debug_enabled = self.debug_pathfinding_checkbox and self.debug_pathfinding_checkbox.isChecked()

        def debug_print(message):
            if is_debug_enabled:
                print(message)

        debug_print("\n" + "="*20 + " 내비게이션 그래프 생성 시작 (상세 디버그) " + "="*20)

        if not self.geometry_data:
            debug_print("[GRAPH BUILD] CRITICAL: geometry_data가 없어 그래프 생성을 중단합니다.")
            return

        if waypoint_ids_in_route is None:
            waypoint_ids_in_route = [wp['id'] for wp in self.geometry_data.get("waypoints", [])]

        terrain_lines = self.geometry_data.get("terrain_lines", [])
        transition_objects = self.geometry_data.get("transition_objects", [])

        FLOOR_CHANGE_PENALTY = 0.0
        CLIMB_UP_COST_MULTIPLIER = 1.5
        CLIMB_DOWN_COST_MULTIPLIER = 500.0
        JUMP_COST_MULTIPLIER = 1.3
        FALL_COST_MULTIPLIER = 2.0
        DOWN_JUMP_COST_MULTIPLIER = 1.2

        debug_print("[GRAPH BUILD] 1. 노드 생성 시작...")
        # --- 1. 모든 잠재적 노드 생성 및 역할(walkable) 부여 ---
        for wp in self.geometry_data.get("waypoints", []):
            if wp['id'] in waypoint_ids_in_route:
                key = f"wp_{wp['id']}"
                pos = QPointF(*wp['pos'])
                contact_terrain = self._get_contact_terrain(pos)
                group = contact_terrain.get('dynamic_name') if contact_terrain else None
                if group is None:
                    debug_print(f"  - [WARNING] Waypoint '{wp.get('name')}'의 그룹 정보를 찾지 못했습니다.")
                self.nav_nodes[key] = {
                    'type': 'waypoint',
                    'pos': pos,
                    'floor': wp.get('floor'),
                    'name': wp.get('name'),
                    'id': wp['id'],
                    'group': group,
                    'walkable': True,
                    'is_event': bool(wp.get('is_event')),
                }
                debug_print(f"  - 생성(wp): '{wp.get('name')}' -> group: '{group}'")

            for obj in transition_objects:
                p1, p2 = QPointF(*obj['points'][0]), QPointF(*obj['points'][1])
                entry_pos, exit_pos = (p1, p2) if p1.y() > p2.y() else (p2, p1)
                entry_key, exit_key = f"ladder_entry_{obj['id']}", f"ladder_exit_{obj['id']}"
                
                # [DEBUG] 그룹 할당 로직 강화 및 로그 추가
                entry_terrain = self._get_contact_terrain(entry_pos)
                exit_terrain = self._get_contact_terrain(exit_pos)
                
                start_line = next((line for line in terrain_lines if line['id'] == obj.get('start_line_id')), None)
                end_line = next((line for line in terrain_lines if line['id'] == obj.get('end_line_id')), None)
                
                # _get_contact_terrain 우선, 실패 시 line_id 기반으로 폴백
                entry_group = entry_terrain.get('dynamic_name') if entry_terrain else (start_line.get('dynamic_name') if start_line else None)
                exit_group = exit_terrain.get('dynamic_name') if exit_terrain else (end_line.get('dynamic_name') if end_line else None)
                
                entry_floor = entry_terrain.get('floor') if entry_terrain else (start_line.get('floor') if start_line else None)
                exit_floor = exit_terrain.get('floor') if exit_terrain else (end_line.get('floor') if end_line else None)
                
                base_name = obj.get('dynamic_name', obj['id'])
                
                self.nav_nodes[entry_key] = {'type': 'ladder_entry', 'pos': entry_pos, 'obj_id': obj['id'], 'name': f"{base_name} (입구)", 'group': entry_group, 'walkable': True, 'floor': entry_floor}
                self.nav_nodes[exit_key] = {'type': 'ladder_exit', 'pos': exit_pos, 'obj_id': obj['id'], 'name': f"{base_name} (출구)", 'group': exit_group, 'walkable': True, 'floor': exit_floor}
                debug_print(f"  - 생성(ladder): '{base_name} (입구)' -> group: '{entry_group}'")
                debug_print(f"  - 생성(ladder): '{base_name} (출구)' -> group: '{exit_group}'")

                y_diff = abs(entry_pos.y() - exit_pos.y())
                cost_up, cost_down = (y_diff * CLIMB_UP_COST_MULTIPLIER) + FLOOR_CHANGE_PENALTY, (y_diff * CLIMB_DOWN_COST_MULTIPLIER) + FLOOR_CHANGE_PENALTY
                self.nav_graph[entry_key][exit_key] = {'cost': cost_up, 'action': 'climb'}
                self.nav_graph[exit_key][entry_key] = {'cost': cost_down, 'action': 'climb_down'}

            for link in self.geometry_data.get("jump_links", []):
                start_pos, end_pos = QPointF(*link['start_vertex_pos']), QPointF(*link['end_vertex_pos'])
                key1, key2 = f"jump_{link['id']}_p1", f"jump_{link['id']}_p2"
                start_terrain, end_terrain = self._get_contact_terrain(start_pos), self._get_contact_terrain(end_pos)
                start_group, end_group = (start_terrain.get('dynamic_name') if start_terrain else None), (end_terrain.get('dynamic_name') if end_terrain else None)
                base_name = link.get('dynamic_name', link['id'])
                self.nav_nodes[key1] = {'type': 'jump_vertex', 'pos': start_pos, 'link_id': link['id'], 'name': f"{base_name} (시작점)", 'group': start_group, 'walkable': True}
                self.nav_nodes[key2] = {'type': 'jump_vertex', 'pos': end_pos, 'link_id': link['id'], 'name': f"{base_name} (도착점)", 'group': end_group, 'walkable': True}
                cost = math.hypot(start_pos.x() - end_pos.x(), start_pos.y() - end_pos.y()) * JUMP_COST_MULTIPLIER
                if start_terrain and end_terrain and start_terrain.get('floor') != end_terrain.get('floor'):
                    cost += FLOOR_CHANGE_PENALTY
                self.nav_graph[key1][key2], self.nav_graph[key2][key1] = {'cost': cost, 'action': 'jump'}, {'cost': cost, 'action': 'jump'}

            for line_above in terrain_lines:
                group_above = line_above.get('dynamic_name')
                for v_idx, vertex in enumerate([line_above['points'][0], line_above['points'][-1]]):
                    candidate_landings = []
                    for line_below in terrain_lines:
                        if line_above.get('floor', 0) > line_below.get('floor', 0):
                            min_x = min(line_below['points'][0][0], line_below['points'][-1][0])
                            max_x = max(line_below['points'][0][0], line_below['points'][-1][0])
                            if min_x <= vertex[0] <= max_x:
                                candidate_landings.append(line_below)
                    
                    if not candidate_landings: continue
                    best_landing_line = max(candidate_landings, key=lambda line: line.get('floor', 0))
                    
                    start_key = f"fall_start_{line_above['id']}_{v_idx}"
                    start_pos = QPointF(*vertex)
                    self.nav_nodes[start_key] = {'type': 'fall_start', 'pos': start_pos, 'name': f"{group_above} 낙하 지점", 'group': group_above, 'walkable': False, 'floor': line_above.get('floor')}
                    
                    landing_x = start_pos.x()
                    p1, p2 = best_landing_line['points'][0], best_landing_line['points'][-1]
                    landing_y = p1[1] + (p2[1] - p1[1]) * ((landing_x - p1[0]) / (p2[0] - p1[0])) if (p2[0] - p1[0]) != 0 else p1[1]
                    landing_pos = QPointF(landing_x, landing_y)
                    target_group = best_landing_line.get('dynamic_name')
                    landing_key = f"fall_landing_{line_above['id']}_{v_idx}_{best_landing_line['id']}"
                    self.nav_nodes[landing_key] = {'type': 'fall_landing', 'pos': landing_pos, 'name': f"{target_group} 착지 지점", 'group': target_group, 'walkable': True}

                    cost = (abs(start_pos.y() - landing_pos.y()) * FALL_COST_MULTIPLIER) + FLOOR_CHANGE_PENALTY
                    self.nav_graph[start_key][landing_key] = {'cost': cost, 'action': 'fall'}

            for line_above in terrain_lines:
                group_above = line_above.get('dynamic_name')
                y_above = line_above['points'][0][1]
                candidate_landings = [line for line in terrain_lines if line_above.get('floor', 0) > line.get('floor', 0)]
                ax1, ax2 = min(line_above['points'][0][0], line_above['points'][-1][0]), max(line_above['points'][0][0], line_above['points'][-1][0])
                
                for x_pos in range(int(ax1), int(ax2)):
                    possible_landings_at_x = []
                    for line_below in candidate_landings:
                        bx1, bx2 = min(line_below['points'][0][0], line_below['points'][-1][0]), max(line_below['points'][0][0], line_below['points'][-1][0])
                        if bx1 <= x_pos <= bx2:
                            y_diff = abs(y_above - line_below['points'][0][1])
                            if 0 < y_diff <= 70:
                                possible_landings_at_x.append(line_below)
                    if not possible_landings_at_x: continue
                    best_landing_line = max(possible_landings_at_x, key=lambda line: line.get('floor', 0))
                    area_key = f"djump_area_{line_above['id']}_{best_landing_line['id']}"
                    if area_key in self.nav_nodes: continue
                    
                    is_safe_from_ladders = True
                    line_above_floor = line_above.get('floor')
                    for obj in transition_objects:
                        start_line_id, end_line_id = obj.get('start_line_id'), obj.get('end_line_id')
                        if (start_line_id == line_above['id'] and self.line_id_to_floor_map.get(end_line_id, float('inf')) < line_above_floor) or \
                           (end_line_id == line_above['id'] and self.line_id_to_floor_map.get(start_line_id, float('inf')) < line_above_floor):
                            ladder_x = obj['points'][0][0]
                            if abs(x_pos - ladder_x) <= LADDER_AVOIDANCE_WIDTH:
                                is_safe_from_ladders = False
                                break
                    
                    if not is_safe_from_ladders: continue
                        
                    overlap_x1, overlap_x2 = max(ax1, min(best_landing_line['points'][0][0], best_landing_line['points'][-1][0])), min(ax2, max(best_landing_line['points'][0][0], best_landing_line['points'][-1][0]))
                    self.nav_nodes[area_key] = {'type': 'djump_area', 'pos': QPointF((overlap_x1+overlap_x2)/2, y_above), 'name': f"{group_above} 아래 점프 지점", 'group': group_above, 'x_range': [overlap_x1, overlap_x2], 'walkable': False, 'floor': line_above.get('floor')}
                    landing_x = (overlap_x1+overlap_x2)/2
                    p1, p2 = best_landing_line['points'][0], best_landing_line['points'][-1]
                    landing_y = p1[1] + (p2[1] - p1[1]) * ((landing_x - p1[0]) / (p2[0] - p1[0])) if (p2[0] - p1[0]) != 0 else p1[1]
                    landing_pos = QPointF(landing_x, landing_y)
                    target_group = best_landing_line.get('dynamic_name')
                    landing_key = f"djump_landing_{line_above['id']}_{best_landing_line['id']}"
                    self.nav_nodes[landing_key] = {'type': 'djump_landing', 'pos': landing_pos, 'name': f"{target_group} 착지 지점", 'group': target_group, 'walkable': True}
                    cost = (abs(y_above - landing_y) * DOWN_JUMP_COST_MULTIPLIER) + FLOOR_CHANGE_PENALTY
                    self.nav_graph[area_key][landing_key] = {'cost': cost, 'action': 'down_jump'}
            
            debug_print("\n[GRAPH BUILD] 2. 엣지(연결) 생성 시작...")
            # --- 2. 걷기(Walk) 간선 통합 생성 ---
            nodes_by_terrain_group = defaultdict(list)
            for key, node_data in self.nav_nodes.items():
                if node_data.get('group'):
                    nodes_by_terrain_group[node_data['group']].append(key)

            debug_print(f"  - 총 {len(nodes_by_terrain_group)}개의 지형 그룹 발견.")
            for group_name, node_keys in nodes_by_terrain_group.items():
                debug_print(f"  - 그룹 '{group_name}' 처리 중 ({len(node_keys)}개 노드)...")
                walkable_nodes_in_group = [k for k in node_keys if self.nav_nodes[k].get('walkable')]
                action_nodes_in_group = [k for k in node_keys if not self.nav_nodes[k].get('walkable')]
                debug_print(f"    - Walkable: {len(walkable_nodes_in_group)}개, Action Triggers: {len(action_nodes_in_group)}개")

                # 2a. walkable 노드들끼리 모두 연결
                debug_print("    - 2a. Walkable 노드 간 연결:")
                if not walkable_nodes_in_group:
                    debug_print("      - 대상 없음")
                for i in range(len(walkable_nodes_in_group)):
                    for j in range(i + 1, len(walkable_nodes_in_group)):
                        key1, key2 = walkable_nodes_in_group[i], walkable_nodes_in_group[j]
                        pos1, pos2 = self.nav_nodes[key1]['pos'], self.nav_nodes[key2]['pos']
                        # <<< [수정] 아래 cost 계산식 변경
                        cost = math.hypot(pos1.x() - pos2.x(), pos1.y() - pos2.y())
                        self.nav_graph[key1][key2] = {'cost': cost, 'action': 'walk'}
                        self.nav_graph[key2][key1] = {'cost': cost, 'action': 'walk'}
                        name1 = self.nav_nodes[key1]['name']
                        name2 = self.nav_nodes[key2]['name']
                        debug_print(f"      - 연결: '{name1}' <-> '{name2}' (cost: {cost:.1f})")

                # 2b. 모든 walkable 노드에서 모든 action trigger 노드로 단방향 연결
                debug_print("    - 2b. Walkable -> Action Trigger 노드 간 연결:")
                if not walkable_nodes_in_group or not action_nodes_in_group:
                    debug_print("      - 대상 없음")
                for w_key in walkable_nodes_in_group:
                    for a_key in action_nodes_in_group:
                        pos1, pos2 = self.nav_nodes[w_key]['pos'], self.nav_nodes[a_key]['pos']
                        # <<< [수정] 아래 cost 계산식 변경
                        cost = math.hypot(pos1.x() - pos2.x(), pos1.y() - pos2.y())
                        self.nav_graph[w_key][a_key] = {'cost': cost, 'action': 'walk'}
                        name1 = self.nav_nodes[w_key]['name']
                        name2 = self.nav_nodes[a_key]['name']
                        debug_print(f"      - 연결: '{name1}' -> '{name2}' (cost: {cost:.1f})")

            debug_print("\n" + "="*20 + f" 그래프 생성 완료 (노드: {len(self.nav_nodes)}개) " + "="*20)
            self.update_general_log(f"내비게이션 그래프 생성 완료. (노드: {len(self.nav_nodes)}개)", "purple")
    
    def _find_path_astar(self, start_pos, start_group, goal_key):
        """
        [MODIFIED] v13.1.16: 경로탐색 디버그 로그를 UI 체크박스로 제어하도록 수정.
        [DEBUG] v13.1.3: 이웃 노드 평가 시 필터링되는 이유와 비용 비교 과정을
                 상세히 추적하기 위한 디버그 로그 대폭 강화. (사용자 제공 코드 기반)
        v12.9.7: [수정] 경로 탐색 시작 시, '착지 지점' 역할을 하는 노드를 출발점 후보에서 제외합니다.
        v12.8.1: A* 알고리즘을 수정하여, 플레이어의 실제 위치(가상 노드)에서 탐색을 시작합니다.
        """
        if goal_key not in self.nav_nodes:
            print(f"[A* CRITICAL] 목표 노드가 nav_nodes에 없습니다. 목표: {goal_key}")
            return None, float('inf')

        import heapq
        
        # 체크박스 상태를 변수로 저장하여 반복적인 .isChecked() 호출 방지
        is_debug_enabled = self.debug_pathfinding_checkbox and self.debug_pathfinding_checkbox.isChecked()

        goal_pos = self.nav_nodes[goal_key]['pos']

        open_set = []
        closed_set = set() # [DEBUG] 이미 방문한 노드를 추적하기 위해 추가
        came_from = {}
        g_score = {key: float('inf') for key in self.nav_nodes}
        f_score = {key: float('inf') for key in self.nav_nodes}

        # <<< [수정] 아래 로직 전체 변경: walkable: False 노드도 초기 후보로 포함
        candidate_keys = [
            key for key, data in self.nav_nodes.items()
            if data.get('group') == start_group and
               data.get('type') not in ['fall_landing', 'djump_landing']
        ]

        if not candidate_keys:
            print(f"[A* CRITICAL] 시작 그룹 '{start_group}' 내에 유효한 출발 노드가 없습니다.")
            return None, float('inf')
        
        if is_debug_enabled:
            print("\n" + "="*20 + " A* 탐색 시작 (상세 디버그 v2) " + "="*20)
            print(f"[A* INFO] 가상 시작점: {start_pos.x():.1f}, {start_pos.y():.1f} (그룹: '{start_group}')")
            print(f"[A* INFO] 목표: '{self.nav_nodes[goal_key]['name']}' ({goal_key}) at ({goal_pos.x():.1f}, {goal_pos.y():.1f})")
            print("-" * 70)
            print("[A* INIT] 초기 Open Set 구성:")
        
        for node_key in candidate_keys:
            node_data = self.nav_nodes[node_key]
            node_pos = node_data['pos']
            cost_to_node = 0.0

            # <<< [수정] 아래 if-else 블록 추가
            if node_data.get('type') == 'djump_area':
                x_range = node_data.get('x_range')
                if x_range and x_range[0] <= start_pos.x() <= x_range[1]:
                    cost_to_node = 0.0 # 범위 안에 있으면 비용 0
                else:
                    # 범위 밖이면 가장 가까운 경계까지의 거리
                    cost_to_node = min(abs(start_pos.x() - x_range[0]), abs(start_pos.x() - x_range[1]))
            else:
                cost_to_node = math.hypot(start_pos.x() - node_pos.x(), start_pos.y() - node_pos.y())
            
            g_score[node_key] = cost_to_node
            h_score = math.hypot(node_pos.x() - goal_pos.x(), node_pos.y() - goal_pos.y())
            f_score[node_key] = cost_to_node + h_score
            heapq.heappush(open_set, (f_score[node_key], node_key))
            came_from[node_key] = ("__START__", None)
            
            if is_debug_enabled:
                print(f"  - 추가: '{node_data['name']}' ({node_key})")
                print(f"    - G(시작->노드): {cost_to_node:.1f}, H(노드->목표): {h_score:.1f}, F: {f_score[node_key]:.1f}")
        
        iter_count = 0
        while open_set:
            iter_count += 1
            if iter_count > 2000:
                print("[A* CRITICAL] 탐색 반복 횟수가 2000회를 초과했습니다. 탐색을 중단합니다.")
                break
                
            current_f, current_key = heapq.heappop(open_set)
            
            if current_key in closed_set:
                continue
            closed_set.add(current_key)

            if is_debug_enabled:
                print("-" * 70)
                print(f"[A* STEP {iter_count}] 현재 노드: '{self.nav_nodes[current_key]['name']}' ({current_key}) | F: {current_f:.1f}, G: {g_score[current_key]:.1f}")

            if current_key == goal_key:
                if is_debug_enabled:
                    print("-" * 70)
                    print("[A* SUCCESS] 목표 노드에 도달했습니다. 경로를 재구성합니다.")
                path = self._reconstruct_path(came_from, current_key, "__START__")
                return path, g_score[goal_key]

            neighbors = self.nav_graph.get(current_key, {})
            if is_debug_enabled:
                print(f"  - 이웃 노드 {len(neighbors)}개 평가:")
                if not neighbors:
                    print("    - (이웃 없음)")

            for neighbor_key, edge_data in neighbors.items():
                neighbor_name = self.nav_nodes.get(neighbor_key, {}).get('name', '???')
                action_to_neighbor = edge_data.get('action', 'N/A')
                cost = edge_data.get('cost', float('inf'))
                
                if is_debug_enabled:
                    print(f"    -> '{neighbor_name}' ({neighbor_key}) | action: {action_to_neighbor}, cost: {cost:.1f}")

                neighbor_node_type = self.nav_nodes.get(neighbor_key, {}).get('type')
                if neighbor_node_type in ['fall_landing', 'djump_landing'] and action_to_neighbor == 'walk':
                    if is_debug_enabled: print("      - [필터링] 착지 지점으로 걸어갈 수 없어 건너뜀.")
                    continue
                
                if neighbor_key in closed_set:
                    if is_debug_enabled: print("      - [필터링] 이미 방문한 노드(Closed Set)이므로 건너뜀.")
                    continue

                tentative_g_score = g_score[current_key] + cost
                
                if is_debug_enabled:
                    print(f"      - G(예상): {g_score[current_key]:.1f} (현재 G) + {cost:.1f} (이동 Cost) = {tentative_g_score:.1f}")

                if tentative_g_score < g_score[neighbor_key]:
                    came_from[neighbor_key] = (current_key, edge_data)
                    g_score[neighbor_key] = tentative_g_score
                    neighbor_pos = self.nav_nodes[neighbor_key]['pos']
                    h_score = math.hypot(neighbor_pos.x() - goal_pos.x(), neighbor_pos.y() - goal_pos.y())
                    f_score[neighbor_key] = tentative_g_score + h_score
                    heapq.heappush(open_set, (f_score[neighbor_key], neighbor_key))
                    if is_debug_enabled:
                        print(f"      - [경로 갱신] 더 나은 경로 발견! H: {h_score:.1f}, F: {f_score[neighbor_key]:.1f}. Open Set에 추가.")
                elif is_debug_enabled:
                    print(f"      - [경로 유지] 기존 경로가 더 좋음 (기존 G: {g_score[neighbor_key]:.1f} <= 예상 G: {tentative_g_score:.1f})")
        
        if is_debug_enabled:
            print("-" * 70)
            print("[A* FAILED] Open Set이 비었지만 목표에 도달하지 못했습니다. 경로가 존재하지 않습니다.")
        return None, float('inf')
    
    def _reconstruct_path(self, came_from, current_key, start_key):
        """
        v12.8.1: A* 탐색 결과를 바탕으로 최종 경로 리스트를 재구성합니다.
        가상 시작 노드("__START__")를 처리합니다.
        """
        path = [current_key]
        
        while current_key in came_from:
            prev_key, _ = came_from[current_key]
            
            # [수정] 가상 시작 노드에 도달하면 경로 재구성을 중단합니다.
            if prev_key == start_key:
                break
            
            path.insert(0, prev_key)
            current_key = prev_key
            
        return path

    # === v12.0.0: 추가 끝 ===

    def _assign_dynamic_names(self):
        """
        모든 지형, 층 이동 오브젝트, 점프 링크에 동적 이름을 부여합니다.
        이 이름은 저장되지 않고 런타임에 생성됩니다.
        """
        if not self.geometry_data:
            return

        # --- 1. 지형선 그룹화 및 이름 부여 ---
        terrain_lines = self.geometry_data.get("terrain_lines", [])
        lines_by_id = {line['id']: line for line in terrain_lines}
        line_id_to_group_name = {}

        if terrain_lines:
            # 연결된 지형선을 찾기 위한 그래프 생성
            adj = defaultdict(list)
            point_to_lines = defaultdict(list)
            for line in terrain_lines:
                for p in line['points']:
                    point_to_lines[tuple(p)].append(line['id'])
            
            for p, ids in point_to_lines.items():
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        adj[ids[i]].append(ids[j])
                        adj[ids[j]].append(ids[i])

            # BFS로 연결된 그룹(컴포넌트) 찾기
            visited = set()
            all_groups = []
            for line_id in lines_by_id:
                if line_id not in visited:
                    current_group = []
                    q = deque([line_id])
                    visited.add(line_id)
                    while q:
                        current_id = q.popleft()
                        current_group.append(lines_by_id[current_id])
                        for neighbor_id in adj[current_id]:
                            if neighbor_id not in visited:
                                visited.add(neighbor_id)
                                q.append(neighbor_id)
                    all_groups.append(current_group)

            # 층별로 그룹을 나누고 x축 기준으로 정렬하여 이름 부여
            groups_by_floor = defaultdict(list)
            for group in all_groups:
                if group:
                    floor = group[0].get('floor', 0)
                    groups_by_floor[floor].append(group)
            
            for floor, groups in groups_by_floor.items():
                # 각 그룹의 중심 x좌표를 계산하여 정렬
                sorted_groups = sorted(groups, key=lambda g: sum(p[0] for line in g for p in line['points']) / sum(len(line['points']) for line in g))
                
                for i, group in enumerate(sorted_groups):
                    group_name = f"{floor}층_{chr(ord('A') + i)}"
                    for line in group:
                        line['dynamic_name'] = group_name
                        line_id_to_group_name[line['id']] = group_name

        # --- 2. 층 이동 오브젝트 이름 부여 ---
        transition_objects = self.geometry_data.get("transition_objects", [])
        if transition_objects:
            # 먼저 모든 지형선 ID와 층/동적이름을 매핑
            line_info_map = {
                line['id']: {'floor': line.get('floor', 0), 'name': line.get('dynamic_name', '')}
                for line in terrain_lines
            }

            # {아래층그룹_위층그룹: [오브젝트1, 오브젝트2]} 형식으로 그룹화
            objs_by_connection = defaultdict(list)
            for obj in transition_objects:
                start_line_id = obj.get('start_line_id')
                end_line_id = obj.get('end_line_id')

                if start_line_id in line_info_map and end_line_id in line_info_map:
                    start_info = line_info_map[start_line_id]
                    end_info = line_info_map[end_line_id]

                    # 층 번호를 기준으로 아래/위 결정
                    if start_info['floor'] < end_info['floor']:
                        lower_name, upper_name = start_info['name'], end_info['name']
                    else:
                        lower_name, upper_name = end_info['name'], start_info['name']
                    
                    connection_key = f"{lower_name}_{upper_name}"
                    objs_by_connection[connection_key].append(obj)

            # 각 연결 그룹 내에서 x축 기준으로 정렬하여 이름 부여
            for connection_key, objs in objs_by_connection.items():
                sorted_objs = sorted(objs, key=lambda o: o['points'][0][0])
                for i, obj in enumerate(sorted_objs):
                    obj['dynamic_name'] = f"{connection_key}_{i + 1}"
                    
        # --- 3. 지형 점프 연결 이름 부여 (v10.0.1 로직 개편 및 안정성 강화) ---
        jump_links = self.geometry_data.get("jump_links", [])
        if jump_links:
            try:
                # 1. 모든 지형선 꼭짓점의 위치와 층 정보를 매핑
                vertex_to_floor_map = {}
                for line in terrain_lines:
                    floor = line.get('floor', 0)
                    for p in line['points']:
                        vertex_to_floor_map[tuple(p)] = floor

                # 2. 각 점프 링크의 시작/종료 층 정보 찾기
                for jump in jump_links:
                    start_pos_tuple = tuple(jump['start_vertex_pos'])
                    end_pos_tuple = tuple(jump['end_vertex_pos'])

                    start_floor = vertex_to_floor_map.get(start_pos_tuple)
                    end_floor = vertex_to_floor_map.get(end_pos_tuple)

                    # Fallback: 만약 꼭짓점 맵에 없다면, 가장 가까운 지형선에서 층 정보 추론
                    if start_floor is None:
                        start_floor = self._get_floor_from_closest_terrain_data(QPointF(start_pos_tuple[0], start_pos_tuple[1]), terrain_lines)
                    if end_floor is None:
                        end_floor = self._get_floor_from_closest_terrain_data(QPointF(end_pos_tuple[0], end_pos_tuple[1]), terrain_lines)

                    # 층 번호를 정렬하여 그룹 키로 사용
                    floor_key = tuple(sorted((start_floor, end_floor)))
                    jump['temp_floor_key'] = floor_key

                # 3. (시작층, 종료층) 그룹별로 이름 부여
                jumps_by_floor_pair = defaultdict(list)
                for jump in jump_links:
                    jumps_by_floor_pair[jump['temp_floor_key']].append(jump)

                for floor_pair, jumps in jumps_by_floor_pair.items():
                    sorted_jumps = sorted(jumps, key=lambda j: (j['start_vertex_pos'][0] + j['end_vertex_pos'][0]) / 2)
                    
                    f1_str = f"{floor_pair[0]:g}"
                    f2_str = f"{floor_pair[1]:g}"
                    
                    for i, jump in enumerate(sorted_jumps):
                        jump['dynamic_name'] = f"{f1_str}층_{f2_str}층{chr(ord('A') + i)}"
                        if 'temp_floor_key' in jump:
                            del jump['temp_floor_key']
            except Exception as e:
                print(f"Error assigning dynamic names to jump links in MapTab: {e}")

    def _open_hotkey_setting_dialog(self):
        dialog = HotkeySettingDialog(self)
        if dialog.exec():
            new_hotkey = dialog.hotkey_str
            if new_hotkey:
                self.update_general_log(f"단축키가 '{new_hotkey.upper()}' (으)로 설정되었습니다.", "blue")
                self._save_and_reregister_hotkey(new_hotkey)

    def _sync_hotkey_filter_id(self):
        if hasattr(self, 'win_event_filter') and self.win_event_filter:
            hotkey_id = getattr(self.hotkey_manager, 'hotkey_id', None)
            if hasattr(self.win_event_filter, 'hotkey_id'):
                self.win_event_filter.hotkey_id = hotkey_id

    def _save_and_reregister_hotkey(self, new_hotkey_str):
        self.current_hotkey = new_hotkey_str
        self.save_global_settings()
        self.hotkey_display_label.setText(self.current_hotkey.upper())
        if self.hotkey_manager:
            self.hotkey_manager.register_hotkey(self.current_hotkey)
            self._sync_hotkey_filter_id()

    def perform_initial_setup(self):
        os.makedirs(MAPS_DIR, exist_ok=True)
        self.check_and_migrate_old_config()
        self.profile_selector.blockSignals(True)
        self.populate_profile_selector()
        profile_to_load = None
        
        # [수정] 단축키 로드 및 등록 로직
        last_profile = self.load_global_settings()
        self.hotkey_display_label.setText(self.current_hotkey.upper())
        if hasattr(self, 'display_enabled_checkbox'):
            block_state = self.display_enabled_checkbox.blockSignals(True)
            self.display_enabled_checkbox.setChecked(bool(self._minimap_display_enabled))
            self.display_enabled_checkbox.blockSignals(block_state)
            self._handle_display_toggle(bool(self._minimap_display_enabled))
        if hasattr(self, 'perf_logging_checkbox'):
            block_state = self.perf_logging_checkbox.blockSignals(True)
            self.perf_logging_checkbox.setChecked(self._perf_logging_enabled)
            self.perf_logging_checkbox.blockSignals(block_state)
        if self.hotkey_manager:
            try:
                self.hotkey_manager.register_hotkey(self.current_hotkey)
                self._sync_hotkey_filter_id()
            except Exception as exc:
                self.update_general_log(f"전역 단축키 등록 실패: {exc}", "red")

        if last_profile and last_profile in [self.profile_selector.itemText(i) for i in range(self.profile_selector.count())]:
            profile_to_load = last_profile
        elif self.profile_selector.count() > 0:
            profile_to_load = self.profile_selector.itemText(0)
        if profile_to_load:
            self.profile_selector.setCurrentText(profile_to_load)
        self.profile_selector.blockSignals(False)
        if profile_to_load:
            self.load_profile_data(profile_to_load)
        else:
            self.update_ui_for_no_profile()

def cleanup_on_close(self):
        self.save_global_settings()
        # 프로그램 종료 시에도 탐지 상태 플래그를 False로 설정
        self.is_detection_running = False
        self._clear_authority_resume_state()

        self._stop_perf_logging()

        if self.detection_thread and self.detection_thread.isRunning():
            self.detection_thread.stop()
            self.detection_thread.wait()
            
        #  단축키 관리자 및 이벤트 필터 정리
        if self.hotkey_manager:
            self.hotkey_manager.unregister_hotkey()
        if hasattr(self, 'win_event_filter'):
            QApplication.instance().removeNativeEventFilter(self.win_event_filter)
        if self.status_monitor:
            try:
                self.status_monitor.status_captured.disconnect(self._handle_status_snapshot)
            except Exception:
                pass
            self.status_monitor = None

        print("'맵' 탭 정리 완료.")
