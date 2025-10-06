"""맵 탭 공통 상수와 헬퍼 함수."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

import numpy as np


MapConfig = {
    "downscale": 0.7,
    "target_fps": 20,
    "detection_threshold_default": 0.85,
    "loop_time_fallback_ms": 120,
    "use_new_capture": True,
    # 표시가 꺼진(헤드리스) 상태에서 템플릿 매칭 최소 간격(초)
    "headless_min_template_interval_sec": 0.15,
    # 템플릿 매칭에서 허용할 최소 다운스케일(항상 0.7 유지)
    "min_downscale_for_matching": 0.7,
    # 시작/연동 직후 강제 매칭 프레임 수(초기 정렬 확보용)
    "startup_force_match_frames": 8,
}


SRC_ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(SRC_ROOT, "..", "workspace"))
CONFIG_PATH = os.path.join(WORKSPACE_ROOT, "config")
MAPS_DIR = os.path.join(CONFIG_PATH, "maps")
GLOBAL_MAP_SETTINGS_FILE = os.path.join(CONFIG_PATH, "global_map_settings.json")
GLOBAL_ACTION_MODEL_DIR = os.path.join(CONFIG_PATH, "global_action_model")

# 기본 판정설정 베이스 프로필(요청: 동바산6)
DEFAULT_STATE_BASE_PROFILE = "동바산6"

# 판정설정 키 목록(필터용)
STATE_MACHINE_CONFIG_KEYS = [
    "idle_time_threshold",
    "climbing_state_frame_threshold",
    "falling_state_frame_threshold",
    "jumping_state_frame_threshold",
    "on_terrain_y_threshold",
    "jump_y_min_threshold",
    "jump_y_max_threshold",
    "fall_y_min_threshold",
    "climb_x_movement_threshold",
    "fall_on_ladder_x_movement_threshold",
    "ladder_x_grab_threshold",
    "move_deadzone",
    "max_jump_duration",
    "y_movement_deadzone",
    "waypoint_arrival_x_threshold",
    "waypoint_arrival_x_threshold_min",
    "waypoint_arrival_x_threshold_max",
    "ladder_arrival_x_threshold",
    "ladder_arrival_short_threshold",
    "jump_link_arrival_x_threshold",
    "ladder_avoidance_width",
    "ladder_down_jump_min_distance",
    "on_ladder_enter_frame_threshold",
    "jump_initial_velocity_threshold",
    "climb_max_velocity",
    "arrival_frame_threshold",
    "action_success_frame_threshold",
    "stuck_detection_wait",
    "airborne_recovery_wait",
    "ladder_recovery_resend_delay",
    "edgefall_timeout_sec",
    "edgefall_trigger_distance",
    "prepare_timeout",
    "max_lock_duration",
    "walk_teleport_probability",
    "walk_teleport_interval",
    "walk_teleport_bonus_delay",
    "walk_teleport_bonus_step",
    "walk_teleport_bonus_max",
]


def _resolve_baseline_state_config_path() -> Path:
    """동바산6 프로필의 map_config.json 경로를 반환.

    요청 사항에 따라 향후 새 프로필 기본 판정설정의 기준으로 사용.
    """
    return Path(MAPS_DIR) / DEFAULT_STATE_BASE_PROFILE / "map_config.json"


def load_baseline_state_machine_config() -> dict:
    """동바산6의 state_machine_config만 읽어서 반환.

    - 파일 없음/읽기 실패 시 빈 dict 반환
    - 허용된 판정설정 키만 필터링하여 반환
    """
    cfg_path = _resolve_baseline_state_config_path()
    if not cfg_path.is_file():
        return {k: v for k, v in STANDARD_STATE_MACHINE_BASELINE.items() if k in STATE_MACHINE_CONFIG_KEYS}

    raw = None
    for enc in ("utf-8", "utf-8-sig", "cp949", "euc-kr"):
        try:
            with cfg_path.open("r", encoding=enc) as f:
                raw = json.load(f)
            break
        except Exception:
            raw = None
            continue

    if not isinstance(raw, dict):
        return {k: v for k, v in STANDARD_STATE_MACHINE_BASELINE.items() if k in STATE_MACHINE_CONFIG_KEYS}

    state = raw.get("state_machine_config") or raw.get("state_config") or {}
    if not isinstance(state, dict):
        return {k: v for k, v in STANDARD_STATE_MACHINE_BASELINE.items() if k in STATE_MACHINE_CONFIG_KEYS}

    # 허용된 키만 추출
    return {k: v for k, v in state.items() if k in STATE_MACHINE_CONFIG_KEYS}

# 동바산6 판정설정 표준 복사본(파일 부재 시 사용)
STANDARD_STATE_MACHINE_BASELINE = {
    "idle_time_threshold": 0.3,
    "climbing_state_frame_threshold": 2,
    "falling_state_frame_threshold": 2,
    "jumping_state_frame_threshold": 1,
    "on_terrain_y_threshold": 1.0,
    "jump_y_min_threshold": 1.0,
    "jump_y_max_threshold": 10.5,
    "fall_y_min_threshold": 4.0,
    "climb_x_movement_threshold": 1.0,
    "fall_on_ladder_x_movement_threshold": 1.0,
    "ladder_x_grab_threshold": 8.0,
    "move_deadzone": 0.2,
    "max_jump_duration": 3.0,
    "y_movement_deadzone": 0.5,
    "waypoint_arrival_x_threshold": 10.0,
    "waypoint_arrival_x_threshold_min": 8.0,
    "waypoint_arrival_x_threshold_max": 12.0,
    "ladder_arrival_x_threshold": 7.5,
    "ladder_arrival_short_threshold": 5.5,
    "jump_link_arrival_x_threshold": 3.1,
    "ladder_avoidance_width": 3.0,
    "ladder_down_jump_min_distance": 3.0,
    "on_ladder_enter_frame_threshold": 3,
    "jump_initial_velocity_threshold": 4.0,
    "climb_max_velocity": 3.0,
    "arrival_frame_threshold": 2,
    "action_success_frame_threshold": 2,
    "stuck_detection_wait": 0.5,
    "airborne_recovery_wait": 2.0,
    "ladder_recovery_resend_delay": 0.5,
    "edgefall_timeout_sec": 8.0,
    # 파일에 없을 수 있으므로 표준 기본값 유지
    "edgefall_trigger_distance": 2.0,
    "prepare_timeout": 3.0,
    "max_lock_duration": 3.5,
    "walk_teleport_probability": 10.0,
    "walk_teleport_interval": 0.5,
    "walk_teleport_bonus_delay": 1.0,
    "walk_teleport_bonus_step": 10.0,
    "walk_teleport_bonus_max": 50.0,
}


ROUTE_SLOT_IDS = ["1", "2", "3", "4", "5"]


PLAYER_ICON_LOWER = np.array([22, 120, 120])
PLAYER_ICON_UPPER = np.array([35, 255, 255])
OTHER_PLAYER_ICON_LOWER1 = np.array([0, 120, 120])
OTHER_PLAYER_ICON_UPPER1 = np.array([10, 255, 255])
OTHER_PLAYER_ICON_LOWER2 = np.array([170, 120, 120])
OTHER_PLAYER_ICON_UPPER2 = np.array([180, 255, 255])
PLAYER_Y_OFFSET = 1

MIN_ICON_WIDTH = 9
MIN_ICON_HEIGHT = 9
MAX_ICON_WIDTH = 20
MAX_ICON_HEIGHT = 20
PLAYER_ICON_STD_WIDTH = 11
PLAYER_ICON_STD_HEIGHT = 11


IDLE_TIME_THRESHOLD = 0.3
CLIMBING_STATE_FRAME_THRESHOLD = 2
FALLING_STATE_FRAME_THRESHOLD = 2
JUMPING_STATE_FRAME_THRESHOLD = 1
ON_TERRAIN_Y_THRESHOLD = 1.0
JUMP_Y_MIN_THRESHOLD = 1.0
JUMP_Y_MAX_THRESHOLD = 10.5
FALL_Y_MIN_THRESHOLD = 4.0
CLIMB_X_MOVEMENT_THRESHOLD = 1.0
FALL_ON_LADDER_X_MOVEMENT_THRESHOLD = 1.0
Y_MOVEMENT_DEADZONE = 0.5
LADDER_X_GRAB_THRESHOLD = 8.0
MOVE_DEADZONE = 0.2
MAX_JUMP_DURATION = 3.0
STUCK_DETECTION_WAIT_DEFAULT = 0.3
AIRBORNE_RECOVERY_WAIT_DEFAULT = 3.0
LADDER_RECOVERY_RESEND_DELAY_DEFAULT = 0.5

WAYPOINT_ARRIVAL_X_THRESHOLD = 9.0
WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT = 8.0
WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT = 10.0
WALK_TELEPORT_PROBABILITY_DEFAULT = 10.0  # percent
WALK_TELEPORT_INTERVAL_DEFAULT = 0.5
WALK_TELEPORT_BONUS_DELAY_DEFAULT = 1.0
WALK_TELEPORT_BONUS_STEP_DEFAULT = 10.0
WALK_TELEPORT_BONUS_MAX_DEFAULT = 50.0
LADDER_ARRIVAL_X_THRESHOLD = 6.5
LADDER_ARRIVAL_SHORT_THRESHOLD = 5.5
JUMP_LINK_ARRIVAL_X_THRESHOLD = 3.1
LADDER_AVOIDANCE_WIDTH = 2.0

MAX_LOCK_DURATION = 5.0
PREPARE_TIMEOUT = 3.0
HYSTERESIS_EXIT_OFFSET = 4.0


def _resolve_key_mappings_path_for_map() -> Path:
    legacy_relative = Path(os.path.join("Project_Maple", "workspace", "config", "key_mappings.json"))
    module_workspace = Path(__file__).resolve().parents[1] / "workspace" / "config" / "key_mappings.json"
    workspace_relative = Path("workspace") / "config" / "key_mappings.json"

    candidates: List[Path] = [
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


def _load_profiles_by_category(target_category: str) -> List[str]:
    target_path = _resolve_key_mappings_path_for_map()
    if not target_path.is_file():
        return []

    raw_data = None
    for encoding in ("utf-8", "utf-8-sig", "cp949", "euc-kr"):
        try:
            with target_path.open("r", encoding=encoding) as f:
                raw_data = json.load(f)
            break
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raw_data = None

    if not isinstance(raw_data, dict):
        return []

    meta = raw_data.get("_meta") if isinstance(raw_data.get("_meta"), dict) else {}
    categories = raw_data.get("_categories") or meta.get("categories") or {}

    if isinstance(raw_data.get("profiles"), dict):
        profiles = raw_data.get("profiles", {})
    else:
        profiles = {key: value for key, value in raw_data.items() if not key.startswith("_")}

    filtered = [
        name
        for name in profiles.keys()
        if isinstance(name, str) and categories.get(name) == target_category
    ]
    filtered.sort()
    return filtered


def load_event_profiles() -> List[str]:
    return _load_profiles_by_category("이벤트")


def load_skill_profiles() -> List[str]:
    return _load_profiles_by_category("스킬")


_BASE_EXPORTS = [
    "MapConfig",
    "SRC_ROOT",
    "WORKSPACE_ROOT",
    "CONFIG_PATH",
    "MAPS_DIR",
    "GLOBAL_MAP_SETTINGS_FILE",
    "GLOBAL_ACTION_MODEL_DIR",
    "DEFAULT_STATE_BASE_PROFILE",
    "STATE_MACHINE_CONFIG_KEYS",
    "load_baseline_state_machine_config",
    "ROUTE_SLOT_IDS",
    "PLAYER_ICON_LOWER",
    "PLAYER_ICON_UPPER",
    "OTHER_PLAYER_ICON_LOWER1",
    "OTHER_PLAYER_ICON_UPPER1",
    "OTHER_PLAYER_ICON_LOWER2",
    "OTHER_PLAYER_ICON_UPPER2",
    "PLAYER_Y_OFFSET",
    "MIN_ICON_WIDTH",
    "MIN_ICON_HEIGHT",
    "MAX_ICON_WIDTH",
    "MAX_ICON_HEIGHT",
    "PLAYER_ICON_STD_WIDTH",
    "PLAYER_ICON_STD_HEIGHT",
    "IDLE_TIME_THRESHOLD",
    "CLIMBING_STATE_FRAME_THRESHOLD",
    "FALLING_STATE_FRAME_THRESHOLD",
    "JUMPING_STATE_FRAME_THRESHOLD",
    "ON_TERRAIN_Y_THRESHOLD",
    "JUMP_Y_MIN_THRESHOLD",
    "JUMP_Y_MAX_THRESHOLD",
    "FALL_Y_MIN_THRESHOLD",
    "CLIMB_X_MOVEMENT_THRESHOLD",
    "FALL_ON_LADDER_X_MOVEMENT_THRESHOLD",
    "Y_MOVEMENT_DEADZONE",
    "LADDER_X_GRAB_THRESHOLD",
    "MOVE_DEADZONE",
    "MAX_JUMP_DURATION",
    "STUCK_DETECTION_WAIT_DEFAULT",
    "AIRBORNE_RECOVERY_WAIT_DEFAULT",
    "LADDER_RECOVERY_RESEND_DELAY_DEFAULT",
    "WAYPOINT_ARRIVAL_X_THRESHOLD",
    "WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT",
    "WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT",
    "WALK_TELEPORT_PROBABILITY_DEFAULT",
    "WALK_TELEPORT_INTERVAL_DEFAULT",
    "WALK_TELEPORT_BONUS_DELAY_DEFAULT",
    "WALK_TELEPORT_BONUS_STEP_DEFAULT",
    "WALK_TELEPORT_BONUS_MAX_DEFAULT",
    "WALK_TELEPORT_PROBABILITY_DEFAULT",
    "WALK_TELEPORT_INTERVAL_DEFAULT",
    "LADDER_ARRIVAL_X_THRESHOLD",
    "JUMP_LINK_ARRIVAL_X_THRESHOLD",
    "LADDER_AVOIDANCE_WIDTH",
    "MAX_LOCK_DURATION",
    "PREPARE_TIMEOUT",
    "HYSTERESIS_EXIT_OFFSET",
    "load_event_profiles",
    "load_skill_profiles",
]

__all__ = list(_BASE_EXPORTS)

try:
    from . import map_ui as _map_ui
except ImportError:
    import map_ui as _map_ui  # type: ignore

exported = getattr(_map_ui, "__all__", None)
if not exported:
    exported = [name for name in dir(_map_ui) if not name.startswith('_')]

globals().update({name: getattr(_map_ui, name) for name in exported})

for name in exported:
    if name not in __all__:
        __all__.append(name)

try:
    from . import map_widgets as _map_widgets
except ImportError:
    import map_widgets as _map_widgets  # type: ignore

widget_exports = getattr(_map_widgets, "__all__", None)
if not widget_exports:
    widget_exports = [name for name in dir(_map_widgets) if not name.startswith('_')]

globals().update({name: getattr(_map_widgets, name) for name in widget_exports})

for name in widget_exports:
    if name not in __all__:
        __all__.append(name)

try:
    from . import map_editors as _map_editors
except ImportError:
    import map_editors as _map_editors  # type: ignore

editor_exports = getattr(_map_editors, "__all__", None)
if not editor_exports:
    editor_exports = [name for name in dir(_map_editors) if not name.startswith('_')]

globals().update({name: getattr(_map_editors, name) for name in editor_exports})

for name in editor_exports:
    if name not in __all__:
        __all__.append(name)
