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
}


SRC_ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(SRC_ROOT, "..", "workspace"))
CONFIG_PATH = os.path.join(WORKSPACE_ROOT, "config")
MAPS_DIR = os.path.join(CONFIG_PATH, "maps")
GLOBAL_MAP_SETTINGS_FILE = os.path.join(CONFIG_PATH, "global_map_settings.json")
GLOBAL_ACTION_MODEL_DIR = os.path.join(CONFIG_PATH, "global_action_model")


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


IDLE_TIME_THRESHOLD = 0.8
CLIMBING_STATE_FRAME_THRESHOLD = 2
FALLING_STATE_FRAME_THRESHOLD = 2
JUMPING_STATE_FRAME_THRESHOLD = 1
ON_TERRAIN_Y_THRESHOLD = 3.0
JUMP_Y_MIN_THRESHOLD = 1.0
JUMP_Y_MAX_THRESHOLD = 10.5
FALL_Y_MIN_THRESHOLD = 4.0
CLIMB_X_MOVEMENT_THRESHOLD = 1.0
FALL_ON_LADDER_X_MOVEMENT_THRESHOLD = 1.0
Y_MOVEMENT_DEADZONE = 0.5
LADDER_X_GRAB_THRESHOLD = 8.0
MOVE_DEADZONE = 0.2
MAX_JUMP_DURATION = 3.0

WAYPOINT_ARRIVAL_X_THRESHOLD = 8.0
LADDER_ARRIVAL_X_THRESHOLD = 8.0
JUMP_LINK_ARRIVAL_X_THRESHOLD = 4.0
LADDER_AVOIDANCE_WIDTH = 2.0

MAX_LOCK_DURATION = 5.0
PREPARE_TIMEOUT = 15.0
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


def load_event_profiles() -> List[str]:
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

    event_profiles = [name for name in profiles.keys() if isinstance(name, str) and categories.get(name) == "이벤트"]
    event_profiles.sort()
    return event_profiles


_BASE_EXPORTS = [
    "MapConfig",
    "SRC_ROOT",
    "WORKSPACE_ROOT",
    "CONFIG_PATH",
    "MAPS_DIR",
    "GLOBAL_MAP_SETTINGS_FILE",
    "GLOBAL_ACTION_MODEL_DIR",
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
    "WAYPOINT_ARRIVAL_X_THRESHOLD",
    "LADDER_ARRIVAL_X_THRESHOLD",
    "JUMP_LINK_ARRIVAL_X_THRESHOLD",
    "LADDER_AVOIDANCE_WIDTH",
    "MAX_LOCK_DURATION",
    "PREPARE_TIMEOUT",
    "HYSTERESIS_EXIT_OFFSET",
    "load_event_profiles",
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
